"""Ingestion adapter contract.

An adapter is responsible for one thing: turning an external source into
validated, provenance-stamped domain objects. It must not compute engineering
values, and it must not invent data.

Every adapter registers a :class:`~app.models.evidence.Dataset` before writing
rows, and stamps every row it writes with that dataset's id and version. That is
what makes the real NSTA download a configuration change rather than a rewrite:
the adapter's ``fetch`` returns the same shape whether it came from an HTTP
response or a file on disk.
"""

from __future__ import annotations

import abc
import hashlib
import json
import logging
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import SourceReliability
from app.db.session import session_scope
from app.models.evidence import Dataset

logger = logging.getLogger(__name__)


@dataclass
class SourceDescriptor:
    """Provenance for one dataset version. Every imported dataset has one."""

    source: str
    name: str
    version: str
    source_url: str | None = None
    description: str | None = None
    download_date: date | None = None
    published_date: date | None = None
    licence: str | None = None
    reliability: str = SourceReliability.TIER_C.value
    is_mock: bool = False
    #: Populated by the validation stage.
    quality_score: float = 0.0
    row_count: int | None = None
    validation_summary: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> Dataset:
        return Dataset(
            source=self.source,
            name=self.name,
            description=self.description,
            source_url=self.source_url,
            download_date=self.download_date,
            published_date=self.published_date,
            licence=self.licence,
            version=self.version,
            reliability=self.reliability,
            quality_score=self.quality_score,
            row_count=self.row_count,
            validation_summary=self.validation_summary,
            is_mock=self.is_mock,
            status="registered",
        )


@dataclass
class ImportResult:
    """Outcome of one adapter run. Always inspectable, never a bare count."""

    source: str
    dataset_id: uuid.UUID | None = None
    wells_created: int = 0
    wells_updated: int = 0
    wells_skipped: int = 0
    buildings_created: int = 0
    temperatures_created: int = 0
    records_written: int = 0
    records_read: int = 0
    records_rejected: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    sample_rejections: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "dataset_id": str(self.dataset_id) if self.dataset_id else None,
            "wells_created": self.wells_created,
            "wells_updated": self.wells_updated,
            "wells_skipped": self.wells_skipped,
            "buildings_created": self.buildings_created,
            "temperatures_created": self.temperatures_created,
            "records_written": self.records_written,
            "records_read": self.records_read,
            "records_rejected": self.records_rejected,
            "errors": self.errors,
            "warnings": self.warnings,
            "duration_seconds": round(self.duration_seconds, 2),
            "ok": self.ok,
        }


class Adapter(abc.ABC):
    """Base class for every ingestion adapter.

    Subclasses implement :meth:`fetch` and one or more ``load_*`` methods. The
    ``run`` wrapper in this class handles dataset registration, timing, error
    capture and the batch commit, so every adapter gets identical provenance and
    failure behaviour.
    """

    #: Stable adapter id, stored on every row it writes.
    source: str = "base"

    #: Whether this adapter produces synthetic development data.
    is_mock: bool = False

    #: What this adapter writes, so a run can report per-entity counts without
    #: every adapter having to increment the counters itself. Overridden by the
    #: building, temperature and price adapters.
    entity_kind: str = "well"

    def descriptor(self) -> SourceDescriptor:
        """Provenance for this adapter's current dataset version."""
        raise NotImplementedError

    @abc.abstractmethod
    def fetch(self, db: Session) -> Iterator[dict[str, Any]]:
        """Yield raw records from the external source.

        Must not write to the database. Keeping fetch and load separate is what
        lets a real HTTP or file source be swapped for the mock without touching
        the validation or loading logic.
        """

    def load(self, db: Session, record: dict[str, Any], dataset: Dataset) -> bool:
        """Normalise, validate and persist one record.

        Returns True when a row was written or updated, False when the record was
        skipped. Implementations must call
        :func:`app.data_normalisation.normalise.reject` rather than raising, so
        one bad record cannot abort a national import.
        """
        raise NotImplementedError

    def run(self, *, limit: int | None = None, dry_run: bool = False) -> ImportResult:
        """Register the dataset, stream the records, load them in batches."""
        import time  # noqa: PLC0415

        started = time.perf_counter()
        result = ImportResult(source=self.source)

        try:
            descriptor = self.descriptor()
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"descriptor failed: {exc}")
            result.duration_seconds = time.perf_counter() - started
            return result

        with session_scope() as db:
            # Upsert on (source, version). A re-import of the same version must
            # refresh the existing row rather than violate the unique
            # constraint, which is what makes the bootstrap idempotent.
            dataset_row = register_dataset(db, descriptor)
            result.dataset_id = dataset_row.id

            try:
                for index, record in enumerate(self.fetch(db)):
                    if limit is not None and index >= limit:
                        break
                    result.records_read += 1

                    if dry_run:
                        continue

                    try:
                        wrote = self.load(db, record, dataset_row)
                    except Exception as exc:  # noqa: BLE001
                        result.records_rejected += 1
                        message = f"{type(exc).__name__}: {exc}"
                        result.errors.append(message)
                        if len(result.sample_rejections) < 25:
                            result.sample_rejections.append(
                                {"index": index, "error": message, "record": _redact(record)}
                            )
                        continue

                    if wrote:
                        # Count by row type, so a run reports what it actually
                        # wrote rather than how many records it read.
                        if isinstance(record, dict):
                            kind = record.get("_entity") or self.entity_kind
                        else:
                            kind = self.entity_kind
                        if kind == "building":
                            result.buildings_created += 1
                        elif kind == "temperature":
                            result.temperatures_created += 1
                        elif kind == "record":
                            # Integrity, geology, prices, regulatory rows: written
                            # but not well rows, so they must not inflate the
                            # wells_created count.
                            result.records_written += 1
                        else:
                            result.wells_created += 1
                        if index and index % 500 == 0:
                            db.flush()
                    else:
                        result.wells_skipped += 1
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"fetch failed: {exc}")

            dataset_row.row_count = result.records_read
            dataset_row.quality_score = descriptor.quality_score
            dataset_row.validation_summary = {
                **descriptor.validation_summary,
                "records_read": result.records_read,
                "records_rejected": result.records_rejected,
            }
            dataset_row.status = "complete" if result.ok else "complete_with_errors"
            dataset_row.last_ingested_at = datetime.now(UTC)
            db.flush()

        result.duration_seconds = time.perf_counter() - started
        return result


def register_dataset(db: Session, descriptor: SourceDescriptor) -> Dataset:
    """Register or update a dataset row, keyed on ``(source, version)``."""
    existing = db.scalar(
        select(Dataset).where(
            Dataset.source == descriptor.source, Dataset.version == descriptor.version
        )
    )
    if existing is not None:
        existing.name = descriptor.name
        existing.source_url = descriptor.source_url
        existing.licence = descriptor.licence
        existing.quality_score = descriptor.quality_score
        existing.is_mock = descriptor.is_mock
        db.flush()
        return existing

    row = descriptor.to_row()
    db.add(row)
    db.flush()
    return row


def compute_checksum(payload: bytes | str) -> str:
    """SHA-256 of a payload, stored so a dataset version can be verified."""
    if isinstance(payload, str):
        payload = payload.encode()
    return hashlib.sha256(payload).hexdigest()


def checksum_file(path: str | Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json_records(path: str | Path) -> Iterator[dict[str, Any]]:
    """Stream records from a JSON array or a JSON-lines file."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"data file not found: {file_path}")

    text = file_path.read_text(encoding="utf-8").strip()
    if not text:
        return

    if text.startswith("["):
        yield from json.loads(text)
        return

    if text.startswith("{") and "\n" not in text:
        payload = json.loads(text)
        # A single object, or an envelope with a list of records.
        for key in ("records", "features", "wells", "items", "data"):
            if isinstance(payload.get(key), list):
                yield from payload[key]
                return
        yield payload
        return

    for line in text.splitlines():
        line = line.strip()
        if line:
            yield json.loads(line)


def _redact(record: dict[str, Any]) -> dict[str, Any]:
    """Trim a rejected record for the log.

    Rejections are persisted for diagnosis, but an import can be of a large file
    containing commercially sensitive operator data, so only the identifying keys
    are kept.
    """
    keep = ("well_id", "id", "name", "operator", "licence", "latitude", "longitude")
    return {k: record.get(k) for k in keep if k in record}

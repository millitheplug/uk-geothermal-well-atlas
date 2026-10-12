"""Settings parsing that deployment depends on."""

from __future__ import annotations

import pytest

from app.core.config import Settings


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://a.vercel.app", ["https://a.vercel.app"]),
        ("https://a.vercel.app, https://b.example.com", ["https://a.vercel.app", "https://b.example.com"]),
        ('["https://a.vercel.app"]', ["https://a.vercel.app"]),
        ("", []),
    ],
)
def test_cors_origins_accepts_comma_separated_and_json(monkeypatch, raw, expected):
    monkeypatch.setenv("CORS_ORIGINS", raw)
    assert Settings().cors_origins == expected


def test_production_requires_a_real_secret_and_debug_off(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings()
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    with pytest.raises(ValueError, match="DEBUG"):
        Settings()
    monkeypatch.setenv("DEBUG", "false")
    assert Settings().environment == "production"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("postgresql://u:p@host/db?sslmode=require", "postgresql+psycopg://u:p@host/db?sslmode=require"),
        ("postgres://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ("sqlite:///./x.db", "sqlite:///./x.db"),
    ],
)
def test_database_url_is_routed_to_the_psycopg_driver(monkeypatch, raw, expected):
    monkeypatch.setenv("DATABASE_URL", raw)
    assert Settings().database_url == expected

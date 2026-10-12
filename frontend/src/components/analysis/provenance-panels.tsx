/**
 * Provenance panels: the calculation trace, evidence, regulatory requirements,
 * validation actions and the agent outputs.
 *
 * These exist so the platform's central claim is checkable rather than
 * asserted. If the score is wrong, the reader should be able to walk down to
 * the input value, the formula that used it and the source that supplied it -
 * without asking anyone.
 */

"use client";

import * as React from "react";
import {
  AlertTriangle,
  BookOpen,
  ClipboardList,
  Download,
  ExternalLink,
  Gavel,
  ScrollText,
  Sigma,
  Sparkles,
} from "lucide-react";

import { Badge, EpistemicBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState, SectionTitle } from "@/components/common/feedback";
import { humanise } from "@/lib/domain";
import { cn } from "@/lib/utils";
import type {
  CalculationTrace,
  Claim,
  Evidence,
  RegulatoryRequirement,
  ValidationAction,
} from "@/types/api";

/**
 * Every calculation the engine performed, with its inputs, units, formula and
 * status. Collapsed by default because there are typically 30–60 of them; the
 * point is that they are *available*, not that they are in your face.
 */
export function TracePanel({ trace }: { trace: CalculationTrace[] }) {
  const [openIndex, setOpenIndex] = React.useState<number | null>(null);
  const [query, setQuery] = React.useState("");

  const filtered = React.useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return trace;
    return trace.filter((entry) =>
      [
        entry.function_name,
        entry.formula,
        entry.result_unit,
        JSON.stringify(entry.inputs),
      ]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [trace, query]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sigma className="h-4 w-4" aria-hidden />
          Calculation trace
        </CardTitle>
        <CardDescription>
          {trace.length} deterministic calculations, each with its inputs, units,
          formula, result and epistemic status. This is the audit trail behind
          every figure on the page. Search it to find where a number came from.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Filter by function, formula, unit or input name"
          className="mb-2 h-8 w-full rounded-md border border-input bg-card px-2.5 text-xs"
          aria-label="Filter the calculation trace"
        />

        {filtered.length === 0 ? (
          <p className="text-xs italic text-muted-foreground">
            No calculation matches that filter.
          </p>
        ) : (
          <ul className="divide-y">
            {filtered.map((entry) => {
              const globalIndex = trace.indexOf(entry);
              const open = openIndex === globalIndex;
              return (
                <li key={`${entry.function_name}-${globalIndex}`}>
                  <button
                    type="button"
                    onClick={() => setOpenIndex(open ? null : globalIndex)}
                    aria-expanded={open}
                    className="flex w-full items-center justify-between gap-2 py-2 text-left hover:bg-muted/40"
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="truncate font-mono text-xs">
                        {entry.function_name}()
                      </span>
                      <EpistemicBadge status={entry.status} />
                    </span>
                    <span className="tabular shrink-0 text-xs font-medium">
                      {entry.result === null || entry.result === undefined
                        ? "no result"
                        : `${formatNumber(entry.result)} ${entry.result_unit}`}
                    </span>
                  </button>

                  {open && (
                    <div className="space-y-2 rounded-md bg-muted/50 p-2.5 text-xs">
                      <div>
                        <SectionTitle>Formula</SectionTitle>
                        <code className="mt-1 block rounded bg-card p-2 font-mono text-[12px] leading-relaxed">
                          {entry.formula}
                        </code>
                      </div>

                      <div>
                        <SectionTitle>Inputs</SectionTitle>
                        <Table className="mt-1">
                          <TableHeader>
                            <TableRow>
                              <TableHead>Name</TableHead>
                              <TableHead>Value</TableHead>
                              <TableHead>Unit</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {Object.entries(entry.inputs).map(([name, value]) => (
                              <TableRow key={name}>
                                <TableCell className="font-mono text-[12px]">
                                  {name}
                                </TableCell>
                                <TableCell>
                                  {value === null || value === undefined
                                    ? "Not available"
                                    : typeof value === "object"
                                      ? JSON.stringify(value)
                                      : String(value)}
                                </TableCell>
                                <TableCell className="text-muted-foreground">
                                  {entry.input_units[name] ?? "—"}
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>

                      {Object.keys(entry.intermediate_values).length > 0 && (
                        <div>
                          <SectionTitle>Intermediate values</SectionTitle>
                          <ul className="mt-1 space-y-0.5 font-mono text-[12px] text-muted-foreground">
                            {Object.entries(entry.intermediate_values).map(
                              ([name, value]) => (
                                <li key={name}>
                                  {name} ={" "}
                                  {value === null || value === undefined
                                    ? "Not available"
                                    : typeof value === "object"
                                      ? JSON.stringify(value)
                                      : String(value)}
                                </li>
                              ),
                            )}
                          </ul>
                        </div>
                      )}

                      {entry.assumptions.length > 0 && (
                        <div>
                          <SectionTitle>Assumptions</SectionTitle>
                          <ul className="mt-1 space-y-0.5 text-muted-foreground">
                            {entry.assumptions.map((assumption, index) => (
                              <li key={index}>
                                · {describe(assumption)}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {entry.sources.length > 0 && (
                        <div>
                          <SectionTitle>Sources</SectionTitle>
                          <ul className="mt-1 space-y-0.5 text-muted-foreground">
                            {entry.sources.map((source, index) => (
                              <li key={index}>· {describe(source)}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {entry.warnings.length > 0 && (
                        <ul className="space-y-0.5 text-priority-medium">
                          {entry.warnings.map((warning, index) => (
                            <li key={index}>
                              <AlertTriangle
                                className="mr-1 inline h-3 w-3"
                                aria-hidden
                              />
                              {warning}
                            </li>
                          ))}
                        </ul>
                      )}

                      <p className="font-mono text-[12px] text-muted-foreground">
                        engine {entry.engine_version}
                        {entry.confidence !== null &&
                          ` · confidence ${Math.round(entry.confidence * 100)}%`}
                      </p>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export function EvidencePanel({
  evidence,
  claims,
}: {
  evidence: Evidence[];
  claims: Claim[];
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <BookOpen className="h-4 w-4" aria-hidden />
          Evidence and claims
        </CardTitle>
        <CardDescription>
          {evidence.length} source documents and {claims.length} attributed
          claims. A claim without evidence is labelled as an assumption rather
          than a fact.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {evidence.length === 0 ? (
          <p className="text-xs italic text-muted-foreground">
            No evidence records are attached to this analysis.
          </p>
        ) : (
          <div className="space-y-2">
            <SectionTitle>Sources</SectionTitle>
            <ul className="space-y-1.5">
              {evidence.map((item) => (
                <li
                  key={item.id}
                  className={cn(
                    "rounded-md border p-2.5",
                    item.is_mock && "border-destructive/40",
                  )}
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-xs font-medium">
                      {item.source_title ?? item.source}
                    </span>
                    <span className="flex items-center gap-1.5">
                      <EpistemicBadge status={item.status} />
                      {item.is_mock && (
                        <Badge variant="outline" className="mock-badge text-[11px]">
                          synthetic
                        </Badge>
                      )}
                    </span>
                  </div>
                  <p className="mt-0.5 text-[12px] text-muted-foreground">
                    {item.source}
                    {item.document_type && ` · ${humanise(item.document_type)}`}
                    {item.source_date && ` · ${item.source_date.slice(0, 10)}`}
                    {item.page_reference && ` · p.${item.page_reference}`}
                  </p>
                  {item.excerpt && (
                    <p className="mt-1 border-l-2 pl-2 text-xs italic leading-relaxed text-muted-foreground">
                      {item.excerpt}
                    </p>
                  )}
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-[12px] text-muted-foreground">
                    <span>Reliability {item.reliability.toFixed(2)}</span>
                    <span>Quality {item.quality.toFixed(2)}</span>
                    <span>Relevance {item.relevance.toFixed(2)}</span>
                    {item.source_url && (
                      <a
                        href={item.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-primary hover:underline"
                      >
                        Open source
                        <ExternalLink className="h-2.5 w-2.5" aria-hidden />
                      </a>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        {claims.length > 0 && (
          <div className="space-y-2">
            <SectionTitle>Claims</SectionTitle>
            <ul className="space-y-1">
              {claims.map((claim) => (
                <li
                  key={claim.id}
                  className="flex items-start justify-between gap-2 border-b py-1.5 last:border-0"
                >
                  <div className="min-w-0">
                    <p className="text-xs">{claim.claim}</p>
                    <p className="mt-0.5 font-mono text-[12px] text-muted-foreground">
                      {claim.field_name}
                      {claim.agent && ` · ${claim.agent}`}
                    </p>
                  </div>
                  <span className="flex shrink-0 items-center gap-1.5">
                    {claim.is_critical && (
                      <Badge variant="outline" className="text-[11px]">
                        critical
                      </Badge>
                    )}
                    <EpistemicBadge status={claim.status} />
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function RegulatoryPanel({
  requirements,
  configuration,
}: {
  requirements: RegulatoryRequirement[];
  configuration: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Gavel className="h-4 w-4" aria-hidden />
          Consent requirements
        </CardTitle>
        <CardDescription>
          Shown for the selected configuration ({humanise(configuration)}).
          Requirements are indicative and jurisdiction-dependent; a screening
          tool cannot establish what a regulator will actually require.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {requirements.length === 0 ? (
          <p className="text-xs italic text-muted-foreground">
            No consent requirements are recorded for this configuration.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {requirements.map((item) => (
              <li key={item.id} className="rounded-md border p-2.5">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-xs font-medium">{item.title}</span>
                  <span className="flex items-center gap-1.5">
                    {item.is_mandatory && (
                      <Badge variant="outline" className="text-[11px]">
                        mandatory
                      </Badge>
                    )}
                    {item.is_mock && (
                      <Badge variant="outline" className="mock-badge text-[11px]">
                        synthetic
                      </Badge>
                    )}
                  </span>
                </div>
                {item.description && (
                  <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                    {item.description}
                  </p>
                )}
                <p className="mt-1 flex flex-wrap gap-x-3 text-[12px] text-muted-foreground">
                  {item.authority && <span>{item.authority}</span>}
                  {item.jurisdiction && <span>{item.jurisdiction}</span>}
                  {item.typical_lead_time_months !== null && (
                    <span>Lead time ~{item.typical_lead_time_months} months</span>
                  )}
                  {item.estimated_cost_gbp !== null && (
                    <span>
                      Indicative cost £{Math.round(item.estimated_cost_gbp).toLocaleString("en-GB")}
                    </span>
                  )}
                </p>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

const PRIORITY_CLASS: Record<ValidationAction["priority"], string> = {
  critical: "border-destructive/40 bg-destructive/10 text-destructive",
  high: "border-priority-low/40 bg-priority-low/10 text-priority-low",
  medium: "border-priority-medium/40 bg-priority-medium/10 text-priority-medium",
  low: "border-border text-muted-foreground",
};

/**
 * Recommended next actions.
 *
 * This is the closest thing the platform has to advice, so it is labelled as
 * such: these are data-gathering steps derived from recorded gaps, not a work
 * programme.
 */
export function ValidationPanel({ actions }: { actions: ValidationAction[] }) {
  if (actions.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ClipboardList className="h-4 w-4" aria-hidden />
            Data-gathering actions
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">
            No actions proposed. If the assessment has not been run, this panel
            is empty rather than reassuring.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ClipboardList className="h-4 w-4" aria-hidden />
          Data-gathering actions
        </CardTitle>
        <CardDescription>
          Derived from the data gaps recorded during the assessment. Each one
          names the risks it would reduce. This is not a project plan.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {actions.map((action) => (
            <li key={action.id} className="rounded-md border p-2.5">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-xs font-medium">{action.title}</span>
                <Badge className={`text-[11px] ${PRIORITY_CLASS[action.priority]}`}>
                  {action.priority}
                </Badge>
              </div>
              {action.description && (
                <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                  {action.description}
                </p>
              )}
              {action.rationale && (
                <p className="mt-1 text-[12px] leading-relaxed text-muted-foreground">
                  Why: {action.rationale}
                </p>
              )}
              <p className="mt-1 flex flex-wrap gap-x-3 text-[12px] text-muted-foreground">
                <span>{humanise(action.action_type)}</span>
                {action.estimated_cost_gbp !== null && (
                  <span>
                    Indicative cost £
                    {Math.round(action.estimated_cost_gbp).toLocaleString("en-GB")}
                  </span>
                )}
                {action.estimated_duration_days !== null && (
                  <span>~{action.estimated_duration_days} days</span>
                )}
              </p>
              {(action.addresses_risk_ids.length > 0 ||
                action.addresses_data_gaps.length > 0) && (
                <p className="mt-1 text-[12px] text-primary">
                  Addresses:{" "}
                  {[
                    ...action.addresses_risk_ids.map((id) => `risk ${id}`),
                    ...action.addresses_data_gaps,
                  ].join(", ")}
                </p>
              )}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

/**
 * Agent outputs.
 *
 * Presented last and marked as interpretation, because that is what it is. The
 * orchestration layer runs eleven agents over the engine's output; a discipline
 * gate rejects any output that asserts commercial viability or states a
 * recommendation different from the engine's.
 */
/**
 * Save a screening report as a markdown file.
 *
 * The filename carries the well name so a downloaded report stays attributable
 * once it leaves the platform. A document that cannot be traced back to the
 * well it assessed is one waiting to be misquoted.
 */
function downloadReport(markdown: string, wellName?: string | null): void {
  const slug =
    (wellName ?? "well")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "well";

  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `geothermal-screening-${slug}.md`;
  link.click();
  URL.revokeObjectURL(url);
}


export function AgentPanel({
  outputs,
  executiveSummary,
  reportMarkdown,
  wellName,
}: {
  outputs: Record<string, unknown> | null;
  executiveSummary: string | null;
  reportMarkdown: string | null;
  wellName?: string | null;
}) {
  const entries = outputs ? Object.entries(outputs) : [];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="h-4 w-4" aria-hidden />
          Agent interpretation
        </CardTitle>
        <CardDescription>
          Narrative produced by the analysis agents from the engine&apos;s
          results. No agent performs arithmetic, and none may state a
          recommendation other than the one the engine assigned. Where an agent
          asserted a fact without a source, the gate relabelled it rather than
          allowing it through.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {executiveSummary ? (
          <div className="rounded-md border border-primary/30 bg-primary/5 p-3">
            <SectionTitle>Executive summary</SectionTitle>
            <p className="mt-1.5 text-xs leading-relaxed">{executiveSummary}</p>
          </div>
        ) : (
          <EmptyState
            title="No agent interpretation was generated"
            message="Run the assessment with agent interpretation enabled, or configure an LLM provider. The deterministic results above stand on their own."
          />
        )}

        {entries.length > 0 && (
          <div className="space-y-2">
            <SectionTitle>Agent outputs ({entries.length})</SectionTitle>
            <ul className="space-y-1.5">
              {entries.map(([name, value]) => (
                <li key={name} className="rounded-md border p-2.5">
                  <p className="font-mono text-[12px] text-muted-foreground">
                    {humanise(name)}
                  </p>
                  <AgentValue value={value} />
                </li>
              ))}
            </ul>
          </div>
        )}

        {reportMarkdown && (
          <div className="space-y-2">
            <div className="flex items-start justify-between gap-2">
              <details>
                <summary className="cursor-pointer text-xs font-medium text-primary">
                  <span className="inline-flex items-center gap-1.5">
                    <ScrollText className="h-3.5 w-3.5" aria-hidden />
                    Full twenty-one section report (markdown)
                  </span>
                </summary>
                <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap rounded-md border bg-muted/40 p-3 font-mono text-[12px] leading-relaxed">
                  {reportMarkdown}
                </pre>
              </details>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="shrink-0"
                onClick={() => downloadReport(reportMarkdown, wellName)}
              >
                <Download className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                Download .md
              </Button>
            </div>
            <p className="text-[12px] leading-relaxed text-muted-foreground">
              Screening output from desk-study data. It is not a statement of
              commercial viability, and no figure in it substitutes for
              engineering sign-off.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** Renders an arbitrary agent payload without assuming a shape. */
function AgentValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) {
    return (
      <p className="mt-0.5 text-xs italic text-muted-foreground">
        Not available
      </p>
    );
  }
  if (typeof value === "string") {
    return <p className="mt-0.5 text-xs leading-relaxed">{value}</p>;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return <p className="mt-0.5 text-xs tabular">{String(value)}</p>;
  }
  if (Array.isArray(value)) {
    return (
      <ul className="mt-0.5 space-y-0.5 text-xs leading-relaxed">
        {value.map((item, index) => (
          <li key={index} className="flex gap-1.5">
            <span aria-hidden>·</span>
            <span>{typeof item === "string" ? item : JSON.stringify(item)}</span>
          </li>
        ))}
      </ul>
    );
  }
  if (typeof value === "object") {
    return (
      <dl className="mt-0.5 space-y-0.5 text-xs">
        {Object.entries(value as Record<string, unknown>).map(([key, item]) => (
          <div key={key} className="flex gap-2">
            <dt className="shrink-0 font-mono text-[12px] text-muted-foreground">
              {key}
            </dt>
            <dd className="min-w-0 break-words">
              {item === null || item === undefined
                ? "Not available"
                : typeof item === "object"
                  ? JSON.stringify(item)
                  : String(item)}
            </dd>
          </div>
        ))}
      </dl>
    );
  }
  return null;
}

function describe(value: unknown): string {
  if (value === null || value === undefined) return "Not available";
  if (typeof value === "string") return value;
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    const label =
      record.description ?? record.rationale ?? record.note ?? record.source;
    const value_ = record.value;
    if (label !== undefined && value_ !== undefined) {
      return `${String(label)} (${String(value_)})`;
    }
    return JSON.stringify(value);
  }
  return String(value);
}

function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return String(value);
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}m`;
  if (Math.abs(value) >= 10_000) return `${Math.round(value).toLocaleString("en-GB")}`;
  return Number(value.toFixed(2)).toLocaleString("en-GB");
}
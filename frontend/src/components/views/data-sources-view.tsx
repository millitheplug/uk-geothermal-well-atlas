/**
 * Data sources, adapters and parameters.
 *
 * This is the page that answers "where did any of this come from". It exists
 * because a screening tool that cannot name its inputs should not be trusted,
 * and because the synthetic development datasets must be obvious here rather
 * than only on the map.
 */

"use client";

import * as React from "react";
import { Database, ExternalLink, Plug, Settings2 } from "lucide-react";

import { PageHeader, EnvironmentStrip } from "@/components/layout/page-header";
import {
  EmptyState,
  ErrorState,
  KeyValueList,
  Loading,
  Notice,
  SectionTitle,
  StatGrid,
  StatTile,
} from "@/components/common/feedback";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useApiData } from "@/components/providers/app-provider";
import { api } from "@/lib/api";
import { humanise } from "@/lib/domain";
import { fmtDate } from "@/lib/utils";
import type { Dataset, ParameterSpec } from "@/types/api";

export function DataSourcesView() {
  const datasets = useApiData(
    (signal) => api.datasets(signal),
    [],
  );
  const adapters = useApiData((signal) => api.adapters(signal), []);
  const parameters = useApiData(
    (signal) => api.parameters(signal),
    [],
  );
  const regulatory = useApiData((signal) => api.regulatory(undefined, signal), []);

  const mockCount = datasets.data?.datasets.filter((d) => d.is_mock).length ?? 0;
  const realCount = (datasets.data?.datasets.length ?? 0) - mockCount;

  return (
    <>
      <PageHeader
        title="Data sources"
        subtitle="Datasets, ingestion adapters and documented parameters"
      >
        <div className="pt-2">
          <EnvironmentStrip />
        </div>
      </PageHeader>

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="space-y-4 p-4">
          <Notice tone="warning" title="On synthetic development data">
            {mockCount > 0 && realCount === 0 ? (
              <>
                Every dataset currently loaded is{" "}
                <strong>synthetic development data</strong> produced by the mock
                adapters. No well, building or price shown anywhere in this
                platform corresponds to a real UK borehole. The adapters are
                drop-in replacements: point them at the NSTA, BGS or DESNZ source
                files and the application needs no changes.
              </>
            ) : mockCount > 0 ? (
              <>
                {realCount} dataset{realCount === 1 ? "" : "s"} loaded from real
                sources and {mockCount} still synthetic. Anything drawn from a
                synthetic dataset is watermarked at the point of use, not only
                here.
              </>
            ) : (
              <>
                No synthetic datasets are currently loaded. Every figure on this
                platform is derived from a real source adapter.
              </>
            )}
          </Notice>

          <StatGrid cols={4}>
            <StatTile
              label="Registered datasets"
              value={String(datasets.data?.datasets.length ?? 0)}
              sub="Each carries a source, licence and version"
            />
            <StatTile
              label="Real-source datasets"
              value={String(realCount)}
              tone={realCount === 0 ? "warning" : "default"}
            />
            <StatTile
              label="Synthetic datasets"
              value={String(mockCount)}
              tone={mockCount > 0 ? "warning" : "muted"}
              sub={mockCount > 0 ? "Watermarked everywhere they appear" : undefined}
            />
            <StatTile
              label="Documented parameters"
              value={String(parameters.data?.count ?? 0)}
              sub="Each with a rationale and, where possible, a source"
            />
          </StatGrid>

          <Tabs defaultValue="datasets">
            <TabsList>
              <TabsTrigger value="datasets">
                <Database className="h-3 w-3" aria-hidden />
                Datasets
              </TabsTrigger>
              <TabsTrigger value="adapters">
                <Plug className="h-3 w-3" aria-hidden />
                Adapters
              </TabsTrigger>
              <TabsTrigger value="parameters">
                <Settings2 className="h-3 w-3" aria-hidden />
                Parameters
              </TabsTrigger>
              <TabsTrigger value="consent">
                Consent catalogue
              </TabsTrigger>
            </TabsList>

            {/* ---- Datasets ---- */}
            <TabsContent value="datasets">
              {datasets.loading && !datasets.data && <Loading label="Loading datasets" />}
              {datasets.error && (
                <ErrorState message={datasets.error} onRetry={datasets.refresh} />
              )}
              {datasets.data && datasets.data.datasets.length === 0 && (
                <EmptyState
                  title="No datasets registered"
                  message="Run the bootstrap sequence or an ingestion adapter on the backend to load data."
                />
              )}
              {datasets.data && datasets.data.datasets.length > 0 && (
                <Card>
                  <CardContent className="p-4">
                    <SectionTitle>Registered datasets</SectionTitle>
                    <div className="mt-2">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Dataset</TableHead>
                            <TableHead>Source</TableHead>
                            <TableHead>Version</TableHead>
                            <TableHead>Licence</TableHead>
                            <TableHead className="text-right">Rows</TableHead>
                            <TableHead className="text-right">Quality</TableHead>
                            <TableHead>Reliability</TableHead>
                            <TableHead>Status</TableHead>
                            <TableHead>Ingested</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {datasets.data.datasets.map((dataset) => (
                            <DatasetRow key={dataset.id} dataset={dataset} />
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                    <p className="mt-2 text-[10px] leading-relaxed text-muted-foreground">
                      Quality is a 0–1 score computed by the validation layer from
                      field completeness and plausibility checks. Reliability is
                      the source tier - a regulator record outranks a vendor
                      estimate, and that difference feeds the confidence score.
                    </p>
                  </CardContent>
                </Card>
              )}
            </TabsContent>

            {/* ---- Adapters ---- */}
            <TabsContent value="adapters">
              <Card>
                <CardHeader>
                  <CardTitle>Ingestion adapters</CardTitle>
                  <CardDescription>
                    Each adapter normalises one external source into the platform
                    schema. The mock adapters are intentionally the same shape as
                    the real ones, so replacing one is a configuration change
                    rather than a code change.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {adapters.loading && !adapters.data && (
                    <Loading label="Loading adapters" compact />
                  )}
                  {adapters.data && (
                    <ul className="space-y-2">
                      {adapters.data.adapters.map((adapter) => (
                        <li
                          key={adapter.name}
                          className={`rounded-md border p-2.5 ${
                            adapter.is_mock ? "border-destructive/40" : ""
                          }`}
                        >
                          <div className="flex flex-wrap items-baseline justify-between gap-2">
                            <span className="font-mono text-xs font-medium">
                              {adapter.name}
                            </span>
                            {adapter.is_mock && (
                              <Badge variant="outline" className="mock-badge text-[9px]">
                                synthetic
                              </Badge>
                            )}
                          </div>
                          <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
                            {adapter.description}
                          </p>
                          <div className="mt-1 flex flex-wrap items-center gap-3 text-[10px] text-muted-foreground">
                            {adapter.licence && <span>{adapter.licence}</span>}
                            {adapter.source_url && (
                              <a
                                href={adapter.source_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center gap-1 text-primary hover:underline"
                              >
                                Source
                                <ExternalLink className="h-2.5 w-2.5" aria-hidden />
                              </a>
                            )}
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            {/* ---- Parameters ---- */}
            <TabsContent value="parameters">
              <Card>
                <CardHeader>
                  <CardTitle>Engine parameters</CardTitle>
                  <CardDescription>
                    Every default the engineering model uses. A parameter with a
                    null source is an assumption made by this platform, and is
                    labelled as such wherever it affects a result.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {parameters.loading && !parameters.data && (
                    <Loading label="Loading parameters" compact />
                  )}
                  {parameters.data && (
                    <>
                      <p className="mb-2 rounded border bg-muted/40 p-2 text-[11px] text-muted-foreground">
                        {parameters.data.note}
                      </p>
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Key</TableHead>
                            <TableHead>Value</TableHead>
                            <TableHead>Unit</TableHead>
                            <TableHead>Rationale</TableHead>
                            <TableHead>Source</TableHead>
                            <TableHead>Range</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {parameters.data.parameters.map((parameter) => (
                            <ParameterRow
                              key={parameter.key}
                              parameter={parameter}
                            />
                          ))}
                        </TableBody>
                      </Table>
                    </>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            {/* ---- Consent catalogue ---- */}
            <TabsContent value="consent">
              <Card>
                <CardHeader>
                  <CardTitle>Consent requirements catalogue</CardTitle>
                  <CardDescription>
                    Indicative requirements by jurisdiction and configuration.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {regulatory.loading && !regulatory.data && (
                    <Loading label="Loading consents" compact />
                  )}
                  {regulatory.data && (
                    <>
                      <p className="mb-2 rounded border bg-muted/40 p-2 text-[11px] text-muted-foreground">
                        {regulatory.data.caveat}
                      </p>
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Requirement</TableHead>
                            <TableHead>Authority</TableHead>
                            <TableHead>Jurisdiction</TableHead>
                            <TableHead>Applies to</TableHead>
                            <TableHead>Mandatory</TableHead>
                            <TableHead className="text-right">Lead time</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {regulatory.data.requirements.map(
                            (requirement: Record<string, unknown>, index: number) => (
                              <TableRow key={String(requirement.id ?? index)}>
                                <TableCell>
                                  <span className="font-medium">
                                    {String(requirement.title ?? "Untitled")}
                                  </span>
                                  {Boolean(requirement.description) && (
                                    <p className="mt-0.5 text-[10px] leading-relaxed text-muted-foreground">
                                      {String(requirement.description)}
                                    </p>
                                  )}
                                </TableCell>
                                <TableCell className="text-muted-foreground">
                                  {String(requirement.authority ?? "Not recorded")}
                                </TableCell>
                                <TableCell className="text-muted-foreground">
                                  {String(requirement.jurisdiction ?? "Not recorded")}
                                </TableCell>
                                <TableCell className="text-muted-foreground">
                                  {Boolean(requirement.applies_to_configuration)
                                    ? humanise(String(requirement.applies_to_configuration))
                                    : "All"}
                                </TableCell>
                                <TableCell>
                                  {requirement.is_mandatory ? (
                                    <Badge variant="outline" className="text-[9px]">
                                      Yes
                                    </Badge>
                                  ) : (
                                    <span className="text-muted-foreground">No</span>
                                  )}
                                </TableCell>
                                <TableCell className="text-right">
                                  {requirement.typical_lead_time_months !== null
                                    ? `${String(requirement.typical_lead_time_months)} mo`
                                    : "Not known"}
                                </TableCell>
                              </TableRow>
                            ),
                          )}
                        </TableBody>
                      </Table>
                    </>
                  )}
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>

          {/* Evidence model explained */}
          <Card>
            <CardContent className="p-4">
              <SectionTitle>The six labels, and what each one obliges</SectionTitle>
              <div className="mt-2 grid gap-3 text-[11px] leading-relaxed md:grid-cols-2">
                <dl>
                  {[
                    ["FACT", "Stated in a cited source document, such as a licence or a regulator record. Cite it or do not use it."],
                    ["MEASURED", "An instrument reading in a log, survey or test. The instrument and the date matter."],
                    ["DERIVED", "Computed from measured or documented values by a formula that is published in the trace."],
                  ].map(([label, rule]) => (
                    <div key={label} className="mb-1.5 flex gap-2">
                      <Badge variant="outline" className="h-4 shrink-0 text-[9px]">
                        {label}
                      </Badge>
                      <span className="text-muted-foreground">{rule}</span>
                    </div>
                  ))}
                </dl>
                <dl>
                  {[
                    ["MODELLED", "Output of a published simulation or correlation, not a reading. Show which model."],
                    ["ESTIMATE", "A third-party or analyst estimate with a documented method. Never present it as measured."],
                    ["ASSUMPTION", "A choice made without observation. State the range you would need to change the answer."],
                    ["UNKNOWN", "No defensible value. Shown as unknown, never as zero, and never silently dropped."],
                  ].map(([label, rule]) => (
                    <div key={label} className="mb-1.5 flex gap-2">
                      <Badge variant="outline" className="h-4 shrink-0 text-[9px]">
                        {label}
                      </Badge>
                      <span className="text-muted-foreground">{rule}</span>
                    </div>
                  ))}
                </dl>
              </div>
              <div className="mt-2 border-t pt-2">
                <KeyValueList
                  dense
                  items={[
                    {
                      label: "Row counts",
                      value: Object.entries(datasets.data?.counts ?? {})
                        .map(([key, value]) => `${key}: ${value.toLocaleString("en-GB")}`)
                        .join(" · ") || "Not loaded",
                    },
                  ]}
                />
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}

function DatasetRow({ dataset }: { dataset: Dataset }) {
  return (
    <TableRow className={dataset.is_mock ? "bg-destructive/[0.03]" : undefined}>
      <TableCell>
        <span className="font-medium">{dataset.name}</span>
        {dataset.description && (
          <p className="mt-0.5 max-w-md text-[10px] leading-relaxed text-muted-foreground">
            {dataset.description}
          </p>
        )}
        {dataset.source_url && (
          <a
            href={dataset.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-0.5 inline-flex items-center gap-1 text-[10px] text-primary hover:underline"
          >
            {dataset.source}
            <ExternalLink className="h-2.5 w-2.5" aria-hidden />
          </a>
        )}
      </TableCell>
      <TableCell className="text-muted-foreground">
        {dataset.source}
      </TableCell>
      <TableCell className="font-mono text-[10px]">{dataset.version}</TableCell>
      <TableCell className="text-[10px] text-muted-foreground">
        {dataset.licence ?? "Not recorded"}
      </TableCell>
      <TableCell className="text-right">
        {dataset.row_count !== null ? dataset.row_count.toLocaleString("en-GB") : "—"}
      </TableCell>
      <TableCell className="text-right">
        {dataset.quality_score.toFixed(2)}
      </TableCell>
      <TableCell>
        <Badge variant="outline" className="text-[9px]">
          {humanise(dataset.reliability)}
        </Badge>
      </TableCell>
      <TableCell>
        <span className="flex flex-wrap items-center gap-1">
          <Badge variant="muted" className="text-[9px]">
            {dataset.status}
          </Badge>
          {dataset.is_mock && (
            <Badge variant="outline" className="mock-badge text-[9px]">
              synthetic
            </Badge>
          )}
        </span>
      </TableCell>
      <TableCell className="text-[10px] text-muted-foreground">
        {dataset.last_ingested_at
          ? fmtDate(dataset.last_ingested_at)
          : dataset.download_date
            ? `Downloaded ${fmtDate(dataset.download_date)}`
            : "Never"}
      </TableCell>
    </TableRow>
  );
}

function ParameterRow({ parameter }: { parameter: ParameterSpec }) {
  const value =
    parameter.value === null || parameter.value === undefined
      ? "Not available"
      : typeof parameter.value === "object"
        ? JSON.stringify(parameter.value)
        : String(parameter.value);

  return (
    <TableRow>
      <TableCell className="font-mono text-[10px]">{parameter.key}</TableCell>
      <TableCell className="font-medium">{value}</TableCell>
      <TableCell className="text-muted-foreground">
        {parameter.unit ?? "—"}
      </TableCell>
      <TableCell className="max-w-md text-[10px] leading-relaxed text-muted-foreground">
        {parameter.rationale}
      </TableCell>
      <TableCell>
        {parameter.source ? (
          <span className="text-[10px]">{parameter.source}</span>
        ) : (
          <Badge variant="outline" className="text-[9px]">
            assumption
          </Badge>
        )}
      </TableCell>
      <TableCell className="text-[10px] text-muted-foreground">
        {parameter.low !== null && parameter.high !== null
          ? `${parameter.low} – ${parameter.high}`
          : "—"}
        {parameter.distribution && (
          <span className="block opacity-70">{parameter.distribution}</span>
        )}
      </TableCell>
    </TableRow>
  );
}
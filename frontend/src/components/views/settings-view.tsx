/**
 * Settings and session.
 *
 * Deliberately short. The things a user might expect to change here - discount
 * rate, heat price, flow rate - are engineering inputs, and they belong on the
 * well record where their effect can be seen against a specific result. Putting
 * them in a global settings panel would create numbers that no single result
 * can be traced back to.
 */

"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { LogOut, ShieldCheck } from "lucide-react";

import { PageHeader, EnvironmentStrip } from "@/components/layout/page-header";
import {
  ErrorState,
  KeyValueList,
  Loading,
  Notice,
  SectionTitle,
} from "@/components/common/feedback";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useApiData, useApp } from "@/components/providers/app-provider";
import { api } from "@/lib/api";
import { hasCustomBasemapStyle } from "@/lib/basemap";
import { humanise } from "@/lib/domain";

export function SettingsView() {
  const { user, signOut, isMock } = useApp();
  const router = useRouter();
  const audit = useApiData((signal) => api.auditLog(signal), []);

  return (
    <>
      <PageHeader title="Settings" subtitle="Session, environment and what this build can and cannot do">
        <div className="pt-2">
          <EnvironmentStrip />
        </div>
      </PageHeader>

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="max-w-4xl space-y-4 p-4">
          <Card>
            <CardHeader>
              <CardTitle>Session</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <KeyValueList
                items={[
                  { label: "Signed in as", value: user?.email ?? "Unknown" },
                  {
                    label: "Name",
                    value: user?.full_name ?? "Not recorded",
                  },
                  { label: "Role", value: humanise(user?.role ?? "unknown") },
                  {
                    label: "Tenant",
                    value: user?.tenant_id ?? "Not recorded",
                  },
                ]}
              />
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  signOut();
                  router.replace("/sign-in");
                }}
              >
                <LogOut className="h-3.5 w-3.5" aria-hidden />
                Sign out
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Environment</CardTitle>
              <CardDescription>
                What this deployment is currently running against.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <KeyValueList
                items={[
                  {
                    label: "API base",
                    value: (
                      <code className="font-mono text-xs">
                        {process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1"}
                      </code>
                    ),
                  },
                  {
                    label: "Map renderer",
                    value: hasCustomBasemapStyle
                      ? "MapLibre GL + configured style"
                      : "MapLibre GL + OpenFreeMap vector",
                  },
                  {
                    label: "Synthetic data",
                    value: isMock ? "Loaded — every screen is watermarked" : "Not loaded",
                  },
                ]}
              />
              <p className="text-xs leading-relaxed text-muted-foreground">
                The renderer is MapLibre GL JS (BSD-3-Clause) and the default
                style is OpenFreeMap over OpenStreetMap data. No access token
                and no vendor account are required. If the style host cannot be
                reached the map falls back to OpenStreetMap raster tiles and
                says so; layers, selection and popups behave identically
                either way.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ShieldCheck className="h-4 w-4" aria-hidden />
                What this platform will not do
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="space-y-2 text-xs leading-relaxed text-muted-foreground">
                <li className="flex gap-2">
                  <Badge variant="outline" className="h-4 shrink-0 text-[11px]">
                    no
                  </Badge>
                  <span>
                    Calculate a score. Every number is produced by the
                    deterministic Python engine, and no language model
                    participates in producing one.
                  </span>
                </li>
                <li className="flex gap-2">
                  <Badge variant="outline" className="h-4 shrink-0 text-[11px]">
                    no
                  </Badge>
                  <span>
                    State that a well is commercially viable. Consent,
                    land access, offtake and construction risk sit outside a
                    desk screen, and the agent gate rejects any claim to the
                    contrary.
                  </span>
                </li>
                <li className="flex gap-2">
                  <Badge variant="outline" className="h-4 shrink-0 text-[11px]">
                    no
                  </Badge>
                  <span>
                    Substitute an unknown with a zero, a regional average or a
                    neighbouring well&apos;s value. Unknowns propagate as unknowns
                    and are named in the data gaps list.
                  </span>
                </li>
                <li className="flex gap-2">
                  <Badge variant="outline" className="h-4 shrink-0 text-[11px]">
                    no
                  </Badge>
                  <span>
                    Present synthetic development data as production data. It is
                    watermarked on every view that draws on it.
                  </span>
                </li>
              </ul>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Recent activity for your organisation</CardTitle>
              <CardDescription>
                Audit entries recorded by the API for the current tenant.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {audit.loading && !audit.data && <Loading label="Loading audit log" compact />}
              {audit.error && (
                <ErrorState message={audit.error} onRetry={audit.refresh} />
              )}
              {audit.data && audit.data.entries.length === 0 && (
                <Notice tone="info">
                  No audit entries yet for this tenant. Analyses, project stage
                  changes and well claims are recorded as they happen.
                </Notice>
              )}
              {audit.data && audit.data.entries.length > 0 && (
                <ul className="divide-y text-xs">
                  {audit.data.entries.slice(0, 40).map(
                    (entry: Record<string, unknown>, index: number) => (
                      <li key={index} className="flex items-baseline justify-between gap-3 py-1.5">
                        <span className="min-w-0">
                          <span className="font-medium">
                            {String(entry.action ?? "action")}
                          </span>
                          <span className="ml-2 text-muted-foreground">
                            {String(entry.resource_type ?? "")}{" "}
                            {String(entry.resource_id ?? "").slice(0, 8)}
                          </span>
                        </span>
                        <span className="shrink-0 text-[12px] text-muted-foreground">
                          {entry.created_at ? String(entry.created_at).slice(0, 19).replace("T", " ") : ""}
                        </span>
                      </li>
                    ),
                  )}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4 sm:p-5">
              <SectionTitle>Why there is no global settings panel for prices</SectionTitle>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                Heat price, discount rate, flow rate and electricity price are
                engineering inputs, not preferences. They change CAPEX, OPEX, LCOH
                and the feasibility score, so they are applied per analysis on the
                well record where the effect on a specific number is visible and
                traceable. A global default would produce results whose
                provenance nobody could reconstruct.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}
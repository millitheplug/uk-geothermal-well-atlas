/**
 * Adoption panel.
 *
 * Wells are national reference data with no tenant of their own, and they become
 * visible to an organisation only by being attached to one of its projects. That
 * is a deliberate isolation model, but it leaves the first-run experience with no
 * way forward: you cannot find a well to adopt, because you cannot see any.
 *
 * So the map and the explorer return wells that belong to no project, flagged
 * `claimable: true`, and this panel is what you get when you click one. It states
 * the model plainly and offers the one action that moves you forward, rather
 * than a 404 with no explanation.
 */

"use client";

import * as React from "react";
import Link from "next/link";
import { FolderPlus, Info, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EpistemicBadge } from "@/components/ui/badge";
import { EmptyState, Notice } from "@/components/common/feedback";
import { useApiData } from "@/components/providers/app-provider";
import { api } from "@/lib/api";
import type { Project } from "@/types/api";

export interface UnadoptedWellSummary {
  id: string;
  wellId: string;
  name: string;
  region: string | null;
  status: string | null;
  temperatureC: number | null;
  temperatureStatus?: string | null;
  depthM: number | null;
  claimable: boolean;
}

export function AdoptWellPanel({
  well,
  onAdopted,
  onDismiss,
}: {
  well: UnadoptedWellSummary;
  onAdopted: (wellId: string) => void;
  onDismiss: () => void;
}) {
  const projects = useApiData<Project[]>((signal) => api.listProjects(signal), []);
  const [target, setTarget] = React.useState<string>("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [creating, setCreating] = React.useState(false);
  const [newName, setNewName] = React.useState("");

  const adopt = async (projectId: string) => {
    setBusy(true);
    setError(null);
    try {
      await api.addWellToProject(projectId, well.id);
      onAdopted(well.id);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The well could not be added to that project.",
      );
    } finally {
      setBusy(false);
    }
  };

  const createAndAdopt = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!newName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const project = await api.createProject({ name: newName.trim() });
      await api.addWellToProject(project.id, well.id);
      onAdopted(well.id);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "The project could not be created.",
      );
    } finally {
      setBusy(false);
    }
  };

  const list = projects.data ?? [];

  return (
    <div className="flex h-full flex-col">
      <div className="border-b p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold">{well.name}</h2>
            <p className="truncate font-mono text-[11px] text-muted-foreground">
              {well.wellId}
              {well.region ? ` · ${well.region}` : ""}
            </p>
          </div>
          <Button variant="ghost" size="xs" onClick={onDismiss}>
            Close
          </Button>
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-auto p-4">
        <Notice tone="info" title="Not in your organisation yet">
          <p>
            Wells are national reference data with no owner. Adding one to a
            project of yours is what makes its full record, evidence and analysis
            available to your organisation. Nobody else can see it, and nothing is
            taken away from anyone - this well is in no project at all.
          </p>
        </Notice>

        <Card>
          <CardContent className="space-y-2 p-3">
            <SectionLabel>What the map can show you</SectionLabel>
            <dl className="space-y-1 text-[11px]">
              <Row label="Depth" value={well.depthM !== null ? `${Math.round(well.depthM).toLocaleString("en-GB")} m` : "Not recorded"} />
              <Row
                label="Temperature"
                value={
                  well.temperatureC !== null ? (
                    <span className="inline-flex items-center gap-1">
                      {well.temperatureC.toFixed(1)} °C
                      {well.temperatureStatus && (
                        <EpistemicBadge
                          status={well.temperatureStatus as never}
                        />
                      )}
                    </span>
                  ) : (
                    <span className="italic text-muted-foreground">
                      Not recorded
                    </span>
                  )
                }
              />
              <Row label="Status" value={well.status ?? "Not recorded"} />
            </dl>
            <p className="flex items-start gap-1.5 text-[10px] leading-relaxed text-muted-foreground">
              <Info className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
              These are the fields the map payload carries. The full record, with
              temperature history, integrity status and matched demand, is
              available once the well is yours.
            </p>
          </CardContent>
        </Card>

        {error && (
          <p
            role="alert"
            className="rounded border border-destructive/40 bg-destructive/10 px-2.5 py-2 text-[11px] text-destructive"
          >
            {error}
          </p>
        )}

        {projects.loading && (
          <p className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            Loading your projects…
          </p>
        )}

        {!projects.loading && list.length === 0 && !creating && (
          <EmptyState
            title="You have no projects yet"
            message="Create one to hold wells you are investigating. Projects also group analyses, so this is where a shortlist lives."
            action={
              <Button size="xs" onClick={() => setCreating(true)}>
                <FolderPlus className="h-3.5 w-3.5" aria-hidden />
                Create a project
              </Button>
            }
          />
        )}

        {list.length > 0 && !creating && (
          <div className="space-y-2">
            <div>
              <SectionLabel>Add to an existing project</SectionLabel>
              <div className="mt-1.5 flex gap-2">
                <Select value={target} onValueChange={setTarget}>
                  <SelectTrigger className="h-8 flex-1 text-xs">
                    <SelectValue placeholder="Choose a project" />
                  </SelectTrigger>
                  <SelectContent>
                    {list.map((project) => (
                      <SelectItem
                        key={project.id}
                        value={project.id}
                        className="text-xs"
                      >
                        {project.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  size="sm"
                  disabled={!target || busy}
                  loading={busy}
                  onClick={() => void adopt(target)}
                >
                  Add well
                </Button>
              </div>
            </div>

            <Button variant="ghost" size="xs" onClick={() => setCreating(true)}>
              Or create a new project
            </Button>
          </div>
        )}

        {creating && (
          <form onSubmit={createAndAdopt} className="space-y-2">
            <SectionLabel>New project</SectionLabel>
            <input
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              placeholder="e.g. South West screening"
              aria-label="New project name"
              className="h-8 w-full rounded-md border border-input bg-card px-2.5 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <div className="flex gap-2">
              <Button
                type="submit"
                size="sm"
                disabled={busy || !newName.trim()}
                loading={busy}
              >
                Create and add
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setCreating(false)}
              >
                Cancel
              </Button>
            </div>
          </form>
        )}
      </div>

      <div className="border-t p-3">
        <Link
          href="/pipeline"
          className="text-[11px] text-primary hover:underline"
        >
          Manage projects
        </Link>
      </div>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
      {children}
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
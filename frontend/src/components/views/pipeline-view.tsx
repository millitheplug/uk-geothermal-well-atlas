/**
 * Project pipeline.
 *
 * Projects are the unit of tenancy: a well becomes visible to an organisation
 * once it is attached to one of their projects. This page therefore doubles as
 * the scoping mechanism, which is why adding a well to a project is the primary
 * action rather than a secondary one.
 */

"use client";

import * as React from "react";
import Link from "next/link";
import {
  Archive,
  FolderKanban,
  Plus,
  Trash2,
} from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import {
  EmptyState,
  ErrorState,
  Loading,
  Notice,
  SectionTitle,
} from "@/components/common/feedback";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/primitives";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useApiData } from "@/components/providers/app-provider";
import { api } from "@/lib/api";
import { humanise } from "@/lib/domain";
import { fmtDate } from "@/lib/utils";
import type { Project } from "@/types/api";

const STAGES = [
  "sourcing",
  "screening",
  "due_diligence",
  "validation",
  "feed_study",
  "investment_decision",
  "delivery",
  "operating",
  "closed",
  "rejected",
] as const;

const STAGE_LABELS: Record<string, string> = {
  sourcing: "Sourcing",
  screening: "Screening",
  due_diligence: "Due diligence",
  validation: "Validation",
  feed_study: "Feed study",
  investment_decision: "Investment decision",
  delivery: "Delivery",
  operating: "Operating",
  closed: "Closed",
  rejected: "Rejected",
};

const STAGE_TONE: Record<string, string> = {
  sourcing: "border-border text-muted-foreground",
  screening: "border-primary/40 bg-primary/10 text-primary",
  due_diligence: "border-sky-500/40 bg-sky-500/10 text-sky-600 dark:text-sky-300",
  validation: "border-indigo-500/40 bg-indigo-500/10 text-indigo-600 dark:text-indigo-300",
  feed_study: "border-violet-500/40 bg-violet-500/10 text-violet-600 dark:text-violet-300",
  investment_decision: "border-priority-high/40 bg-priority-high/10 text-priority-high",
  delivery: "border-priority-medium/40 bg-priority-medium/10 text-priority-medium",
  operating: "border-priority-high/40 bg-priority-high/10 text-priority-high",
  closed: "border-border text-muted-foreground",
  rejected: "border-destructive/40 bg-destructive/10 text-destructive",
};

export function PipelineView() {
  const projects = useApiData<Project[]>((signal) => api.listProjects(signal), []);
  const [createOpen, setCreateOpen] = React.useState(false);
  const [busyId, setBusyId] = React.useState<string | null>(null);
  const [actionError, setActionError] = React.useState<string | null>(null);

  const changeStage = async (project: Project, stage: string) => {
    setBusyId(project.id);
    setActionError(null);
    try {
      await api.updateProjectStage(project.id, stage);
      projects.refresh();
    } catch (caught) {
      setActionError(
        caught instanceof Error
          ? caught.message
          : "The stage could not be changed.",
      );
    } finally {
      setBusyId(null);
    }
  };

  const archive = async (project: Project) => {
    setBusyId(project.id);
    setActionError(null);
    try {
      await api.archiveProject(project.id);
      projects.refresh();
    } catch (caught) {
      setActionError(
        caught instanceof Error
          ? caught.message
          : "The project could not be archived.",
      );
    } finally {
      setBusyId(null);
    }
  };

  return (
    <>
      <PageHeader
        title="Project pipeline"
        subtitle="Where each investigation sits, and which wells are in scope"
        actions={
          <Dialog open={createOpen} onOpenChange={setCreateOpen}>
            <DialogTrigger asChild>
              <Button size="sm">
                <Plus className="h-3.5 w-3.5" aria-hidden />
                New project
              </Button>
            </DialogTrigger>
            <CreateProjectDialog
              onCreated={() => {
                projects.refresh();
                setCreateOpen(false);
              }}
            />
          </Dialog>
        }
      />

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="space-y-4 p-4">
          <Notice tone="info" title="Projects define what you can see">
            Wells are national reference data with no owner. Adding a well to a
            project is what makes it visible to your organisation, and running an
            analysis on it attaches the result to your tenant. Nothing here is
            shared with anyone outside your organisation.
          </Notice>

          {projects.loading && !projects.data && <Loading label="Loading projects" />}
          {projects.error && (
            <ErrorState message={projects.error} onRetry={projects.refresh} />
          )}
          {actionError && (
            <ErrorState
              title="That action did not complete"
              message={actionError}
              onRetry={() => setActionError(null)}
            />
          )}

          {projects.data && projects.data.length === 0 && (
            <EmptyState
              title="No projects yet"
              message="Create a project to start tracking wells. A project can hold as many wells as you like and moves through the stages described below."
              action={
                <Button size="sm" onClick={() => setCreateOpen(true)}>
                  <Plus className="h-3.5 w-3.5" aria-hidden />
                  Create the first project
                </Button>
              }
            />
          )}

          <div className="grid gap-3 lg:grid-cols-2">
            {projects.data?.map((project) => (
              <Card key={project.id}>
                <CardHeader>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <CardTitle className="flex items-center gap-1.5">
                        <FolderKanban
                          className="h-3.5 w-3.5 text-muted-foreground"
                          aria-hidden
                        />
                        {project.name}
                      </CardTitle>
                      <p className="mt-0.5 font-mono text-[12px] text-muted-foreground">
                        {project.slug}
                      </p>
                    </div>
                    <Badge
                      className={`shrink-0 text-[11px] ${STAGE_TONE[project.stage] ?? STAGE_TONE.sourcing}`}
                    >
                      {STAGE_LABELS[project.stage] ?? humanise(project.stage)}
                    </Badge>
                  </div>
                  {project.description && (
                    <CardDescription>{project.description}</CardDescription>
                  )}
                </CardHeader>

                <CardContent className="space-y-3">
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                    <div className="flex justify-between">
                      <dt className="text-muted-foreground">Target region</dt>
                      <dd>{project.target_region ?? "Not set"}</dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-muted-foreground">Scenario</dt>
                      <dd>
                        {project.target_scenario
                          ? humanise(project.target_scenario)
                          : "Not set"}
                      </dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-muted-foreground">Created</dt>
                      <dd>{fmtDate(project.created_at)}</dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-muted-foreground">Updated</dt>
                      <dd>{fmtDate(project.updated_at)}</dd>
                    </div>
                  </dl>

                  <div className="border-t pt-2">
                    <SectionTitle>Stage</SectionTitle>
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {STAGES.map((stage) => (
                        <button
                          key={stage}
                          type="button"
                          disabled={busyId === project.id || stage === project.stage}
                          onClick={() => void changeStage(project, stage)}
                          className={`rounded border px-2 py-0.5 text-[12px] transition-colors disabled:cursor-default ${
                            stage === project.stage
                              ? STAGE_TONE[stage]
                              : "border-border text-muted-foreground hover:bg-muted"
                          }`}
                        >
                          {STAGE_LABELS[stage]}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="flex items-center justify-between border-t pt-2">
                    <Link
                      href="/candidates"
                      className="text-xs text-primary hover:underline"
                    >
                      Add wells from the candidate table
                    </Link>
                    <Button
                      variant="ghost"
                      size="xs"
                      disabled={busyId === project.id}
                      onClick={() => void archive(project)}
                    >
                      <Archive className="h-3 w-3" aria-hidden />
                      Archive
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>

          <Card>
            <CardContent className="p-4 sm:p-5">
              <SectionTitle>What the stages mean here</SectionTitle>
              <div className="mt-2 grid gap-3 text-xs leading-relaxed text-muted-foreground sm:grid-cols-2">
                <div>
                  <p className="font-medium text-foreground">Up to screening</p>
                  <p className="mt-0.5">
                    Sourcing, screening and due diligence are desk work. This
                    platform supports the first two: it produces a ranked,
                    evidence-labelled shortlist and a list of what it does not
                    know.
                  </p>
                </div>
                <div>
                  <p className="font-medium text-foreground">
                    Validation onwards
                  </p>
                  <p className="mt-0.5">
                    Validation, feed study, investment decision, delivery and
                    operation are outside anything a screening tool can support.
                    The stage exists so that moving a project past the point where
                    this platform&apos;s output stops being the deciding input is a
                    deliberate act.
                  </p>
                </div>
                <div className="sm:col-span-2">
                  <p className="mt-1 flex items-start gap-1.5">
                    <Trash2 className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                    Archiving keeps the project and its analyses. Nothing is
                    deleted, because an analysis that was run and then withdrawn
                    is part of the record of why a decision was taken.
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}

function CreateProjectDialog({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [region, setRegion] = React.useState<string>("__none__");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.createProject({
        name: name.trim(),
        description: description.trim() || undefined,
        target_region: region === "__none__" ? undefined : region,
      });
      setName("");
      setDescription("");
      setRegion("__none__");
      onCreated();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not create.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <DialogContent>
      <form onSubmit={submit} className="space-y-4">
        <DialogHeader>
          <DialogTitle>New project</DialogTitle>
          <DialogDescription>
            A project groups wells and analyses for one investigation. Only the
            name is required.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-1.5">
          <Label htmlFor="project-name">Name</Label>
          <Input
            id="project-name"
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="e.g. Lincolnshire basin shallow wells"
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="project-region">Target region</Label>
          <Select value={region} onValueChange={setRegion}>
            <SelectTrigger id="project-region">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__">Not set</SelectItem>
              {[
                "South East England",
                "South West England",
                "East Midlands",
                "West Midlands",
                "Yorkshire and the Humber",
                "North West England",
                "North East England",
                "Scotland",
                "Wales",
                "Northern Ireland",
              ].map((value) => (
                <SelectItem key={value} value={value} className="text-xs">
                  {value}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="project-description">Description</Label>
          <textarea
            id="project-description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            rows={3}
            placeholder="What this investigation is trying to establish"
            className="w-full rounded-md border border-input bg-card px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </div>

        {error && (
          <p
            role="alert"
            className="rounded border border-destructive/40 bg-destructive/10 px-2.5 py-2 text-xs text-destructive"
          >
            {error}
          </p>
        )}

        <DialogFooter>
          <Button type="submit" disabled={busy || !name.trim()} loading={busy}>
            Create project
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}

/** Stage definitions are duplicated from the backend enum so the UI can label
 *  them without a round trip. The API validates the value regardless. */
/**
 * Sign-in: "What are you investigating?"
 *
 * The question is asked before the credentials, deliberately. The first thing
 * this platform does is decide what evidence a user needs, and the honest
 * answer differs between someone triaging the whole North Sea onshore fleet and
 * someone who already has one well in mind. Asking first sets the expectations
 * about what the tool can and cannot tell them.
 *
 * The screen also states the two guarantees up front - deterministic
 * engineering, explicit provenance - because a user who has not been told that
 * will read a screening score as a bankable one.
 */

"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  ClipboardCheck,
  FileSearch,
  Flame,
  Globe2,
  KeyRound,
  Loader2,
  MapPinned,
  ShieldQuestion,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/primitives";
import { useApp } from "@/components/providers/app-provider";
import { cn } from "@/lib/utils";

const INVESTIGATIONS = [
  {
    id: "national",
    title: "National screening",
    question: "Where in onshore UK should we look at all?",
    detail:
      "Rank every known well by feasibility and find the regions where the evidence and the engineering line up.",
    icon: Globe2,
    landing: "/dashboard",
  },
  {
    id: "regional",
    title: "Regional shortlist",
    question: "Which wells in a given area are worth a site visit?",
    detail:
      "Filter by region, licence, temperature and depth, then compare the surviving candidates side by side.",
    icon: MapPinned,
    landing: "/candidates",
  },
  {
    id: "well",
    title: "One specific well",
    question: "What can be established about this borehole?",
    detail:
      "Full record with temperature history, integrity status, matched demand and the full calculation trace.",
    icon: FileSearch,
    landing: "/explorer",
  },
  {
    id: "network",
    title: "Heat network or site",
    question: "Can this supply heat to a specific place?",
    detail:
      "Building-level demand, indicative corridors and delivered heat at network flow temperature.",
    icon: Flame,
    landing: "/heat-demand",
  },
] as const;

type InvestigationId = (typeof INVESTIGATIONS)[number]["id"];

export function SignInScreen() {
  const router = useRouter();
  const { signIn, health } = useApp();

  const [focus, setFocus] = React.useState<InvestigationId | null>(null);
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const landing = INVESTIGATIONS.find((item) => item.id === focus)?.landing;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await signIn(email.trim(), password);
      router.replace(landing ?? "/dashboard");
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Sign-in failed.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto grid min-h-screen max-w-6xl gap-10 px-6 py-10 lg:grid-cols-[1.1fr_0.9fr] lg:items-center">
        {/* Left: what this is, and the question */}
        <div>
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded bg-primary text-primary-foreground">
              <Flame className="h-4.5 w-4.5" aria-hidden />
            </div>
            <div>
              <div className="text-sm font-semibold leading-tight">
                UK Geothermal Well Atlas
              </div>
              <div className="text-[11px] text-muted-foreground">
                Screening for well repurposing to geothermal heat
              </div>
            </div>
          </div>

          <h1 className="mt-8 text-2xl font-semibold leading-tight tracking-tight">
            What are you investigating?
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-muted-foreground">
            The answer changes which evidence matters, which parameters carry
            the most weight, and what the platform will refuse to tell you.
          </p>

          <ul className="mt-6 grid gap-2 sm:grid-cols-2">
            {INVESTIGATIONS.map((item) => {
              const Icon = item.icon;
              const selected = focus === item.id;
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => setFocus(item.id)}
                    aria-pressed={selected}
                    className={cn(
                      "flex h-full w-full flex-col gap-1 rounded-md border p-3 text-left transition-colors",
                      selected
                        ? "border-primary bg-primary/5 ring-1 ring-primary"
                        : "hover:border-primary/50 hover:bg-muted/50",
                    )}
                  >
                    <span className="flex items-center gap-1.5 text-xs font-semibold">
                      <Icon className="h-3.5 w-3.5 text-primary" aria-hidden />
                      {item.title}
                    </span>
                    <span className="text-[11px] font-medium text-foreground">
                      {item.question}
                    </span>
                    <span className="text-[11px] leading-relaxed text-muted-foreground">
                      {item.detail}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>

          <div className="mt-8 grid gap-2 sm:grid-cols-2">
            <Guarantee
              icon={ClipboardCheck}
              title="Deterministic engineering"
              body="Every calculation runs in Python with a recorded formula, inputs and units. No language model computes a number, and none can set the score."
            />
            <Guarantee
              icon={ShieldQuestion}
              title="Explicit provenance"
              body="Figures are labelled fact, measured, derived, modelled, estimate, assumption or unknown. An unknown is shown as unknown, never as zero."
            />
          </div>
        </div>

        {/* Right: credentials */}
        <div className="rounded-lg border bg-card p-6 shadow-sm">
          <h2 className="text-sm font-semibold">Sign in</h2>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            Wells are national reference data, but projects and analyses are
            scoped to an organisation. Sign in to see what your team has
            claimed.
          </p>

          <form onSubmit={submit} className="mt-5 space-y-3.5">
            <div className="space-y-1.5">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@organisation.org"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
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

            <Button type="submit" className="w-full" disabled={busy} loading={busy}>
              {busy ? "Signing in…" : "Sign in"}
              {!busy && <ArrowRight aria-hidden />}
            </Button>

            <p className="text-[11px] leading-relaxed text-muted-foreground">
              {focus ? (
                <>
                  You will land on{" "}
                  <strong className="text-foreground">
                    {INVESTIGATIONS.find((item) => item.id === focus)?.title}
                  </strong>
                  . You can change that later.
                </>
              ) : (
                "Choose an investigation to land in the right place, or sign in and pick from the navigation."
              )}
            </p>
          </form>

          <div className="mt-5 space-y-1.5 border-t pt-4 text-[11px] text-muted-foreground">
            <p className="flex items-center gap-1.5 font-medium text-foreground">
              <KeyRound className="h-3 w-3" aria-hidden />
              No account yet?
            </p>
            <p>
              Authentication is never disabled, in any environment, including
              development. A build that runs open locally and closed in
              production is a build where nobody has tested the auth path. From
              the repository root:
            </p>
            <pre className="overflow-x-auto rounded bg-muted p-2 font-mono text-[10px] leading-relaxed">
{`export DATABASE_URL=sqlite:///./geothermal.db
python -m scripts.cli init
python -m scripts.cli bootstrap
python -m scripts.cli seed-user \\
  --email you@example.com \\
  --password "choose-a-strong-one"`}
            </pre>
            <p>
              Then start the API with{" "}
              <code className="rounded bg-muted px-1 font-mono">
                uvicorn app.main:app --reload
              </code>{" "}
              from the <code className="rounded bg-muted px-1 font-mono">backend/</code>{" "}
              directory.
            </p>
            {health && (
              <p className="pt-1">
                Backend {health.version} · {health.database} · spatial{" "}
                {health.spatial_dialect} · interpretation via {health.llm}
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Guarantee({
  icon: Icon,
  title,
  body,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  body: string;
}) {
  return (
    <div className="rounded-md border bg-muted/40 p-3">
      <p className="flex items-center gap-1.5 text-[11px] font-semibold">
        <Icon className="h-3.5 w-3.5 text-primary" aria-hidden />
        {title}
      </p>
      <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
        {body}
      </p>
    </div>
  );
}

/** Spinner used while the session bootstrap is still running. */
export function BootSpinner() {
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
      Loading…
    </div>
  );
}
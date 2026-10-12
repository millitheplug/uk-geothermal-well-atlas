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

import { BrandMark } from "@/components/layout/app-shell";
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
    <div className="flex min-h-dvh flex-col bg-background lg:grid lg:grid-cols-[1.15fr_1fr]">
      {/* Brand and question. Below lg it follows the form, so the first thing a
          phone shows is the way in. */}
      <div className="bg-rail px-5 py-8 text-rail-foreground sm:px-10 lg:order-none lg:flex lg:min-h-dvh lg:flex-col lg:justify-center lg:px-14 lg:py-14 xl:px-20">
        <div className="mx-auto w-full max-w-2xl">
          <div className="flex items-center gap-3">
            <BrandMark className="h-10 w-10" />
            <div>
              <div className="font-display text-[1.625rem]">Well Atlas</div>
              <div className="text-sm text-rail-muted">
                UK Geothermal Well Atlas. Screening for well repurposing to
                geothermal heat
              </div>
            </div>
          </div>

          <h1 className="font-display mt-10 text-[2.25rem] sm:text-[3rem]">
            What are you investigating?
          </h1>
          <p className="voice-note mt-3 max-w-xl text-base text-rail-foreground/80">
            The answer changes which evidence matters, which parameters carry
            the most weight, and what the platform will refuse to tell you.
          </p>

          <ul className="mt-7 grid gap-3 sm:grid-cols-2">
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
                      "flex h-full w-full flex-col gap-1.5 rounded-md border p-4 text-left transition-colors",
                      selected
                        ? "border-accent bg-rail-active ring-1 ring-accent"
                        : "border-rail-border bg-rail-active/40 hover:border-rail-muted hover:bg-rail-active/70",
                    )}
                  >
                    <span className="flex items-center gap-2 text-sm font-semibold text-white">
                      <Icon className="h-4 w-4 text-accent" aria-hidden />
                      {item.title}
                    </span>
                    <span className="text-sm font-medium text-rail-foreground">
                      {item.question}
                    </span>
                    <span className="voice-note text-[0.8125rem] text-rail-muted">
                      {item.detail}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>

          <div className="mt-8 grid gap-3 sm:grid-cols-2">
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

        </div>

      {/* Credentials. First on a phone, second on a wide screen. */}
      <div className="order-first flex items-center justify-center px-5 py-8 sm:px-10 lg:order-none lg:min-h-dvh lg:px-12">
        <div className="w-full max-w-md">
          <h2 className="font-display text-[2rem]">Sign in</h2>
          <p className="voice-note mt-2 text-[0.9375rem] text-muted-foreground">
            Wells are national reference data, but projects and analyses are
            scoped to an organisation. Sign in to see what your team has
            claimed.
          </p>

          <form onSubmit={submit} className="mt-6 space-y-4">
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
                className="rounded-md border border-l-4 border-destructive/30 border-l-destructive bg-destructive/10 px-3 py-2.5 text-sm text-foreground"
              >
                {error}
              </p>
            )}

            <Button type="submit" size="lg" className="w-full" disabled={busy} loading={busy}>
              {busy ? "Signing in…" : "Sign in"}
              {!busy && <ArrowRight aria-hidden />}
            </Button>

            <p className="voice-note text-[0.8125rem] text-muted-foreground">
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

          <details className="group mt-6 border-t pt-4 text-sm text-muted-foreground">
            <summary className="flex min-h-10 cursor-pointer list-none items-center gap-2 font-medium text-foreground [&::-webkit-details-marker]:hidden">
              <KeyRound className="h-4 w-4" aria-hidden />
              No account yet?
              <span className="ml-auto text-xs font-normal text-muted-foreground group-open:hidden">
                Show setup steps
              </span>
            </summary>
            <div className="mt-2 space-y-2">
            <p>
              Authentication is never disabled, in any environment, including
              development. A build that runs open locally and closed in
              production is a build where nobody has tested the auth path. From
              the repository root:
            </p>
            <pre className="overflow-x-auto rounded bg-muted p-2 font-mono text-[12px] leading-relaxed">
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
              <p className="pt-1 text-xs">
                Backend {health.version} · {health.database} · spatial{" "}
                {health.spatial_dialect} · interpretation via {health.llm}
              </p>
            )}
            </div>
          </details>
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
    <div className="rounded-md border border-dashed border-rail-border p-4">
      <p className="flex items-center gap-2 text-sm font-semibold text-white">
        <Icon className="h-4 w-4 text-accent" aria-hidden />
        {title}
      </p>
      <p className="voice-note mt-1.5 text-[0.8125rem] text-rail-muted">
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
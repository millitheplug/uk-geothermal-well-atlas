/**
 * Registration: "What does this account actually get?"
 *
 * A sign-up is the one moment where a stranger can create rows in the
 * database, so the screen says plainly what is being created: an organisation
 * of their own, containing nothing yet. The alternative is a person landing on
 * an empty dashboard and reasonably concluding the platform is broken.
 *
 * The guarantees shown before sign-in are not repeated here. What matters at
 * this point is scope and honesty about the address - an unknown must still be
 * shown as unknown when it is a field on a form.
 */

"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Globe2, Lock, ShieldQuestion } from "lucide-react";

import { BrandMark } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/primitives";
import { useApp } from "@/components/providers/app-provider";

/**
 * Kept in step with ``RegisterRequest`` in ``app/schemas/well.py`` and with
 * ``validate_password_strength``: all three demand 12 characters. Promising
 * fewer here and rejecting it at the API would be a form that contradicts its
 * own label.
 */
const MIN_PASSWORD = 12;

const WHAT_YOU_GET = [
  {
    icon: Lock,
    title: "An organisation of your own",
    body: "Projects and analyses belong to the account you create here. Nothing of anyone else's is visible from it, and yours is not visible to them.",
  },
  {
    icon: Globe2,
    title: "The national wells are open",
    body: "Onshore well records are national reference data, visible to every account. A well only joins your projects when you adopt it - that has not happened yet.",
  },
  {
    icon: ShieldQuestion,
    title: "No address is verified",
    body: "There is no mail service behind this platform, so nothing checks your email and nothing claims it was checked. The account works as soon as it is created.",
  },
];

export function SignUpScreen() {
  const router = useRouter();
  const { signUp } = useApp();

  const [fullName, setFullName] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [organisation, setOrganisation] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await signUp({
        email: email.trim(),
        password,
        full_name: fullName.trim(),
        organisation: organisation.trim(),
      });
      router.replace("/dashboard");
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Could not create the account.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-dvh flex-col bg-background lg:grid lg:grid-cols-[1.15fr_1fr]">
      {/* What is being created. Below lg it follows the form, so a phone shows
          the way in first, exactly as sign-in does. */}
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
            Create an organisation
          </h1>
          <p className="voice-note mt-3 max-w-xl text-base text-rail-foreground/80">
            One sign-up makes an organisation and the account that administers
            it. It starts empty, because that is the true state of it - the
            platform reports what is there rather than filling the gap with a
            number.
          </p>

          <ul className="mt-7 grid gap-3">
            {WHAT_YOU_GET.map((item) => {
              const Icon = item.icon;
              return (
                <li
                  key={item.title}
                  className="rounded-md border border-rail-border bg-rail-active/40 p-4"
                >
                  <span className="flex items-center gap-2 text-sm font-semibold text-white">
                    <Icon className="h-4 w-4 text-accent" aria-hidden />
                    {item.title}
                  </span>
                  <span className="voice-note mt-1.5 block text-[0.8125rem] text-rail-muted">
                    {item.body}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      </div>

      {/* The form itself. */}
      <div className="flex items-center justify-center px-5 py-8 sm:px-10 lg:order-none lg:min-h-dvh lg:px-12">
        <div className="w-full max-w-md">
          <h2 className="font-display text-[2rem]">Create account</h2>
          <p className="voice-note mt-2 text-[0.9375rem] text-muted-foreground">
            Both names on the form are optional - only an email and a password
            are needed to start.
          </p>

          <form onSubmit={submit} className="mt-6 space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="full_name">Your name</Label>
              <Input
                id="full_name"
                type="text"
                autoComplete="name"
                value={fullName}
                onChange={(event) => setFullName(event.target.value)}
                placeholder="Optional - defaults to your email name"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="signup-email">Email</Label>
              <Input
                id="signup-email"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@organisation.org"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="organisation">Organisation</Label>
              <Input
                id="organisation"
                type="text"
                autoComplete="organization"
                value={organisation}
                onChange={(event) => setOrganisation(event.target.value)}
                placeholder="Optional - names your new organisation"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="signup-password">Password</Label>
              <Input
                id="signup-password"
                type="password"
                autoComplete="new-password"
                required
                minLength={MIN_PASSWORD}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
              <p className="voice-note text-[0.8125rem] text-muted-foreground">
                At least {MIN_PASSWORD} characters. Length matters more than
                symbols, so a passphrase is enough.
              </p>
            </div>

            {error && (
              <p
                role="alert"
                className="rounded-md border border-l-4 border-destructive/30 border-l-destructive bg-destructive/10 px-3 py-2.5 text-sm text-foreground"
              >
                {error}
              </p>
            )}

            <Button
              type="submit"
              size="lg"
              className="w-full"
              disabled={busy}
              loading={busy}
            >
              {busy ? "Creating account…" : "Create account"}
              {!busy && <ArrowRight aria-hidden />}
            </Button>

            <p className="voice-note text-[0.8125rem] text-muted-foreground">
              You will be signed in immediately and land on your dashboard with
              the national wells in view.
            </p>
          </form>

          <p className="mt-6 border-t pt-4 text-sm text-muted-foreground">
            Already registered?{" "}
            <Link
              href="/sign-in"
              className="font-medium text-foreground underline underline-offset-4"
            >
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}

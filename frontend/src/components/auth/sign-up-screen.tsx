/**
 * Sign-up: create an account and a private organisation.
 *
 * Every registration makes a new organisation with the registrant as its owner,
 * so a new account never lands inside someone else's workspace. The screen says
 * so before the form is filled in, because "organisation" otherwise reads as
 * "pick a team to join".
 *
 * On success the API has already signed the new user in, so the screen goes
 * straight to the dashboard.
 */

"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Building2, ShieldCheck } from "lucide-react";

import { BrandMark } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/primitives";
import { useApp } from "@/components/providers/app-provider";
import { ApiError } from "@/lib/api";

/** Mirrors the API's password policy so most mistakes are caught before sending. */
const MIN_PASSWORD_LENGTH = 12;

type Field = "full_name" | "email" | "organisation" | "password" | "password_confirm";

function validate(values: Record<Field, string>): Partial<Record<Field, string>> {
  const problems: Partial<Record<Field, string>> = {};
  if (!values.full_name.trim()) problems.full_name = "Enter your name.";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(values.email.trim())) {
    problems.email = "Enter a valid email address.";
  }
  if (values.organisation.trim().length < 2) {
    problems.organisation = "Enter your organisation's name.";
  }
  if (values.password.length < MIN_PASSWORD_LENGTH) {
    problems.password = `Use at least ${MIN_PASSWORD_LENGTH} characters. A short sentence works well.`;
  }
  if (values.password_confirm !== values.password) {
    problems.password_confirm = "The two passwords do not match.";
  }
  return problems;
}

export function SignUpScreen() {
  const router = useRouter();
  const { register } = useApp();

  const [values, setValues] = React.useState<Record<Field, string>>({
    full_name: "",
    email: "",
    organisation: "",
    password: "",
    password_confirm: "",
  });
  const [fieldErrors, setFieldErrors] = React.useState<
    Partial<Record<Field, string>>
  >({});
  const [error, setError] = React.useState<string | null>(null);
  const [emailTaken, setEmailTaken] = React.useState(false);
  const [busy, setBusy] = React.useState(false);

  const set = (field: Field) => (event: React.ChangeEvent<HTMLInputElement>) => {
    const next = event.target.value;
    setValues((current) => ({ ...current, [field]: next }));
    setFieldErrors((current) => ({ ...current, [field]: undefined }));
    if (field === "email") setEmailTaken(false);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setEmailTaken(false);

    const problems = validate(values);
    setFieldErrors(problems);
    if (Object.keys(problems).length > 0) return;

    setBusy(true);
    try {
      await register({
        full_name: values.full_name.trim(),
        email: values.email.trim(),
        organisation: values.organisation.trim(),
        password: values.password,
        password_confirm: values.password_confirm,
      });
      router.replace("/dashboard");
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        setEmailTaken(true);
      } else if (caught instanceof ApiError && caught.isRateLimited) {
        setError("Too many attempts. Wait a minute and try again.");
      } else {
        setError(
          caught instanceof Error ? caught.message : "Sign-up failed.",
        );
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-dvh flex-col bg-background lg:grid lg:grid-cols-[1.15fr_1fr]">
      <div className="bg-rail px-5 py-8 text-rail-foreground sm:px-10 lg:flex lg:min-h-dvh lg:flex-col lg:justify-center lg:px-14 lg:py-14 xl:px-20">
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
            Start your own workspace
          </h1>
          <p className="voice-note mt-3 max-w-xl text-base text-rail-foreground/80">
            Creating an account also creates a new organisation with you as its
            owner. Your projects and assessments belong to that organisation and
            are not visible to anyone outside it.
          </p>

          <div className="mt-8 grid gap-3 sm:grid-cols-2">
            <Note
              icon={Building2}
              title="A workspace of your own"
              body="You are not added to anyone else's organisation. Wells are shared national reference data; what you do with them is private."
            />
            <Note
              icon={ShieldCheck}
              title="Passwords are never stored"
              body="Only a salted hash is kept. Your email and the IP address and browser of sign-ins are recorded for access control and audit."
            />
          </div>
        </div>
      </div>

      <div className="order-first flex items-center justify-center px-5 py-8 sm:px-10 lg:order-none lg:min-h-dvh lg:px-12">
        <div className="w-full max-w-md">
          <h2 className="font-display text-[2rem]">Create an account</h2>
          <p className="voice-note mt-2 text-[0.9375rem] text-muted-foreground">
            It takes a minute. You will be signed in as soon as it is done.
          </p>

          <form onSubmit={submit} noValidate className="mt-6 space-y-4">
            <TextField
              id="full_name"
              label="Your name"
              autoComplete="name"
              value={values.full_name}
              onChange={set("full_name")}
              error={fieldErrors.full_name}
            />
            <TextField
              id="email"
              label="Email"
              type="email"
              autoComplete="username"
              placeholder="you@organisation.org"
              value={values.email}
              onChange={set("email")}
              error={fieldErrors.email}
            />
            <TextField
              id="organisation"
              label="Organisation"
              autoComplete="organization"
              value={values.organisation}
              onChange={set("organisation")}
              error={fieldErrors.organisation}
              hint="This becomes your private workspace."
            />
            <TextField
              id="password"
              label="Password"
              type="password"
              autoComplete="new-password"
              value={values.password}
              onChange={set("password")}
              error={fieldErrors.password}
              hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
            />
            <TextField
              id="password_confirm"
              label="Confirm password"
              type="password"
              autoComplete="new-password"
              value={values.password_confirm}
              onChange={set("password_confirm")}
              error={fieldErrors.password_confirm}
            />

            {emailTaken && (
              <p
                role="alert"
                className="rounded-md border border-l-4 border-destructive/30 border-l-destructive bg-destructive/10 px-3 py-2.5 text-sm text-foreground"
              >
                An account with this email already exists.{" "}
                <Link href="/sign-in" className="font-medium underline">
                  Sign in instead
                </Link>
                .
              </p>
            )}

            {error && (
              <p
                role="alert"
                className="rounded-md border border-l-4 border-destructive/30 border-l-destructive bg-destructive/10 px-3 py-2.5 text-sm text-foreground"
              >
                {error}
              </p>
            )}

            <Button type="submit" size="lg" className="w-full" disabled={busy} loading={busy}>
              {busy ? "Creating your account…" : "Create account"}
              {!busy && <ArrowRight aria-hidden />}
            </Button>
          </form>

          <p className="mt-6 border-t pt-4 text-sm text-muted-foreground">
            Already have an account?{" "}
            <Link href="/sign-in" className="font-medium text-foreground underline">
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}

function TextField({
  id,
  label,
  error,
  hint,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement> & {
  id: string;
  label: string;
  error?: string;
  hint?: string;
}) {
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        name={id}
        required
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        {...props}
      />
      {error ? (
        <p id={`${id}-error`} role="alert" className="text-[0.8125rem] text-destructive">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-[0.8125rem] text-muted-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

function Note({
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
      <p className="voice-note mt-1.5 text-[0.8125rem] text-rail-muted">{body}</p>
    </div>
  );
}

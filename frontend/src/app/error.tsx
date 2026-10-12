"use client";

import * as React from "react";
import { RotateCcw, ServerCrash } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

/**
 * Route-level error boundary.
 *
 * Shows the actual error rather than a generic apology. If the backend
 * returned a validation failure explaining which field was wrong, that message
 * is the most useful thing on the screen, and hiding it behind "something went
 * wrong" makes the platform harder to trust and to debug.
 */
export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  React.useEffect(() => {
    // Left to the browser console rather than a logging service: this build has
    // no telemetry, and pretending otherwise would be its own small dishonesty.
    console.error(error);
  }, [error]);

  const isNetwork =
    error.message.includes("Could not reach") ||
    error.message.includes("Failed to fetch");

  return (
    <div className="flex min-h-[60vh] items-center justify-center p-6">
      <Card className="max-w-xl">
        <CardContent className="p-5">
          <div className="flex items-start gap-2.5">
            <ServerCrash className="mt-0.5 h-5 w-5 shrink-0 text-destructive" aria-hidden />
            <div className="min-w-0">
              <h1 className="text-sm font-semibold">
                {isNetwork
                  ? "The API could not be reached"
                  : "Something went wrong on this view"}
              </h1>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                {isNetwork
                  ? "No data was returned. Check that the backend is running, then try again."
                  : "The error below is reproduced verbatim. No figure on this screen should be relied on until the cause is understood."}
              </p>
            </div>
          </div>

          <pre className="mt-3 max-h-40 overflow-auto whitespace-pre-wrap rounded-md border bg-muted/50 p-2.5 font-mono text-[12px] leading-relaxed text-destructive">
            {error.message}
            {error.digest && `\n\ndigest: ${error.digest}`}
          </pre>

          <Button size="sm" className="mt-3" onClick={reset}>
            <RotateCcw className="h-3.5 w-3.5" aria-hidden />
            Try again
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
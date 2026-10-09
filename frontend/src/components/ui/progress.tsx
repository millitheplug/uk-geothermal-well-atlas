"use client";

import * as React from "react";
import * as ProgressPrimitive from "@radix-ui/react-progress";

import { cn } from "@/lib/utils";

const Progress = React.forwardRef<
  React.ElementRef<typeof ProgressPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root> & {
    /** Optional status colour; defaults to the primary accent. */
    tone?: "default" | "high" | "medium" | "low" | "none";
  }
>(({ className, value, tone = "default", ...props }, ref) => {
  const colour =
    tone === "high"
      ? "bg-priority-high"
      : tone === "medium"
        ? "bg-priority-medium"
        : tone === "low"
          ? "bg-priority-low"
          : tone === "none"
            ? "bg-priority-none"
            : "bg-primary";

  return (
    <ProgressPrimitive.Root
      ref={ref}
      className={cn(
        "relative h-2 w-full overflow-hidden rounded-full bg-muted",
        className,
      )}
      value={value}
      {...props}
    >
      <ProgressPrimitive.Indicator
        className={cn("h-full w-full flex-1 transition-transform", colour)}
        style={{ transform: `translateX(-${100 - (value ?? 0)}%)` }}
      />
    </ProgressPrimitive.Root>
  );
});
Progress.displayName = ProgressPrimitive.Root.displayName;

export { Progress };

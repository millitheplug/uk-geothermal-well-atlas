import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        destructive:
          "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        /** The single bright call to action on a screen. */
        accent: "bg-accent text-accent-foreground hover:bg-accent/85",
        outline:
          "border border-input bg-card hover:bg-muted hover:text-foreground",
        secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        ghost: "hover:bg-muted hover:text-foreground",
        link: "text-primary underline-offset-4 hover:underline",
        /** Used on the map: high contrast against arbitrary basemap imagery. */
        map: "border border-white/30 bg-slate-900/85 text-white shadow-md backdrop-blur hover:bg-slate-900/95",
      },
      size: {
        // 40px on touch screens, 36px with a pointer: comfortable to tap,
        // still compact in a dense table toolbar.
        default: "h-10 px-4 py-2 md:h-9",
        sm: "h-9 rounded-md px-3 text-xs md:h-8",
        xs: "h-8 rounded px-2.5 text-xs md:h-7",
        lg: "h-11 rounded-md px-8 md:h-10",
        icon: "h-10 w-10 md:h-9 md:w-9",
        "icon-sm": "h-8 w-8 md:h-7 md:w-7",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  /** Render the child element instead of a <button>, keeping the styling. */
  asChild?: boolean;
  /** Show a spinner and disable the button. */
  loading?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    { className, variant, size, asChild = false, loading = false, children, disabled, ...props },
    ref,
  ) => {
    const Comp = asChild ? Slot : "button";

    // `asChild` forwards to a single child, so the spinner cannot be injected -
    // a link with a spinner inside would render an invalid anchor. Callers using
    // asChild should render their own pending state.
    if (asChild) {
      return (
        <Comp
          className={cn(buttonVariants({ variant, size }), className)}
          ref={ref}
          {...props}
        >
          {children}
        </Comp>
      );
    }

    return (
      <Comp
        className={cn(buttonVariants({ variant, size }), className)}
        ref={ref}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        {...props}
      >
        {loading && <Loader2 className="animate-spin" aria-hidden />}
        {children}
      </Comp>
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
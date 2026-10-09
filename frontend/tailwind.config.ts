import type { Config } from "tailwindcss";

/**
 * Design tokens.
 *
 * Two constraints drive the palette:
 *
 * 1. Epistemic status must be legible at a glance and colour-blind safe. Status
 *    is never signalled by hue alone - every status also carries a label and an
 *    icon, which is why the semantic scale below is deliberately narrow and
 *    high-contrast against the surface rather than expressive.
 * 2. Score colours must be *ordered*, because the map colours wells by score.
 *    A perceptual ramp (viridis-like) is used instead of a rainbow: adjacent
 *    bands are distinguishable, and the ordering survives greyscale printing
 *    and the common red-green colour deficiencies.
 */
const config: Config = {
  darkMode: ["class"],
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: { "2xl": "1400px" },
    },
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        /** Recommendation levels, per the specification's four bands. */
        priority: {
          high: "hsl(var(--priority-high))",
          medium: "hsl(var(--priority-medium))",
          low: "hsl(var(--priority-low))",
          none: "hsl(var(--priority-none))",
        },
        /** The six epistemic labels. */
        epistemic: {
          fact: "hsl(var(--ep-fact))",
          measured: "hsl(var(--ep-measured))",
          derived: "hsl(var(--ep-derived))",
          estimate: "hsl(var(--ep-estimate))",
          modelled: "hsl(var(--ep-modelled))",
          assumption: "hsl(var(--ep-assumption))",
          unknown: "hsl(var(--ep-unknown))",
        },
        /** Ordered ramp for feasibility scores, 0-100. */
        score: {
          0: "hsl(var(--score-0))",
          20: "hsl(var(--score-20))",
          40: "hsl(var(--score-40))",
          60: "hsl(var(--score-60))",
          80: "hsl(var(--score-80))",
          100: "hsl(var(--score-100))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        "fade-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "fade-in": "fade-in 0.25s ease-out",
        shimmer: "shimmer 1.6s infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;

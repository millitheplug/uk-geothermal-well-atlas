import type { Metadata } from "next";
import { Archivo, JetBrains_Mono, Source_Serif_4 } from "next/font/google";

import { AppChrome } from "@/components/layout/app-chrome";
import { AppProvider } from "@/components/providers/app-provider";
import { TooltipProvider } from "@/components/ui/tooltip";
// Base stylesheet for the map renderer: popup positioning, controls and the
// attribution control. Imported ahead of globals.css so this file's theme
// overrides win the cascade at equal specificity.
import "maplibre-gl/dist/maplibre-gl.css";
import "./globals.css";

// One grotesque with a width axis: condensed for titles and figures, normal
// width for the interface. A serif carries the explanatory notes.
const sans = Archivo({
  subsets: ["latin"],
  axes: ["wdth"],
  variable: "--font-sans",
  display: "swap",
});

const serif = Source_Serif_4({
  subsets: ["latin"],
  weight: ["400", "600"],
  style: ["normal", "italic"],
  variable: "--font-serif",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "UK Geothermal Well Atlas",
    template: "%s | UK Geothermal Well Atlas",
  },
  description:
    "Screening platform for repurposing UK onshore oil, gas and exploration wells to geothermal heat production and district heating.",
  robots: {
    // A screening tool for a specific operational area has no business in a
    // public index, and the development dataset must not be indexed at all.
    index: false,
    follow: false,
  },
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  // Lets fixed bars sit under the notch and home indicator (see .pb-safe).
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#14202b" },
    { media: "(prefers-color-scheme: dark)", color: "#0a1016" },
  ],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en-GB" suppressHydrationWarning>
      <body className={`${sans.variable} ${serif.variable} ${mono.variable} font-sans antialiased`}>
        <AppProvider>
          <TooltipProvider delayDuration={200}>
            <AppChrome>{children}</AppChrome>
          </TooltipProvider>
        </AppProvider>
      </body>
    </html>
  );
}
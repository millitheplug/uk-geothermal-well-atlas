import type { Metadata } from "next";

import { MapWorkspace } from "@/components/map/map-workspace";
import { PageScroll } from "@/components/layout/app-chrome";

export const metadata: Metadata = {
  title: "National map",
  description:
    "Every known onshore UK oil, gas and exploration well, positioned and coloured by deterministic feasibility score.",
};

export default function MapPage() {
  return (
    <PageScroll className="flex">
      <MapWorkspace />
    </PageScroll>
  );
}
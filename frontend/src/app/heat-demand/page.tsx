import type { Metadata } from "next";

import { PageScroll } from "@/components/layout/app-chrome";
import { HeatDemandView } from "@/components/views/heat-demand-view";

export const metadata: Metadata = { title: "Heat demand" };

export default function HeatDemandPage() {
  return (
    <PageScroll className="flex flex-col">
      <HeatDemandView />
    </PageScroll>
  );
}
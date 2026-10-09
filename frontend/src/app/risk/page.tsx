import type { Metadata } from "next";

import { PageScroll } from "@/components/layout/app-chrome";
import { RiskView } from "@/components/views/risk-view";

export const metadata: Metadata = { title: "Risk register" };

export default function RiskPage() {
  return (
    <PageScroll className="flex flex-col">
      <RiskView />
    </PageScroll>
  );
}
import type { Metadata } from "next";

import { PageScroll } from "@/components/layout/app-chrome";
import { FinancialsView } from "@/components/views/financials-view";

export const metadata: Metadata = { title: "Financials" };

export default function FinancialsPage() {
  return (
    <PageScroll className="flex flex-col">
      <FinancialsView />
    </PageScroll>
  );
}
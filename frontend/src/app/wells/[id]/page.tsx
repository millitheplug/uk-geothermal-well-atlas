import type { Metadata } from "next";

import { PageScroll } from "@/components/layout/app-chrome";
import { WellDetailView } from "@/components/views/well-detail-view";

export const metadata: Metadata = { title: "Well record" };

export default function WellDetailPage() {
  return (
    <PageScroll className="flex flex-col">
      <WellDetailView />
    </PageScroll>
  );
}
import type { Metadata } from "next";

import { PageScroll } from "@/components/layout/app-chrome";
import { DashboardView } from "@/components/views/dashboard-view";

export const metadata: Metadata = { title: "National dashboard" };

export default function DashboardPage() {
  return (
    <PageScroll className="flex flex-col">
      <DashboardView />
    </PageScroll>
  );
}
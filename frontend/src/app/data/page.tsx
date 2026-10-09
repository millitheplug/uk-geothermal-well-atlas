import type { Metadata } from "next";

import { PageScroll } from "@/components/layout/app-chrome";
import { DataSourcesView } from "@/components/views/data-sources-view";

export const metadata: Metadata = { title: "Data sources" };

export default function DataPage() {
  return (
    <PageScroll className="flex flex-col">
      <DataSourcesView />
    </PageScroll>
  );
}
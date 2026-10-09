import type { Metadata } from "next";

import { PageScroll } from "@/components/layout/app-chrome";
import { ExplorerView } from "@/components/views/explorer-view";

export const metadata: Metadata = { title: "Well explorer" };

export default function ExplorerPage() {
  return (
    <PageScroll className="flex flex-col">
      <ExplorerView />
    </PageScroll>
  );
}
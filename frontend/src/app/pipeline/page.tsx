import type { Metadata } from "next";

import { PageScroll } from "@/components/layout/app-chrome";
import { PipelineView } from "@/components/views/pipeline-view";

export const metadata: Metadata = { title: "Projects" };

export default function PipelinePage() {
  return (
    <PageScroll className="flex flex-col">
      <PipelineView />
    </PageScroll>
  );
}
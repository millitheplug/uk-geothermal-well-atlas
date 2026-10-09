import type { Metadata } from "next";

import { PageScroll } from "@/components/layout/app-chrome";
import { CandidatesView } from "@/components/views/candidates-view";

export const metadata: Metadata = { title: "Candidate ranking" };

export default function CandidatesPage() {
  return (
    <PageScroll className="flex flex-col">
      <CandidatesView />
    </PageScroll>
  );
}
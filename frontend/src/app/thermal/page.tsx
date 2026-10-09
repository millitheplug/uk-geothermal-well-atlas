import type { Metadata } from "next";

import { PageScroll } from "@/components/layout/app-chrome";
import { ThermalView } from "@/components/views/thermal-view";

export const metadata: Metadata = { title: "Thermal analysis" };

export default function ThermalPage() {
  return (
    <PageScroll className="flex flex-col">
      <ThermalView />
    </PageScroll>
  );
}
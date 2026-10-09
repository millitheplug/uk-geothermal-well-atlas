import type { Metadata } from "next";

import { PageScroll } from "@/components/layout/app-chrome";
import { SettingsView } from "@/components/views/settings-view";

export const metadata: Metadata = { title: "Settings" };

export default function SettingsPage() {
  return (
    <PageScroll className="flex flex-col">
      <SettingsView />
    </PageScroll>
  );
}
import Link from "next/link";
import { Compass } from "lucide-react";

import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 p-6 text-center">
      <Compass className="h-8 w-8 text-muted-foreground" aria-hidden />
      <h1 className="text-lg font-semibold">That page does not exist</h1>
      <p className="max-w-md text-sm leading-relaxed text-muted-foreground">
        If you followed a link to a well record, the well may not be visible to
        your organisation: wells are national reference data but become visible
        once they are attached to one of your projects or analyses.
      </p>
      <div className="mt-2 flex gap-2">
        <Button size="sm" asChild>
          <Link href="/">Open the map</Link>
        </Button>
        <Button size="sm" variant="outline" asChild>
          <Link href="/explorer">Search the well inventory</Link>
        </Button>
      </div>
    </div>
  );
}
import type { ReactNode } from "react";

import { AppErrorBoundary } from "@/shared/ui/AppErrorBoundary";
import "@/shared/i18n";
import { StaticUiBridge } from "@/shared/i18n/StaticUiBridge";

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <StaticUiBridge>
      <AppErrorBoundary>{children}</AppErrorBoundary>
    </StaticUiBridge>
  );
}

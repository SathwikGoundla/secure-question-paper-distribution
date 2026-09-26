import type { ReactNode } from "react";

export function PageContainer({ children }: { children: ReactNode }) {
  return <main className="page-container">{children}</main>;
}

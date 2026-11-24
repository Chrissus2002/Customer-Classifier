import type { ReactNode } from "react";
import { SidebarNav } from "./SidebarNav";
import { PageHeader } from "./PageHeader";

type Breadcrumb = {
  label: string;
  to?: string;
};

type AppShellProps = {
  eyebrow: string;
  title: string;
  description: string;
  breadcrumbs?: Breadcrumb[];
  actions?: ReactNode;
  children: ReactNode;
};

export function AppShell({
  eyebrow,
  title,
  description,
  breadcrumbs = [],
  actions,
  children,
}: AppShellProps) {
  return (
    <div className="app-shell">
      <header className="workspace-topbar">
        <div className="workspace-brand">
          <span className="eyebrow">Dialo</span>
          <strong>Journey Builder</strong>
        </div>
        <SidebarNav />
      </header>

      <main className="main-panel app-shell__main">
        <PageHeader
          eyebrow={eyebrow}
          title={title}
          description={description}
          breadcrumbs={breadcrumbs}
          actions={actions}
        />
        {children}
      </main>
    </div>
  );
}

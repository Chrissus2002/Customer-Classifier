import type { ReactNode } from "react";
import { Link } from "react-router-dom";

type Breadcrumb = {
  label: string;
  to?: string;
};

type PageHeaderProps = {
  eyebrow: string;
  title: string;
  description: string;
  breadcrumbs?: Breadcrumb[];
  actions?: ReactNode;
};

export function PageHeader({ eyebrow, title, description, breadcrumbs = [], actions }: PageHeaderProps) {
  return (
    <header className="page-header">
      <div className="page-header-copy">
        {breadcrumbs.length > 0 && (
          <nav className="breadcrumbs" aria-label="Breadcrumb">
            {breadcrumbs.map((breadcrumb, index) => (
              <span key={`${breadcrumb.label}-${index}`} className="breadcrumb-item">
                {breadcrumb.to ? <Link to={breadcrumb.to}>{breadcrumb.label}</Link> : <span>{breadcrumb.label}</span>}
                {index < breadcrumbs.length - 1 ? <span className="breadcrumb-separator">/</span> : null}
              </span>
            ))}
          </nav>
        )}
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actions ? <div className="header-actions">{actions}</div> : null}
    </header>
  );
}

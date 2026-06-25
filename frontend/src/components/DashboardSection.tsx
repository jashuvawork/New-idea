import { ReactNode } from 'react';

export function DashboardSection({
  title,
  subtitle,
  children,
  className = '',
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`space-y-3 ${className}`}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-nexus-border/70 pb-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.18em] text-nexus-accent">
          {title}
        </h2>
        {subtitle ? <p className="text-[10px] text-nexus-muted">{subtitle}</p> : null}
      </div>
      <div className="grid grid-cols-12 gap-3">{children}</div>
    </section>
  );
}

import type { ReactNode } from "react";

export function PageHeader({
  eyebrow,
  title,
  description,
  action
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="border-b border-slate-200/80 px-6 py-6 md:px-8">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div className="max-w-2xl">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-accent">
            {eyebrow}
          </p>
          <h2 className="mt-2 text-3xl font-semibold tracking-tight text-ink">{title}</h2>
          <p className="mt-3 text-sm leading-6 text-slate-600">{description}</p>
        </div>
        {action ? <div>{action}</div> : null}
      </div>
    </div>
  );
}

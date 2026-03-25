"use client";

import Link from "next/link";
import { useProjects } from "@/lib/hooks";
import { StatusBadge } from "@/components/ui/status-badge";
import { Loader2, FolderOpen } from "lucide-react";

export function ProjectList() {
  const { data: projects, isLoading, isError, error } = useProjects();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-slate-500">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        加载中...
      </div>
    );
  }

  if (isError) {
    return (
      <div className="rounded-[20px] border border-rose-200 bg-rose-50 p-5 text-sm text-rose-700">
        加载失败：{(error as Error)?.message ?? "未知错误"}
      </div>
    );
  }

  if (!projects || projects.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-slate-500">
        <FolderOpen className="mb-3 h-10 w-10 text-slate-300" />
        <p className="text-sm">暂无项目</p>
        <Link
          href="/create"
          className="mt-3 text-sm font-semibold text-accent hover:underline"
        >
          创建第一个项目
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {projects.map((project) => (
        <Link
          key={project.id}
          href={`/${project.kind}/${project.id}`}
          className="block rounded-[22px] border border-slate-200 bg-white p-4 transition hover:border-accent/30 hover:bg-shell"
        >
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div className="max-w-2xl">
              <div className="flex items-center gap-3">
                <p className="text-base font-semibold text-ink">
                  {project.name}
                </p>
                <StatusBadge status={project.status} />
              </div>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                {project.summary}
              </p>
            </div>
            <div className="min-w-48">
              <div className="mb-2 flex items-center justify-between text-xs font-medium uppercase tracking-[0.18em] text-slate-500">
                <span>{project.kind}</span>
                <span>{project.progress}%</span>
              </div>
              <div className="h-2 rounded-full bg-slate-100">
                <div
                  className="h-2 rounded-full bg-accent transition-all"
                  style={{ width: `${project.progress}%` }}
                />
              </div>
              <p className="mt-2 text-xs text-slate-500">
                最近更新：{project.updatedAt}
              </p>
            </div>
          </div>
        </Link>
      ))}
    </div>
  );
}

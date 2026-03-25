"use client";

import { useProjects } from "@/lib/hooks";
import { useTasks } from "@/lib/hooks";
import { Loader2 } from "lucide-react";

export function MetricGrid() {
  const projects = useProjects();
  const tasks = useTasks(50);

  const isLoading = projects.isLoading || tasks.isLoading;
  const hasError = projects.isError || tasks.isError;

  const projectCount = projects.data?.length ?? 0;
  const runningTasks =
    tasks.data?.filter(
      (t) => t.status === "running" || t.status === "pending"
    ).length ?? 0;
  const completedTasks =
    tasks.data?.filter((t) => t.status === "completed").length ?? 0;

  const metrics = [
    {
      label: "活跃项目",
      value: isLoading ? "..." : String(projectCount),
      detail: "小说、视频和 PPT 项目总数。",
    },
    {
      label: "运行中任务",
      value: isLoading ? "..." : String(runningTasks),
      detail: "当前正在执行或排队的后台任务。",
    },
    {
      label: "已完成任务",
      value: isLoading ? "..." : String(completedTasks),
      detail: "历史完成的任务总计。",
    },
  ];

  return (
    <div className="grid gap-4 md:grid-cols-3">
      {hasError && (
        <div className="col-span-full rounded-[24px] border border-rose-200 bg-rose-50 p-5 text-sm text-rose-700">
          无法连接后端服务。请确认服务器已启动。
        </div>
      )}
      {metrics.map((metric) => (
        <article
          key={metric.label}
          className="rounded-[24px] border border-slate-200 bg-[linear-gradient(180deg,#ffffff_0%,#f9fafb_100%)] p-5"
        >
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">
            {metric.label}
          </p>
          <p className="mt-4 flex items-center gap-2 text-3xl font-semibold tracking-tight text-ink">
            {isLoading ? (
              <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
            ) : (
              metric.value
            )}
          </p>
          <p className="mt-3 text-sm leading-6 text-slate-600">
            {metric.detail}
          </p>
        </article>
      ))}
    </div>
  );
}

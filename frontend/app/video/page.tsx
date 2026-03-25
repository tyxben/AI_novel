"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Plus, Clapperboard, Film, RefreshCw } from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { Panel } from "@/components/ui/panel";
import { StatusBadge } from "@/components/ui/status-badge";
import { useVideoTasks } from "@/lib/hooks";
import type { TaskDetail } from "@/lib/types";

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function getProjectTitle(p: TaskDetail): string {
  const inspiration = p.params?.inspiration;
  if (inspiration) {
    return inspiration.length > 30
      ? inspiration.slice(0, 30) + "..."
      : inspiration;
  }
  const inputFile = p.params?.input_file;
  if (inputFile) {
    const name =
      typeof inputFile === "string"
        ? inputFile.split("/").pop() ?? inputFile
        : String(inputFile);
    return name.length > 30 ? name.slice(0, 30) + "..." : name;
  }
  return "视频项目";
}

function getMode(p: TaskDetail): string {
  if (p.task_type === "director_generate") return "导演模式";
  if (p.params?.run_mode === "agent") return "Agent 模式";
  return "经典模式";
}

function formatTime(iso: string | null | undefined): string {
  if (!iso) return "--";
  try {
    const d = new Date(iso);
    const now = new Date();
    const diff = now.getTime() - d.getTime();
    if (diff < 60_000) return "刚刚";
    if (diff < 3600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
    if (diff < 86400_000) return `${Math.floor(diff / 3600_000)} 小时前`;
    return d.toLocaleDateString("zh-CN");
  } catch {
    return iso;
  }
}

/* ------------------------------------------------------------------ */
/*  Page component                                                    */
/* ------------------------------------------------------------------ */

export default function VideoPage() {
  const router = useRouter();
  const { data: projects, isLoading, isError, error, refetch } = useVideoTasks();

  return (
    <>
      <PageHeader
        eyebrow="视频"
        title="视频工作台"
        description="AI 导演模式和经典短视频制作统一在一个工作区里，查看项目进度和管理创作流程。"
        action={
          <div className="flex items-center gap-3">
            <button
              onClick={() => refetch()}
              className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-shell"
            >
              <RefreshCw className="h-4 w-4" />
              刷新
            </button>
            <Link
              href="/video/create"
              className="inline-flex items-center gap-2 rounded-full bg-ink px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-ink/90"
            >
              <Plus className="h-4 w-4" />
              新建视频
            </Link>
          </div>
        }
      />

      <div className="space-y-5 px-6 py-6 md:px-8">
        {isLoading && (
          <Panel title="加载中">
            <div className="flex items-center gap-3 py-8 text-sm text-slate-500">
              <RefreshCw className="h-4 w-4 animate-spin" />
              正在获取视频项目...
            </div>
          </Panel>
        )}

        {isError && (
          <Panel title="连接失败">
            <div className="rounded-[20px] bg-rose-50 p-4 text-sm text-rose-700">
              <p className="font-medium">无法连接到后端服务</p>
              <p className="mt-1 text-rose-600">
                {error instanceof Error ? error.message : "未知错误"}
              </p>
              <p className="mt-2 text-xs text-rose-500">
                请确认任务队列服务已启动 (python -m src.task_queue.server)
              </p>
            </div>
          </Panel>
        )}

        {!isLoading && !isError && (!projects || projects.length === 0) && (
          <Panel title="暂无视频项目">
            <div className="py-8 text-center">
              <Clapperboard className="mx-auto h-12 w-12 text-slate-300" />
              <p className="mt-4 text-sm text-slate-500">
                还没有视频项目，点击右上角「新建视频」开始创作
              </p>
              <Link
                href="/video/create"
                className="mt-4 inline-flex items-center gap-2 rounded-full bg-accent px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-accent/90"
              >
                <Plus className="h-4 w-4" />
                新建视频
              </Link>
            </div>
          </Panel>
        )}

        {projects && projects.length > 0 && (
          <div className="space-y-3">
            {projects.map((project) => (
              <button
                key={project.task_id}
                onClick={() => router.push(`/video/${project.task_id}`)}
                className="block w-full rounded-[22px] border border-slate-200 bg-white p-4 text-left transition hover:border-accent/30 hover:bg-shell"
              >
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div className="max-w-2xl">
                    <div className="flex items-center gap-3">
                      <Film className="h-4 w-4 text-accent" />
                      <p className="text-base font-semibold text-ink">
                        {getProjectTitle(project)}
                      </p>
                      <StatusBadge status={project.status} />
                    </div>
                    <div className="mt-2 flex items-center gap-3">
                      <span className="inline-flex rounded-full bg-sky-50 px-2.5 py-0.5 text-xs font-medium text-sky-700">
                        {getMode(project)}
                      </span>
                      {project.progress_msg && (
                        <span className="text-xs text-slate-500">
                          {project.progress_msg}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="min-w-48">
                    <div className="mb-2 flex items-center justify-between text-xs font-medium text-slate-500">
                      <span>进度</span>
                      <span>{Math.round(project.progress * 100)}%</span>
                    </div>
                    <div className="h-2 rounded-full bg-slate-100">
                      <div
                        className="h-2 rounded-full bg-accent transition-all"
                        style={{
                          width: `${Math.round(project.progress * 100)}%`,
                        }}
                      />
                    </div>
                    <p className="mt-2 text-xs text-slate-500">
                      创建于：{formatTime(project.created_at)}
                    </p>
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </>
  );
}

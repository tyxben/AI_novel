"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Plus, FileStack, Presentation, RefreshCw } from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { Panel } from "@/components/ui/panel";
import { StatusBadge } from "@/components/ui/status-badge";
import { usePPTs } from "@/lib/hooks";

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function getThemeLabel(theme?: string): string {
  const labels: Record<string, string> = {
    modern: "现代",
    classic: "经典",
    minimal: "简约",
    vibrant: "活力",
    business: "商务",
    creative: "创意",
    tech: "科技",
    education: "教育",
  };
  return labels[theme ?? ""] ?? theme ?? "默认";
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

export default function PptPage() {
  const router = useRouter();
  const { data: projects, isLoading, error, refetch } = usePPTs();

  return (
    <>
      <PageHeader
        eyebrow="PPT"
        title="PPT 工作台"
        description="管理 PPT 项目，从主题或文档生成幻灯片大纲、预览和导出。"
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
              href="/ppt/create"
              className="inline-flex items-center gap-2 rounded-full bg-ink px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-ink/90"
            >
              <Plus className="h-4 w-4" />
              新建 PPT
            </Link>
          </div>
        }
      />

      <div className="space-y-5 px-6 py-6 md:px-8">
        {isLoading && !projects && (
          <Panel title="加载中">
            <div className="flex items-center gap-3 py-8 text-sm text-slate-500">
              <RefreshCw className="h-4 w-4 animate-spin" />
              正在获取 PPT 项目...
            </div>
          </Panel>
        )}

        {error && (
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

        {!isLoading && !error && projects && projects.length === 0 && (
          <Panel title="暂无 PPT 项目">
            <div className="py-8 text-center">
              <FileStack className="mx-auto h-12 w-12 text-slate-300" />
              <p className="mt-4 text-sm text-slate-500">
                还没有 PPT 项目，点击右上角「新建 PPT」开始创作
              </p>
              <Link
                href="/ppt/create"
                className="mt-4 inline-flex items-center gap-2 rounded-full bg-accent px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-accent/90"
              >
                <Plus className="h-4 w-4" />
                新建 PPT
              </Link>
            </div>
          </Panel>
        )}

        {projects && projects.length > 0 && (
          <div className="space-y-3">
            {projects.map((project) => (
              <button
                key={project.id}
                onClick={() => router.push(`/ppt/${project.id}`)}
                className="block w-full rounded-[22px] border border-slate-200 bg-white p-4 text-left transition hover:border-accent/30 hover:bg-shell"
              >
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div className="max-w-2xl">
                    <div className="flex items-center gap-3">
                      <Presentation className="h-4 w-4 text-accent" />
                      <p className="text-base font-semibold text-ink">
                        {project.name}
                      </p>
                      <StatusBadge status={project.status} />
                    </div>
                    {project.summary && (
                      <p className="mt-2 text-xs text-slate-500">
                        {project.summary}
                      </p>
                    )}
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
                      更新于：{formatTime(project.updatedAt)}
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

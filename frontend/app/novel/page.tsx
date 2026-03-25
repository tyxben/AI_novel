"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { PageHeader } from "@/components/layout/page-header";
import { Panel } from "@/components/ui/panel";
import { StatusBadge } from "@/components/ui/status-badge";
import { Loader2, BookOpenText, Plus } from "lucide-react";

const STATUS_LABELS: Record<string, string> = {
  created: "已创建",
  generating: "生成中",
  completed: "已完成",
  polished: "已润色",
  error: "异常",
  unknown: "未知",
};

export default function NovelPage() {
  const { data: novels, isLoading, isError, error } = useQuery<any[]>({
    queryKey: ["novels"],
    queryFn: () => api.listNovels(),
  });

  return (
    <>
      <PageHeader
        eyebrow="小说"
        title="小说工作台"
        description="管理所有小说项目，查看进度，进入项目工作区。"
        action={
          <Link
            href="/create"
            className="inline-flex items-center gap-2 rounded-full bg-accent px-5 py-3 text-sm font-semibold text-white transition hover:bg-accent/90"
          >
            <Plus className="h-4 w-4" />
            新建小说
          </Link>
        }
      />
      <div className="space-y-5 px-6 py-6 md:px-8">
        <Panel title="小说项目" description="点击项目卡片进入工作区。">
          {isLoading && (
            <div className="flex items-center justify-center py-12 text-slate-500">
              <Loader2 className="mr-2 h-5 w-5 animate-spin" />
              加载中...
            </div>
          )}

          {isError && (
            <div className="rounded-[20px] border border-rose-200 bg-rose-50 p-5 text-sm text-rose-700">
              加载失败：{(error as Error)?.message ?? "未知错误"}
            </div>
          )}

          {!isLoading && !isError && (!novels || novels.length === 0) && (
            <div className="flex flex-col items-center justify-center py-12 text-slate-500">
              <BookOpenText className="mb-3 h-10 w-10 text-slate-300" />
              <p className="text-sm">暂无小说项目</p>
              <Link
                href="/create"
                className="mt-3 text-sm font-semibold text-accent hover:underline"
              >
                创建第一部小说
              </Link>
            </div>
          )}

          {novels && novels.length > 0 && (
            <div className="space-y-3">
              {novels.map((novel: any) => {
                const completed = novel.completed_chapters ?? 0;
                const total = novel.total_chapters ?? 0;
                const pct = total > 0 ? Math.round((completed / total) * 100) : 0;
                // Extract a short display title
                const rawTitle: string = novel.title ?? novel.id;
                const displayTitle = rawTitle.length > 30 ? rawTitle.slice(0, 30) + "..." : rawTitle;

                return (
                  <Link
                    key={novel.id}
                    href={`/novel/${novel.id}`}
                    className="block rounded-[22px] border border-slate-200 bg-white p-5 transition hover:border-accent/30 hover:bg-shell"
                  >
                    <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-3">
                          <BookOpenText className="h-5 w-5 shrink-0 text-accent" />
                          <p className="text-base font-semibold text-ink truncate" title={rawTitle}>
                            {displayTitle}
                          </p>
                          <StatusBadge status={novel.status} />
                        </div>
                        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                          <span>{novel.genre}</span>
                          {novel.author_name && <span>作者: {novel.author_name}</span>}
                          <span>目标: {(novel.target_words / 10000).toFixed(0)}万字</span>
                          {novel.published_count != null && novel.published_count > 0 && (
                            <span className="text-emerald-600">已发布: {novel.published_count}章</span>
                          )}
                          <span>{STATUS_LABELS[novel.status] ?? novel.status}</span>
                        </div>
                        {novel.synopsis && (
                          <p className="mt-2 text-sm leading-6 text-slate-600 line-clamp-2">
                            {novel.synopsis}
                          </p>
                        )}
                      </div>
                      <div className="min-w-48 shrink-0">
                        <div className="mb-2 flex items-center justify-between text-xs font-medium text-slate-500">
                          <span>章节进度</span>
                          <span>{completed} / {total} ({pct}%)</span>
                        </div>
                        <div className="h-2 rounded-full bg-slate-100">
                          <div
                            className="h-2 rounded-full bg-accent transition-all"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <div className="mt-2 flex items-center justify-between text-xs text-slate-400">
                          <span>{novel.style_name}</span>
                          <span>{novel.id}</span>
                        </div>
                      </div>
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}

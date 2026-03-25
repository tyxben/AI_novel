"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import {
  FolderKanban,
  BookOpenText,
  Clapperboard,
  FileStack,
  RefreshCw,
  Search,
  Filter,
} from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { Panel } from "@/components/ui/panel";
import { StatusBadge } from "@/components/ui/status-badge";
import { useTasks } from "@/lib/hooks";
import type { TaskDetail } from "@/lib/types";

/* ------------------------------------------------------------------ */
/*  Local types                                                       */
/* ------------------------------------------------------------------ */

type ProjectKind = "all" | "novel" | "video" | "ppt";

/* ------------------------------------------------------------------ */
/*  Constants                                                         */
/* ------------------------------------------------------------------ */

const KIND_MAP: Record<string, ProjectKind> = {
  novel_create: "novel",
  novel_generate: "novel",
  novel_polish: "novel",
  novel_feedback: "novel",
  video_generate: "video",
  director_generate: "video",
  ppt_generate: "ppt",
  ppt_outline: "ppt",
  ppt_continue: "ppt",
  ppt_render_html: "ppt",
  ppt_export: "ppt",
};

const KIND_LABELS: Record<string, string> = {
  novel: "小说",
  video: "视频",
  ppt: "PPT",
};

const KIND_ICONS: Record<string, typeof FolderKanban> = {
  novel: BookOpenText,
  video: Clapperboard,
  ppt: FileStack,
};

const KIND_COLORS: Record<string, string> = {
  novel: "bg-emerald-50 text-emerald-700",
  video: "bg-sky-50 text-sky-700",
  ppt: "bg-violet-50 text-violet-700",
};

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function getKind(taskType: string): ProjectKind {
  return KIND_MAP[taskType] ?? "novel";
}

function getRoute(task: TaskDetail): string {
  const kind = getKind(task.task_type);
  return `/${kind}/${task.task_id}`;
}

function getTitle(task: TaskDetail): string {
  const p = task.params;
  if (typeof p.inspiration === "string" && p.inspiration) {
    return p.inspiration.length > 50
      ? p.inspiration.slice(0, 50) + "..."
      : p.inspiration;
  }
  if (typeof p.genre === "string" && typeof p.theme === "string") {
    return `${p.genre} - ${p.theme}`.slice(0, 50);
  }
  if (typeof p.topic === "string" && p.topic) {
    return p.topic.length > 50 ? p.topic.slice(0, 50) + "..." : p.topic;
  }
  if (typeof p.input_file === "string" && p.input_file) {
    const name = (p.input_file as string).split("/").pop() ?? p.input_file;
    return String(name).length > 50
      ? String(name).slice(0, 50) + "..."
      : String(name);
  }
  if (typeof p.project_path === "string" && p.project_path) {
    return (p.project_path as string).split("/").pop() ?? "项目";
  }
  if (typeof p.project_id === "string") {
    return `项目 ${(p.project_id as string).slice(0, 8)}`;
  }
  return `任务 ${task.task_id.slice(0, 8)}`;
}

function getTaskTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    novel_create: "创建小说",
    novel_generate: "生成章节",
    novel_polish: "润色修改",
    novel_feedback: "反馈重写",
    video_generate: "生成视频",
    director_generate: "导演模式",
    ppt_generate: "一键生成",
    ppt_outline: "大纲生成",
    ppt_continue: "继续生成",
    ppt_render_html: "HTML 渲染",
    ppt_export: "PPTX 导出",
  };
  return labels[type] ?? type;
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

export default function ProjectsPage() {
  const router = useRouter();
  const { data: tasks = [], isLoading: loading, error: queryError, refetch } = useTasks(200);
  const error = queryError ? (queryError as Error).message : null;
  const [kindFilter, setKindFilter] = useState<ProjectKind>("all");
  const [searchQuery, setSearchQuery] = useState("");

  // Filter tasks
  const filtered = useMemo(() =>
    tasks.filter((task) => {
      const kind = getKind(task.task_type);
      if (kindFilter !== "all" && kind !== kindFilter) return false;
      if (searchQuery.trim()) {
        const title = getTitle(task).toLowerCase();
        const query = searchQuery.toLowerCase();
        if (!title.includes(query) && !task.task_type.includes(query))
          return false;
      }
      return true;
    }),
    [tasks, kindFilter, searchQuery]
  );

  // Stats
  const novelCount = tasks.filter(
    (t) => getKind(t.task_type) === "novel"
  ).length;
  const videoCount = tasks.filter(
    (t) => getKind(t.task_type) === "video"
  ).length;
  const pptCount = tasks.filter(
    (t) => getKind(t.task_type) === "ppt"
  ).length;
  const runningCount = tasks.filter((t) => t.status === "running").length;

  return (
    <>
      <PageHeader
        eyebrow="项目"
        title="项目中心"
        description="统一管理所有小说、视频和 PPT 项目，快速查看状态和进度。"
        action={
          <button
            onClick={() => refetch()}
            className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-shell"
          >
            <RefreshCw className="h-4 w-4" />
            刷新
          </button>
        }
      />

      <div className="space-y-5 px-6 py-6 md:px-8">
        {/* Stats */}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <div className="rounded-[20px] border border-slate-200 bg-white p-4 text-center">
            <p className="text-2xl font-semibold text-ink">{tasks.length}</p>
            <p className="mt-1 text-xs text-slate-500">全部项目</p>
          </div>
          <div className="rounded-[20px] border border-slate-200 bg-white p-4 text-center">
            <p className="text-2xl font-semibold text-emerald-600">
              {novelCount}
            </p>
            <p className="mt-1 text-xs text-slate-500">小说</p>
          </div>
          <div className="rounded-[20px] border border-slate-200 bg-white p-4 text-center">
            <p className="text-2xl font-semibold text-sky-600">{videoCount}</p>
            <p className="mt-1 text-xs text-slate-500">视频</p>
          </div>
          <div className="rounded-[20px] border border-slate-200 bg-white p-4 text-center">
            <p className="text-2xl font-semibold text-violet-600">{pptCount}</p>
            <p className="mt-1 text-xs text-slate-500">PPT</p>
          </div>
        </div>

        {/* Filters */}
        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索项目..."
              className="w-full rounded-[16px] border border-slate-200 bg-white py-2.5 pl-10 pr-4 text-sm text-ink placeholder:text-slate-400 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>

          <div className="flex items-center gap-2">
            <Filter className="h-4 w-4 text-slate-400" />
            {(
              [
                { value: "all", label: "全部" },
                { value: "novel", label: "小说" },
                { value: "video", label: "视频" },
                { value: "ppt", label: "PPT" },
              ] as const
            ).map((opt) => (
              <button
                key={opt.value}
                onClick={() => setKindFilter(opt.value)}
                className={`rounded-full px-3 py-1.5 text-xs font-medium transition ${
                  kindFilter === opt.value
                    ? "bg-ink text-white"
                    : "bg-white text-slate-600 hover:bg-shell"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Loading */}
        {loading && tasks.length === 0 && (
          <Panel title="加载中">
            <div className="flex items-center gap-3 py-8 text-sm text-slate-500">
              <RefreshCw className="h-4 w-4 animate-spin" />
              正在获取项目列表...
            </div>
          </Panel>
        )}

        {/* Error */}
        {error && (
          <Panel title="连接失败">
            <div className="rounded-[20px] bg-rose-50 p-4 text-sm text-rose-700">
              <p className="font-medium">无法连接到后端服务</p>
              <p className="mt-1 text-rose-600">{error}</p>
              <p className="mt-2 text-xs text-rose-500">
                请确认任务队列服务已启动 (python -m src.task_queue.server)
              </p>
            </div>
          </Panel>
        )}

        {/* Empty */}
        {!loading && !error && filtered.length === 0 && (
          <Panel title="暂无项目">
            <div className="py-8 text-center">
              <FolderKanban className="mx-auto h-12 w-12 text-slate-300" />
              <p className="mt-4 text-sm text-slate-500">
                {tasks.length === 0
                  ? "还没有任何项目"
                  : "没有匹配的项目"}
              </p>
            </div>
          </Panel>
        )}

        {/* Project List */}
        {filtered.length > 0 && (
          <div className="space-y-3">
            {filtered.map((task) => {
              const kind = getKind(task.task_type);
              const Icon = KIND_ICONS[kind] ?? FolderKanban;

              return (
                <button
                  key={task.task_id}
                  onClick={() => router.push(getRoute(task))}
                  className="block w-full rounded-[22px] border border-slate-200 bg-white p-4 text-left transition hover:border-accent/30 hover:bg-shell"
                >
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div className="max-w-2xl">
                      <div className="flex items-center gap-3">
                        <Icon className="h-4 w-4 text-accent" />
                        <p className="text-base font-semibold text-ink">
                          {getTitle(task)}
                        </p>
                        <StatusBadge status={task.status} />
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <span
                          className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${KIND_COLORS[kind] ?? "bg-slate-100 text-slate-600"}`}
                        >
                          {KIND_LABELS[kind] ?? kind}
                        </span>
                        <span className="inline-flex rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600">
                          {getTaskTypeLabel(task.task_type)}
                        </span>
                        {task.progress_msg && (
                          <span className="text-xs text-slate-500">
                            {task.progress_msg}
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="min-w-48">
                      <div className="mb-2 flex items-center justify-between text-xs font-medium text-slate-500">
                        <span>进度</span>
                        <span>{Math.round(task.progress * 100)}%</span>
                      </div>
                      <div className="h-2 rounded-full bg-slate-100">
                        <div
                          className="h-2 rounded-full bg-accent transition-all"
                          style={{
                            width: `${Math.round(task.progress * 100)}%`,
                          }}
                        />
                      </div>
                      <p className="mt-2 text-xs text-slate-500">
                        更新于：{formatTime(task.finished_at ?? task.started_at ?? task.created_at)}
                      </p>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        )}

        {/* Running tasks summary */}
        {runningCount > 0 && (
          <div className="rounded-[20px] bg-accent/5 p-4">
            <p className="text-sm font-medium text-accent">
              {runningCount} 个任务正在运行中
            </p>
          </div>
        )}
      </div>
    </>
  );
}

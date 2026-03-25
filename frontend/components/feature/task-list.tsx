"use client";

import { useTasks, useCancelTask, useDeleteTask } from "@/lib/hooks";
import { StatusBadge } from "@/components/ui/status-badge";
import { Loader2, ListX, XCircle, Trash2 } from "lucide-react";
import type { TaskDetail } from "@/lib/types";
import { useState } from "react";

const taskTypeLabels: Record<string, string> = {
  novel_create: "创建小说",
  novel_generate: "生成章节",
  novel_polish: "精修润色",
  novel_feedback: "反馈重写",
  video_generate: "生成视频",
  director_generate: "导演模式",
  ppt_generate: "生成PPT",
  ppt_outline: "PPT大纲",
  ppt_continue: "继续生成PPT",
  ppt_render_html: "渲染HTML",
  ppt_export: "导出PPT",
};

function taskKindFromType(taskType: string): string {
  if (taskType.startsWith("novel_")) return "小说";
  if (taskType.startsWith("video_") || taskType.startsWith("director_"))
    return "视频";
  if (taskType.startsWith("ppt_")) return "PPT";
  return "其他";
}

function formatTime(dateStr?: string | null): string {
  if (!dateStr) return "-";
  try {
    const d = new Date(dateStr);
    const now = new Date();
    const diff = now.getTime() - d.getTime();
    if (diff < 60_000) return "刚刚";
    if (diff < 3600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
    if (diff < 86400_000) return `${Math.floor(diff / 3600_000)} 小时前`;
    return d.toLocaleDateString("zh-CN");
  } catch {
    return dateStr;
  }
}

export function TaskList({
  limit,
  filterKind,
}: {
  limit?: number;
  filterKind?: string;
} = {}) {
  const { data: tasks, isLoading, isError, error } = useTasks(limit);
  const cancelMut = useCancelTask();
  const deleteMut = useDeleteTask();
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

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

  if (!tasks || tasks.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-slate-500">
        <ListX className="mb-3 h-10 w-10 text-slate-300" />
        <p className="text-sm">暂无任务</p>
      </div>
    );
  }

  let filtered = tasks;
  if (filterKind) {
    filtered = tasks.filter((t) => {
      const kind = taskKindFromType(t.task_type);
      return kind === filterKind;
    });
  }

  return (
    <div className="space-y-3">
      {filtered.map((task: TaskDetail) => (
        <article
          key={task.task_id}
          className="rounded-[22px] border border-slate-200 bg-white p-4"
        >
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div className="flex-1">
              <div className="flex items-center gap-3">
                <p className="font-semibold text-ink">
                  {taskTypeLabels[task.task_type] ?? task.task_type}
                </p>
                <StatusBadge status={task.status} />
              </div>
              <p className="mt-1 text-sm text-slate-600">
                {taskKindFromType(task.task_type)}
                {task.progress_msg ? ` - ${task.progress_msg}` : ""}
              </p>
              {/* Progress bar */}
              {(task.status === "running" || task.status === "pending") && (
                <div className="mt-2 h-1.5 w-full max-w-xs rounded-full bg-slate-100">
                  <div
                    className="h-1.5 rounded-full bg-accent transition-all"
                    style={{ width: `${Math.round(task.progress * 100)}%` }}
                  />
                </div>
              )}
              {task.error && (
                <p className="mt-2 max-w-lg truncate text-xs text-rose-600">
                  {task.error.split("\n")[0]}
                </p>
              )}
            </div>
            <div className="flex items-center gap-2">
              <p className="text-xs text-slate-500">
                {formatTime(task.created_at)}
              </p>
              {/* Cancel button for running/pending */}
              {(task.status === "running" || task.status === "pending") && (
                <button
                  onClick={() => cancelMut.mutate(task.task_id)}
                  disabled={cancelMut.isPending}
                  className="rounded-xl border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-xs font-medium text-amber-700 transition hover:bg-amber-100"
                  title="取消任务"
                >
                  <XCircle className="h-3.5 w-3.5" />
                </button>
              )}
              {/* Delete button for completed/failed/cancelled */}
              {(task.status === "completed" ||
                task.status === "failed" ||
                task.status === "cancelled") && (
                <>
                  {confirmDelete === task.task_id ? (
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => {
                          deleteMut.mutate(task.task_id);
                          setConfirmDelete(null);
                        }}
                        className="rounded-lg bg-rose-600 px-2 py-1 text-xs font-medium text-white"
                      >
                        确认
                      </button>
                      <button
                        onClick={() => setConfirmDelete(null)}
                        className="rounded-lg border border-slate-200 px-2 py-1 text-xs font-medium text-slate-600"
                      >
                        取消
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => setConfirmDelete(task.task_id)}
                      className="rounded-xl border border-rose-200 bg-rose-50 px-2.5 py-1.5 text-xs font-medium text-rose-700 transition hover:bg-rose-100"
                      title="删除任务"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                </>
              )}
            </div>
          </div>
        </article>
      ))}
    </div>
  );
}

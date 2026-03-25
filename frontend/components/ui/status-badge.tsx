import { cn } from "@/lib/utils";

const tones: Record<string, string> = {
  running: "bg-emerald-50 text-emerald-700",
  completed: "bg-slate-900 text-white",
  paused: "bg-amber-50 text-amber-700",
  idle: "bg-slate-100 text-slate-700",
  failed: "bg-rose-50 text-rose-700",
  queued: "bg-sky-50 text-sky-700",
  pending: "bg-sky-50 text-sky-700",
  cancelled: "bg-slate-100 text-slate-500",
  creating: "bg-violet-50 text-violet-700",
  generating: "bg-emerald-50 text-emerald-700",
  polished: "bg-indigo-50 text-indigo-700",
  created: "bg-sky-50 text-sky-700",
  error: "bg-rose-50 text-rose-700",
  unknown: "bg-slate-100 text-slate-500",
  outline_ready: "bg-amber-50 text-amber-700",
  in_progress: "bg-emerald-50 text-emerald-700",
};

const labels: Record<string, string> = {
  running: "运行中",
  completed: "已完成",
  paused: "已暂停",
  idle: "空闲",
  failed: "失败",
  queued: "排队中",
  pending: "等待中",
  cancelled: "已取消",
  creating: "创建中",
  generating: "生成中",
  polished: "已润色",
  created: "已创建",
  error: "异常",
  unknown: "未知",
  outline_ready: "大纲就绪",
  in_progress: "进行中",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "inline-flex rounded-full px-2.5 py-1 text-xs font-semibold",
        tones[status] ?? tones.idle
      )}
    >
      {labels[status] ?? status}
    </span>
  );
}

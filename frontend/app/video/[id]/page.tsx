"use client";

import { use } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Play,
  Eye,
  Download,
  RefreshCw,
  CheckCircle2,
  Circle,
  Loader2,
  XCircle,
  Film,
  Clock,
  Monitor,
  FileText,
} from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { Panel } from "@/components/ui/panel";
import { StatusBadge } from "@/components/ui/status-badge";
import { useTask } from "@/lib/hooks";
import type { TaskDetail } from "@/lib/types";

/* ------------------------------------------------------------------ */
/*  Local types                                                       */
/* ------------------------------------------------------------------ */

type ParsedResult = {
  output?: string;
  output_path?: string;
  segments?: Array<{
    text?: string;
    prompt?: string;
    image_path?: string;
  }>;
  concept?: {
    title?: string;
    visual_style?: string;
  };
};

/* ------------------------------------------------------------------ */
/*  Constants                                                         */
/* ------------------------------------------------------------------ */

const PIPELINE_STAGES = [
  { key: "segment", label: "分段", range: [0, 0.2] },
  { key: "prompt", label: "Prompt 生成", range: [0.2, 0.4] },
  { key: "image", label: "图片/视频生成", range: [0.4, 0.6] },
  { key: "tts", label: "配音合成", range: [0.6, 0.8] },
  { key: "video", label: "视频合成", range: [0.8, 1.0] },
];

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function getStageStatus(
  progress: number,
  taskStatus: string,
  stageRange: number[]
): "pending" | "running" | "completed" | "failed" {
  if (taskStatus === "failed") {
    if (progress >= stageRange[1]) return "completed";
    if (progress >= stageRange[0]) return "failed";
    return "pending";
  }
  if (progress >= stageRange[1]) return "completed";
  if (progress >= stageRange[0]) return "running";
  return "pending";
}

function getStageIcon(status: string) {
  switch (status) {
    case "completed":
      return <CheckCircle2 className="h-5 w-5 text-emerald-600" />;
    case "running":
      return <Loader2 className="h-5 w-5 animate-spin text-accent" />;
    case "failed":
      return <XCircle className="h-5 w-5 text-rose-500" />;
    default:
      return <Circle className="h-5 w-5 text-slate-300" />;
  }
}

function formatTime(iso: string | null | undefined): string {
  if (!iso) return "--";
  try {
    return new Date(iso).toLocaleString("zh-CN");
  } catch {
    return iso;
  }
}

function getMode(task: TaskDetail): string {
  if (task.task_type === "director_generate") return "AI 导演模式";
  if (task.params?.run_mode === "agent") return "Agent 模式";
  return "经典模式";
}

function getTitle(task: TaskDetail): string {
  if (task.params?.inspiration) return String(task.params.inspiration);
  if (task.params?.input_file) {
    return String(task.params.input_file).split("/").pop() ?? "视频项目";
  }
  return "视频项目";
}

function parseResult(result: string | undefined): ParsedResult | null {
  if (!result) return null;
  try {
    return JSON.parse(result);
  } catch {
    return null;
  }
}

/* ------------------------------------------------------------------ */
/*  Page component                                                    */
/* ------------------------------------------------------------------ */

export default function VideoDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { data: task, isLoading, isError, error } = useTask(id);

  if (isLoading && !task) {
    return (
      <>
        <PageHeader
          eyebrow="视频项目"
          title="加载中..."
          description="正在获取项目信息"
        />
        <div className="flex items-center gap-3 px-6 py-12 text-sm text-slate-500">
          <RefreshCw className="h-4 w-4 animate-spin" />
          加载中...
        </div>
      </>
    );
  }

  if (isError || !task) {
    return (
      <>
        <PageHeader
          eyebrow="视频项目"
          title="加载失败"
          description={
            error instanceof Error ? error.message : "未知错误"
          }
          action={
            <Link
              href="/video"
              className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700"
            >
              <ArrowLeft className="h-4 w-4" />
              返回列表
            </Link>
          }
        />
      </>
    );
  }

  const parsed = parseResult(task.result);
  const outputPath = parsed?.output ?? parsed?.output_path;

  return (
    <>
      <PageHeader
        eyebrow="视频项目"
        title={getTitle(task)}
        description={`${getMode(task)} | 创建于 ${formatTime(task.created_at)}`}
        action={
          <Link
            href="/video"
            className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-shell"
          >
            <ArrowLeft className="h-4 w-4" />
            返回列表
          </Link>
        }
      />

      <div className="grid gap-5 px-6 py-6 md:px-8 xl:grid-cols-[minmax(0,1.45fr)_360px]">
        {/* ---- Left Column ---- */}
        <div className="space-y-5">
          {/* Status + Actions */}
          <Panel title="项目状态">
            <div className="flex flex-wrap items-center gap-3">
              <StatusBadge status={task.status} />
              <span className="text-sm text-slate-500">
                {task.progress_msg || `进度 ${Math.round(task.progress * 100)}%`}
              </span>
            </div>
            <div className="mt-4 h-2.5 rounded-full bg-slate-100">
              <div
                className="h-2.5 rounded-full bg-accent transition-all"
                style={{
                  width: `${Math.round(task.progress * 100)}%`,
                }}
              />
            </div>
            {task.status === "completed" && (
              <div className="mt-4 flex flex-wrap gap-3">
                {outputPath && (
                  <button className="inline-flex items-center gap-2 rounded-full bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent/90">
                    <Eye className="h-4 w-4" />
                    预览
                  </button>
                )}
                {outputPath && (
                  <button className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-shell">
                    <Download className="h-4 w-4" />
                    导出
                  </button>
                )}
              </div>
            )}
            {task.status === "pending" && (
              <div className="mt-4">
                <button className="inline-flex items-center gap-2 rounded-full bg-ink px-4 py-2 text-sm font-semibold text-white transition hover:bg-ink/90">
                  <Play className="h-4 w-4" />
                  生成视频
                </button>
              </div>
            )}
          </Panel>

          {/* Pipeline Stages */}
          <Panel title="流水线阶段">
            <div className="space-y-1">
              {PIPELINE_STAGES.map((stage, idx) => {
                const status = getStageStatus(
                  task.progress,
                  task.status,
                  stage.range
                );
                return (
                  <div
                    key={stage.key}
                    className="flex items-center gap-3 rounded-[16px] px-3 py-2.5 transition hover:bg-shell"
                  >
                    {getStageIcon(status)}
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-slate-400">
                          {idx + 1}
                        </span>
                        <span className="text-sm font-medium text-ink">
                          {stage.label}
                        </span>
                      </div>
                    </div>
                    <span className="text-xs text-slate-400">
                      {status === "completed"
                        ? "已完成"
                        : status === "running"
                        ? "进行中"
                        : status === "failed"
                        ? "失败"
                        : "等待中"}
                    </span>
                  </div>
                );
              })}
            </div>
          </Panel>

          {/* Segments (if available in result) */}
          {parsed?.segments && parsed.segments.length > 0 && (
            <Panel
              title="分段内容"
              description={`共 ${parsed.segments.length} 个片段`}
            >
              <div className="space-y-3">
                {parsed.segments.map((seg, idx) => (
                  <div
                    key={idx}
                    className="rounded-[16px] border border-slate-100 p-3"
                  >
                    <div className="flex items-start gap-2">
                      <span className="mt-0.5 inline-flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-accent/10 text-xs font-medium text-accent">
                        {idx + 1}
                      </span>
                      <div className="min-w-0 flex-1">
                        {seg.text && (
                          <p className="text-sm leading-6 text-slate-700">
                            {seg.text}
                          </p>
                        )}
                        {seg.prompt && (
                          <p className="mt-1 text-xs leading-5 text-slate-400">
                            Prompt: {seg.prompt}
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </Panel>
          )}

          {/* Output path */}
          {outputPath && (
            <Panel title="输出文件">
              <div className="rounded-[16px] bg-shell p-3">
                <p className="break-all text-sm font-mono text-slate-600">
                  {outputPath}
                </p>
              </div>
            </Panel>
          )}

          {/* Error display */}
          {task.error && (
            <Panel title="错误信息">
              <div className="rounded-[16px] bg-rose-50 p-4">
                <pre className="whitespace-pre-wrap text-xs leading-5 text-rose-700">
                  {task.error}
                </pre>
              </div>
            </Panel>
          )}
        </div>

        {/* ---- Right Column ---- */}
        <div className="space-y-5">
          {/* Active task progress */}
          {(task.status === "running" || task.status === "pending") && (
            <Panel title="实时进度">
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin text-accent" />
                  <span className="text-sm font-medium text-ink">
                    {task.progress_msg || "处理中..."}
                  </span>
                </div>
                <div className="h-2 rounded-full bg-slate-100">
                  <div
                    className="h-2 rounded-full bg-accent transition-all"
                    style={{
                      width: `${Math.round(task.progress * 100)}%`,
                    }}
                  />
                </div>
                <p className="text-xs text-slate-500">
                  {Math.round(task.progress * 100)}% 完成
                </p>
              </div>
            </Panel>
          )}

          {/* Project info */}
          <Panel title="项目信息">
            <div className="space-y-3">
              <div className="flex items-center gap-3 rounded-[16px] bg-shell p-3">
                <Film className="h-4 w-4 text-accent" />
                <div>
                  <p className="text-xs text-slate-500">模式</p>
                  <p className="text-sm font-medium text-ink">
                    {getMode(task)}
                  </p>
                </div>
              </div>

              {task.params?.input_file && (
                <div className="flex items-center gap-3 rounded-[16px] bg-shell p-3">
                  <FileText className="h-4 w-4 text-accent" />
                  <div className="min-w-0">
                    <p className="text-xs text-slate-500">输入文件</p>
                    <p className="truncate text-sm font-medium text-ink">
                      {String(task.params.input_file)}
                    </p>
                  </div>
                </div>
              )}

              {task.params?.target_duration && (
                <div className="flex items-center gap-3 rounded-[16px] bg-shell p-3">
                  <Clock className="h-4 w-4 text-accent" />
                  <div>
                    <p className="text-xs text-slate-500">目标时长</p>
                    <p className="text-sm font-medium text-ink">
                      {task.params.target_duration} 秒
                    </p>
                  </div>
                </div>
              )}

              {task.params?.budget && (
                <div className="flex items-center gap-3 rounded-[16px] bg-shell p-3">
                  <Monitor className="h-4 w-4 text-accent" />
                  <div>
                    <p className="text-xs text-slate-500">预算</p>
                    <p className="text-sm font-medium text-ink">
                      {task.params.budget === "low"
                        ? "低"
                        : task.params.budget === "medium"
                        ? "中"
                        : "高"}
                    </p>
                  </div>
                </div>
              )}

              <div className="space-y-2 pt-2 text-xs text-slate-500">
                <p>创建时间：{formatTime(task.created_at)}</p>
                {task.started_at && (
                  <p>开始时间：{formatTime(task.started_at)}</p>
                )}
                {task.finished_at && (
                  <p>完成时间：{formatTime(task.finished_at)}</p>
                )}
              </div>
            </div>
          </Panel>

          {/* Director concept (if available) */}
          {parsed?.concept && (
            <Panel title="导演方案">
              <div className="space-y-2 text-sm">
                {parsed.concept.title && (
                  <div>
                    <p className="text-xs text-slate-500">标题</p>
                    <p className="font-medium text-ink">
                      {parsed.concept.title}
                    </p>
                  </div>
                )}
                {parsed.concept.visual_style && (
                  <div>
                    <p className="text-xs text-slate-500">视觉风格</p>
                    <p className="text-slate-700">
                      {parsed.concept.visual_style}
                    </p>
                  </div>
                )}
              </div>
            </Panel>
          )}
        </div>
      </div>
    </>
  );
}

"use client";

import { useState, use } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  Play,
  Eye,
  Download,
  RefreshCw,
  Loader2,
  Presentation,
  Palette,
  Layers,
  ExternalLink,
  Edit3,
  Save,
  X,
  Trash2,
  Plus,
  Image as ImageIcon,
} from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { Panel } from "@/components/ui/panel";
import { StatusBadge } from "@/components/ui/status-badge";
import { usePPT, useTask, useContinuePPT, useRenderPPT, useExportPPT } from "@/lib/hooks";

/* ------------------------------------------------------------------ */
/*  Local types                                                       */
/* ------------------------------------------------------------------ */

type OutlineItem = {
  page_number?: number;
  title?: string;
  purpose?: string;
  layout?: string;
  needs_image?: boolean;
  bullet_points?: string[];
  image_strategy?: string;
};

type QualityReport = {
  overall_score?: number;
  issues?: string[];
  suggestions?: string[];
};

type PPTProject = {
  id: string;
  name: string;
  status: string;
  outline?: OutlineItem[] | null;
  quality_report?: QualityReport | null;
  output_html?: string;
  output_pptx?: string;
  total_pages?: number;
  files?: { name: string; path: string; size: number }[];
};

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function formatTime(iso: string | null | undefined): string {
  if (!iso) return "--";
  try {
    return new Date(iso).toLocaleString("zh-CN");
  } catch {
    return iso;
  }
}

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

const LAYOUT_OPTIONS = [
  "title_slide",
  "section_header",
  "content",
  "two_column",
  "image_full",
  "comparison",
  "timeline",
  "chart",
  "quote",
  "closing",
];

const THEME_OPTIONS = [
  { value: "modern", label: "现代" },
  { value: "classic", label: "经典" },
  { value: "minimal", label: "简约" },
  { value: "vibrant", label: "活力" },
  { value: "business", label: "商务" },
  { value: "creative", label: "创意" },
  { value: "tech", label: "科技" },
  { value: "education", label: "教育" },
];

/* ------------------------------------------------------------------ */
/*  Page component                                                    */
/* ------------------------------------------------------------------ */

export default function PptDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const { data: project, isLoading, error, refetch } = usePPT(id);

  // Outline editing state
  const [isEditing, setIsEditing] = useState(false);
  const [editedOutline, setEditedOutline] = useState<OutlineItem[]>([]);
  const [generateImages, setGenerateImages] = useState(true);
  const [selectedTheme, setSelectedTheme] = useState("modern");

  // Task tracking
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const { data: activeTask } = useTask(activeTaskId);

  // Mutations
  const continueMutation = useContinuePPT(id);
  const renderMutation = useRenderPPT(id);
  const exportMutation = useExportPPT(id);

  const startEditing = () => {
    if (project?.outline) {
      setEditedOutline(JSON.parse(JSON.stringify(project.outline)));
    }
    setIsEditing(true);
  };

  const cancelEditing = () => {
    setIsEditing(false);
    setEditedOutline([]);
  };

  const updateOutlineItem = (
    index: number,
    field: keyof OutlineItem,
    value: any
  ) => {
    setEditedOutline((prev) => {
      const updated = [...prev];
      updated[index] = { ...updated[index], [field]: value };
      return updated;
    });
  };

  const deleteOutlineItem = (index: number) => {
    setEditedOutline((prev) => {
      const updated = prev.filter((_, i) => i !== index);
      // Re-number pages
      return updated.map((item, i) => ({ ...item, page_number: i + 1 }));
    });
  };

  const addOutlineItem = () => {
    setEditedOutline((prev) => [
      ...prev,
      {
        page_number: prev.length + 1,
        title: "新页面",
        purpose: "",
        layout: "content",
        needs_image: false,
        bullet_points: [],
      },
    ]);
  };

  const handleContinueGenerate = async () => {
    try {
      const outlineToUse = isEditing ? editedOutline : project?.outline ?? [];
      const result = await continueMutation.mutateAsync({
        edited_outline: { slides: outlineToUse },
        generate_images: generateImages,
        theme: selectedTheme,
      });
      setActiveTaskId(result.task_id);
      setIsEditing(false);
    } catch {
      // Error handled by React Query
    }
  };

  const handleRender = async () => {
    try {
      const result = await renderMutation.mutateAsync({ theme: selectedTheme });
      setActiveTaskId(result.task_id);
    } catch {
      // Error handled by React Query
    }
  };

  const handleExport = async () => {
    try {
      const result = await exportMutation.mutateAsync();
      setActiveTaskId(result.task_id);
    } catch {
      // Error handled by React Query
    }
  };

  if (isLoading && !project) {
    return (
      <>
        <PageHeader
          eyebrow="PPT 项目"
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

  if (error || !project) {
    return (
      <>
        <PageHeader
          eyebrow="PPT 项目"
          title="加载失败"
          description={
            error instanceof Error ? error.message : "未知错误"
          }
          action={
            <Link
              href="/ppt"
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

  const ppt = project as PPTProject;
  const outline = ppt.outline;
  const qualityReport = ppt.quality_report;
  const hasOutline = outline && Array.isArray(outline) && outline.length > 0;
  const isOutlineReady = ppt.status === "outline_ready";
  const isCompleted = ppt.status === "completed";
  const hasHtml = !!ppt.output_html;
  const hasPptx = !!ppt.output_pptx;

  // Active task status
  const isTaskRunning =
    activeTask?.status === "pending" || activeTask?.status === "running";
  const isTaskCompleted = activeTask?.status === "completed";
  const isTaskFailed = activeTask?.status === "failed";

  return (
    <>
      <PageHeader
        eyebrow="PPT 项目"
        title={ppt.name}
        description={`状态: ${ppt.status} | ${ppt.total_pages ? `${ppt.total_pages} 页` : ""}`}
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
              href="/ppt"
              className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-shell"
            >
              <ArrowLeft className="h-4 w-4" />
              返回列表
            </Link>
          </div>
        }
      />

      <div className="grid gap-5 px-6 py-6 md:px-8 xl:grid-cols-[minmax(0,1.45fr)_360px]">
        {/* ---- Left Column ---- */}
        <div className="space-y-5">
          {/* Status + Actions */}
          <Panel title="项目状态">
            <div className="flex flex-wrap items-center gap-3">
              <StatusBadge status={ppt.status} />
              <span className="text-sm text-slate-500">
                {ppt.status === "outline_ready"
                  ? "大纲已就绪，可编辑后生成完整 PPT"
                  : ppt.status === "completed"
                    ? "生成完成"
                    : ppt.status}
              </span>
            </div>

            {/* Action buttons */}
            <div className="mt-4 flex flex-wrap gap-3">
              {isOutlineReady && !isEditing && (
                <>
                  <button
                    onClick={startEditing}
                    className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-shell"
                  >
                    <Edit3 className="h-4 w-4" />
                    编辑大纲
                  </button>
                  <button
                    onClick={handleContinueGenerate}
                    disabled={continueMutation.isPending}
                    className="inline-flex items-center gap-2 rounded-full bg-ink px-4 py-2 text-sm font-semibold text-white transition hover:bg-ink/90 disabled:opacity-50"
                  >
                    {continueMutation.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Play className="h-4 w-4" />
                    )}
                    直接生成 PPT
                  </button>
                </>
              )}

              {isCompleted && (
                <>
                  {!hasHtml && (
                    <button
                      onClick={handleRender}
                      disabled={renderMutation.isPending}
                      className="inline-flex items-center gap-2 rounded-full bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent/90 disabled:opacity-50"
                    >
                      {renderMutation.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Eye className="h-4 w-4" />
                      )}
                      渲染预览
                    </button>
                  )}
                  {hasHtml && !hasPptx && (
                    <button
                      onClick={handleExport}
                      disabled={exportMutation.isPending}
                      className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-shell disabled:opacity-50"
                    >
                      {exportMutation.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Download className="h-4 w-4" />
                      )}
                      导出 PPTX
                    </button>
                  )}
                  {hasOutline && !isEditing && (
                    <button
                      onClick={startEditing}
                      className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-shell"
                    >
                      <Edit3 className="h-4 w-4" />
                      编辑大纲
                    </button>
                  )}
                </>
              )}
            </div>
          </Panel>

          {/* Active task progress */}
          {isTaskRunning && activeTask && (
            <Panel title="任务进度">
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin text-accent" />
                  <span className="text-sm font-medium text-ink">
                    {activeTask.progress_msg || "处理中..."}
                  </span>
                </div>
                <div className="h-2 rounded-full bg-slate-100">
                  <div
                    className="h-2 rounded-full bg-accent transition-all"
                    style={{
                      width: `${Math.round(activeTask.progress * 100)}%`,
                    }}
                  />
                </div>
                <p className="text-xs text-slate-500">
                  {Math.round(activeTask.progress * 100)}% 完成
                </p>
              </div>
            </Panel>
          )}

          {isTaskCompleted && (
            <Panel title="任务完成">
              <div className="flex items-center gap-2 text-sm text-emerald-600">
                <span>任务已完成，点击刷新查看最新结果。</span>
                <button
                  onClick={() => {
                    setActiveTaskId(null);
                    refetch();
                  }}
                  className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-100"
                >
                  <RefreshCw className="h-3 w-3" />
                  刷新
                </button>
              </div>
            </Panel>
          )}

          {isTaskFailed && activeTask && (
            <Panel title="任务失败">
              <div className="rounded-[16px] bg-rose-50 p-4">
                <pre className="whitespace-pre-wrap text-xs leading-5 text-rose-700">
                  {activeTask.error || "未知错误"}
                </pre>
              </div>
            </Panel>
          )}

          {/* Outline editor */}
          {isEditing && (
            <Panel
              title="编辑大纲"
              description="编辑后点击「确认并生成 PPT」"
            >
              <div className="space-y-4">
                {/* Generation options */}
                <div className="flex flex-wrap items-center gap-4 rounded-[16px] bg-shell p-4">
                  <div>
                    <label className="mb-1 block text-xs font-medium text-slate-500">
                      主题风格
                    </label>
                    <select
                      value={selectedTheme}
                      onChange={(e) => setSelectedTheme(e.target.value)}
                      className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm"
                    >
                      {THEME_OPTIONS.map((t) => (
                        <option key={t.value} value={t.value}>
                          {t.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={generateImages}
                      onChange={(e) => setGenerateImages(e.target.checked)}
                      className="rounded accent-accent"
                    />
                    <ImageIcon className="h-4 w-4 text-slate-400" />
                    生成 AI 配图
                  </label>
                </div>

                {/* Slide items */}
                <div className="space-y-3">
                  {editedOutline.map((item, idx) => (
                    <div
                      key={idx}
                      className="rounded-[16px] border border-slate-200 p-4"
                    >
                      <div className="mb-3 flex items-center justify-between">
                        <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-accent/10 text-xs font-semibold text-accent">
                          {item.page_number ?? idx + 1}
                        </span>
                        <button
                          onClick={() => deleteOutlineItem(idx)}
                          className="rounded-full p-1 text-slate-400 hover:bg-rose-50 hover:text-rose-500"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                      <div className="grid gap-3 md:grid-cols-2">
                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-500">
                            标题
                          </label>
                          <input
                            type="text"
                            value={item.title ?? ""}
                            onChange={(e) =>
                              updateOutlineItem(idx, "title", e.target.value)
                            }
                            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm"
                          />
                        </div>
                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-500">
                            布局
                          </label>
                          <select
                            value={item.layout ?? "content"}
                            onChange={(e) =>
                              updateOutlineItem(idx, "layout", e.target.value)
                            }
                            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm"
                          >
                            {LAYOUT_OPTIONS.map((l) => (
                              <option key={l} value={l}>
                                {l}
                              </option>
                            ))}
                          </select>
                        </div>
                      </div>
                      <div className="mt-3">
                        <label className="mb-1 block text-xs font-medium text-slate-500">
                          用途 / 说明
                        </label>
                        <input
                          type="text"
                          value={item.purpose ?? ""}
                          onChange={(e) =>
                            updateOutlineItem(idx, "purpose", e.target.value)
                          }
                          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm"
                        />
                      </div>
                      <div className="mt-2">
                        <label className="flex items-center gap-2 text-xs text-slate-500">
                          <input
                            type="checkbox"
                            checked={item.needs_image ?? false}
                            onChange={(e) =>
                              updateOutlineItem(
                                idx,
                                "needs_image",
                                e.target.checked
                              )
                            }
                            className="rounded accent-accent"
                          />
                          需要配图
                        </label>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Add / confirm buttons */}
                <div className="flex flex-wrap gap-3">
                  <button
                    onClick={addOutlineItem}
                    className="inline-flex items-center gap-2 rounded-full border border-dashed border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 transition hover:bg-shell"
                  >
                    <Plus className="h-4 w-4" />
                    新增一页
                  </button>
                  <div className="flex-1" />
                  <button
                    onClick={cancelEditing}
                    className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-shell"
                  >
                    <X className="h-4 w-4" />
                    取消
                  </button>
                  <button
                    onClick={handleContinueGenerate}
                    disabled={continueMutation.isPending}
                    className="inline-flex items-center gap-2 rounded-full bg-ink px-5 py-2 text-sm font-semibold text-white transition hover:bg-ink/90 disabled:opacity-50"
                  >
                    {continueMutation.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Save className="h-4 w-4" />
                    )}
                    确认并生成 PPT
                  </button>
                </div>
              </div>
            </Panel>
          )}

          {/* Outline display (when not editing) */}
          {!isEditing && hasOutline && (
            <Panel
              title="大纲结构"
              description={`共 ${outline!.length} 页幻灯片`}
            >
              <div className="space-y-2">
                {outline!.map((item: OutlineItem, idx: number) => (
                  <div
                    key={idx}
                    className="flex items-start gap-3 rounded-[16px] border border-slate-100 p-3 transition hover:bg-shell/50"
                  >
                    <span className="mt-0.5 inline-flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-accent/10 text-xs font-semibold text-accent">
                      {item.page_number ?? idx + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-ink">
                        {item.title ?? `第 ${idx + 1} 页`}
                      </p>
                      {item.purpose && (
                        <p className="mt-0.5 text-xs text-slate-500">
                          {item.purpose}
                        </p>
                      )}
                      <div className="mt-1 flex items-center gap-2">
                        {item.layout && (
                          <span className="inline-flex rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-500">
                            {item.layout}
                          </span>
                        )}
                        {item.needs_image && (
                          <span className="inline-flex rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-600">
                            需要图片
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </Panel>
          )}

          {/* HTML Preview link */}
          {hasHtml && (
            <Panel title="HTML 预览">
              <div className="rounded-[16px] bg-shell p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-ink">
                      预览文件已生成
                    </p>
                    <p className="mt-1 break-all font-mono text-xs text-slate-500">
                      {ppt.output_html}
                    </p>
                  </div>
                  <button className="inline-flex items-center gap-2 rounded-full bg-accent px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-accent/90">
                    <ExternalLink className="h-3 w-3" />
                    打开预览
                  </button>
                </div>
              </div>
            </Panel>
          )}

          {/* Quality Report */}
          {qualityReport &&
            (qualityReport.overall_score != null ||
              (qualityReport.issues && qualityReport.issues.length > 0)) && (
              <Panel title="质量报告">
                <div className="space-y-3">
                  {qualityReport.overall_score != null && (
                    <div className="flex items-center gap-3">
                      <span className="text-sm text-slate-500">总分</span>
                      <span className="text-2xl font-semibold text-ink">
                        {qualityReport.overall_score}
                      </span>
                      <span className="text-sm text-slate-400">/ 10</span>
                    </div>
                  )}
                  {qualityReport.issues &&
                    qualityReport.issues.length > 0 && (
                      <div>
                        <p className="mb-2 text-xs font-medium text-slate-500">
                          问题
                        </p>
                        <ul className="space-y-1">
                          {qualityReport.issues.map(
                            (issue: string, idx: number) => (
                              <li
                                key={idx}
                                className="text-sm leading-6 text-slate-600"
                              >
                                - {issue}
                              </li>
                            )
                          )}
                        </ul>
                      </div>
                    )}
                  {qualityReport.suggestions &&
                    qualityReport.suggestions.length > 0 && (
                      <div>
                        <p className="mb-2 text-xs font-medium text-slate-500">
                          改进建议
                        </p>
                        <ul className="space-y-1">
                          {qualityReport.suggestions.map(
                            (s: string, idx: number) => (
                              <li
                                key={idx}
                                className="text-sm leading-6 text-slate-600"
                              >
                                - {s}
                              </li>
                            )
                          )}
                        </ul>
                      </div>
                    )}
                </div>
              </Panel>
            )}

          {/* Output files */}
          {hasPptx && (
            <Panel title="输出文件">
              <div className="rounded-[16px] bg-shell p-3">
                <p className="break-all font-mono text-sm text-slate-600">
                  {ppt.output_pptx}
                </p>
              </div>
            </Panel>
          )}

          {/* Mutation errors */}
          {continueMutation.error && (
            <Panel title="错误信息">
              <div className="rounded-[16px] bg-rose-50 p-4">
                <pre className="whitespace-pre-wrap text-xs leading-5 text-rose-700">
                  {continueMutation.error instanceof Error
                    ? continueMutation.error.message
                    : "生成失败"}
                </pre>
              </div>
            </Panel>
          )}
          {renderMutation.error && (
            <Panel title="渲染错误">
              <div className="rounded-[16px] bg-rose-50 p-4">
                <pre className="whitespace-pre-wrap text-xs leading-5 text-rose-700">
                  {renderMutation.error instanceof Error
                    ? renderMutation.error.message
                    : "渲染失败"}
                </pre>
              </div>
            </Panel>
          )}
          {exportMutation.error && (
            <Panel title="导出错误">
              <div className="rounded-[16px] bg-rose-50 p-4">
                <pre className="whitespace-pre-wrap text-xs leading-5 text-rose-700">
                  {exportMutation.error instanceof Error
                    ? exportMutation.error.message
                    : "导出失败"}
                </pre>
              </div>
            </Panel>
          )}
        </div>

        {/* ---- Right Column ---- */}
        <div className="space-y-5">
          {/* Project info */}
          <Panel title="项目信息">
            <div className="space-y-3">
              <div className="flex items-center gap-3 rounded-[16px] bg-shell p-3">
                <Presentation className="h-4 w-4 text-accent" />
                <div>
                  <p className="text-xs text-slate-500">项目 ID</p>
                  <p className="break-all font-mono text-xs font-medium text-ink">
                    {ppt.id}
                  </p>
                </div>
              </div>

              {ppt.total_pages != null && ppt.total_pages > 0 && (
                <div className="flex items-center gap-3 rounded-[16px] bg-shell p-3">
                  <Layers className="h-4 w-4 text-accent" />
                  <div>
                    <p className="text-xs text-slate-500">页数</p>
                    <p className="text-sm font-medium text-ink">
                      {ppt.total_pages} 页
                    </p>
                  </div>
                </div>
              )}
            </div>
          </Panel>

          {/* Project files */}
          {ppt.files && ppt.files.length > 0 && (
            <Panel title="项目文件">
              <div className="space-y-1">
                {ppt.files.map((file, idx) => (
                  <div
                    key={idx}
                    className="flex items-center justify-between rounded-lg p-2 text-xs hover:bg-shell"
                  >
                    <span className="truncate font-mono text-slate-600">
                      {file.path}
                    </span>
                    <span className="ml-2 whitespace-nowrap text-slate-400">
                      {file.size > 1024 * 1024
                        ? `${(file.size / 1024 / 1024).toFixed(1)} MB`
                        : file.size > 1024
                          ? `${(file.size / 1024).toFixed(1)} KB`
                          : `${file.size} B`}
                    </span>
                  </div>
                ))}
              </div>
            </Panel>
          )}
        </div>
      </div>
    </>
  );
}

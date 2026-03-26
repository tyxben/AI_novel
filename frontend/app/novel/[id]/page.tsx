"use client";

import { useState, use, useEffect, useRef, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import {
  useNovel,
  useGenerateChapters,
  usePolishChapters,
  useExportNovel,
  useDeleteNovel,
  useAnalyzeFeedback,
  useApplyFeedback,
  useEditNovel,
  useChapter,
  useTasks,
  useSaveChapter,
  useProofreadChapter,
  useApplyFixes,
  useNovelSettings,
  useSaveNovelSettings,
  useAnalyzeSettingImpact,
  useRewriteAffected,
  useAgentChat,
  useTask,
  useResizeNovel,
  usePublishChapters,
  useNarrativeOverview,
  useNarrativeDebts,
  useStoryArcs,
  useKnowledgeGraph,
  useChapterBrief,
  useFulfillDebt,
  useConversations,
  useConversationMessages,
  useCreateConversation,
  useDeleteConversation,
  useRebuildNarrative,
  useVolumesSummary,
} from "@/lib/hooks";
import { PageHeader } from "@/components/layout/page-header";
import { Panel } from "@/components/ui/panel";
import { StatusBadge } from "@/components/ui/status-badge";
import type { TaskDetail } from "@/lib/types";
import {
  Loader2,
  ChevronDown,
  ChevronRight,
  Play,
  Sparkles,
  Download,
  Trash2,
  MessageSquare,
  MessageSquarePlus,
  Pencil,
  BookOpenText,
  Users,
  Globe,
  FileText,
  Save,
  Search,
  Check,
  Settings2,
  AlertTriangle,
  RefreshCw,
  Plus,
  X,
  Eye,
  Bot,
  Send,
  Scaling,
  CheckCircle2,
  Circle,
  GitBranch,
  ChevronUp,
} from "lucide-react";

const btnCls =
  "inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition disabled:opacity-50";
const btnPrimary = btnCls + " bg-accent text-white hover:bg-accent/90";
const btnSecondary =
  btnCls + " border border-slate-200 bg-white text-ink hover:bg-shell";
const btnDanger =
  btnCls + " border border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100";
const inputCls =
  "w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-ink outline-none transition focus:border-accent focus:ring-1 focus:ring-accent/30";
const labelCls =
  "mb-1.5 block text-xs font-semibold uppercase tracking-[0.15em] text-slate-500";
const tabCls =
  "px-4 py-2 text-sm font-semibold rounded-xl transition cursor-pointer";
const tabActive = tabCls + " bg-accent text-white";
const tabInactive = tabCls + " text-slate-500 hover:bg-shell hover:text-ink";

export default function NovelDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { data: novel, isLoading, isError, error } = useNovel(id);
  const [activeTab, setActiveTab] = useState<
    "overview" | "chapters" | "settings" | "feedback" | "edit" | "agent" | "narrative"
  >("overview");

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24 text-slate-500">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        加载项目...
      </div>
    );
  }

  if (isError) {
    return (
      <>
        <PageHeader
          eyebrow="小说项目"
          title="加载失败"
          description={(error as Error)?.message ?? "未知错误"}
        />
        <div className="px-6 py-6 md:px-8">
          <div className="rounded-[20px] border border-rose-200 bg-rose-50 p-5 text-sm text-rose-700">
            无法加载项目数据。请确认后端服务正在运行，且项目 ID 正确。
          </div>
        </div>
      </>
    );
  }

  if (!novel) {
    return (
      <div className="flex items-center justify-center py-24 text-slate-500">
        项目不存在
      </div>
    );
  }

  return (
    <>
      <PageHeader
        eyebrow="小说项目"
        title={novel.title || `项目 ${id}`}
        description={`${novel.genre} / ${novel.style_name || "默认风格"} / 目标 ${((novel.target_words ?? 0) / 10000).toFixed(0)} 万字`}
      />

      {/* Tab navigation */}
      <div className="flex gap-2 px-6 pb-2 pt-2 md:px-8">
        {[
          { key: "overview" as const, label: "总览", icon: BookOpenText },
          { key: "chapters" as const, label: "章节", icon: FileText },
          { key: "settings" as const, label: "设定", icon: Settings2 },
          { key: "feedback" as const, label: "反馈", icon: MessageSquare },
          { key: "edit" as const, label: "AI编辑", icon: Pencil },
          { key: "agent" as const, label: "Agent 对话", icon: Bot },
          { key: "narrative" as const, label: "叙事控制", icon: GitBranch },
        ].map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={activeTab === tab.key ? tabActive : tabInactive}
          >
            <tab.icon className="mr-1.5 inline h-4 w-4" />
            {tab.label}
          </button>
        ))}
      </div>

      <div className="grid gap-5 px-6 py-4 md:px-8 xl:grid-cols-[minmax(0,1.45fr)_360px]">
        {/* Left column */}
        <div className="space-y-5">
          {activeTab === "overview" && (
            <>
              <ProjectOverview novel={novel} id={id} />
              <ActionButtons novel={novel} id={id} />
              <OutlineSection outline={novel.outline} />
              <CharactersSection characters={novel.characters ?? []} />
              <WorldSection worldSetting={novel.world_setting} />
            </>
          )}
          {activeTab === "chapters" && (
            <ChaptersSection
              chapters={novel.chapters ?? []}
              novelId={id}
            />
          )}
          {activeTab === "settings" && (
            <SettingsEditorSection novelId={id} />
          )}
          {activeTab === "feedback" && (
            <FeedbackSection novelId={id} totalChapters={novel.total_chapters ?? 0} />
          )}
          {activeTab === "edit" && (
            <EditSection novelId={id} />
          )}
          {activeTab === "agent" && (
            <AgentChatSection novelId={id} />
          )}
          {activeTab === "narrative" && (
            <NarrativeControlSection novelId={id} />
          )}
        </div>

        {/* Right column */}
        <div className="space-y-5">
          <ActiveTaskPanel novelId={id} />
          <QuickStats novel={novel} />
        </div>
      </div>
    </>
  );
}

// ─── Project Overview ─────────────────────────────────────────────────
function ProjectOverview({
  novel,
  id,
}: {
  novel: any;
  id: string;
}) {
  return (
    <Panel title="项目概览">
      <div className="grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.15em] text-slate-500">
            状态
          </p>
          <div className="mt-1">
            <StatusBadge status={novel.status} />
          </div>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.15em] text-slate-500">
            进度
          </p>
          <p className="mt-1 font-semibold text-ink">
            {novel.progress ?? 0}%
          </p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.15em] text-slate-500">
            章节
          </p>
          <p className="mt-1 font-semibold text-ink">
            {novel.current_chapter ?? 0} / {novel.total_chapters ?? 0}
          </p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.15em] text-slate-500">
            主题
          </p>
          <p className="mt-1 text-ink">{novel.theme || "-"}</p>
        </div>
      </div>
      <div className="mt-4 h-2 rounded-full bg-slate-100">
        <div
          className="h-2 rounded-full bg-accent transition-all"
          style={{ width: `${novel.progress ?? 0}%` }}
        />
      </div>
    </Panel>
  );
}

// ─── Action Buttons ───────────────────────────────────────────────────
function ActionButtons({ novel, id }: { novel: any; id: string }) {
  const router = useRouter();
  const genMut = useGenerateChapters(id);
  const polishMut = usePolishChapters(id);
  const exportMut = useExportNovel(id);
  const deleteMut = useDeleteNovel();
  const resizeMut = useResizeNovel(id);
  const [confirmDelete, setConfirmDelete] = useState(false);

  // Resize controls
  const [showResizeForm, setShowResizeForm] = useState(false);
  const [newTotal, setNewTotal] = useState<number | "">(novel.total_chapters ?? 0);

  // Generation controls
  const [showGenOptions, setShowGenOptions] = useState(false);
  const [batchSize, setBatchSize] = useState(5);
  const [targetTotal, setTargetTotal] = useState<number | "">("");
  const [genStartCh, setGenStartCh] = useState<number | "">("");
  const [genEndCh, setGenEndCh] = useState<number | "">("");
  const [silentMode, setSilentMode] = useState(false);

  // Polish controls
  const [showPolishOptions, setShowPolishOptions] = useState(false);
  const [polishStartCh, setPolishStartCh] = useState<number | "">("");
  const [polishEndCh, setPolishEndCh] = useState<number | "">("");

  const handleGenerate = () => {
    const params: any = { batch_size: batchSize, silent: silentMode };
    if (targetTotal) params.target_total_chapters = Number(targetTotal);
    if (genStartCh) params.start_chapter = Number(genStartCh);
    if (genEndCh) params.end_chapter = Number(genEndCh);
    genMut.mutate(params);
  };

  const handlePolish = () => {
    const params: any = {};
    if (polishStartCh) params.start_chapter = Number(polishStartCh);
    if (polishEndCh) params.end_chapter = Number(polishEndCh);
    polishMut.mutate(params);
  };

  return (
    <Panel title="操作">
      <div className="space-y-4">
        {/* Main action row */}
        <div className="flex flex-wrap gap-3">
          <button
            className={btnPrimary}
            onClick={() => {
              if (showGenOptions) handleGenerate();
              else setShowGenOptions(true);
            }}
            disabled={genMut.isPending}
          >
            {genMut.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Play className="h-4 w-4" />
            )}
            生成章节
          </button>
          <button
            className={btnSecondary}
            onClick={() => {
              if (showPolishOptions) handlePolish();
              else setShowPolishOptions(true);
            }}
            disabled={polishMut.isPending}
          >
            {polishMut.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Sparkles className="h-4 w-4" />
            )}
            精修润色
          </button>
          <button
            className={btnSecondary}
            onClick={() => exportMut.mutate()}
            disabled={exportMut.isPending}
          >
            {exportMut.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Download className="h-4 w-4" />
            )}
            导出
          </button>
          <button
            className={btnSecondary}
            onClick={() => setShowResizeForm(!showResizeForm)}
            disabled={resizeMut.isPending}
          >
            {resizeMut.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Scaling className="h-4 w-4" />
            )}
            调整章节数
          </button>
          {confirmDelete ? (
            <div className="flex items-center gap-2">
              <button
                className={btnDanger}
                onClick={async () => {
                  await deleteMut.mutateAsync(id);
                  router.push("/novel");
                }}
              >
                确认删除
              </button>
              <button
                className={btnSecondary}
                onClick={() => setConfirmDelete(false)}
              >
                取消
              </button>
            </div>
          ) : (
            <button className={btnDanger} onClick={() => setConfirmDelete(true)}>
              <Trash2 className="h-4 w-4" />
              删除
            </button>
          )}
        </div>

        {/* Generation options panel */}
        {showGenOptions && (
          <div className="rounded-[20px] border border-slate-100 bg-shell p-4">
            <div className="mb-3 flex items-center justify-between">
              <p className="text-sm font-semibold text-ink">章节生成参数</p>
              <button onClick={() => setShowGenOptions(false)} className="text-slate-400 hover:text-slate-600">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <div>
                <label className={labelCls}>批次大小</label>
                <input
                  type="number"
                  min={1}
                  max={100}
                  className={inputCls}
                  value={batchSize}
                  onChange={(e) => setBatchSize(Number(e.target.value) || 5)}
                />
              </div>
              <div>
                <label className={labelCls}>目标总章数</label>
                <input
                  type="number"
                  min={1}
                  className={inputCls}
                  placeholder="自动"
                  value={targetTotal}
                  onChange={(e) =>
                    setTargetTotal(e.target.value ? Number(e.target.value) : "")
                  }
                />
              </div>
              <div>
                <label className={labelCls}>起始章节</label>
                <input
                  type="number"
                  min={1}
                  className={inputCls}
                  placeholder="自动"
                  value={genStartCh}
                  onChange={(e) =>
                    setGenStartCh(e.target.value ? Number(e.target.value) : "")
                  }
                />
              </div>
              <div>
                <label className={labelCls}>结束章节</label>
                <input
                  type="number"
                  min={1}
                  className={inputCls}
                  placeholder="自动"
                  value={genEndCh}
                  onChange={(e) =>
                    setGenEndCh(e.target.value ? Number(e.target.value) : "")
                  }
                />
              </div>
            </div>
            <label className="mt-3 flex items-center gap-2 text-sm text-slate-600">
              <input
                type="checkbox"
                checked={silentMode}
                onChange={(e) => setSilentMode(e.target.checked)}
                className="accent-accent"
              />
              静默模式（跳过质量检查，加速生成）
            </label>
            <button className={btnPrimary + " mt-3"} onClick={handleGenerate} disabled={genMut.isPending}>
              {genMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              开始生成
            </button>
          </div>
        )}

        {/* Polish options panel */}
        {showPolishOptions && (
          <div className="rounded-[20px] border border-slate-100 bg-shell p-4">
            <div className="mb-3 flex items-center justify-between">
              <p className="text-sm font-semibold text-ink">精修参数</p>
              <button onClick={() => setShowPolishOptions(false)} className="text-slate-400 hover:text-slate-600">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>起始章节</label>
                <input
                  type="number"
                  min={1}
                  className={inputCls}
                  placeholder="第1章"
                  value={polishStartCh}
                  onChange={(e) =>
                    setPolishStartCh(e.target.value ? Number(e.target.value) : "")
                  }
                />
              </div>
              <div>
                <label className={labelCls}>结束章节</label>
                <input
                  type="number"
                  min={1}
                  className={inputCls}
                  placeholder="最后一章"
                  value={polishEndCh}
                  onChange={(e) =>
                    setPolishEndCh(e.target.value ? Number(e.target.value) : "")
                  }
                />
              </div>
            </div>
            <button className={btnPrimary + " mt-3"} onClick={handlePolish} disabled={polishMut.isPending}>
              {polishMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              开始精修
            </button>
          </div>
        )}

        {/* Resize panel */}
        {showResizeForm && (
          <div className="rounded-[20px] border border-slate-100 bg-shell p-4">
            <div className="mb-3 flex items-center justify-between">
              <p className="text-sm font-semibold text-ink">调整章节数</p>
              <button onClick={() => setShowResizeForm(false)} className="text-slate-400 hover:text-slate-600">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>当前总章数</label>
                <input
                  type="number"
                  className={inputCls + " bg-slate-50"}
                  value={novel.total_chapters ?? 0}
                  disabled
                />
              </div>
              <div>
                <label className={labelCls}>新目标章数</label>
                <input
                  type="number"
                  min={1}
                  className={inputCls}
                  value={newTotal}
                  onChange={(e) =>
                    setNewTotal(e.target.value ? Number(e.target.value) : "")
                  }
                />
              </div>
            </div>
            <p className="mt-2 text-xs text-slate-500">
              扩容需要 LLM 生成新大纲，缩减立即生效。
            </p>
            <button
              className={btnPrimary + " mt-3"}
              onClick={() => {
                if (newTotal && newTotal !== novel.total_chapters) {
                  resizeMut.mutate(Number(newTotal), {
                    onSuccess: () => setShowResizeForm(false),
                  });
                }
              }}
              disabled={resizeMut.isPending || !newTotal || newTotal === novel.total_chapters}
            >
              {resizeMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Scaling className="h-4 w-4" />}
              确认调整
            </button>
            {resizeMut.isSuccess && (
              <div className="mt-2 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-700">
                {(resizeMut.data as any)?.action === "expanding"
                  ? "扩容任务已提交，请在右侧任务面板查看进度。"
                  : `章节数已从 ${(resizeMut.data as any)?.old_total ?? "?"} 调整为 ${(resizeMut.data as any)?.new_total ?? "?"}`}
              </div>
            )}
            {resizeMut.isError && (
              <div className="mt-2 rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700">
                {(resizeMut.error as Error)?.message ?? "调整失败"}
              </div>
            )}
          </div>
        )}

        {/* Error/success messages */}
        {(genMut.isError || polishMut.isError || exportMut.isError) && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700">
            {(genMut.error as Error)?.message ??
              (polishMut.error as Error)?.message ??
              (exportMut.error as Error)?.message ??
              "操作失败"}
          </div>
        )}
        {genMut.isSuccess && (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-700">
            章节生成任务已提交，请在右侧任务面板查看进度。
          </div>
        )}
        {polishMut.isSuccess && (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-700">
            精修任务已提交，请在右侧任务面板查看进度。
          </div>
        )}
        {exportMut.isSuccess && (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-700">
            导出成功
          </div>
        )}
      </div>
    </Panel>
  );
}

// ─── Outline Section ──────────────────────────────────────────────────
function OutlineSection({ outline }: { outline: any }) {
  const [expanded, setExpanded] = useState(false);
  const [expandedChapters, setExpandedChapters] = useState<Set<number>>(new Set());

  if (!outline) {
    return (
      <Panel title="大纲" description="项目创建后会生成大纲。">
        <p className="text-sm text-slate-500">暂无大纲数据</p>
      </Panel>
    );
  }

  const toggleChapter = (idx: number) => {
    setExpandedChapters((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const renderChapterDetail = (ch: any, j: number) => {
    const isOpen = expandedChapters.has(j);
    return (
      <div key={j} className="border-b border-slate-50 last:border-0">
        <button
          onClick={() => toggleChapter(j)}
          className="flex w-full items-center gap-2 py-2 text-left text-sm hover:bg-shell/50"
        >
          {isOpen ? (
            <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-slate-400" />
          )}
          <span className="font-mono text-xs text-slate-400">
            {String(ch.chapter_number ?? j + 1).padStart(2, "0")}
          </span>
          <span className="flex-1 text-ink">
            {ch.title || `第 ${ch.chapter_number ?? j + 1} 章`}
          </span>
          {ch.mood && (
            <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-700">
              {ch.mood}
            </span>
          )}
        </button>
        {isOpen && (
          <div className="ml-8 space-y-2 pb-3 text-sm">
            {ch.goal && (
              <div>
                <span className="text-xs font-semibold text-slate-500">目标: </span>
                <span className="text-slate-700">{ch.goal}</span>
              </div>
            )}
            {ch.chapter_summary && (
              <div>
                <span className="text-xs font-semibold text-slate-500">摘要: </span>
                <span className="text-slate-700">{ch.chapter_summary}</span>
              </div>
            )}
            {ch.key_events && ch.key_events.length > 0 && (
              <div>
                <span className="text-xs font-semibold text-slate-500">关键事件:</span>
                <ul className="ml-4 mt-1 list-disc text-slate-700">
                  {ch.key_events.map((evt: string, k: number) => (
                    <li key={k} className="text-xs">{evt}</li>
                  ))}
                </ul>
              </div>
            )}
            {ch.involved_characters && ch.involved_characters.length > 0 && (
              <div>
                <span className="text-xs font-semibold text-slate-500">涉及角色: </span>
                <span className="text-xs text-slate-700">
                  {ch.involved_characters.join(", ")}
                </span>
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  const renderOutline = () => {
    if (typeof outline === "string") {
      return (
        <pre className="whitespace-pre-wrap text-sm leading-7 text-slate-700">
          {outline}
        </pre>
      );
    }

    // Acts structure
    if (outline.acts && Array.isArray(outline.acts)) {
      return (
        <div className="space-y-4">
          {outline.acts.map((act: any, i: number) => (
            <div key={i} className="rounded-[20px] border border-slate-100 p-4">
              <p className="text-sm font-semibold text-ink">
                {act.title || `第 ${i + 1} 幕`}
              </p>
              {act.description && (
                <p className="mt-1 text-sm text-slate-600">{act.description}</p>
              )}
              {act.chapters && Array.isArray(act.chapters) && (
                <div className="mt-2">{act.chapters.map(renderChapterDetail)}</div>
              )}
            </div>
          ))}
        </div>
      );
    }

    // Volumes structure
    if (outline.volumes && Array.isArray(outline.volumes)) {
      return (
        <div className="space-y-4">
          {outline.volumes.map((vol: any, i: number) => (
            <div key={i} className="rounded-[20px] border border-slate-100 p-4">
              <p className="text-sm font-semibold text-ink">
                {vol.title || `第 ${i + 1} 卷`}
              </p>
              {vol.description && (
                <p className="mt-1 text-sm text-slate-600">{vol.description}</p>
              )}
              {vol.chapters && Array.isArray(vol.chapters) && (
                <div className="mt-2">{vol.chapters.map(renderChapterDetail)}</div>
              )}
            </div>
          ))}
        </div>
      );
    }

    // Main storyline + flat chapters
    if (outline.chapters && Array.isArray(outline.chapters)) {
      return (
        <div className="space-y-4">
          {outline.main_storyline && (
            <div className="rounded-[20px] border border-accent/20 bg-accent/5 p-4">
              <p className="text-sm font-semibold text-accent">主线设定</p>
              <div className="mt-2 space-y-1 text-sm text-slate-700">
                {outline.main_storyline.protagonist_goal && (
                  <p><span className="font-semibold text-slate-500">目标: </span>{outline.main_storyline.protagonist_goal}</p>
                )}
                {outline.main_storyline.core_conflict && (
                  <p><span className="font-semibold text-slate-500">核心冲突: </span>{outline.main_storyline.core_conflict}</p>
                )}
                {outline.main_storyline.stakes && (
                  <p><span className="font-semibold text-slate-500">赌注: </span>{outline.main_storyline.stakes}</p>
                )}
              </div>
            </div>
          )}
          <div>{outline.chapters.map(renderChapterDetail)}</div>
        </div>
      );
    }

    // Fallback
    return (
      <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-[20px] bg-shell p-4 text-xs text-slate-600">
        {JSON.stringify(outline, null, 2)}
      </pre>
    );
  };

  return (
    <Panel title="大纲">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 text-sm font-semibold text-accent"
      >
        {expanded ? (
          <ChevronDown className="h-4 w-4" />
        ) : (
          <ChevronRight className="h-4 w-4" />
        )}
        {expanded ? "收起大纲" : "展开大纲"}
      </button>
      {expanded && <div className="mt-4">{renderOutline()}</div>}
    </Panel>
  );
}

// ─── Chapters Section ─────────────────────────────────────────────────
function ChaptersSection({
  chapters,
  novelId,
}: {
  chapters: any[];
  novelId: string;
}) {
  const [expandedChapter, setExpandedChapter] = useState<number | null>(null);
  const publishMut = usePublishChapters(novelId);

  // Batch publish controls
  const [showBatchPublish, setShowBatchPublish] = useState(false);
  const [batchUpTo, setBatchUpTo] = useState<number | "">(1);

  const publishedCount = chapters.filter((ch) => ch.published).length;

  const handleTogglePublish = (ch: any, e: React.MouseEvent) => {
    e.stopPropagation();
    publishMut.mutate({
      chapters: [ch.chapter_number],
      published: !ch.published,
    });
  };

  const handleBatchPublish = () => {
    if (!batchUpTo) return;
    const nums = chapters
      .filter((ch) => ch.chapter_number <= Number(batchUpTo) && !ch.published)
      .map((ch) => ch.chapter_number);
    if (nums.length === 0) return;
    publishMut.mutate({ chapters: nums, published: true });
    setShowBatchPublish(false);
  };

  if (!chapters || chapters.length === 0) {
    return (
      <Panel title="章节列表">
        <div className="flex flex-col items-center py-8 text-slate-500">
          <FileText className="mb-2 h-8 w-8 text-slate-300" />
          <p className="text-sm">暂无章节，点击"生成章节"开始创作</p>
        </div>
      </Panel>
    );
  }

  return (
    <Panel title="章节列表" description={`共 ${chapters.length} 章 / 已发布 ${publishedCount} 章 -- 点击展开阅读和编辑`}>
      {/* Batch publish toolbar */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {!showBatchPublish ? (
          <button
            className={btnSecondary}
            onClick={() => {
              setBatchUpTo(chapters.length);
              setShowBatchPublish(true);
            }}
          >
            <CheckCircle2 className="h-3.5 w-3.5" />
            批量发布
          </button>
        ) : (
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">标记前</span>
            <input
              type="number"
              min={1}
              max={chapters.length}
              className={inputCls + " w-20"}
              value={batchUpTo}
              onChange={(e) =>
                setBatchUpTo(e.target.value ? Number(e.target.value) : "")
              }
            />
            <span className="text-xs text-slate-500">章为已发布</span>
            <button
              className={btnPrimary}
              onClick={handleBatchPublish}
              disabled={publishMut.isPending || !batchUpTo}
            >
              {publishMut.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Check className="h-3.5 w-3.5" />
              )}
              确认
            </button>
            <button
              className={btnSecondary}
              onClick={() => setShowBatchPublish(false)}
            >
              取消
            </button>
          </div>
        )}
        {publishMut.isError && (
          <span className="text-xs text-rose-600">
            {(publishMut.error as Error)?.message ?? "操作失败"}
          </span>
        )}
      </div>

      <div className="max-h-[700px] space-y-1 overflow-y-auto">
        {chapters.map((ch) => (
          <div key={ch.chapter_number}>
            <button
              onClick={() =>
                setExpandedChapter(
                  expandedChapter === ch.chapter_number
                    ? null
                    : ch.chapter_number
                )
              }
              className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm transition hover:bg-shell"
            >
              {expandedChapter === ch.chapter_number ? (
                <ChevronDown className="h-4 w-4 text-slate-400" />
              ) : (
                <ChevronRight className="h-4 w-4 text-slate-400" />
              )}
              <span className="min-w-[3rem] font-mono text-xs text-slate-400">
                {String(ch.chapter_number).padStart(3, "0")}
              </span>
              <span className="flex-1 font-medium text-ink">
                {ch.title || `第 ${ch.chapter_number} 章`}
              </span>
              {ch.word_count != null && (
                <span className="text-xs text-slate-400">
                  {ch.word_count} 字
                </span>
              )}
              {ch.status && <StatusBadge status={ch.status} />}
              {/* Publish toggle */}
              <span
                role="button"
                title={ch.published ? "已发布 (点击取消)" : "未发布 (点击发布)"}
                onClick={(e) => handleTogglePublish(ch, e)}
                className={`ml-1 flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium transition ${
                  ch.published
                    ? "bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                    : "bg-slate-100 text-slate-400 hover:bg-slate-200 hover:text-slate-600"
                }`}
              >
                {ch.published ? (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                ) : (
                  <Circle className="h-3.5 w-3.5" />
                )}
                {ch.published ? "已发布" : "未发布"}
              </span>
            </button>
            {expandedChapter === ch.chapter_number && (
              <ChapterEditor
                novelId={novelId}
                chapterNum={ch.chapter_number}
              />
            )}
          </div>
        ))}
      </div>
    </Panel>
  );
}

// ─── Chapter Editor (replaces ChapterReader) ──────────────────────────
function ChapterEditor({
  novelId,
  chapterNum,
}: {
  novelId: string;
  chapterNum: number;
}) {
  const { data, isLoading, isError, error } = useChapter(novelId, chapterNum);
  const saveMut = useSaveChapter(novelId);
  const proofreadMut = useProofreadChapter(novelId);
  const applyFixesMut = useApplyFixes(novelId);

  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState("");
  const [issues, setIssues] = useState<any[]>([]);
  const [selectedIssues, setSelectedIssues] = useState<Set<number>>(new Set());

  // Initialize edit text when data loads
  useEffect(() => {
    if (data?.text && !editing) {
      setEditText(data.text);
    }
  }, [data?.text, editing]);

  const handleStartEdit = () => {
    setEditText(data?.text ?? "");
    setEditing(true);
  };

  const handleSave = () => {
    saveMut.mutate(
      { chapterNum, text: editText },
      {
        onSuccess: () => {
          setEditing(false);
        },
      }
    );
  };

  const handleProofread = () => {
    proofreadMut.mutate(chapterNum, {
      onSuccess: (result) => {
        setIssues(result?.issues ?? []);
        setSelectedIssues(new Set((result?.issues ?? []).map((_: any, i: number) => i)));
      },
    });
  };

  const handleApplyFixes = () => {
    const indices = Array.from(selectedIssues);
    applyFixesMut.mutate(
      {
        chapterNum,
        text: editing ? editText : (data?.text ?? ""),
        issues,
        selectedIndices: indices,
      },
      {
        onSuccess: (result) => {
          if (result?.text) {
            setEditText(result.text);
            setEditing(true);
          }
          setIssues([]);
          setSelectedIssues(new Set());
        },
      }
    );
  };

  const toggleIssue = (idx: number) => {
    setSelectedIssues((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const ISSUE_TYPE_LABELS: Record<string, string> = {
    punctuation: "标点",
    grammar: "语法",
    typo: "错别字",
    word_choice: "用词",
    redundancy: "冗余",
  };

  return (
    <div className="mx-3 mb-2 space-y-3 rounded-[20px] border border-slate-100 bg-shell p-4">
      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          加载章节内容...
        </div>
      )}
      {isError && (
        <p className="text-xs text-rose-600">
          加载失败：{(error as Error)?.message ?? "未知错误"}
        </p>
      )}

      {data?.text && (
        <>
          {/* Action buttons */}
          <div className="flex flex-wrap gap-2">
            {!editing ? (
              <button className={btnSecondary} onClick={handleStartEdit}>
                <Pencil className="h-3.5 w-3.5" />
                编辑
              </button>
            ) : (
              <>
                <button
                  className={btnPrimary}
                  onClick={handleSave}
                  disabled={saveMut.isPending}
                >
                  {saveMut.isPending ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Save className="h-3.5 w-3.5" />
                  )}
                  保存
                </button>
                <button
                  className={btnSecondary}
                  onClick={() => {
                    setEditing(false);
                    setEditText(data.text);
                  }}
                >
                  取消
                </button>
              </>
            )}
            <button
              className={btnSecondary}
              onClick={handleProofread}
              disabled={proofreadMut.isPending}
            >
              {proofreadMut.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Search className="h-3.5 w-3.5" />
              )}
              AI 校对
            </button>
          </div>

          {/* Text area (editable or read-only) */}
          {editing ? (
            <textarea
              className="max-h-[500px] min-h-[300px] w-full resize-y rounded-xl border border-slate-200 bg-white p-3 text-sm leading-7 text-slate-700 outline-none focus:border-accent"
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
            />
          ) : (
            <div className="max-h-[400px] overflow-y-auto whitespace-pre-wrap text-sm leading-7 text-slate-700">
              {data.text}
            </div>
          )}

          {/* Save status */}
          {saveMut.isSuccess && (
            <p className="text-xs text-emerald-600">
              已保存（{(saveMut.data as any)?.char_count}字，原{(saveMut.data as any)?.old_char_count}字）
            </p>
          )}
          {saveMut.isError && (
            <p className="text-xs text-rose-600">
              保存失败：{(saveMut.error as Error)?.message}
            </p>
          )}

          {/* Proofread issues */}
          {issues.length > 0 && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-3">
              <div className="mb-2 flex items-center justify-between">
                <p className="text-sm font-semibold text-amber-800">
                  发现 {issues.length} 个问题
                </p>
                <div className="flex gap-2">
                  <button
                    className="text-xs font-semibold text-amber-700 hover:underline"
                    onClick={() =>
                      setSelectedIssues(new Set(issues.map((_: any, i: number) => i)))
                    }
                  >
                    全选
                  </button>
                  <button
                    className="text-xs font-semibold text-amber-700 hover:underline"
                    onClick={() => setSelectedIssues(new Set())}
                  >
                    全不选
                  </button>
                </div>
              </div>
              <div className="max-h-[250px] space-y-1.5 overflow-y-auto">
                {issues.map((issue: any, idx: number) => (
                  <label
                    key={idx}
                    className="flex cursor-pointer items-start gap-2 rounded-lg p-1.5 text-xs hover:bg-amber-100"
                  >
                    <input
                      type="checkbox"
                      className="mt-0.5 accent-accent"
                      checked={selectedIssues.has(idx)}
                      onChange={() => toggleIssue(idx)}
                    />
                    <div className="flex-1">
                      <span className="rounded bg-amber-200 px-1 py-0.5 text-xs font-medium text-amber-800">
                        {ISSUE_TYPE_LABELS[issue.issue_type] ?? issue.issue_type}
                      </span>{" "}
                      <span className="text-amber-900">
                        「{(issue.original ?? "").slice(0, 30)}」 →
                        「{(issue.correction ?? "").slice(0, 30)}」
                      </span>
                      {issue.explanation && (
                        <span className="ml-1 text-amber-700">
                          -- {issue.explanation.slice(0, 50)}
                        </span>
                      )}
                    </div>
                  </label>
                ))}
              </div>
              <button
                className={btnPrimary + " mt-2"}
                onClick={handleApplyFixes}
                disabled={selectedIssues.size === 0 || applyFixesMut.isPending}
              >
                {applyFixesMut.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Check className="h-3.5 w-3.5" />
                )}
                应用选中的 {selectedIssues.size} 条修正
              </button>
              {applyFixesMut.isError && (
                <p className="mt-1 text-xs text-rose-600">
                  修正失败：{(applyFixesMut.error as Error)?.message}
                </p>
              )}
            </div>
          )}
          {proofreadMut.isSuccess && issues.length === 0 && (
            <p className="text-xs text-emerald-600">AI 校对完成，未发现问题</p>
          )}
        </>
      )}
    </div>
  );
}

// ─── Characters Section ───────────────────────────────────────────────
function CharactersSection({ characters }: { characters: any[] }) {
  const [expanded, setExpanded] = useState(false);

  if (!characters || characters.length === 0) {
    return null;
  }

  return (
    <Panel title="角色设定">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 text-sm font-semibold text-accent"
      >
        {expanded ? (
          <ChevronDown className="h-4 w-4" />
        ) : (
          <ChevronRight className="h-4 w-4" />
        )}
        <Users className="h-4 w-4" />
        {expanded ? "收起" : `查看 ${characters.length} 个角色`}
      </button>
      {expanded && (
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {characters.map((char, i) => (
            <div
              key={char.character_id ?? i}
              className="rounded-[20px] border border-slate-100 p-4"
            >
              <div className="flex items-center gap-2">
                <p className="font-semibold text-ink">{char.name}</p>
                {char.role && (
                  <span className="rounded-full bg-accent/10 px-2 py-0.5 text-xs font-medium text-accent">
                    {char.role}
                  </span>
                )}
                {char.gender && (
                  <span className="text-xs text-slate-400">{char.gender}</span>
                )}
                {char.age && (
                  <span className="text-xs text-slate-400">{char.age}岁</span>
                )}
              </div>
              {char.occupation && (
                <p className="mt-1 text-xs text-slate-500">职业: {char.occupation}</p>
              )}
              {char.description && (
                <p className="mt-2 text-sm leading-6 text-slate-600">
                  {char.description}
                </p>
              )}

              {/* Appearance */}
              {char.appearance && typeof char.appearance === "object" && (
                <div className="mt-2">
                  <p className="text-xs font-semibold text-slate-500">外貌</p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {char.appearance.height && (
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                        {char.appearance.height}
                      </span>
                    )}
                    {char.appearance.build && (
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                        {char.appearance.build}
                      </span>
                    )}
                    {char.appearance.hair && (
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                        {char.appearance.hair}
                      </span>
                    )}
                    {char.appearance.eyes && (
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                        {char.appearance.eyes}
                      </span>
                    )}
                    {char.appearance.clothing_style && (
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                        {char.appearance.clothing_style}
                      </span>
                    )}
                    {char.appearance.distinctive_features?.map((f: string, k: number) => (
                      <span key={k} className="rounded bg-amber-50 px-1.5 py-0.5 text-xs text-amber-700">
                        {f}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Personality */}
              {char.personality && typeof char.personality === "object" && (
                <div className="mt-2">
                  <p className="text-xs font-semibold text-slate-500">性格</p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {char.personality.traits?.map((t: string, k: number) => (
                      <span key={k} className="rounded bg-blue-50 px-1.5 py-0.5 text-xs text-blue-700">
                        {t}
                      </span>
                    ))}
                  </div>
                  {char.personality.motivation && (
                    <p className="mt-1 text-xs text-slate-500">
                      动机: {char.personality.motivation}
                    </p>
                  )}
                  {char.personality.flaw && (
                    <p className="text-xs text-slate-500">
                      缺点: {char.personality.flaw}
                    </p>
                  )}
                  {char.personality.speech_style && (
                    <p className="text-xs text-slate-500">
                      说话风格: {char.personality.speech_style}
                    </p>
                  )}
                </div>
              )}

              {/* Character Arc */}
              {char.character_arc && typeof char.character_arc === "object" && (
                <div className="mt-2">
                  <p className="text-xs font-semibold text-slate-500">角色弧线</p>
                  <div className="mt-1 flex items-center gap-1 text-xs text-slate-600">
                    <span className="rounded bg-slate-100 px-1.5 py-0.5">
                      {char.character_arc.initial_state || "?"}
                    </span>
                    <span className="text-slate-400">→</span>
                    <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-700">
                      {char.character_arc.final_state || "?"}
                    </span>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

// ─── World Setting Section ────────────────────────────────────────────
function WorldSection({ worldSetting }: { worldSetting: any }) {
  const [expanded, setExpanded] = useState(false);

  if (!worldSetting) {
    return null;
  }

  const ws = typeof worldSetting === "string" ? null : worldSetting;

  return (
    <Panel title="世界观设定">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 text-sm font-semibold text-accent"
      >
        {expanded ? (
          <ChevronDown className="h-4 w-4" />
        ) : (
          <ChevronRight className="h-4 w-4" />
        )}
        <Globe className="h-4 w-4" />
        {expanded ? "收起" : "查看世界观"}
      </button>
      {expanded && (
        <div className="mt-4 space-y-4">
          {typeof worldSetting === "string" ? (
            <pre className="whitespace-pre-wrap text-sm leading-7 text-slate-700">
              {worldSetting}
            </pre>
          ) : (
            <>
              {/* Basic info */}
              <div className="grid grid-cols-2 gap-3 text-sm">
                {ws?.era && (
                  <div>
                    <span className="text-xs font-semibold text-slate-500">时代</span>
                    <p className="text-ink">{ws.era}</p>
                  </div>
                )}
                {ws?.location && (
                  <div>
                    <span className="text-xs font-semibold text-slate-500">地点</span>
                    <p className="text-ink">{ws.location}</p>
                  </div>
                )}
              </div>

              {/* Power system */}
              {ws?.power_system && (
                <div className="rounded-[16px] border border-slate-100 p-3">
                  <p className="text-sm font-semibold text-ink">
                    力量体系: {ws.power_system.name}
                  </p>
                  {ws.power_system.levels && ws.power_system.levels.length > 0 && (
                    <div className="mt-2 space-y-1">
                      {ws.power_system.levels.map((level: any, i: number) => (
                        <div key={i} className="flex items-start gap-2 text-xs">
                          <span className="min-w-[1.5rem] rounded bg-accent/10 px-1.5 py-0.5 text-center font-mono text-accent">
                            {level.rank ?? i + 1}
                          </span>
                          <span className="font-medium text-ink">{level.name}</span>
                          {level.description && level.description !== level.name && (
                            <span className="text-slate-500">- {level.description}</span>
                          )}
                          {level.typical_abilities && level.typical_abilities.length > 0 && (
                            <span className="text-slate-400">
                              ({level.typical_abilities.join(", ")})
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Factions */}
              {ws?.factions && ws.factions.length > 0 && (
                <div className="rounded-[16px] border border-slate-100 p-3">
                  <p className="text-sm font-semibold text-ink">势力</p>
                  <div className="mt-2 space-y-1">
                    {ws.factions.map((faction: any, i: number) => (
                      <div key={i} className="text-xs">
                        <span className="font-medium text-ink">{faction.name || faction}</span>
                        {faction.description && (
                          <span className="ml-1 text-slate-500">- {faction.description}</span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Rules */}
              {ws?.rules && ws.rules.length > 0 && (
                <div className="rounded-[16px] border border-slate-100 p-3">
                  <p className="text-sm font-semibold text-ink">世界规则</p>
                  <ul className="mt-2 list-disc space-y-1 pl-4">
                    {ws.rules.map((rule: string, i: number) => (
                      <li key={i} className="text-xs text-slate-700">{rule}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Terms dictionary */}
              {ws?.terms && Object.keys(ws.terms).length > 0 && (
                <div className="rounded-[16px] border border-slate-100 p-3">
                  <p className="text-sm font-semibold text-ink">专有名词</p>
                  <div className="mt-2 grid grid-cols-2 gap-1">
                    {Object.entries(ws.terms).map(([term, desc]: [string, any]) => (
                      <div key={term} className="text-xs">
                        <span className="font-medium text-ink">{term}</span>
                        {desc && <span className="ml-1 text-slate-500">: {desc}</span>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </Panel>
  );
}

// ─── Feedback Section ─────────────────────────────────────────────────
function FeedbackSection({ novelId, totalChapters }: { novelId: string; totalChapters: number }) {
  const [feedbackText, setFeedbackText] = useState("");
  const [chapterInput, setChapterInput] = useState("1");
  const analyzeMut = useAnalyzeFeedback(novelId);
  const applyMut = useApplyFeedback(novelId);
  const [analysisResult, setAnalysisResult] = useState<any>(null);

  return (
    <Panel title="读者反馈" description="输入反馈内容，分析影响范围或直接应用到指定章节。">
      <div className="space-y-4">
        <div className="flex items-center gap-2 text-accent">
          <MessageSquare className="h-5 w-5" />
          <span className="text-sm font-semibold">反馈重写</span>
        </div>

        <div>
          <label className={labelCls}>反馈内容</label>
          <textarea
            className={inputCls + " min-h-[80px] resize-y"}
            placeholder="例如：第5章主角性格变化太突兀，跟前面的铺垫不一致..."
            value={feedbackText}
            onChange={(e) => setFeedbackText(e.target.value)}
            rows={3}
          />
        </div>

        <div>
          <label className={labelCls}>
            相关章节（支持: 单章 8，范围 8-12，多章 3,7,15）
          </label>
          <input
            type="text"
            className={inputCls + " max-w-xs"}
            placeholder="例如: 5 或 3-8 或 1,5,10"
            value={chapterInput}
            onChange={(e) => setChapterInput(e.target.value)}
          />
        </div>

        <div className="flex gap-3">
          <button
            className={btnSecondary}
            onClick={() => {
              analyzeMut.mutate(
                {
                  feedback_text: feedbackText,
                  chapter_input: chapterInput,
                  dry_run: true,
                },
                {
                  onSuccess: (data) => setAnalysisResult(data),
                }
              );
            }}
            disabled={!feedbackText.trim() || analyzeMut.isPending}
          >
            {analyzeMut.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Eye className="h-4 w-4" />
            )}
            分析影响
          </button>
          <button
            className={btnPrimary}
            onClick={() =>
              applyMut.mutate({
                feedback_text: feedbackText,
                chapter_input: chapterInput,
                dry_run: false,
              })
            }
            disabled={!feedbackText.trim() || applyMut.isPending}
          >
            {applyMut.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            应用反馈
          </button>
        </div>

        {/* Analysis results */}
        {analysisResult && (
          <div className="rounded-[20px] border border-blue-200 bg-blue-50 p-4">
            <p className="mb-2 text-sm font-semibold text-blue-900">分析结果</p>
            {analysisResult.analysis && (
              <div className="space-y-2 text-sm">
                <div className="flex items-center gap-3">
                  <span className="text-xs font-semibold text-blue-700">问题类型:</span>
                  <span className="text-blue-900">{analysisResult.analysis.feedback_type ?? "未知"}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs font-semibold text-blue-700">严重程度:</span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                      analysisResult.analysis.severity === "high"
                        ? "bg-rose-100 text-rose-700"
                        : analysisResult.analysis.severity === "medium"
                          ? "bg-amber-100 text-amber-700"
                          : "bg-emerald-100 text-emerald-700"
                    }`}
                  >
                    {analysisResult.analysis.severity ?? "?"}
                  </span>
                </div>
                {analysisResult.analysis.summary && (
                  <div>
                    <span className="text-xs font-semibold text-blue-700">诊断摘要:</span>
                    <p className="mt-0.5 text-blue-900">{analysisResult.analysis.summary}</p>
                  </div>
                )}
                {analysisResult.analysis.target_chapters?.length > 0 && (
                  <div>
                    <span className="text-xs font-semibold text-blue-700">直接影响:</span>
                    <span className="ml-1 text-blue-900">
                      第{analysisResult.analysis.target_chapters.join("、")}章
                    </span>
                  </div>
                )}
                {analysisResult.analysis.propagation_chapters?.length > 0 && (
                  <div>
                    <span className="text-xs font-semibold text-blue-700">传播影响:</span>
                    <span className="ml-1 text-blue-900">
                      第{analysisResult.analysis.propagation_chapters.join("、")}章
                    </span>
                  </div>
                )}

                {/* Rewrite instructions per chapter */}
                {analysisResult.analysis.rewrite_instructions &&
                  Object.keys(analysisResult.analysis.rewrite_instructions).length > 0 && (
                    <div className="mt-2 rounded-xl border border-blue-200 bg-white p-3">
                      <p className="mb-1 text-xs font-semibold text-blue-700">修改方案:</p>
                      {Object.entries(analysisResult.analysis.rewrite_instructions)
                        .sort(([a], [b]) => Number(a) - Number(b))
                        .map(([chNum, instr]: [string, any]) => (
                          <div key={chNum} className="mt-1 border-t border-blue-100 pt-1">
                            <p className="text-xs font-semibold text-blue-800">第{chNum}章:</p>
                            <p className="text-xs text-blue-700">{instr}</p>
                          </div>
                        ))}
                    </div>
                  )}
              </div>
            )}
          </div>
        )}

        {/* Apply feedback results */}
        {applyMut.isSuccess && (applyMut.data as any)?.rewritten_chapters && (
          <div className="rounded-[20px] border border-emerald-200 bg-emerald-50 p-4">
            <p className="mb-2 text-sm font-semibold text-emerald-900">重写完成</p>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-emerald-200 text-left text-emerald-700">
                    <th className="py-1.5 pr-4">章节</th>
                    <th className="py-1.5 pr-4">原字数</th>
                    <th className="py-1.5 pr-4">新字数</th>
                    <th className="py-1.5">类型</th>
                  </tr>
                </thead>
                <tbody className="text-emerald-900">
                  {((applyMut.data as any).rewritten_chapters ?? []).map((rw: any) => (
                    <tr key={rw.chapter_number} className="border-b border-emerald-100">
                      <td className="py-1.5 pr-4">第{rw.chapter_number}章</td>
                      <td className="py-1.5 pr-4">{rw.original_chars}字</td>
                      <td className="py-1.5 pr-4">{rw.new_chars}字</td>
                      <td className="py-1.5">
                        {rw.is_propagation ? "传播修改" : "直接修改"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Error messages */}
        {(analyzeMut.isError || applyMut.isError) && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700">
            {(analyzeMut.error as Error)?.message ??
              (applyMut.error as Error)?.message ??
              "操作失败"}
          </div>
        )}
        {analyzeMut.isSuccess && !analysisResult && (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-700">
            分析任务已提交，请在任务中心查看进度。
          </div>
        )}
        {applyMut.isSuccess && !(applyMut.data as any)?.rewritten_chapters && (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-700">
            反馈应用任务已提交，请在任务中心查看进度。
          </div>
        )}
      </div>
    </Panel>
  );
}

// ─── Edit Section ─────────────────────────────────────────────────────
function EditSection({ novelId }: { novelId: string }) {
  const [instruction, setInstruction] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState<number | "">(1);
  const editMut = useEditNovel(novelId);
  const [editResult, setEditResult] = useState<any>(null);

  const ENTITY_LABELS: Record<string, string> = {
    character: "角色",
    outline: "大纲",
    world_setting: "世界观",
  };
  const CHANGE_LABELS: Record<string, string> = {
    add: "新增",
    update: "修改",
    delete: "删除",
  };

  return (
    <Panel title="AI 编辑" description="用自然语言指令修改小说设定或内容。">
      <div className="space-y-4">
        <div className="flex items-center gap-2 text-accent">
          <Pencil className="h-5 w-5" />
          <span className="text-sm font-semibold">智能编辑</span>
        </div>

        <div>
          <label className={labelCls}>编辑指令</label>
          <textarea
            className={inputCls + " min-h-[80px] resize-y"}
            placeholder="例如：把主角的武器从剑改成枪，从第3章开始生效..."
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            rows={3}
          />
        </div>

        <div>
          <label className={labelCls}>生效起始章节</label>
          <input
            type="number"
            min={1}
            className={inputCls + " max-w-[120px]"}
            value={effectiveFrom}
            onChange={(e) =>
              setEffectiveFrom(e.target.value ? Number(e.target.value) : "")
            }
          />
        </div>

        <button
          className={btnPrimary}
          onClick={() =>
            editMut.mutate(
              {
                instruction,
                effective_from_chapter: effectiveFrom || undefined,
              },
              {
                onSuccess: (data) => setEditResult(data),
              }
            )
          }
          disabled={!instruction.trim() || editMut.isPending}
        >
          {editMut.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Pencil className="h-4 w-4" />
          )}
          执行编辑
        </button>

        {/* Edit result display */}
        {editResult && (
          <div className="rounded-[20px] border border-blue-200 bg-blue-50 p-4">
            <p className="mb-2 text-sm font-semibold text-blue-900">
              {editResult.status === "failed" ? "编辑失败" : "编辑完成"}
            </p>
            {editResult.status !== "failed" && (
              <div className="space-y-1 text-sm text-blue-900">
                <p>
                  <span className="font-semibold text-blue-700">操作: </span>
                  {CHANGE_LABELS[editResult.change_type] ?? editResult.change_type}
                  {ENTITY_LABELS[editResult.entity_type] ?? editResult.entity_type}
                </p>
                {editResult.entity_id && (
                  <p>
                    <span className="font-semibold text-blue-700">对象: </span>
                    {editResult.entity_id}
                  </p>
                )}
                {editResult.effective_from_chapter != null && (
                  <p>
                    <span className="font-semibold text-blue-700">生效章节: </span>
                    第 {editResult.effective_from_chapter} 章起
                  </p>
                )}
                {editResult.reasoning && (
                  <p>
                    <span className="font-semibold text-blue-700">说明: </span>
                    {editResult.reasoning}
                  </p>
                )}

                {/* Change details */}
                {editResult.old_value && editResult.new_value && (
                  <div className="mt-2 rounded-xl border border-blue-200 bg-white p-3">
                    <p className="mb-1 text-xs font-semibold text-blue-700">变更详情:</p>
                    <div className="space-y-0.5">
                      {renderChangeDetails(editResult.old_value, editResult.new_value)}
                    </div>
                  </div>
                )}
                {!editResult.old_value && editResult.new_value && (
                  <div className="mt-2 rounded-xl border border-blue-200 bg-white p-3">
                    <p className="mb-1 text-xs font-semibold text-blue-700">新增内容:</p>
                    <div className="space-y-0.5">
                      {Object.entries(editResult.new_value)
                        .filter(([_, v]) => v)
                        .map(([k, v]) => (
                          <p key={k} className="text-xs">
                            <code className="rounded bg-slate-100 px-1">{k}</code>:{" "}
                            {String(v).slice(0, 60)}
                          </p>
                        ))}
                    </div>
                  </div>
                )}
              </div>
            )}
            {editResult.status === "failed" && (
              <p className="text-sm text-rose-700">{editResult.error || "未知错误"}</p>
            )}
          </div>
        )}

        {editMut.isError && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700">
            {(editMut.error as Error)?.message ?? "编辑失败"}
          </div>
        )}
      </div>
    </Panel>
  );
}

// ─── Agent Chat ──────────────────────────────────────────────────────
interface ToolStep {
  step?: number;
  thinking?: string;
  tool: string;
  args?: any;
  result?: any;
}

interface ChatMessage {
  role: "user" | "agent";
  content: string;
  steps?: ToolStep[];
  model?: string;
}

const TOOL_LABELS: Record<string, { label: string; icon: string }> = {
  read_chapter: { label: "读取章节", icon: "📖" },
  edit_setting: { label: "修改设定", icon: "✏️" },
  rewrite_chapter: { label: "重写章节", icon: "🔄" },
  resize_novel: { label: "调整章节数", icon: "📐" },
  publish_chapters: { label: "标记发布", icon: "📤" },
  proofread_chapter: { label: "校对章节", icon: "🔍" },
  get_novel_info: { label: "获取信息", icon: "ℹ️" },
  search_chapters: { label: "搜索内容", icon: "🔎" },
  reply_to_user: { label: "回复", icon: "💬" },
};

function formatToolResult(result: any): string {
  if (!result) return "";
  if (typeof result === "string") return result;
  if (result.error) return `❌ ${result.error}`;
  // Compact key summaries
  const lines: string[] = [];
  for (const [k, v] of Object.entries(result)) {
    if (k === "text" && typeof v === "string") {
      lines.push(`${k}: ${(v as string).slice(0, 120)}${(v as string).length > 120 ? "..." : ""}`);
    } else if (typeof v === "string" && (v as string).length > 200) {
      lines.push(`${k}: ${(v as string).slice(0, 200)}...`);
    } else if (Array.isArray(v)) {
      lines.push(`${k}: [${(v as any[]).length} items]`);
    } else if (typeof v === "object" && v !== null) {
      lines.push(`${k}: ${JSON.stringify(v).slice(0, 150)}`);
    } else {
      lines.push(`${k}: ${v}`);
    }
  }
  return lines.join("\n");
}

function ToolStepCard({ step, defaultOpen }: { step: ToolStep; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const info = TOOL_LABELS[step.tool] ?? { label: step.tool, icon: "🔧" };
  const hasError = step.result?.error;
  const isReply = step.tool === "reply_to_user";

  if (isReply) return null; // reply content shown in main bubble

  return (
    <div className={`rounded-lg border text-xs ${hasError ? "border-rose-200 bg-rose-50/50" : "border-slate-200 bg-white"}`}>
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-slate-50/50 transition rounded-lg"
      >
        <span>{info.icon}</span>
        <span className="font-semibold text-ink">{info.label}</span>
        {step.args && !isReply && (
          <span className="text-slate-400 truncate flex-1">
            {Object.entries(step.args).map(([k, v]) =>
              typeof v === "string" ? `${k}="${(v as string).slice(0, 30)}"` : `${k}=${JSON.stringify(v)}`
            ).join(" ")}
          </span>
        )}
        {hasError && <span className="text-rose-500 text-[10px]">失败</span>}
        {!hasError && !isReply && <span className="text-emerald-500 text-[10px]">✓</span>}
        <ChevronDown className={`h-3 w-3 text-slate-400 transition ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="border-t border-slate-100 px-3 py-2 space-y-1.5">
          {step.thinking && (
            <div className="text-slate-500 italic">
              <span className="text-slate-400">思考: </span>{step.thinking}
            </div>
          )}
          {step.result && (
            <pre className="whitespace-pre-wrap text-[11px] text-slate-600 max-h-48 overflow-y-auto bg-slate-50 rounded p-2">
              {formatToolResult(step.result)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

function AgentChatSection({ novelId }: { novelId: string }) {
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [optimisticMessages, setOptimisticMessages] = useState<ChatMessage[]>([]);
  const [inputMessage, setInputMessage] = useState("");
  const [contextChapters, setContextChapters] = useState("");
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const qc = useQueryClient();

  const { data: conversations, isLoading: convsLoading } = useConversations(novelId);
  const { data: serverMessages, refetch: refetchMessages } = useConversationMessages(novelId, activeSessionId);
  const createConv = useCreateConversation(novelId);
  const deleteConv = useDeleteConversation(novelId);
  const agentChatMut = useAgentChat(novelId);
  const { data: taskData } = useTask(activeTaskId);

  // Merge server messages with optimistic messages
  const displayMessages: ChatMessage[] = (() => {
    const base: ChatMessage[] = (serverMessages ?? []).map((m) => ({
      role: m.role,
      content: m.content,
      steps: m.steps,
      model: m.model,
    }));
    // Append optimistic user messages not yet in server response
    const serverCount = base.length;
    const optimisticNew = optimisticMessages.slice(
      Math.max(0, serverCount)
    );
    return [...base, ...optimisticNew];
  })();

  // Auto-select latest conversation on load
  useEffect(() => {
    if (!activeSessionId && conversations && conversations.length > 0) {
      setActiveSessionId(conversations[0].session_id);
    }
  }, [conversations, activeSessionId]);

  // Auto-scroll to bottom when messages change
  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [displayMessages.length, scrollToBottom]);

  // Clear optimistic messages when switching sessions
  useEffect(() => {
    setOptimisticMessages([]);
    setActiveTaskId(null);
  }, [activeSessionId]);

  // Poll task completion
  useEffect(() => {
    if (!taskData || !activeTaskId) return;
    if (taskData.status === "completed") {
      // Refetch server messages to get the stored agent reply
      refetchMessages();
      setOptimisticMessages([]);
      setActiveTaskId(null);
      // Invalidate caches — agent may have modified chapters, settings, etc.
      qc.invalidateQueries({ queryKey: ["novel", novelId] });
      qc.invalidateQueries({ queryKey: ["chapter"] });
      qc.invalidateQueries({ queryKey: ["novel-settings", novelId] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
      qc.invalidateQueries({ queryKey: ["conversations", novelId] });
    } else if (taskData.status === "failed") {
      const errMsg = taskData.error || "Agent 处理失败，请稍后重试。";
      setOptimisticMessages((prev) => [
        ...prev,
        { role: "agent", content: `[错误] ${errMsg}` },
      ]);
      setActiveTaskId(null);
    }
  }, [taskData, activeTaskId, novelId, qc, refetchMessages]);

  const handleNewConversation = async () => {
    try {
      const conv = await createConv.mutateAsync(undefined);
      setActiveSessionId(conv.session_id);
      setOptimisticMessages([]);
      setActiveTaskId(null);
    } catch {
      // ignore
    }
  };

  const handleDeleteConversation = async (sessionId: string) => {
    try {
      await deleteConv.mutateAsync(sessionId);
      if (activeSessionId === sessionId) {
        setActiveSessionId(null);
        setOptimisticMessages([]);
        setActiveTaskId(null);
      }
    } catch {
      // ignore
    }
  };

  const handleSelectConversation = (sessionId: string) => {
    if (sessionId === activeSessionId) return;
    setActiveSessionId(sessionId);
  };

  const handleSend = () => {
    const msg = inputMessage.trim();
    if (!msg || agentChatMut.isPending || activeTaskId) return;

    const chapters = contextChapters
      .split(/[,，\s]+/)
      .map((s) => parseInt(s.trim(), 10))
      .filter((n) => !isNaN(n) && n > 0);

    // Optimistically add user message
    setOptimisticMessages((prev) => [...prev, { role: "user", content: msg }]);
    setInputMessage("");

    // Build conversation history for multi-turn context
    const allMsgs = [...displayMessages, { role: "user" as const, content: msg }];
    const history = allMsgs.map((m) => ({
      role: m.role === "agent" ? "assistant" : "user",
      content: m.content,
    }));

    agentChatMut.mutate(
      {
        message: msg,
        contextChapters: chapters.length > 0 ? chapters : undefined,
        history: history.length > 0 ? history : undefined,
        sessionId: activeSessionId ?? undefined,
      },
      {
        onSuccess: (data) => {
          setActiveTaskId(data.task_id);
          // If backend created a new session, track it
          if (data.session_id && !activeSessionId) {
            setActiveSessionId(data.session_id);
            qc.invalidateQueries({ queryKey: ["conversations", novelId] });
          }
        },
        onError: (err) => {
          setOptimisticMessages((prev) => [
            ...prev,
            {
              role: "agent",
              content: `[错误] ${(err as Error)?.message ?? "发送失败"}`,
            },
          ]);
        },
      }
    );
  };

  const isWorking = agentChatMut.isPending || !!activeTaskId;

  const formatDate = (dateStr: string) => {
    try {
      const d = new Date(dateStr);
      const now = new Date();
      const diffMs = now.getTime() - d.getTime();
      const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
      if (diffDays === 0) return "今天";
      if (diffDays === 1) return "昨天";
      if (diffDays < 7) return `${diffDays}天前`;
      return `${d.getMonth() + 1}/${d.getDate()}`;
    } catch {
      return "";
    }
  };

  return (
    <Panel title="Agent 对话" description="与 AI Agent 对话，讨论你的小说。">
      <div className="flex" style={{ height: "min(70vh, 680px)" }}>
        {/* Left sidebar — conversation list */}
        <div
          className={`shrink-0 border-r border-slate-200 transition-all overflow-hidden ${
            sidebarOpen ? "w-[200px]" : "w-0 border-r-0"
          }`}
        >
          <div className="flex flex-col h-full w-[200px]">
            {/* New conversation button */}
            <button
              onClick={handleNewConversation}
              disabled={createConv.isPending}
              className="m-2 flex items-center justify-center gap-1.5 rounded-xl border border-dashed border-slate-300 px-3 py-2 text-xs font-semibold text-slate-600 transition hover:border-accent hover:text-accent disabled:opacity-50"
            >
              {createConv.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <MessageSquarePlus className="h-3.5 w-3.5" />
              )}
              新对话
            </button>

            {/* Conversation list */}
            <div className="flex-1 overflow-y-auto">
              {convsLoading ? (
                <div className="flex items-center justify-center py-6 text-slate-400">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                </div>
              ) : !conversations || conversations.length === 0 ? (
                <p className="px-3 py-4 text-center text-xs text-slate-400">
                  暂无对话
                </p>
              ) : (
                <div className="space-y-0.5 px-1.5">
                  {conversations.map((conv) => (
                    <div
                      key={conv.session_id}
                      className={`group relative flex items-center rounded-lg px-2.5 py-2 text-xs cursor-pointer transition ${
                        activeSessionId === conv.session_id
                          ? "bg-accent/10 text-accent font-semibold"
                          : "text-slate-600 hover:bg-slate-50"
                      }`}
                      onClick={() => handleSelectConversation(conv.session_id)}
                    >
                      <div className="flex-1 min-w-0">
                        <p className="truncate">{conv.title || "新对话"}</p>
                        <p className="mt-0.5 text-[10px] text-slate-400">
                          {formatDate(conv.updated_at || conv.created_at)}
                          {conv.message_count > 0 && ` / ${conv.message_count}条`}
                        </p>
                      </div>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteConversation(conv.session_id);
                        }}
                        className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-slate-300 opacity-0 transition hover:bg-rose-50 hover:text-rose-500 group-hover:opacity-100"
                        title="删除对话"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Right main area */}
        <div className="flex flex-1 flex-col min-w-0">
          {/* Toggle sidebar button */}
          <div className="flex items-center gap-2 border-b border-slate-100 px-2 py-1">
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="rounded p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
              title={sidebarOpen ? "收起会话列表" : "展开会话列表"}
            >
              {sidebarOpen ? (
                <ChevronRight className="h-3.5 w-3.5 rotate-180" />
              ) : (
                <ChevronRight className="h-3.5 w-3.5" />
              )}
            </button>
            <span className="text-xs text-slate-400 truncate">
              {activeSessionId
                ? conversations?.find((c) => c.session_id === activeSessionId)?.title || "当前对话"
                : "选择或创建对话"}
            </span>
          </div>

          {/* Chat messages */}
          <div
            ref={scrollRef}
            className="flex-1 overflow-y-auto space-y-3 px-3 py-2"
          >
            {displayMessages.length === 0 && !isWorking && (
              <div className="flex flex-col items-center justify-center py-16 text-slate-400">
                <Bot className="mb-3 h-10 w-10" />
                <p className="text-sm">向 Agent 提问关于你的小说的任何问题</p>
                <p className="mt-1 text-xs text-slate-400">
                  例如：分析第3章的角色动机、检查前5章的伏笔一致性...
                </p>
              </div>
            )}

            {displayMessages.map((msg, idx) =>
              msg.role === "user" ? (
                <div key={idx} className="flex justify-end">
                  <div className="max-w-[80%] rounded-2xl rounded-br-md bg-accent px-4 py-2.5 text-sm text-white">
                    <p className="whitespace-pre-wrap">{msg.content}</p>
                  </div>
                </div>
              ) : (
                <div key={idx} className="flex justify-start">
                  <div className="max-w-[90%] space-y-2">
                    {msg.steps && msg.steps.length > 0 && (
                      <div className="space-y-1.5">
                        {msg.steps.map((step, si) => (
                          <ToolStepCard key={si} step={step} defaultOpen={si === msg.steps!.length - 1} />
                        ))}
                      </div>
                    )}
                    <div className="rounded-2xl rounded-bl-md border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm text-ink">
                      <p className="whitespace-pre-wrap">{msg.content}</p>
                      {msg.model && (
                        <p className="mt-1.5 text-[10px] text-slate-400">
                          model: {msg.model}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              )
            )}

            {/* Thinking indicator */}
            {isWorking && (
              <div className="flex justify-start">
                <div className="flex items-center gap-2 rounded-2xl rounded-bl-md border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm text-slate-500">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span>
                    Agent 思考中
                    {taskData?.progress != null &&
                      taskData.progress > 0 &&
                      ` (${Math.round(taskData.progress * 100)}%)`}
                    {taskData?.progress_msg && ` — ${taskData.progress_msg}`}
                    ...
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* Divider */}
          <div className="border-t border-slate-200" />

          {/* Input area */}
          <div className="space-y-2 px-3 pt-3 pb-1">
            <div className="flex items-end gap-2">
              <div className="flex-1 space-y-2">
                <textarea
                  className={inputCls + " min-h-[48px] max-h-[120px] resize-none"}
                  placeholder="输入消息..."
                  value={inputMessage}
                  onChange={(e) => setInputMessage(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      handleSend();
                    }
                  }}
                  rows={1}
                  disabled={isWorking}
                />
              </div>
              <button
                className={btnPrimary + " shrink-0 px-3"}
                onClick={handleSend}
                disabled={!inputMessage.trim() || isWorking}
                title="发送"
              >
                {isWorking ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </button>
            </div>

            {/* Context chapters input */}
            <div className="flex items-center gap-2">
              <label className="text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-400 whitespace-nowrap">
                参考章节
              </label>
              <input
                type="text"
                className={inputCls + " max-w-[220px] !py-1.5 text-xs"}
                placeholder="如 1,3,5 (可选)"
                value={contextChapters}
                onChange={(e) => setContextChapters(e.target.value)}
                disabled={isWorking}
              />
            </div>
          </div>
        </div>
      </div>
    </Panel>
  );
}

function renderChangeDetails(oldVal: any, newVal: any): React.ReactNode {
  const oldFlat = flattenDict(oldVal);
  const newFlat = flattenDict(newVal);
  const allKeys = new Set([...Object.keys(oldFlat), ...Object.keys(newFlat)]);
  const changes: React.ReactNode[] = [];

  Array.from(allKeys)
    .sort()
    .forEach((key) => {
      const ov = oldFlat[key] ?? "(无)";
      const nv = newFlat[key] ?? "(无)";
      if (String(ov) !== String(nv)) {
        changes.push(
          <p key={key} className="text-xs">
            <code className="rounded bg-slate-100 px-1">{key}</code>:{" "}
            <span className="text-rose-600 line-through">{String(ov).slice(0, 40)}</span>{" "}
            → <span className="text-emerald-700">{String(nv).slice(0, 40)}</span>
          </p>
        );
      }
    });

  return changes.length > 0 ? changes : <p className="text-xs text-slate-500">无可见变更</p>;
}

function flattenDict(d: any, prefix = ""): Record<string, any> {
  const items: Record<string, any> = {};
  if (!d || typeof d !== "object") return items;
  for (const [k, v] of Object.entries(d)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) {
      Object.assign(items, flattenDict(v, key));
    } else {
      items[key] = v;
    }
  }
  return items;
}

// ─── Settings Editor Section ──────────────────────────────────────────
function SettingsEditorSection({ novelId }: { novelId: string }) {
  const { data: settings, isLoading, isError, error, refetch } = useNovelSettings(novelId);
  const saveMut = useSaveNovelSettings(novelId);
  const impactMut = useAnalyzeSettingImpact(novelId);
  const rewriteMut = useRewriteAffected(novelId);

  const [settingsTab, setSettingsTab] = useState<"world" | "characters" | "outline">("world");
  const [impactResult, setImpactResult] = useState<any>(null);

  // World setting state
  const [era, setEra] = useState("");
  const [location, setLocation] = useState("");
  const [powerName, setPowerName] = useState("");
  const [powerLevels, setPowerLevels] = useState<Array<{ name: string; description: string; abilities: string }>>([]);
  const [rules, setRules] = useState("");
  const [terms, setTerms] = useState<Array<{ term: string; desc: string }>>([]);

  // Character state
  const [selectedCharIdx, setSelectedCharIdx] = useState(0);
  const [characters, setCharacters] = useState<any[]>([]);

  // Outline state
  const [outlineChapters, setOutlineChapters] = useState<any[]>([]);
  const [selectedChIdx, setSelectedChIdx] = useState(0);
  const [mainStoryline, setMainStoryline] = useState<any>({});

  // Load settings into state
  useEffect(() => {
    if (settings) {
      // World
      const ws = settings.world_setting ?? {};
      setEra(ws.era ?? "");
      setLocation(ws.location ?? "");
      const ps = ws.power_system ?? {};
      setPowerName(ps.name ?? "");
      setPowerLevels(
        (ps.levels ?? []).map((l: any) => ({
          name: l.name ?? "",
          description: l.description ?? "",
          abilities: (l.typical_abilities ?? []).join(", "),
        }))
      );
      setRules((ws.rules ?? []).join("\n"));
      setTerms(
        Object.entries(ws.terms ?? {}).map(([term, desc]) => ({
          term,
          desc: String(desc),
        }))
      );

      // Characters
      setCharacters(settings.characters ?? []);
      setSelectedCharIdx(0);

      // Outline
      const outline = settings.outline ?? {};
      setOutlineChapters(outline.chapters ?? []);
      setMainStoryline(outline.main_storyline ?? {});
      setSelectedChIdx(0);
    }
  }, [settings]);

  const handleSave = () => {
    // Build settings object from form state
    const newSettings: any = {
      world_setting: {
        era,
        location,
        power_system: {
          name: powerName,
          levels: powerLevels
            .filter((l) => l.name.trim())
            .map((l, i) => ({
              rank: i + 1,
              name: l.name,
              description: l.description || l.name,
              typical_abilities: l.abilities
                .split(",")
                .map((a) => a.trim())
                .filter(Boolean),
            })),
        },
        rules: rules
          .split("\n")
          .map((r) => r.trim())
          .filter(Boolean),
        terms: Object.fromEntries(
          terms.filter((t) => t.term.trim()).map((t) => [t.term.trim(), t.desc.trim()])
        ),
      },
      characters,
      outline: {
        main_storyline: mainStoryline,
        chapters: outlineChapters,
      },
    };
    saveMut.mutate(newSettings);
  };

  const handleAnalyzeImpact = () => {
    impactMut.mutate(
      {
        setting_type: "world_setting",
        new_value: {
          era,
          location,
          power_system: {
            name: powerName,
            levels: powerLevels
              .filter((l) => l.name.trim())
              .map((l, i) => ({
                rank: i + 1,
                name: l.name,
                description: l.description || l.name,
                typical_abilities: l.abilities
                  .split(",")
                  .map((a) => a.trim())
                  .filter(Boolean),
              })),
          },
          rules: rules
            .split("\n")
            .map((r) => r.trim())
            .filter(Boolean),
          terms: Object.fromEntries(
            terms.filter((t) => t.term.trim()).map((t) => [t.term.trim(), t.desc.trim()])
          ),
        },
      },
      {
        onSuccess: (data) => setImpactResult(data),
      }
    );
  };

  const handleRewriteAffected = () => {
    if (impactResult) {
      rewriteMut.mutate(impactResult);
    }
  };

  const currentChar = characters[selectedCharIdx] ?? {};

  const updateChar = (field: string, value: any) => {
    setCharacters((prev) => {
      const copy = [...prev];
      copy[selectedCharIdx] = { ...copy[selectedCharIdx], [field]: value };
      return copy;
    });
  };

  const updateCharNested = (parent: string, field: string, value: any) => {
    setCharacters((prev) => {
      const copy = [...prev];
      const existing = copy[selectedCharIdx]?.[parent] ?? {};
      copy[selectedCharIdx] = {
        ...copy[selectedCharIdx],
        [parent]: { ...existing, [field]: value },
      };
      return copy;
    });
  };

  const addCharacter = () => {
    const newChar = {
      character_id: `new_${Date.now()}`,
      name: `新角色${characters.length + 1}`,
      gender: "男",
      age: 20,
      occupation: "待设定",
      status: "active",
      alias: [],
      appearance: { height: "", build: "", hair: "", eyes: "", clothing_style: "", distinctive_features: [] },
      personality: { traits: [], core_belief: "", motivation: "", flaw: "", speech_style: "", catchphrases: [] },
      character_arc: { initial_state: "", final_state: "", turning_points: [] },
    };
    setCharacters([...characters, newChar]);
    setSelectedCharIdx(characters.length);
  };

  const deleteCharacter = () => {
    if (characters.length <= 1) return;
    setCharacters((prev) => prev.filter((_, i) => i !== selectedCharIdx));
    setSelectedCharIdx(Math.max(0, selectedCharIdx - 1));
  };

  if (isLoading) {
    return (
      <Panel title="设定编辑">
        <div className="flex items-center gap-2 py-8 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          加载设定...
        </div>
      </Panel>
    );
  }

  if (isError) {
    return (
      <Panel title="设定编辑">
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700">
          加载失败：{(error as Error)?.message}
        </div>
      </Panel>
    );
  }

  return (
    <div className="space-y-5">
      {/* Settings sub-tabs */}
      <div className="flex gap-2">
        {[
          { key: "world" as const, label: "世界观", icon: Globe },
          { key: "characters" as const, label: "角色", icon: Users },
          { key: "outline" as const, label: "大纲", icon: BookOpenText },
        ].map((tab) => (
          <button
            key={tab.key}
            onClick={() => setSettingsTab(tab.key)}
            className={settingsTab === tab.key ? tabActive : tabInactive}
          >
            <tab.icon className="mr-1 inline h-3.5 w-3.5" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* World setting editor */}
      {settingsTab === "world" && (
        <Panel title="世界观编辑">
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>时代</label>
                <input className={inputCls} value={era} onChange={(e) => setEra(e.target.value)} placeholder="如: 仙侠世界" />
              </div>
              <div>
                <label className={labelCls}>地点</label>
                <input className={inputCls} value={location} onChange={(e) => setLocation(e.target.value)} placeholder="如: 天元大陆" />
              </div>
            </div>

            <div>
              <label className={labelCls}>力量体系名称</label>
              <input className={inputCls} value={powerName} onChange={(e) => setPowerName(e.target.value)} placeholder="如: 灵气修炼" />
            </div>

            {/* Power levels table */}
            <div>
              <label className={labelCls}>等级体系</label>
              <div className="space-y-2">
                {powerLevels.map((level, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <span className="min-w-[2rem] text-center text-xs font-mono text-slate-400">{i + 1}</span>
                    <input
                      className={inputCls + " max-w-[120px]"}
                      value={level.name}
                      onChange={(e) => {
                        const copy = [...powerLevels];
                        copy[i] = { ...copy[i], name: e.target.value };
                        setPowerLevels(copy);
                      }}
                      placeholder="等级名"
                    />
                    <input
                      className={inputCls + " max-w-[200px]"}
                      value={level.description}
                      onChange={(e) => {
                        const copy = [...powerLevels];
                        copy[i] = { ...copy[i], description: e.target.value };
                        setPowerLevels(copy);
                      }}
                      placeholder="描述"
                    />
                    <input
                      className={inputCls}
                      value={level.abilities}
                      onChange={(e) => {
                        const copy = [...powerLevels];
                        copy[i] = { ...copy[i], abilities: e.target.value };
                        setPowerLevels(copy);
                      }}
                      placeholder="能力（逗号分隔）"
                    />
                    <button
                      className="text-slate-400 hover:text-rose-500"
                      onClick={() => setPowerLevels(powerLevels.filter((_, j) => j !== i))}
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                ))}
                <button
                  className="text-xs font-semibold text-accent hover:underline"
                  onClick={() => setPowerLevels([...powerLevels, { name: "", description: "", abilities: "" }])}
                >
                  <Plus className="mr-1 inline h-3 w-3" />
                  添加等级
                </button>
              </div>
            </div>

            <div>
              <label className={labelCls}>世界规则（每行一条）</label>
              <textarea
                className={inputCls + " min-h-[80px] resize-y"}
                value={rules}
                onChange={(e) => setRules(e.target.value)}
                placeholder="每行一条世界规则..."
                rows={3}
              />
            </div>

            {/* Terms dictionary */}
            <div>
              <label className={labelCls}>专有名词</label>
              <div className="space-y-2">
                {terms.map((t, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <input
                      className={inputCls + " max-w-[150px]"}
                      value={t.term}
                      onChange={(e) => {
                        const copy = [...terms];
                        copy[i] = { ...copy[i], term: e.target.value };
                        setTerms(copy);
                      }}
                      placeholder="名词"
                    />
                    <input
                      className={inputCls}
                      value={t.desc}
                      onChange={(e) => {
                        const copy = [...terms];
                        copy[i] = { ...copy[i], desc: e.target.value };
                        setTerms(copy);
                      }}
                      placeholder="释义"
                    />
                    <button
                      className="text-slate-400 hover:text-rose-500"
                      onClick={() => setTerms(terms.filter((_, j) => j !== i))}
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                ))}
                <button
                  className="text-xs font-semibold text-accent hover:underline"
                  onClick={() => setTerms([...terms, { term: "", desc: "" }])}
                >
                  <Plus className="mr-1 inline h-3 w-3" />
                  添加名词
                </button>
              </div>
            </div>

            {/* Action buttons */}
            <div className="flex flex-wrap gap-3 border-t border-slate-100 pt-4">
              <button className={btnPrimary} onClick={handleSave} disabled={saveMut.isPending}>
                {saveMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                保存设定
              </button>
              <button className={btnSecondary} onClick={handleAnalyzeImpact} disabled={impactMut.isPending}>
                {impactMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <AlertTriangle className="h-4 w-4" />}
                评估影响
              </button>
              {impactResult?.affected_chapters?.length > 0 && (
                <button className={btnSecondary} onClick={handleRewriteAffected} disabled={rewriteMut.isPending}>
                  {rewriteMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                  重写受影响章节 ({impactResult.affected_chapters.length})
                </button>
              )}
            </div>

            {saveMut.isSuccess && (
              <p className="text-xs text-emerald-600">设定已保存（旧版本已备份）</p>
            )}
            {saveMut.isError && (
              <p className="text-xs text-rose-600">保存失败：{(saveMut.error as Error)?.message}</p>
            )}

            {/* Impact analysis result */}
            {impactResult && (
              <ImpactReport impact={impactResult} />
            )}

            {rewriteMut.isSuccess && (
              <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-700">
                已重写 {(rewriteMut.data as any)?.rewritten?.length ?? 0} 章
                {(rewriteMut.data as any)?.rewritten?.map((r: any) => (
                  <span key={r.chapter_number} className="ml-2">
                    第{r.chapter_number}章: {r.old_chars}→{r.new_chars}字
                  </span>
                ))}
              </div>
            )}
            {rewriteMut.isError && (
              <p className="text-xs text-rose-600">重写失败：{(rewriteMut.error as Error)?.message}</p>
            )}
          </div>
        </Panel>
      )}

      {/* Character editor */}
      {settingsTab === "characters" && (
        <Panel title="角色编辑">
          <div className="space-y-4">
            {/* Character selector */}
            <div className="flex items-center gap-3">
              <select
                className={inputCls + " max-w-xs"}
                value={selectedCharIdx}
                onChange={(e) => setSelectedCharIdx(Number(e.target.value))}
              >
                {characters.map((c, i) => (
                  <option key={i} value={i}>
                    {c.name || "未命名"} ({c.gender ?? "?"}, {c.occupation ?? "?"})
                  </option>
                ))}
              </select>
              <button className={btnSecondary} onClick={addCharacter}>
                <Plus className="h-3.5 w-3.5" />
                新增
              </button>
              <button
                className={btnDanger}
                onClick={deleteCharacter}
                disabled={characters.length <= 1}
              >
                <Trash2 className="h-3.5 w-3.5" />
                删除
              </button>
            </div>

            {characters.length > 0 && (
              <div className="space-y-4 rounded-[20px] border border-slate-100 p-4">
                {/* Basic info */}
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                  <div>
                    <label className={labelCls}>姓名</label>
                    <input className={inputCls} value={currentChar.name ?? ""} onChange={(e) => updateChar("name", e.target.value)} />
                  </div>
                  <div>
                    <label className={labelCls}>性别</label>
                    <select className={inputCls} value={currentChar.gender ?? "男"} onChange={(e) => updateChar("gender", e.target.value)}>
                      <option value="男">男</option>
                      <option value="女">女</option>
                      <option value="其他">其他</option>
                    </select>
                  </div>
                  <div>
                    <label className={labelCls}>年龄</label>
                    <input type="number" className={inputCls} value={currentChar.age ?? 18} onChange={(e) => updateChar("age", Number(e.target.value))} />
                  </div>
                  <div>
                    <label className={labelCls}>职业</label>
                    <input className={inputCls} value={currentChar.occupation ?? ""} onChange={(e) => updateChar("occupation", e.target.value)} />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className={labelCls}>状态</label>
                    <select className={inputCls} value={currentChar.status ?? "active"} onChange={(e) => updateChar("status", e.target.value)}>
                      <option value="active">活跃</option>
                      <option value="inactive">不活跃</option>
                      <option value="deceased">死亡</option>
                    </select>
                  </div>
                  <div>
                    <label className={labelCls}>别名（逗号分隔）</label>
                    <input
                      className={inputCls}
                      value={(currentChar.alias ?? []).join(", ")}
                      onChange={(e) => updateChar("alias", e.target.value.split(",").map((a: string) => a.trim()).filter(Boolean))}
                    />
                  </div>
                </div>

                {/* Appearance */}
                <div>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-[0.15em] text-accent">外貌</p>
                  <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
                    {[
                      { key: "height", label: "身高" },
                      { key: "build", label: "体型" },
                      { key: "hair", label: "发型" },
                      { key: "eyes", label: "眼睛" },
                      { key: "clothing_style", label: "服装风格" },
                    ].map(({ key, label }) => (
                      <div key={key}>
                        <label className={labelCls}>{label}</label>
                        <input
                          className={inputCls}
                          value={currentChar.appearance?.[key] ?? ""}
                          onChange={(e) => updateCharNested("appearance", key, e.target.value)}
                        />
                      </div>
                    ))}
                    <div>
                      <label className={labelCls}>特征（逗号分隔）</label>
                      <input
                        className={inputCls}
                        value={(currentChar.appearance?.distinctive_features ?? []).join(", ")}
                        onChange={(e) =>
                          updateCharNested(
                            "appearance",
                            "distinctive_features",
                            e.target.value.split(",").map((f: string) => f.trim()).filter(Boolean)
                          )
                        }
                      />
                    </div>
                  </div>
                </div>

                {/* Personality */}
                <div>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-[0.15em] text-accent">性格</p>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className={labelCls}>性格特质（逗号分隔）</label>
                      <input
                        className={inputCls}
                        value={(currentChar.personality?.traits ?? []).join(", ")}
                        onChange={(e) =>
                          updateCharNested("personality", "traits", e.target.value.split(",").map((t: string) => t.trim()).filter(Boolean))
                        }
                      />
                    </div>
                    <div>
                      <label className={labelCls}>说话风格</label>
                      <input
                        className={inputCls}
                        value={currentChar.personality?.speech_style ?? ""}
                        onChange={(e) => updateCharNested("personality", "speech_style", e.target.value)}
                      />
                    </div>
                    <div>
                      <label className={labelCls}>核心信念</label>
                      <input
                        className={inputCls}
                        value={currentChar.personality?.core_belief ?? ""}
                        onChange={(e) => updateCharNested("personality", "core_belief", e.target.value)}
                      />
                    </div>
                    <div>
                      <label className={labelCls}>动机</label>
                      <input
                        className={inputCls}
                        value={currentChar.personality?.motivation ?? ""}
                        onChange={(e) => updateCharNested("personality", "motivation", e.target.value)}
                      />
                    </div>
                    <div>
                      <label className={labelCls}>缺点</label>
                      <input
                        className={inputCls}
                        value={currentChar.personality?.flaw ?? ""}
                        onChange={(e) => updateCharNested("personality", "flaw", e.target.value)}
                      />
                    </div>
                    <div>
                      <label className={labelCls}>口头禅（逗号分隔）</label>
                      <input
                        className={inputCls}
                        value={(currentChar.personality?.catchphrases ?? []).join(", ")}
                        onChange={(e) =>
                          updateCharNested("personality", "catchphrases", e.target.value.split(",").map((p: string) => p.trim()).filter(Boolean))
                        }
                      />
                    </div>
                  </div>
                </div>

                {/* Character Arc */}
                <div>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-[0.15em] text-accent">角色弧线</p>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className={labelCls}>初始状态</label>
                      <input
                        className={inputCls}
                        value={currentChar.character_arc?.initial_state ?? ""}
                        onChange={(e) => updateCharNested("character_arc", "initial_state", e.target.value)}
                      />
                    </div>
                    <div>
                      <label className={labelCls}>最终状态</label>
                      <input
                        className={inputCls}
                        value={currentChar.character_arc?.final_state ?? ""}
                        onChange={(e) => updateCharNested("character_arc", "final_state", e.target.value)}
                      />
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Save button */}
            <button className={btnPrimary} onClick={handleSave} disabled={saveMut.isPending}>
              {saveMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              保存全部设定
            </button>
            {saveMut.isSuccess && <p className="text-xs text-emerald-600">设定已保存</p>}
            {saveMut.isError && <p className="text-xs text-rose-600">保存失败：{(saveMut.error as Error)?.message}</p>}
          </div>
        </Panel>
      )}

      {/* Outline editor */}
      {settingsTab === "outline" && (
        <Panel title="大纲编辑">
          <div className="space-y-4">
            {/* Main storyline */}
            <div className="rounded-[20px] border border-accent/20 bg-accent/5 p-4">
              <p className="mb-3 text-sm font-semibold text-accent">主线设定</p>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={labelCls}>主角目标</label>
                  <input
                    className={inputCls}
                    value={mainStoryline.protagonist_goal ?? ""}
                    onChange={(e) => setMainStoryline({ ...mainStoryline, protagonist_goal: e.target.value })}
                  />
                </div>
                <div>
                  <label className={labelCls}>核心冲突</label>
                  <input
                    className={inputCls}
                    value={mainStoryline.core_conflict ?? ""}
                    onChange={(e) => setMainStoryline({ ...mainStoryline, core_conflict: e.target.value })}
                  />
                </div>
                <div>
                  <label className={labelCls}>赌注</label>
                  <input
                    className={inputCls}
                    value={mainStoryline.stakes ?? ""}
                    onChange={(e) => setMainStoryline({ ...mainStoryline, stakes: e.target.value })}
                  />
                </div>
                <div>
                  <label className={labelCls}>角色弧线</label>
                  <input
                    className={inputCls}
                    value={mainStoryline.character_arc ?? ""}
                    onChange={(e) => setMainStoryline({ ...mainStoryline, character_arc: e.target.value })}
                  />
                </div>
              </div>
            </div>

            {/* Chapter selector */}
            {outlineChapters.length > 0 && (
              <>
                <div className="flex items-center gap-3">
                  <label className={labelCls + " mb-0"}>章节</label>
                  <select
                    className={inputCls + " max-w-xs"}
                    value={selectedChIdx}
                    onChange={(e) => setSelectedChIdx(Number(e.target.value))}
                  >
                    {outlineChapters.map((ch: any, i: number) => (
                      <option key={i} value={i}>
                        第{ch.chapter_number ?? i + 1}章: {ch.title || "无标题"}
                      </option>
                    ))}
                  </select>
                </div>

                {outlineChapters[selectedChIdx] && (
                  <div className="space-y-3 rounded-[20px] border border-slate-100 p-4">
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className={labelCls}>章节标题</label>
                        <input
                          className={inputCls}
                          value={outlineChapters[selectedChIdx]?.title ?? ""}
                          onChange={(e) => {
                            const copy = [...outlineChapters];
                            copy[selectedChIdx] = { ...copy[selectedChIdx], title: e.target.value };
                            setOutlineChapters(copy);
                          }}
                        />
                      </div>
                      <div>
                        <label className={labelCls}>基调</label>
                        <select
                          className={inputCls}
                          value={outlineChapters[selectedChIdx]?.mood ?? "蓄力"}
                          onChange={(e) => {
                            const copy = [...outlineChapters];
                            copy[selectedChIdx] = { ...copy[selectedChIdx], mood: e.target.value };
                            setOutlineChapters(copy);
                          }}
                        >
                          {["蓄力", "爆发", "过渡", "高潮", "低谷", "转折", "平稳"].map((m) => (
                            <option key={m} value={m}>{m}</option>
                          ))}
                        </select>
                      </div>
                    </div>
                    <div>
                      <label className={labelCls}>章节目标</label>
                      <input
                        className={inputCls}
                        value={outlineChapters[selectedChIdx]?.goal ?? ""}
                        onChange={(e) => {
                          const copy = [...outlineChapters];
                          copy[selectedChIdx] = { ...copy[selectedChIdx], goal: e.target.value };
                          setOutlineChapters(copy);
                        }}
                      />
                    </div>
                    <div>
                      <label className={labelCls}>关键事件（每行一条）</label>
                      <textarea
                        className={inputCls + " min-h-[80px] resize-y"}
                        value={(outlineChapters[selectedChIdx]?.key_events ?? []).join("\n")}
                        onChange={(e) => {
                          const copy = [...outlineChapters];
                          copy[selectedChIdx] = {
                            ...copy[selectedChIdx],
                            key_events: e.target.value.split("\n").filter((l: string) => l.trim()),
                          };
                          setOutlineChapters(copy);
                        }}
                        rows={3}
                      />
                    </div>
                    <div>
                      <label className={labelCls}>章节摘要</label>
                      <textarea
                        className={inputCls + " min-h-[60px] resize-y"}
                        value={outlineChapters[selectedChIdx]?.chapter_summary ?? ""}
                        onChange={(e) => {
                          const copy = [...outlineChapters];
                          copy[selectedChIdx] = { ...copy[selectedChIdx], chapter_summary: e.target.value };
                          setOutlineChapters(copy);
                        }}
                        rows={2}
                      />
                    </div>
                  </div>
                )}
              </>
            )}

            {/* Save button */}
            <button className={btnPrimary} onClick={handleSave} disabled={saveMut.isPending}>
              {saveMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              保存全部设定
            </button>
            {saveMut.isSuccess && <p className="text-xs text-emerald-600">设定已保存</p>}
            {saveMut.isError && <p className="text-xs text-rose-600">保存失败：{(saveMut.error as Error)?.message}</p>}
          </div>
        </Panel>
      )}
    </div>
  );
}

// ─── Impact Report ────────────────────────────────────────────────────
function ImpactReport({ impact }: { impact: any }) {
  if (!impact) return null;

  const severityColors: Record<string, string> = {
    high: "bg-rose-100 text-rose-700 border-rose-200",
    medium: "bg-amber-100 text-amber-700 border-amber-200",
    low: "bg-emerald-100 text-emerald-700 border-emerald-200",
  };

  return (
    <div className={`rounded-[20px] border p-4 ${severityColors[impact.severity] ?? "bg-slate-100 text-slate-700 border-slate-200"}`}>
      <p className="mb-2 text-sm font-semibold">影响评估报告</p>
      <div className="space-y-2 text-sm">
        <p>
          <span className="font-semibold">严重度: </span>
          {impact.severity ?? "未知"}
        </p>
        {impact.summary && (
          <p>
            <span className="font-semibold">总结: </span>
            {impact.summary}
          </p>
        )}
        {impact.affected_chapters?.length > 0 ? (
          <p>
            <span className="font-semibold">受影响章节: </span>
            第{impact.affected_chapters.join("、")}章
          </p>
        ) : (
          <p>
            <span className="font-semibold">受影响章节: </span>无
          </p>
        )}
        {impact.conflicts?.length > 0 && (
          <div>
            <span className="font-semibold">具体矛盾:</span>
            <ul className="ml-4 mt-1 list-disc space-y-1">
              {impact.conflicts.map((c: any, i: number) => (
                <li key={i} className="text-xs">
                  <span className="font-medium">第{c.chapter_number}章</span>: {c.reason}
                  {c.conflict_text && (
                    <span className="ml-1 opacity-70">({c.conflict_text.slice(0, 80)})</span>
                  )}
                  {c.suggested_fix && (
                    <span className="ml-1 italic">建议: {c.suggested_fix.slice(0, 80)}</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Narrative Control Section ─────────────────────────────────────────
const DEBT_TYPE_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  must_pay_next: { bg: "bg-rose-100", text: "text-rose-700", label: "下章必还" },
  pay_within_3: { bg: "bg-amber-100", text: "text-amber-700", label: "3章内还" },
  long_tail: { bg: "bg-sky-100", text: "text-sky-700", label: "长线伏笔" },
};

const DEBT_STATUS_STYLES: Record<string, { bg: string; border: string }> = {
  pending: { bg: "bg-amber-50", border: "border-amber-200" },
  overdue: { bg: "bg-rose-50", border: "border-rose-200" },
  fulfilled: { bg: "bg-emerald-50", border: "border-emerald-200" },
};

const ARC_PHASE_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  setup: { bg: "bg-sky-100", text: "text-sky-700", label: "铺垫" },
  escalation: { bg: "bg-amber-100", text: "text-amber-700", label: "升级" },
  climax: { bg: "bg-rose-100", text: "text-rose-700", label: "高潮" },
  resolution: { bg: "bg-emerald-100", text: "text-emerald-700", label: "收束" },
};

// ─── Knowledge Graph SVG Visualization ──────────────────────────────────
function KnowledgeGraphVisualization({
  nodes,
  edges,
}: {
  nodes: any[];
  edges: any[];
}) {
  const [positions, setPositions] = useState<
    Record<string, { x: number; y: number }>
  >({});

  const nodeList = useMemo(() => {
    if (nodes.length) return nodes;
    const names = new Set<string>();
    for (const e of edges) {
      const s = e.source ?? e.from ?? "";
      const t = e.target ?? e.to ?? "";
      if (s) names.add(s);
      if (t) names.add(t);
    }
    return [...names].map((n) => ({ id: n, name: n }));
  }, [nodes, edges]);

  // Initialize positions in a circle then run force simulation
  useEffect(() => {
    if (nodeList.length === 0) return;

    const cx = 300,
      cy = 200,
      radius = Math.min(150, 30 + nodeList.length * 10);
    const pos: Record<string, { x: number; y: number }> = {};

    nodeList.forEach((node: any, i: number) => {
      const angle = (2 * Math.PI * i) / nodeList.length;
      const name = node.name ?? node.id ?? String(node);
      pos[name] = {
        x: cx + radius * Math.cos(angle),
        y: cy + radius * Math.sin(angle),
      };
    });

    // Run 50 iterations of simple force layout
    let current = { ...pos };
    const nodeNames = Object.keys(current);

    for (let iter = 0; iter < 50; iter++) {
      const forces: Record<string, { fx: number; fy: number }> = {};
      nodeNames.forEach((n) => (forces[n] = { fx: 0, fy: 0 }));

      // Repulsion between all nodes
      for (let i = 0; i < nodeNames.length; i++) {
        for (let j = i + 1; j < nodeNames.length; j++) {
          const a = nodeNames[i],
            b = nodeNames[j];
          const dx = current[a].x - current[b].x;
          const dy = current[a].y - current[b].y;
          const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
          const force = 5000 / (dist * dist);
          forces[a].fx += (dx / dist) * force;
          forces[a].fy += (dy / dist) * force;
          forces[b].fx -= (dx / dist) * force;
          forces[b].fy -= (dy / dist) * force;
        }
      }

      // Attraction along edges
      for (const edge of edges) {
        const src = edge.source ?? edge.from ?? "";
        const tgt = edge.target ?? edge.to ?? "";
        if (!current[src] || !current[tgt]) continue;
        const dx = current[tgt].x - current[src].x;
        const dy = current[tgt].y - current[src].y;
        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
        const force = dist * 0.01;
        if (forces[src]) {
          forces[src].fx += (dx / dist) * force;
          forces[src].fy += (dy / dist) * force;
        }
        if (forces[tgt]) {
          forces[tgt].fx -= (dx / dist) * force;
          forces[tgt].fy -= (dy / dist) * force;
        }
      }

      // Center gravity
      nodeNames.forEach((n) => {
        forces[n].fx += (300 - current[n].x) * 0.01;
        forces[n].fy += (200 - current[n].y) * 0.01;
      });

      // Apply forces
      const next: Record<string, { x: number; y: number }> = {};
      nodeNames.forEach((n) => {
        next[n] = {
          x: Math.max(40, Math.min(560, current[n].x + forces[n].fx * 0.3)),
          y: Math.max(40, Math.min(360, current[n].y + forces[n].fy * 0.3)),
        };
      });
      current = next;
    }

    setPositions(current);
  }, [nodeList, edges]);

  const roleColors: Record<string, string> = {
    protagonist: "#6366f1",
    antagonist: "#ef4444",
    supporting: "#0ea5e9",
    mentor: "#f59e0b",
  };

  const edgeElements = edges.map((edge: any, i: number) => {
    const src = edge.source ?? edge.from ?? "";
    const tgt = edge.target ?? edge.to ?? "";
    const rel = edge.relation ?? edge.label ?? edge.type ?? "关联";
    const p1 = positions[src];
    const p2 = positions[tgt];
    if (!p1 || !p2) return null;
    const mx = (p1.x + p2.x) / 2;
    const my = (p1.y + p2.y) / 2;
    return (
      <g key={`edge-${i}`}>
        <line
          x1={p1.x}
          y1={p1.y}
          x2={p2.x}
          y2={p2.y}
          stroke="#cbd5e1"
          strokeWidth={1.5}
        />
        <text
          x={mx}
          y={my - 4}
          textAnchor="middle"
          className="text-[9px]"
          fill="#94a3b8"
        >
          {rel}
        </text>
      </g>
    );
  });

  const nodeElements = nodeList.map((node: any, i: number) => {
    const name = node.name ?? node.id ?? String(node);
    const role = node.role ?? "";
    const pos = positions[name];
    if (!pos) return null;
    const color = roleColors[role] ?? "#64748b";
    return (
      <g key={`node-${i}`}>
        <circle
          cx={pos.x}
          cy={pos.y}
          r={20}
          fill={color}
          opacity={0.15}
          stroke={color}
          strokeWidth={2}
        />
        <text
          x={pos.x}
          y={pos.y + 4}
          textAnchor="middle"
          className="text-xs font-semibold"
          fill={color}
        >
          {name}
        </text>
      </g>
    );
  });

  return (
    <div>
      <svg
        viewBox="0 0 600 400"
        className="w-full rounded-xl border border-slate-200 bg-white"
      >
        {edgeElements}
        {nodeElements}
      </svg>
      {/* Role legend */}
      <div className="mt-2 flex gap-4 justify-center">
        {Object.entries({
          protagonist: "主角",
          antagonist: "反派",
          supporting: "配角",
          mentor: "导师",
        }).map(([k, v]) => (
          <div key={k} className="flex items-center gap-1 text-xs text-slate-500">
            <div
              className="h-2.5 w-2.5 rounded-full border-2"
              style={{ borderColor: roleColors[k], backgroundColor: roleColors[k] + "26" }}
            />
            {v}
          </div>
        ))}
      </div>
    </div>
  );
}

function NarrativeControlSection({ novelId }: { novelId: string }) {
  const [debtFilter, setDebtFilter] = useState("all");
  const [graphOpen, setGraphOpen] = useState(false);
  const [selectedBriefChapter, setSelectedBriefChapter] = useState<number | null>(null);
  const [rebuildTaskId, setRebuildTaskId] = useState<string | null>(null);

  const { data: overview, isLoading: overviewLoading } = useNarrativeOverview(novelId);
  const { data: debts, isLoading: debtsLoading } = useNarrativeDebts(novelId, debtFilter);
  const { data: arcs, isLoading: arcsLoading } = useStoryArcs(novelId);
  const { data: graph, isLoading: graphLoading } = useKnowledgeGraph(novelId);
  const { data: volumes, isLoading: volumesLoading } = useVolumesSummary(novelId);
  const { data: brief } = useChapterBrief(novelId, selectedBriefChapter);
  const fulfillDebt = useFulfillDebt(novelId);
  const rebuildMut = useRebuildNarrative(novelId);
  const { data: rebuildTask } = useTask(rebuildTaskId);

  // Track rebuild task completion
  useEffect(() => {
    if (!rebuildTask || !rebuildTaskId) return;
    if (rebuildTask.status === "completed" || rebuildTask.status === "failed") {
      // Keep the task ID for a short while so user sees the result
      const timer = setTimeout(() => setRebuildTaskId(null), 8000);
      return () => clearTimeout(timer);
    }
  }, [rebuildTask, rebuildTaskId]);

  const handleRebuild = async () => {
    try {
      const result = await rebuildMut.mutateAsync();
      setRebuildTaskId(result.task_id);
    } catch {
      // error handled by mutation state
    }
  };

  const debtFilterTabs = [
    { key: "all", label: "全部" },
    { key: "pending", label: "待处理" },
    { key: "overdue", label: "逾期" },
    { key: "fulfilled", label: "已兑现" },
  ];

  return (
    <div className="space-y-5">
      {/* A. Overview Panel */}
      <Panel title="叙事概览">
        {overviewLoading ? (
          <div className="flex items-center justify-center py-8 text-slate-400">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            加载中...
          </div>
        ) : overview ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-center">
              <p className="text-2xl font-bold text-amber-700">{overview.pending_debts ?? 0}</p>
              <p className="mt-1 text-xs font-semibold text-amber-600">待处理债务</p>
            </div>
            <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-center">
              <p className="text-2xl font-bold text-rose-700">{overview.overdue_debts ?? 0}</p>
              <p className="mt-1 text-xs font-semibold text-rose-600">逾期债务</p>
            </div>
            <div className="rounded-xl border border-sky-200 bg-sky-50 p-3 text-center">
              <p className="text-2xl font-bold text-sky-700">{overview.active_arcs ?? 0}</p>
              <p className="mt-1 text-xs font-semibold text-sky-600">活跃弧线</p>
            </div>
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-center">
              <p className="text-2xl font-bold text-emerald-700">
                {overview.arc_completion != null ? `${Math.round(overview.arc_completion)}%` : "-"}
              </p>
              <p className="mt-1 text-xs font-semibold text-emerald-600">弧线完成度</p>
            </div>
          </div>
        ) : (
          <p className="py-4 text-center text-sm text-slate-400">暂无叙事数据</p>
        )}

        {/* Rebuild narrative button */}
        <div className="mt-4 flex items-center gap-3">
          <button
            onClick={handleRebuild}
            disabled={rebuildMut.isPending || (!!rebuildTaskId && rebuildTask?.status !== "completed" && rebuildTask?.status !== "failed")}
            className="inline-flex items-center gap-2 rounded-xl bg-purple-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-purple-700 disabled:opacity-50"
          >
            {rebuildMut.isPending || (rebuildTaskId && rebuildTask?.status !== "completed" && rebuildTask?.status !== "failed") ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            从已有章节重建叙事数据
          </button>
          {rebuildTaskId && rebuildTask && (
            <span className={`text-xs font-medium ${
              rebuildTask.status === "completed" ? "text-emerald-600" :
              rebuildTask.status === "failed" ? "text-rose-600" :
              "text-purple-600"
            }`}>
              {rebuildTask.status === "completed"
                ? (() => { try { const r = JSON.parse(typeof rebuildTask.result === 'string' ? rebuildTask.result : '{}'); return `重建完成！${r.chapters_scanned ?? 0}章扫描, ${r.debts_extracted ?? 0}个债务, ${r.arcs_detected ?? 0}个弧线`; } catch { return "重建完成！"; } })()
                : rebuildTask.status === "failed"
                ? `重建失败: ${rebuildTask.error || "未知错误"}`
                : `${rebuildTask.progress_msg || "正在分析..."} (${Math.round((rebuildTask.progress ?? 0) * 100)}%)`}
            </span>
          )}
        </div>
      </Panel>

      {/* A2. Volume Settlement Panel */}
      <Panel title="分卷收束">
        {volumesLoading ? (
          <div className="flex items-center justify-center py-6 text-slate-400">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 加载中...
          </div>
        ) : !volumes || volumes.length === 0 ? (
          <p className="py-4 text-center text-sm text-slate-400">暂无分卷数据</p>
        ) : (
          <div className="space-y-3">
            {volumes.map((vol: any) => {
              const rate = Math.round((vol.settlement_rate ?? 0) * 100);
              const isComplete = rate >= 80;
              return (
                <div key={vol.volume_number} className="rounded-xl border border-slate-200 p-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="text-sm font-semibold text-ink">
                        第{vol.volume_number}卷: {vol.title || '未命名'}
                      </span>
                      <span className="ml-2 text-xs text-slate-400">
                        第{vol.start_chapter}-{vol.end_chapter}章
                      </span>
                    </div>
                    <span className={`text-xs font-semibold ${isComplete ? 'text-emerald-600' : 'text-amber-600'}`}>
                      {rate}% 收束
                    </span>
                  </div>
                  {/* Settlement progress bar */}
                  <div className="mt-2 h-2 rounded-full bg-slate-100">
                    <div
                      className={`h-2 rounded-full transition-all ${isComplete ? 'bg-emerald-500' : 'bg-amber-400'}`}
                      style={{ width: `${rate}%` }}
                    />
                  </div>
                  <div className="mt-1 flex justify-between text-[10px] text-slate-400">
                    <span>{vol.debts_fulfilled ?? 0} 已兑现</span>
                    <span>{vol.debts_pending ?? 0} 待处理</span>
                    <span>共 {vol.debts_total ?? 0} 债务</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Panel>

      {/* B. Debts Panel */}
      <Panel title="叙事债务">
        {/* Filter tabs */}
        <div className="mb-4 flex gap-2">
          {debtFilterTabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setDebtFilter(tab.key)}
              className={debtFilter === tab.key ? tabActive : tabInactive}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {debtsLoading ? (
          <div className="flex items-center justify-center py-8 text-slate-400">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            加载中...
          </div>
        ) : (debts?.debts ?? debts ?? []).length === 0 ? (
          <p className="py-6 text-center text-sm text-slate-400">暂无叙事债务</p>
        ) : (() => {
          const debtList = debts?.debts ?? debts ?? [];
          return (
            <div className="overflow-hidden rounded-xl border border-slate-200">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50 text-[11px] uppercase tracking-wider text-slate-400">
                  <tr>
                    <th className="px-3 py-2">状态</th>
                    <th className="px-3 py-2">类型</th>
                    <th className="px-3 py-2">来源</th>
                    <th className="px-3 py-2 w-full">描述</th>
                    <th className="px-3 py-2">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {debtList.map((debt: any, idx: number) => {
                    const typeStyle = DEBT_TYPE_STYLES[debt.debt_type] ?? DEBT_TYPE_STYLES.long_tail;
                    return (
                      <tr key={debt.id ?? idx} className="hover:bg-slate-50 transition-colors">
                        <td className="px-3 py-2 whitespace-nowrap">
                          <span className={`inline-block h-2 w-2 rounded-full ${
                            debt.status === "fulfilled" ? "bg-emerald-500" :
                            debt.status === "overdue" ? "bg-rose-500" :
                            "bg-amber-400"
                          }`} title={debt.status === "fulfilled" ? "已兑现" : debt.status === "overdue" ? "已逾期" : "待处理"} />
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap">
                          <span className={`inline-flex rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${typeStyle.bg} ${typeStyle.text}`}>
                            {typeStyle.label}
                          </span>
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap text-slate-500">第{debt.source_chapter}章</td>
                        <td className="px-3 py-2 text-slate-700 max-w-0">
                          <p className="truncate" title={debt.description}>{debt.description}</p>
                          {debt.fulfillment_note && (
                            <p className="truncate text-[10px] text-emerald-600 mt-0.5" title={debt.fulfillment_note}>{debt.fulfillment_note}</p>
                          )}
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap">
                          {debt.status !== "fulfilled" && (
                            <button
                              onClick={() => fulfillDebt.mutate(debt.id)}
                              disabled={fulfillDebt.isPending}
                              className="rounded px-2 py-1 text-[10px] font-semibold text-emerald-700 bg-emerald-50 hover:bg-emerald-100 transition disabled:opacity-50"
                            >
                              <Check className="mr-0.5 inline h-2.5 w-2.5" />兑现
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div className="bg-slate-50 px-3 py-1.5 text-[10px] text-slate-400 text-right">
                共 {debtList.length} 条
              </div>
            </div>
          );
        })()}
      </Panel>

      {/* C. Story Arcs Panel */}
      <Panel title="故事弧线">
        {arcsLoading ? (
          <div className="flex items-center justify-center py-8 text-slate-400">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            加载中...
          </div>
        ) : (arcs?.arcs ?? arcs ?? []).length === 0 ? (
          <p className="py-6 text-center text-sm text-slate-400">暂无故事弧线</p>
        ) : (() => {
          const arcList: any[] = arcs?.arcs ?? arcs ?? [];
          const timelinePhaseColors: Record<string, string> = {
            setup: "bg-sky-400",
            escalation: "bg-amber-400",
            climax: "bg-rose-500",
            resolution: "bg-emerald-500",
          };

          // Compute chapter range across all arcs
          const allChapterNums = arcList.flatMap((arc: any) => {
            const chs = arc.chapters ?? [];
            if (chs.length) return chs;
            const s = arc.start_chapter ?? 1;
            const e = arc.end_chapter ?? s;
            return Array.from({ length: e - s + 1 }, (_, i) => s + i);
          });
          const minCh = allChapterNums.length ? Math.min(...allChapterNums) : 1;
          const maxCh = allChapterNums.length ? Math.max(...allChapterNums) : 1;
          const totalRange = Math.max(maxCh - minCh + 1, 1);

          return (
            <div>
              {/* Timeline visualization */}
              <div className="mt-2">
                {/* Chapter number ruler */}
                <div className="flex items-end mb-2 pl-[140px]">
                  {Array.from({ length: totalRange }, (_, i) => minCh + i).map((ch) => (
                    <div
                      key={ch}
                      className="text-[10px] text-slate-400 text-center"
                      style={{ width: `${100 / totalRange}%` }}
                    >
                      {ch}
                    </div>
                  ))}
                </div>

                {/* Arc bars */}
                <div className="space-y-2">
                  {arcList.map((arc: any, idx: number) => {
                    const chapters = arc.chapters ?? [];
                    const startCh = chapters.length
                      ? Math.min(...chapters)
                      : (arc.start_chapter ?? 1);
                    const endCh = chapters.length
                      ? Math.max(...chapters)
                      : (arc.end_chapter ?? startCh);
                    const phase = arc.current_phase ?? arc.phase ?? "setup";
                    const leftPct = ((startCh - minCh) / totalRange) * 100;
                    const widthPct = ((endCh - startCh + 1) / totalRange) * 100;
                    const color = timelinePhaseColors[phase] ?? "bg-slate-400";

                    return (
                      <div key={arc.id ?? idx} className="flex items-center gap-2">
                        <div className="w-[130px] truncate text-right text-xs text-slate-600 font-medium">
                          {arc.title ?? arc.name ?? `弧线${idx + 1}`}
                        </div>
                        <div className="relative flex-1 h-7 bg-slate-50 rounded">
                          <div
                            className={`absolute h-7 rounded ${color} opacity-80 flex items-center justify-center`}
                            style={{
                              left: `${leftPct}%`,
                              width: `${Math.max(widthPct, 3)}%`,
                            }}
                            title={`${arc.title ?? arc.name ?? ""}: 第${startCh}-${endCh}章 (${phase})`}
                          >
                            <span className="text-[10px] text-white font-semibold truncate px-1">
                              {arc.hook ?? arc.description ?? ""}
                            </span>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Phase legend */}
                <div className="mt-3 flex gap-4 justify-center">
                  {Object.entries({
                    setup: "铺垫",
                    escalation: "升级",
                    climax: "高潮",
                    resolution: "收束",
                  }).map(([k, v]) => (
                    <div key={k} className="flex items-center gap-1 text-xs text-slate-500">
                      <div className={`h-2.5 w-2.5 rounded-sm ${timelinePhaseColors[k]}`} />
                      {v}
                    </div>
                  ))}
                </div>
              </div>

              {/* Detail cards (below timeline) */}
              <div className="mt-6 space-y-4">
                {(() => {
                  const phaseGuidance: Record<string, string> = {
                    setup: "建立情境，引入冲突种子",
                    escalation: "加剧矛盾，提高stakes",
                    climax: "主要冲突爆发，转折点",
                    resolution: "解决冲突，揭示后果",
                  };
                  return arcList.map((arc: any, idx: number) => {
                  const phaseStyle =
                    ARC_PHASE_STYLES[arc.current_phase ?? arc.phase] ??
                    ARC_PHASE_STYLES.setup;
                  const phaseKey = arc.current_phase ?? arc.phase ?? "setup";
                  const chapters = arc.chapters ?? [];
                  const startCh = chapters.length
                    ? Math.min(...chapters)
                    : (arc.start_chapter ?? 1);
                  const endCh = chapters.length
                    ? Math.max(...chapters)
                    : (arc.end_chapter ?? startCh);
                  const currentCh = arc.current_chapter ?? startCh;
                  const totalSpan = Math.max(endCh - startCh, 1);
                  const progress = Math.min(
                    Math.round(((currentCh - startCh) / totalSpan) * 100),
                    100
                  );
                  return (
                    <div
                      key={arc.id ?? `detail-${idx}`}
                      className="rounded-xl border border-slate-200 bg-white p-4"
                    >
                      <div className="flex items-center justify-between">
                        <h4 className="text-sm font-semibold text-ink">
                          {arc.title ?? arc.name ?? `弧线 ${idx + 1}`}
                        </h4>
                        <div className="text-right">
                          <span
                            className={`inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ${phaseStyle.bg} ${phaseStyle.text}`}
                          >
                            {phaseStyle.label}
                          </span>
                          {phaseGuidance[phaseKey] && (
                            <p className="mt-0.5 text-[10px] text-slate-400">
                              {phaseGuidance[phaseKey]}
                            </p>
                          )}
                        </div>
                      </div>
                      {(arc.description ?? arc.hook) && (
                        <p className="mt-1 text-xs text-slate-500">
                          {arc.description ?? arc.hook}
                        </p>
                      )}
                      <div className="mt-3 flex items-center gap-3 text-xs text-slate-500">
                        <span>
                          第{startCh}章 - 第{endCh}章
                        </span>
                        <span
                          className={`font-semibold ${
                            arc.status === "completed"
                              ? "text-emerald-600"
                              : arc.status === "active"
                                ? "text-sky-600"
                                : "text-slate-500"
                          }`}
                        >
                          {arc.status === "completed"
                            ? "已完结"
                            : arc.status === "active"
                              ? "进行中"
                              : (arc.status ?? "计划中")}
                        </span>
                      </div>
                      <div className="mt-2 h-2 rounded-full bg-slate-100">
                        <div
                          className={`h-2 rounded-full transition-all ${
                            arc.status === "completed"
                              ? "bg-emerald-500"
                              : "bg-accent"
                          }`}
                          style={{
                            width: `${arc.status === "completed" ? 100 : progress}%`,
                          }}
                        />
                      </div>
                      <p className="mt-1 text-right text-xs text-slate-400">
                        {arc.status === "completed" ? "100" : progress}%
                      </p>
                    </div>
                  );
                });
                })()}
              </div>
            </div>
          );
        })()}
      </Panel>

      {/* Chapter Brief Lookup */}
      <Panel title="章节纲要查询">
        <div className="flex items-center gap-3">
          <input
            type="number"
            min={1}
            placeholder="输入章节号..."
            className={inputCls + " max-w-[180px]"}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                const val = parseInt((e.target as HTMLInputElement).value);
                if (!isNaN(val) && val > 0) setSelectedBriefChapter(val);
              }
            }}
          />
          <button
            onClick={() => {
              const input = document.querySelector<HTMLInputElement>(
                'input[type="number"][placeholder="输入章节号..."]'
              );
              if (input) {
                const val = parseInt(input.value);
                if (!isNaN(val) && val > 0) setSelectedBriefChapter(val);
              }
            }}
            className={btnSecondary}
          >
            <Search className="h-4 w-4" />
            查询
          </button>
        </div>
        {selectedBriefChapter !== null && brief && (
          <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm">
            <h4 className="font-semibold text-ink">第{selectedBriefChapter}章纲要</h4>
            {brief.title && <p className="mt-1 text-slate-600">标题: {brief.title}</p>}
            {brief.summary && <p className="mt-2 text-slate-600">{brief.summary}</p>}
            {brief.key_events && (
              <div className="mt-2">
                <p className="text-xs font-semibold text-slate-500">关键事件:</p>
                <ul className="mt-1 list-inside list-disc text-slate-600">
                  {(Array.isArray(brief.key_events) ? brief.key_events : []).map((ev: string, i: number) => (
                    <li key={i}>{ev}</li>
                  ))}
                </ul>
              </div>
            )}
            {brief.debts_introduced && brief.debts_introduced.length > 0 && (
              <div className="mt-2">
                <p className="text-xs font-semibold text-slate-500">引入的债务:</p>
                <ul className="mt-1 list-inside list-disc text-slate-600">
                  {brief.debts_introduced.map((d: string, i: number) => (
                    <li key={i}>{d}</li>
                  ))}
                </ul>
              </div>
            )}
            {brief.debts_resolved && brief.debts_resolved.length > 0 && (
              <div className="mt-2">
                <p className="text-xs font-semibold text-slate-500">解决的债务:</p>
                <ul className="mt-1 list-inside list-disc text-slate-600">
                  {brief.debts_resolved.map((d: string, i: number) => (
                    <li key={i}>{d}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </Panel>

      {/* D. Knowledge Graph Panel (collapsible) */}
      <Panel title="知识图谱" className={graphOpen ? "" : ""}>
        <button
          onClick={() => setGraphOpen(!graphOpen)}
          className="flex w-full items-center justify-between rounded-xl px-1 py-1 text-sm font-semibold text-slate-600 transition hover:text-ink"
        >
          <span>{graphOpen ? "收起" : "展开"} 角色关系图</span>
          {graphOpen ? (
            <ChevronUp className="h-4 w-4" />
          ) : (
            <ChevronDown className="h-4 w-4" />
          )}
        </button>

        {graphOpen && (
          <>
            {graphLoading ? (
              <div className="flex items-center justify-center py-8 text-slate-400">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                加载中...
              </div>
            ) : (() => {
              const graphNodes = graph?.nodes ?? [];
              const graphEdges = graph?.edges ?? graph?.relationships ?? [];
              if (graphNodes.length === 0 && graphEdges.length === 0) {
                return (
                  <p className="py-6 text-center text-sm text-slate-400">
                    暂无知识图谱数据
                  </p>
                );
              }
              return (
                <div className="mt-3">
                  <KnowledgeGraphVisualization
                    nodes={graphNodes}
                    edges={graphEdges}
                  />
                </div>
              );
            })()}
          </>
        )}
      </Panel>
    </div>
  );
}

// ─── Active Task Panel (Sidebar) ──────────────────────────────────────
function ActiveTaskPanel({ novelId }: { novelId: string }) {
  const qc = useQueryClient();
  const { data: tasks } = useTasks(20);
  const prevRunningRef = useRef<Set<string>>(new Set());

  // Invalidate chapter/novel caches when any novel task transitions to completed
  useEffect(() => {
    if (!tasks) return;
    const myTasks = tasks.filter(
      (t: TaskDetail) =>
        t.task_type.startsWith("novel_") &&
        (t.params?.project_path?.includes(novelId) ||
          t.params?.novel_id === novelId)
    );
    const currentRunning = new Set(
      myTasks
        .filter((t: TaskDetail) => t.status === "running" || t.status === "pending")
        .map((t: TaskDetail) => t.task_id)
    );
    const justCompleted = myTasks.filter(
      (t: TaskDetail) =>
        t.status === "completed" && prevRunningRef.current.has(t.task_id)
    );
    if (justCompleted.length > 0) {
      qc.invalidateQueries({ queryKey: ["novel", novelId] });
      qc.invalidateQueries({ queryKey: ["chapter"] });
      qc.invalidateQueries({ queryKey: ["novel-settings", novelId] });
    }
    prevRunningRef.current = currentRunning;
  }, [tasks, novelId, qc]);

  const novelTasks = tasks?.filter(
    (t: TaskDetail) =>
      t.task_type.startsWith("novel_") &&
      (t.status === "running" || t.status === "pending") &&
      (t.params?.project_path?.includes(novelId) ||
        t.params?.novel_id === novelId)
  );

  const recentTasks = tasks
    ?.filter(
      (t: TaskDetail) =>
        t.task_type.startsWith("novel_") &&
        (t.params?.project_path?.includes(novelId) ||
          t.params?.novel_id === novelId)
    )
    ?.slice(0, 5);

  const taskTypeLabels: Record<string, string> = {
    novel_create: "创建项目",
    novel_generate: "生成章节",
    novel_polish: "精修润色",
    novel_feedback: "反馈重写",
    novel_edit: "AI 编辑",
  };

  // Hide entire panel when no active tasks
  if (!novelTasks || novelTasks.length === 0) return null;

  return (
    <Panel title="任务进度">
      <div className="space-y-3">
        {novelTasks.map((task: TaskDetail) => (
          <div
            key={task.task_id}
            className="rounded-[20px] border border-emerald-100 bg-emerald-50 p-3"
          >
            <div className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin text-emerald-600" />
              <p className="text-sm font-semibold text-emerald-800">
                {taskTypeLabels[task.task_type] ?? task.task_type}
              </p>
            </div>
            <p className="mt-1 text-xs text-emerald-700">
              {task.progress_msg || "处理中..."}
            </p>
            <div className="mt-2 h-1.5 rounded-full bg-emerald-200">
              <div
                className="h-1.5 rounded-full bg-emerald-500 transition-all"
                style={{
                  width: `${Math.round(task.progress * 100)}%`,
                }}
              />
            </div>
            <p className="mt-1 text-right text-xs text-emerald-600">
              {Math.round(task.progress * 100)}%
            </p>
          </div>
        ))}
      </div>
    </Panel>
  );
}

// ─── Quick Stats (Sidebar) ────────────────────────────────────────────
function QuickStats({ novel }: { novel: any }) {
  const totalWords =
    novel.chapters?.reduce(
      (sum: number, ch: any) => sum + (ch.word_count ?? 0),
      0
    ) ?? 0;

  return (
    <Panel title="快速统计">
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-[0.15em] text-slate-500">
            总章节
          </span>
          <span className="font-semibold text-ink">
            {novel.chapters?.length ?? 0}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-[0.15em] text-slate-500">
            已生成字数
          </span>
          <span className="font-semibold text-ink">
            {totalWords > 10000
              ? `${(totalWords / 10000).toFixed(1)} 万`
              : `${totalWords} 字`}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-[0.15em] text-slate-500">
            目标字数
          </span>
          <span className="font-semibold text-ink">
            {((novel.target_words ?? 0) / 10000).toFixed(0)} 万字
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-[0.15em] text-slate-500">
            创建时间
          </span>
          <span className="text-xs text-slate-600">
            {novel.created_at
              ? new Date(novel.created_at).toLocaleDateString("zh-CN")
              : "-"}
          </span>
        </div>
      </div>
    </Panel>
  );
}

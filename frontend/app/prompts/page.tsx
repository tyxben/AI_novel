"use client";

import { useState } from "react";
import {
  Wand2,
  Loader2,
  Save,
  RotateCcw,
  ChevronRight,
  Sparkles,
  Eye,
  Database,
} from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { Panel } from "@/components/ui/panel";
import {
  usePromptBlocks,
  usePromptBlock,
  useBlockVersions,
  usePromptTemplates,
  useUpdateBlock,
  useRollbackBlock,
  useBuildPrompt,
  useSeedPrompts,
} from "@/lib/hooks";

/* ------------------------------------------------------------------ */
/*  Constants                                                         */
/* ------------------------------------------------------------------ */

const AGENT_OPTIONS = [
  { value: "", label: "全部 Agent" },
  { value: "writer", label: "Writer" },
  { value: "style_keeper", label: "StyleKeeper" },
  { value: "quality_reviewer", label: "QualityReviewer" },
  { value: "consistency_checker", label: "ConsistencyChecker" },
  { value: "novel_director", label: "NovelDirector" },
  { value: "universal", label: "Universal" },
];

const TYPE_OPTIONS = [
  { value: "", label: "全部类型" },
  { value: "anti_pattern", label: "anti_pattern" },
  { value: "craft_technique", label: "craft_technique" },
  { value: "system_instruction", label: "system_instruction" },
  { value: "style_guide", label: "style_guide" },
  { value: "quality_criteria", label: "quality_criteria" },
  { value: "genre_preset", label: "genre_preset" },
];

const TYPE_COLORS: Record<string, string> = {
  anti_pattern: "bg-rose-50 text-rose-700",
  craft_technique: "bg-sky-50 text-sky-700",
  system_instruction: "bg-violet-50 text-violet-700",
  style_guide: "bg-amber-50 text-amber-700",
  quality_criteria: "bg-emerald-50 text-emerald-700",
  genre_preset: "bg-indigo-50 text-indigo-700",
};

function scoreColor(score: number | null | undefined): string {
  if (score == null) return "text-slate-400";
  if (score >= 8) return "text-emerald-600";
  if (score >= 6) return "text-amber-600";
  return "text-rose-600";
}

function scoreBg(score: number | null | undefined): string {
  if (score == null) return "bg-slate-50 text-slate-500";
  if (score >= 8) return "bg-emerald-50 text-emerald-700";
  if (score >= 6) return "bg-amber-50 text-amber-700";
  return "bg-rose-50 text-rose-700";
}

/* ------------------------------------------------------------------ */
/*  Main Page                                                         */
/* ------------------------------------------------------------------ */

export default function PromptsPage() {
  // Filters
  const [agentFilter, setAgentFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");

  // Selection
  const [selectedBlockId, setSelectedBlockId] = useState<string | null>(null);

  // Edit state
  const [editContent, setEditContent] = useState("");
  const [editDirty, setEditDirty] = useState(false);

  // Preview state
  const [previewAgent, setPreviewAgent] = useState("writer");
  const [previewScenario, setPreviewScenario] = useState("");
  const [previewGenre, setPreviewGenre] = useState("");
  const [previewResult, setPreviewResult] = useState<string | null>(null);

  // Queries
  const blocksQuery = usePromptBlocks({
    agent: agentFilter || undefined,
    block_type: typeFilter || undefined,
  });
  const blockDetail = usePromptBlock(selectedBlockId);
  const versionsQuery = useBlockVersions(selectedBlockId);
  const templatesQuery = usePromptTemplates();

  // Mutations
  const updateBlock = useUpdateBlock();
  const rollbackBlock = useRollbackBlock();
  const buildPrompt = useBuildPrompt();
  const seedPrompts = useSeedPrompts();

  const blocks = blocksQuery.data ?? [];
  const versions = versionsQuery.data ?? [];
  const templates = templatesQuery.data ?? [];

  // When block detail loads, set the edit content
  const detail = blockDetail.data;

  function handleSelectBlock(baseId: string) {
    setSelectedBlockId(baseId);
    setEditDirty(false);
    setPreviewResult(null);
  }

  function handleContentLoaded() {
    if (detail && !editDirty) {
      setEditContent(detail.content ?? "");
    }
  }
  // Sync content when detail changes
  if (detail && !editDirty && editContent !== (detail.content ?? "")) {
    handleContentLoaded();
  }

  function handleSave() {
    if (!selectedBlockId || !editDirty) return;
    updateBlock.mutate(
      { baseId: selectedBlockId, content: editContent },
      {
        onSuccess: () => {
          setEditDirty(false);
        },
      }
    );
  }

  function handleRollback(version: number) {
    if (!selectedBlockId) return;
    rollbackBlock.mutate(
      { baseId: selectedBlockId, version },
      {
        onSuccess: () => {
          setEditDirty(false);
        },
      }
    );
  }

  function handlePreview() {
    buildPrompt.mutate(
      {
        agent_name: previewAgent,
        scenario: previewScenario || undefined,
        genre: previewGenre || undefined,
      },
      {
        onSuccess: (data) => {
          setPreviewResult(data.prompt);
        },
      }
    );
  }

  function handleSeed() {
    seedPrompts.mutate();
  }

  return (
    <>
      <PageHeader
        eyebrow="PROMPT REGISTRY"
        title="Prompt 管理"
        description="管理 Prompt Block 版本、模板组装和 A/B 测试。支持按 Agent、类型筛选，编辑保存自动创建新版本。"
      />

      <div className="space-y-5 px-6 py-6 md:px-8">
        {/* Block List + Detail */}
        <div className="grid gap-5 lg:grid-cols-[380px_minmax(0,1fr)]">
          {/* Left: Block List */}
          <Panel title="Prompt Blocks" description="按 Agent 和类型筛选">
            {/* Filters */}
            <div className="mb-4 flex gap-2">
              <select
                value={agentFilter}
                onChange={(e) => setAgentFilter(e.target.value)}
                className="flex-1 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
              >
                {AGENT_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              <select
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                className="flex-1 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
              >
                {TYPE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Loading */}
            {blocksQuery.isLoading && (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="h-5 w-5 animate-spin text-accent" />
              </div>
            )}

            {/* Error */}
            {blocksQuery.isError && (
              <div className="rounded-2xl bg-rose-50 p-4 text-sm text-rose-700">
                加载失败: {(blocksQuery.error as Error).message}
              </div>
            )}

            {/* Empty state with seed button */}
            {!blocksQuery.isLoading && !blocksQuery.isError && blocks.length === 0 && (
              <div className="flex flex-col items-center gap-3 py-12 text-center">
                <Database className="h-8 w-8 text-slate-300" />
                <p className="text-sm text-slate-500">暂无 Prompt Block 数据</p>
                <button
                  onClick={handleSeed}
                  disabled={seedPrompts.isPending}
                  className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2 text-sm font-medium text-white transition hover:bg-accent/90 disabled:opacity-50"
                >
                  {seedPrompts.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Sparkles className="h-4 w-4" />
                  )}
                  初始化种子数据
                </button>
                {seedPrompts.isSuccess && (
                  <p className="text-xs text-emerald-600">
                    已创建 {seedPrompts.data?.blocks_count ?? 0} 个 Block，{seedPrompts.data?.templates_count ?? 0} 个模板
                  </p>
                )}
              </div>
            )}

            {/* Block list */}
            {blocks.length > 0 && (
              <div className="max-h-[600px] space-y-2 overflow-y-auto pr-1">
                {blocks.map((block: any) => {
                  const isSelected = block.base_id === selectedBlockId;
                  return (
                    <button
                      key={block.base_id}
                      onClick={() => handleSelectBlock(block.base_id)}
                      className={`w-full rounded-2xl border p-3 text-left transition ${
                        isSelected
                          ? "border-accent/40 bg-accent/5"
                          : "border-slate-100 hover:border-slate-200 hover:bg-shell"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium text-ink">
                            {block.base_id}
                          </p>
                          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                            <span
                              className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                                TYPE_COLORS[block.block_type] ?? "bg-slate-100 text-slate-600"
                              }`}
                            >
                              {block.block_type}
                            </span>
                            {block.agent && (
                              <span className="inline-block rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-600">
                                {block.agent}
                              </span>
                            )}
                            <span className="text-[10px] text-slate-400">
                              v{block.version ?? 1}
                            </span>
                          </div>
                        </div>
                        <div className="flex flex-col items-end gap-1">
                          {block.avg_score != null && (
                            <span
                              className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-bold ${scoreBg(
                                block.avg_score
                              )}`}
                            >
                              {Number(block.avg_score).toFixed(1)}
                            </span>
                          )}
                          {block.usage_count != null && block.usage_count > 0 && (
                            <span className="text-[10px] text-slate-400">
                              {block.usage_count} 次使用
                            </span>
                          )}
                          <ChevronRight
                            className={`h-3.5 w-3.5 ${
                              isSelected ? "text-accent" : "text-slate-300"
                            }`}
                          />
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </Panel>

          {/* Right: Block Detail */}
          <div className="space-y-5">
            {!selectedBlockId && (
              <Panel title="Block 详情" className="flex min-h-[400px] items-center justify-center">
                <p className="text-sm text-slate-400">
                  <Wand2 className="mb-2 mx-auto h-8 w-8 text-slate-300" />
                  从左侧列表选择一个 Block 查看详情
                </p>
              </Panel>
            )}

            {selectedBlockId && (
              <>
                {/* Block Detail Panel */}
                <Panel
                  title={detail?.base_id ?? selectedBlockId}
                  description={detail ? `${detail.block_type} | v${detail.version ?? 1}` : "加载中..."}
                >
                  {blockDetail.isLoading && (
                    <div className="flex items-center justify-center py-8">
                      <Loader2 className="h-5 w-5 animate-spin text-accent" />
                    </div>
                  )}

                  {blockDetail.isError && (
                    <div className="rounded-2xl bg-rose-50 p-4 text-sm text-rose-700">
                      加载失败: {(blockDetail.error as Error).message}
                    </div>
                  )}

                  {detail && (
                    <div className="space-y-4">
                      {/* Stats row */}
                      <div className="flex flex-wrap items-center gap-3">
                        {detail.agent && (
                          <span className="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">
                            Agent: {detail.agent}
                          </span>
                        )}
                        {detail.genre && (
                          <span className="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">
                            Genre: {detail.genre}
                          </span>
                        )}
                        {detail.usage_count != null && (
                          <span className="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">
                            使用 {detail.usage_count} 次
                          </span>
                        )}
                        {detail.avg_score != null && (
                          <span
                            className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-bold ${scoreBg(
                              detail.avg_score
                            )}`}
                          >
                            评分 {Number(detail.avg_score).toFixed(1)}
                          </span>
                        )}
                        {detail.needs_optimization && (
                          <span className="inline-flex items-center rounded-full bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-700">
                            需要优化
                          </span>
                        )}
                        {detail.created_at && (
                          <span className="text-xs text-slate-400">
                            创建于 {new Date(detail.created_at).toLocaleDateString("zh-CN")}
                          </span>
                        )}
                      </div>

                      {/* Content editor */}
                      <div>
                        <label className="mb-1.5 block text-xs font-medium text-slate-500">
                          内容 (编辑后保存将创建新版本)
                        </label>
                        <textarea
                          value={editContent}
                          onChange={(e) => {
                            setEditContent(e.target.value);
                            setEditDirty(true);
                          }}
                          rows={12}
                          className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 font-mono text-sm text-ink leading-relaxed placeholder:text-slate-400 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                        />
                      </div>

                      {/* Save button */}
                      <div className="flex items-center gap-3">
                        <button
                          onClick={handleSave}
                          disabled={!editDirty || updateBlock.isPending}
                          className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2 text-sm font-medium text-white transition hover:bg-accent/90 disabled:opacity-50"
                        >
                          {updateBlock.isPending ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <Save className="h-4 w-4" />
                          )}
                          保存新版本
                        </button>
                        {updateBlock.isSuccess && (
                          <span className="text-xs text-emerald-600">已保存</span>
                        )}
                        {updateBlock.isError && (
                          <span className="text-xs text-rose-600">
                            保存失败: {(updateBlock.error as Error).message}
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                </Panel>

                {/* Version History */}
                <Panel title="版本历史" description="点击回滚到指定版本">
                  {versionsQuery.isLoading && (
                    <div className="flex items-center justify-center py-4">
                      <Loader2 className="h-4 w-4 animate-spin text-accent" />
                    </div>
                  )}
                  {versions.length === 0 && !versionsQuery.isLoading && (
                    <p className="py-4 text-center text-sm text-slate-400">暂无版本记录</p>
                  )}
                  {versions.length > 0 && (
                    <div className="max-h-[300px] space-y-2 overflow-y-auto">
                      {versions.map((v: any) => (
                        <div
                          key={v.version ?? v.id}
                          className="flex items-center justify-between rounded-xl border border-slate-100 px-4 py-3 transition hover:border-slate-200"
                        >
                          <div>
                            <span className="text-sm font-medium text-ink">
                              v{v.version}
                            </span>
                            {v.created_at && (
                              <span className="ml-3 text-xs text-slate-400">
                                {new Date(v.created_at).toLocaleString("zh-CN")}
                              </span>
                            )}
                            {v.avg_score != null && (
                              <span className={`ml-3 text-xs font-bold ${scoreColor(v.avg_score)}`}>
                                {Number(v.avg_score).toFixed(1)}
                              </span>
                            )}
                          </div>
                          {v.version !== detail?.version && (
                            <button
                              onClick={() => handleRollback(v.version)}
                              disabled={rollbackBlock.isPending}
                              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-shell disabled:opacity-50"
                            >
                              {rollbackBlock.isPending ? (
                                <Loader2 className="h-3 w-3 animate-spin" />
                              ) : (
                                <RotateCcw className="h-3 w-3" />
                              )}
                              回滚
                            </button>
                          )}
                          {v.version === detail?.version && (
                            <span className="rounded-full bg-accent/10 px-2.5 py-1 text-xs font-semibold text-accent">
                              当前
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </Panel>

                {/* Preview / Build Prompt */}
                <Panel title="预览组装" description="选择 Agent + 场景 + 类型，预览最终拼装的 Prompt">
                  <div className="space-y-4">
                    <div className="flex flex-wrap gap-3">
                      <div className="flex-1 min-w-[140px]">
                        <label className="mb-1 block text-xs font-medium text-slate-500">
                          Agent
                        </label>
                        <select
                          value={previewAgent}
                          onChange={(e) => setPreviewAgent(e.target.value)}
                          className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                        >
                          {AGENT_OPTIONS.filter((o) => o.value !== "").map((o) => (
                            <option key={o.value} value={o.value}>
                              {o.label}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="flex-1 min-w-[140px]">
                        <label className="mb-1 block text-xs font-medium text-slate-500">
                          场景
                        </label>
                        <input
                          value={previewScenario}
                          onChange={(e) => setPreviewScenario(e.target.value)}
                          placeholder="如: chapter_write"
                          className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-ink placeholder:text-slate-400 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                        />
                      </div>
                      <div className="flex-1 min-w-[140px]">
                        <label className="mb-1 block text-xs font-medium text-slate-500">
                          Genre
                        </label>
                        <input
                          value={previewGenre}
                          onChange={(e) => setPreviewGenre(e.target.value)}
                          placeholder="如: 玄幻"
                          className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-ink placeholder:text-slate-400 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                        />
                      </div>
                    </div>
                    <button
                      onClick={handlePreview}
                      disabled={buildPrompt.isPending}
                      className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-shell disabled:opacity-50"
                    >
                      {buildPrompt.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Eye className="h-4 w-4" />
                      )}
                      预览组装结果
                    </button>
                    {buildPrompt.isError && (
                      <p className="text-xs text-rose-600">
                        预览失败: {(buildPrompt.error as Error).message}
                      </p>
                    )}
                    {previewResult && (
                      <div className="rounded-xl border border-slate-200 bg-shell p-4">
                        <div className="mb-2 flex items-center justify-between">
                          <span className="text-xs font-medium text-slate-500">
                            组装结果
                          </span>
                          <span className="text-xs text-slate-400">
                            {previewResult.length} 字符
                          </span>
                        </div>
                        <pre className="max-h-[400px] overflow-auto whitespace-pre-wrap font-mono text-xs leading-relaxed text-ink">
                          {previewResult}
                        </pre>
                      </div>
                    )}
                  </div>
                </Panel>
              </>
            )}
          </div>
        </div>

        {/* Templates Section */}
        <Panel title="Prompt 模板" description="模板定义了 Agent 在特定场景下使用的 Block 组合">
          {templatesQuery.isLoading && (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-accent" />
            </div>
          )}
          {templatesQuery.isError && (
            <div className="rounded-2xl bg-rose-50 p-4 text-sm text-rose-700">
              加载失败: {(templatesQuery.error as Error).message}
            </div>
          )}
          {!templatesQuery.isLoading && templates.length === 0 && (
            <p className="py-8 text-center text-sm text-slate-400">
              暂无模板数据，请先初始化种子数据
            </p>
          )}
          {templates.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-100">
                    <th className="py-2.5 pr-4 font-medium text-slate-500">模板 ID</th>
                    <th className="py-2.5 pr-4 font-medium text-slate-500">Agent</th>
                    <th className="py-2.5 pr-4 font-medium text-slate-500">场景</th>
                    <th className="py-2.5 pr-4 font-medium text-slate-500">Genre</th>
                    <th className="py-2.5 pr-4 font-medium text-slate-500">Block 引用</th>
                  </tr>
                </thead>
                <tbody>
                  {templates.map((t: any) => (
                    <TemplateRow key={t.template_id ?? t.id} template={t} onBlockClick={handleSelectBlock} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  Sub-component: Template Row                                        */
/* ------------------------------------------------------------------ */

function TemplateRow({
  template,
  onBlockClick,
}: {
  template: any;
  onBlockClick: (baseId: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const refs: string[] = template.block_refs ?? [];

  return (
    <>
      <tr
        className="border-b border-slate-50 transition hover:bg-shell/50 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <td className="py-3 pr-4 font-medium text-ink">{template.template_id}</td>
        <td className="py-3 pr-4 text-slate-600">{template.agent_name}</td>
        <td className="py-3 pr-4 text-slate-600">{template.scenario ?? "-"}</td>
        <td className="py-3 pr-4 text-slate-600">{template.genre ?? "-"}</td>
        <td className="py-3 pr-4">
          <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-600">
            {refs.length} 个 Block
            <ChevronRight
              className={`h-3 w-3 transition ${expanded ? "rotate-90" : ""}`}
            />
          </span>
        </td>
      </tr>
      {expanded && refs.length > 0 && (
        <tr>
          <td colSpan={5} className="pb-3 pt-1">
            <div className="ml-4 flex flex-wrap gap-1.5">
              {refs.map((refId: string) => (
                <button
                  key={refId}
                  onClick={(e) => {
                    e.stopPropagation();
                    onBlockClick(refId);
                  }}
                  className="rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-accent transition hover:bg-accent/5"
                >
                  {refId}
                </button>
              ))}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

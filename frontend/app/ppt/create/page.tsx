"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  Sparkles,
  FileText,
  Loader2,
} from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { Panel } from "@/components/ui/panel";
import { useCreatePPT } from "@/lib/hooks";

/* ------------------------------------------------------------------ */
/*  Constants                                                         */
/* ------------------------------------------------------------------ */

type Mode = "topic" | "document";

const THEMES = [
  { value: "modern", label: "简约现代", desc: "简洁专业" },
  { value: "business", label: "商务正式", desc: "稳重大方" },
  { value: "creative", label: "创意活泼", desc: "色彩丰富" },
  { value: "tech", label: "科技极客", desc: "硬核风格" },
  { value: "education", label: "教育清新", desc: "温和友好" },
] as const;

const AUDIENCES = [
  { value: "business", label: "商务人士" },
  { value: "technical", label: "技术人员" },
  { value: "educational", label: "教育场景" },
  { value: "creative", label: "创意人群" },
  { value: "general", label: "通用" },
] as const;

const SCENARIOS = [
  { value: "quarterly_review", label: "季度汇报" },
  { value: "product_launch", label: "产品发布" },
  { value: "tech_share", label: "技术分享" },
  { value: "course_lecture", label: "课程讲义" },
  { value: "pitch_deck", label: "融资路演" },
  { value: "workshop", label: "工作坊" },
  { value: "status_update", label: "进度更新" },
] as const;

/* ------------------------------------------------------------------ */
/*  Page component                                                    */
/* ------------------------------------------------------------------ */

export default function PptCreatePage() {
  const router = useRouter();
  const createPPT = useCreatePPT();
  const [mode, setMode] = useState<Mode>("topic");
  const [error, setError] = useState<string | null>(null);

  // Topic mode fields
  const [topic, setTopic] = useState("");
  const [audience, setAudience] = useState("business");
  const [scenario, setScenario] = useState("quarterly_review");

  // Document mode fields
  const [documentText, setDocumentText] = useState("");

  // Common fields
  const [theme, setTheme] = useState("modern");
  const [targetPages, setTargetPages] = useState(15);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (mode === "topic" && !topic.trim()) {
      setError("请输入演示主题");
      return;
    }
    if (mode === "document" && !documentText.trim()) {
      setError("请输入文档内容");
      return;
    }

    const params: Record<string, unknown> = {
      theme,
      target_pages: targetPages,
    };

    if (mode === "topic") {
      params.topic = topic.trim();
      params.audience = audience;
      params.scenario = scenario;
    } else {
      params.document_text = documentText.trim();
    }

    try {
      const result = await createPPT.mutateAsync(params);
      router.push(`/ppt/${result.task_id}`);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "提交失败"
      );
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="新建 PPT"
        title="创建 PPT 项目"
        description="选择输入方式，设置主题和参数后提交到任务队列自动生成幻灯片大纲。"
        action={
          <Link
            href="/ppt"
            className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-shell"
          >
            <ArrowLeft className="h-4 w-4" />
            返回列表
          </Link>
        }
      />

      <div className="space-y-5 px-6 py-6 md:px-8">
        {/* Mode Selector */}
        <div className="grid gap-4 md:grid-cols-2">
          <button
            type="button"
            onClick={() => setMode("topic")}
            className={`rounded-[22px] border-2 p-5 text-left transition ${
              mode === "topic"
                ? "border-accent bg-accent/5"
                : "border-slate-200 bg-white hover:border-slate-300"
            }`}
          >
            <Sparkles
              className={`h-6 w-6 ${
                mode === "topic" ? "text-accent" : "text-slate-400"
              }`}
            />
            <h3 className="mt-3 text-lg font-semibold text-ink">主题模式</h3>
            <p className="mt-1 text-sm text-slate-600">
              输入演示主题和受众类型，AI 自动生成结构化大纲和内容。
            </p>
          </button>

          <button
            type="button"
            onClick={() => setMode("document")}
            className={`rounded-[22px] border-2 p-5 text-left transition ${
              mode === "document"
                ? "border-accent bg-accent/5"
                : "border-slate-200 bg-white hover:border-slate-300"
            }`}
          >
            <FileText
              className={`h-6 w-6 ${
                mode === "document" ? "text-accent" : "text-slate-400"
              }`}
            />
            <h3 className="mt-3 text-lg font-semibold text-ink">文档模式</h3>
            <p className="mt-1 text-sm text-slate-600">
              粘贴已有文档文本，AI 自动提取关键信息并生成幻灯片。
            </p>
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          {/* Mode-specific input */}
          {mode === "topic" ? (
            <Panel title="主题设置" description="描述演示主题和受众">
              <div className="space-y-5">
                <div>
                  <label className="mb-2 block text-sm font-medium text-ink">
                    演示主题
                  </label>
                  <textarea
                    value={topic}
                    onChange={(e) => setTopic(e.target.value)}
                    placeholder="例如：2024年Q3产品运营数据复盘及Q4增长策略"
                    rows={3}
                    className="w-full rounded-[16px] border border-slate-200 bg-white px-4 py-3 text-sm text-ink placeholder:text-slate-400 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                  />
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium text-ink">
                    受众类型
                  </label>
                  <div className="flex flex-wrap gap-3">
                    {AUDIENCES.map((opt) => (
                      <button
                        key={opt.value}
                        type="button"
                        onClick={() => setAudience(opt.value)}
                        className={`rounded-[16px] border-2 px-4 py-3 text-center transition ${
                          audience === opt.value
                            ? "border-accent bg-accent/5"
                            : "border-slate-200 bg-white hover:border-slate-300"
                        }`}
                      >
                        <p className="text-sm font-semibold text-ink">
                          {opt.label}
                        </p>
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium text-ink">
                    演示场景
                  </label>
                  <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                    {SCENARIOS.map((opt) => (
                      <button
                        key={opt.value}
                        type="button"
                        onClick={() => setScenario(opt.value)}
                        className={`rounded-[16px] border-2 p-3 text-center transition ${
                          scenario === opt.value
                            ? "border-accent bg-accent/5"
                            : "border-slate-200 bg-white hover:border-slate-300"
                        }`}
                      >
                        <p className="text-sm font-semibold text-ink">
                          {opt.label}
                        </p>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </Panel>
          ) : (
            <Panel title="文档输入" description="粘贴文档内容">
              <div>
                <label className="mb-2 block text-sm font-medium text-ink">
                  文档内容
                </label>
                <textarea
                  value={documentText}
                  onChange={(e) => setDocumentText(e.target.value)}
                  placeholder="在这里粘贴要转换为 PPT 的文档文本..."
                  rows={10}
                  className="w-full rounded-[16px] border border-slate-200 bg-white px-4 py-3 text-sm text-ink placeholder:text-slate-400 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                />
              </div>
            </Panel>
          )}

          {/* Common settings */}
          <div className="mt-5">
            <Panel title="通用设置" description="主题风格和页数">
              <div className="space-y-5">
                <div>
                  <label className="mb-2 block text-sm font-medium text-ink">
                    主题风格
                  </label>
                  <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
                    {THEMES.map((t) => (
                      <button
                        key={t.value}
                        type="button"
                        onClick={() => setTheme(t.value)}
                        className={`rounded-[16px] border-2 p-3 text-center transition ${
                          theme === t.value
                            ? "border-accent bg-accent/5"
                            : "border-slate-200 bg-white hover:border-slate-300"
                        }`}
                      >
                        <p className="text-sm font-semibold text-ink">
                          {t.label}
                        </p>
                        <p className="mt-0.5 text-xs text-slate-500">
                          {t.desc}
                        </p>
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium text-ink">
                    目标页数：{targetPages === 0 ? "自动" : `${targetPages} 页`}
                  </label>
                  <input
                    type="range"
                    min={0}
                    max={30}
                    step={1}
                    value={targetPages}
                    onChange={(e) =>
                      setTargetPages(parseInt(e.target.value, 10))
                    }
                    className="w-full accent-accent"
                  />
                  <div className="mt-1 flex justify-between text-xs text-slate-400">
                    <span>自动</span>
                    <span>30 页</span>
                  </div>
                </div>
              </div>
            </Panel>
          </div>

          {/* Error */}
          {(error || createPPT.error) && (
            <div className="mt-4 rounded-[16px] bg-rose-50 px-4 py-3 text-sm text-rose-700">
              {error ||
                (createPPT.error instanceof Error
                  ? createPPT.error.message
                  : "提交失败")}
            </div>
          )}

          {/* Submit */}
          <div className="mt-5 flex justify-end">
            <button
              type="submit"
              disabled={createPPT.isPending}
              className="inline-flex items-center gap-2 rounded-full bg-ink px-6 py-3 text-sm font-semibold text-white transition hover:bg-ink/90 disabled:opacity-50"
            >
              {createPPT.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="h-4 w-4" />
              )}
              {createPPT.isPending ? "提交中..." : "生成大纲"}
            </button>
          </div>
        </form>
      </div>
    </>
  );
}

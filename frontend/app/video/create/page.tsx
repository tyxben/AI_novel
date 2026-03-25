"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  Sparkles,
  FileText,
  Loader2,
  Settings2,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { Panel } from "@/components/ui/panel";
import { useCreateVideo } from "@/lib/hooks";

/* ------------------------------------------------------------------ */
/*  Option maps (mirror old Gradio frontend)                          */
/* ------------------------------------------------------------------ */

const STYLE_OPTIONS = [
  { value: "anime", label: "动漫风" },
  { value: "realistic", label: "写实" },
  { value: "watercolor", label: "水彩" },
  { value: "chinese_ink", label: "水墨" },
  { value: "cyberpunk", label: "赛博朋克" },
] as const;

const VOICE_OPTIONS = [
  { value: "zh-CN-YunxiNeural", label: "云希-男" },
  { value: "zh-CN-XiaoxiaoNeural", label: "晓晓-女" },
  { value: "zh-CN-YunjianNeural", label: "云健-男播音" },
] as const;

const RATE_OPTIONS = [
  { value: "-20%", label: "慢速" },
  { value: "+0%", label: "正常" },
  { value: "+20%", label: "快速" },
] as const;

const IMAGE_BACKEND_OPTIONS = [
  { value: "siliconflow", label: "SiliconFlow" },
  { value: "dashscope", label: "阿里云通义" },
] as const;

const LLM_OPTIONS = [
  { value: "auto", label: "自动检测" },
  { value: "gemini", label: "Gemini" },
  { value: "deepseek", label: "DeepSeek" },
  { value: "openai", label: "OpenAI" },
  { value: "ollama", label: "Ollama 本地" },
] as const;

const RESOLUTION_OPTIONS = [
  { value: "9:16", label: "竖屏 9:16", dims: [1080, 1920] },
  { value: "16:9", label: "横屏 16:9", dims: [1920, 1080] },
  { value: "1:1", label: "方形 1:1", dims: [1080, 1080] },
] as const;

const QUALITY_OPTIONS = [
  { value: 23, label: "标准" },
  { value: 18, label: "高清" },
  { value: 12, label: "极致" },
] as const;

const CODEC_OPTIONS = [
  { value: "libx265", label: "H.265（推荐）" },
  { value: "libx264", label: "H.264（兼容）" },
] as const;

const VIDEO_MODE_OPTIONS = [
  { value: "static", label: "静态图+特效（免费）" },
  { value: "ai_video", label: "AI 视频片段（付费）" },
] as const;

const VIDEOGEN_BACKEND_OPTIONS = [
  { value: "kling", label: "可灵 Kling" },
  { value: "seedance", label: "即梦 Seedance" },
  { value: "minimax", label: "MiniMax 海螺" },
  { value: "sora", label: "OpenAI Sora" },
] as const;

type Mode = "director" | "classic";

/* ------------------------------------------------------------------ */
/*  Reusable form components                                          */
/* ------------------------------------------------------------------ */

function SelectField({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string | number;
  onChange: (v: string) => void;
  options: ReadonlyArray<{ value: string | number; label: string }>;
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-ink">
        {label}
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-[16px] border border-slate-200 bg-white px-4 py-3 text-sm text-ink focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
      >
        {options.map((opt) => (
          <option key={String(opt.value)} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function ButtonGroup({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: ReadonlyArray<{ value: string; label: string; desc?: string }>;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-ink">
        {label}
      </label>
      <div className="flex flex-wrap gap-3">
        {options.map((opt) => (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(opt.value)}
            className={`flex-1 rounded-[16px] border-2 p-3 text-center transition ${
              value === opt.value
                ? "border-accent bg-accent/5"
                : "border-slate-200 bg-white hover:border-slate-300"
            }`}
          >
            <p className="text-sm font-semibold text-ink">{opt.label}</p>
            {opt.desc && (
              <p className="mt-1 text-xs text-slate-500">{opt.desc}</p>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Page component                                                    */
/* ------------------------------------------------------------------ */

export default function VideoCreatePage() {
  const router = useRouter();
  const createVideo = useCreateVideo();
  const [mode, setMode] = useState<Mode>("director");
  const [error, setError] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Director mode fields
  const [inspiration, setInspiration] = useState("");
  const [targetDuration, setTargetDuration] = useState(60);
  const [budget, setBudget] = useState<"low" | "medium" | "high">("low");

  // Classic mode fields
  const [inputText, setInputText] = useState("");
  const [inputFile, setInputFile] = useState("");
  const [runMode, setRunMode] = useState<"classic" | "agent">("classic");
  const [budgetMode, setBudgetMode] = useState(false);
  const [qualityThreshold, setQualityThreshold] = useState(7.0);

  // Shared advanced config
  const [style, setStyle] = useState("anime");
  const [voice, setVoice] = useState("zh-CN-YunxiNeural");
  const [rate, setRate] = useState("+0%");
  const [imageBackend, setImageBackend] = useState("siliconflow");
  const [llm, setLlm] = useState("auto");
  const [resolution, setResolution] = useState("9:16");
  const [quality, setQuality] = useState("18");
  const [codec, setCodec] = useState("libx265");
  const [videoMode, setVideoMode] = useState("static");
  const [videogenBackend, setVideogenBackend] = useState("kling");

  const submitting = createVideo.isPending;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    // Build config from advanced settings
    const resOption = RESOLUTION_OPTIONS.find((r) => r.value === resolution);
    const config: Record<string, unknown> = {
      promptgen: { style },
      tts: { voice, rate },
      imagegen: { backend: imageBackend },
      llm: { provider: llm },
      video: {
        codec,
        crf: parseInt(quality, 10),
        resolution: resOption?.dims ?? [1080, 1920],
      },
    };

    // Add videogen config if AI video mode selected
    if (videoMode === "ai_video") {
      config.videogen = {
        backend: videogenBackend,
        duration: 5,
        aspect_ratio: resolution,
        use_image_as_first_frame: true,
      };
    }

    if (mode === "director") {
      if (!inspiration.trim()) {
        setError("请输入创意灵感");
        return;
      }
      createVideo.mutate(
        {
          inspiration: inspiration.trim(),
          target_duration: targetDuration,
          budget,
          config,
        },
        {
          onSuccess: (data) => {
            router.push(`/video/${data.task_id}`);
          },
          onError: (err) => {
            setError(err instanceof Error ? err.message : "提交失败");
          },
        }
      );
    } else {
      // Classic mode: need either text or file path
      const resolvedInput = inputFile.trim() || inputText.trim();
      if (!resolvedInput) {
        setError("请输入文本内容或文本文件路径");
        return;
      }
      createVideo.mutate(
        {
          input_file: resolvedInput,
          run_mode: runMode,
          budget_mode: budgetMode,
          quality_threshold: runMode === "agent" ? qualityThreshold : undefined,
          config,
        },
        {
          onSuccess: (data) => {
            router.push(`/video/${data.task_id}`);
          },
          onError: (err) => {
            setError(err instanceof Error ? err.message : "提交失败");
          },
        }
      );
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="新建视频"
        title="创建视频项目"
        description="选择创作模式，输入内容后提交到任务队列自动生成视频。"
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

      <div className="space-y-5 px-6 py-6 md:px-8">
        {/* Mode Selector */}
        <div className="grid gap-4 md:grid-cols-2">
          <button
            type="button"
            onClick={() => setMode("director")}
            className={`rounded-[22px] border-2 p-5 text-left transition ${
              mode === "director"
                ? "border-accent bg-accent/5"
                : "border-slate-200 bg-white hover:border-slate-300"
            }`}
          >
            <Sparkles
              className={`h-6 w-6 ${
                mode === "director" ? "text-accent" : "text-slate-400"
              }`}
            />
            <h3 className="mt-3 text-lg font-semibold text-ink">
              AI 导演模式
            </h3>
            <p className="mt-1 text-sm text-slate-600">
              输入一句创意灵感，AI 自动规划脚本、生成素材并合成视频。
            </p>
          </button>

          <button
            type="button"
            onClick={() => setMode("classic")}
            className={`rounded-[22px] border-2 p-5 text-left transition ${
              mode === "classic"
                ? "border-accent bg-accent/5"
                : "border-slate-200 bg-white hover:border-slate-300"
            }`}
          >
            <FileText
              className={`h-6 w-6 ${
                mode === "classic" ? "text-accent" : "text-slate-400"
              }`}
            />
            <h3 className="mt-3 text-lg font-semibold text-ink">经典模式</h3>
            <p className="mt-1 text-sm text-slate-600">
              提供一个文本文件，按照传统流水线分段、生图、配音、合成。
            </p>
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit}>
          {mode === "director" ? (
            <Panel title="AI 导演模式" description="输入创意灵感和参数">
              <div className="space-y-5">
                <div>
                  <label className="mb-2 block text-sm font-medium text-ink">
                    创意灵感
                  </label>
                  <textarea
                    value={inspiration}
                    onChange={(e) => setInspiration(e.target.value)}
                    placeholder="例如：一个孤独的宇航员在火星上发现了一朵花..."
                    rows={4}
                    className="w-full rounded-[16px] border border-slate-200 bg-white px-4 py-3 text-sm text-ink placeholder:text-slate-400 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                  />
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium text-ink">
                    目标时长：{targetDuration} 秒
                  </label>
                  <input
                    type="range"
                    min={30}
                    max={180}
                    step={10}
                    value={targetDuration}
                    onChange={(e) =>
                      setTargetDuration(parseInt(e.target.value, 10))
                    }
                    className="w-full accent-accent"
                  />
                  <div className="mt-1 flex justify-between text-xs text-slate-400">
                    <span>30 秒</span>
                    <span>180 秒</span>
                  </div>
                </div>

                <ButtonGroup
                  label="预算级别"
                  value={budget}
                  onChange={(v) => setBudget(v as "low" | "medium" | "high")}
                  options={[
                    { value: "low", label: "低", desc: "纯图片 + TTS" },
                    { value: "medium", label: "中", desc: "图片 + AI 视频片段" },
                    { value: "high", label: "高", desc: "全 AI 视频片段" },
                  ]}
                />
              </div>
            </Panel>
          ) : (
            <Panel title="经典模式" description="指定文本文件和运行配置">
              <div className="space-y-5">
                <div>
                  <label className="mb-2 block text-sm font-medium text-ink">
                    文本文件路径
                  </label>
                  <input
                    type="text"
                    value={inputFile}
                    onChange={(e) => setInputFile(e.target.value)}
                    placeholder="例如：input/novel.txt"
                    className="w-full rounded-[16px] border border-slate-200 bg-white px-4 py-3 text-sm text-ink placeholder:text-slate-400 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                  />
                  <p className="mt-1 text-xs text-slate-400">
                    输入服务器上的文件路径
                  </p>
                </div>

                <ButtonGroup
                  label="运行模式"
                  value={runMode}
                  onChange={(v) => setRunMode(v as "classic" | "agent")}
                  options={[
                    { value: "classic", label: "经典流水线", desc: "顺序执行各阶段" },
                    { value: "agent", label: "Agent 模式", desc: "多 Agent 协作决策" },
                  ]}
                />

                {/* Agent mode specific options */}
                {runMode === "agent" && (
                  <div className="space-y-4 rounded-[16px] border border-slate-100 bg-shell p-4">
                    <p className="text-xs font-medium uppercase tracking-wider text-slate-500">
                      Agent 模式选项
                    </p>
                    <div className="flex items-center gap-3">
                      <input
                        type="checkbox"
                        id="budget-mode"
                        checked={budgetMode}
                        onChange={(e) => setBudgetMode(e.target.checked)}
                        className="h-4 w-4 rounded border-slate-300 accent-accent"
                      />
                      <label
                        htmlFor="budget-mode"
                        className="text-sm text-ink"
                      >
                        省钱模式（减少 LLM 调用）
                      </label>
                    </div>
                    <div>
                      <label className="mb-2 block text-sm font-medium text-ink">
                        质量阈值：{qualityThreshold.toFixed(1)}
                      </label>
                      <input
                        type="range"
                        min={1}
                        max={10}
                        step={0.5}
                        value={qualityThreshold}
                        onChange={(e) =>
                          setQualityThreshold(parseFloat(e.target.value))
                        }
                        className="w-full accent-accent"
                      />
                      <div className="mt-1 flex justify-between text-xs text-slate-400">
                        <span>1.0（宽松）</span>
                        <span>10.0（严格）</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </Panel>
          )}

          {/* Advanced Settings Accordion */}
          <div className="mt-5">
            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="flex w-full items-center justify-between rounded-[22px] border border-slate-200 bg-white px-5 py-3 text-left transition hover:bg-shell"
            >
              <div className="flex items-center gap-2">
                <Settings2 className="h-4 w-4 text-slate-500" />
                <span className="text-sm font-medium text-ink">
                  高级设置
                </span>
                <span className="text-xs text-slate-400">
                  画风、配音、画质、分辨率、编码器、AI视频
                </span>
              </div>
              {showAdvanced ? (
                <ChevronUp className="h-4 w-4 text-slate-400" />
              ) : (
                <ChevronDown className="h-4 w-4 text-slate-400" />
              )}
            </button>

            {showAdvanced && (
              <div className="mt-3 space-y-5 rounded-[22px] border border-slate-200 bg-white p-5">
                {/* Row 1: Style + Voice + Rate */}
                <div className="grid gap-4 md:grid-cols-3">
                  <SelectField
                    label="画风"
                    value={style}
                    onChange={setStyle}
                    options={STYLE_OPTIONS}
                  />
                  <SelectField
                    label="配音"
                    value={voice}
                    onChange={setVoice}
                    options={VOICE_OPTIONS}
                  />
                  <SelectField
                    label="语速"
                    value={rate}
                    onChange={setRate}
                    options={RATE_OPTIONS}
                  />
                </div>

                {/* Row 2: Image Backend + LLM */}
                <div className="grid gap-4 md:grid-cols-2">
                  <SelectField
                    label="图片生成后端"
                    value={imageBackend}
                    onChange={setImageBackend}
                    options={IMAGE_BACKEND_OPTIONS}
                  />
                  <SelectField
                    label="LLM 服务"
                    value={llm}
                    onChange={setLlm}
                    options={LLM_OPTIONS}
                  />
                </div>

                {/* Row 3: Resolution + Quality + Codec */}
                <div className="grid gap-4 md:grid-cols-3">
                  <SelectField
                    label="分辨率"
                    value={resolution}
                    onChange={setResolution}
                    options={RESOLUTION_OPTIONS}
                  />
                  <SelectField
                    label="画质"
                    value={quality}
                    onChange={(v) => setQuality(v)}
                    options={QUALITY_OPTIONS}
                  />
                  <SelectField
                    label="编码器"
                    value={codec}
                    onChange={setCodec}
                    options={CODEC_OPTIONS}
                  />
                </div>

                {/* Row 4: Video Mode + AI Video Backend */}
                <div className="grid gap-4 md:grid-cols-2">
                  <SelectField
                    label="视频素材模式"
                    value={videoMode}
                    onChange={setVideoMode}
                    options={VIDEO_MODE_OPTIONS}
                  />
                  {videoMode === "ai_video" && (
                    <SelectField
                      label="AI 视频后端"
                      value={videogenBackend}
                      onChange={setVideogenBackend}
                      options={VIDEOGEN_BACKEND_OPTIONS}
                    />
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Error */}
          {(error || createVideo.isError) && (
            <div className="mt-4 rounded-[16px] bg-rose-50 px-4 py-3 text-sm text-rose-700">
              {error ||
                (createVideo.error instanceof Error
                  ? createVideo.error.message
                  : "提交失败")}
            </div>
          )}

          {/* Submit */}
          <div className="mt-5 flex justify-end">
            <button
              type="submit"
              disabled={submitting}
              className="inline-flex items-center gap-2 rounded-full bg-ink px-6 py-3 text-sm font-semibold text-white transition hover:bg-ink/90 disabled:opacity-50"
            >
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="h-4 w-4" />
              )}
              {submitting ? "提交中..." : "开始创建"}
            </button>
          </div>
        </form>
      </div>
    </>
  );
}

"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { PageHeader } from "@/components/layout/page-header";
import { Panel } from "@/components/ui/panel";
import { useCreateNovel, useCreateVideo, useCreatePPT } from "@/lib/hooks";
import { Loader2, BookOpenText, Clapperboard, FileStack } from "lucide-react";

const GENRES = [
  { value: "玄幻", label: "玄幻" },
  { value: "仙侠", label: "仙侠" },
  { value: "都市", label: "都市" },
  { value: "科幻", label: "科幻" },
  { value: "悬疑", label: "悬疑" },
  { value: "历史", label: "历史" },
  { value: "言情", label: "言情" },
  { value: "武侠", label: "武侠" },
  { value: "轻小说", label: "轻小说" },
];

const STYLES = [
  { value: "webnovel.shuangwen", label: "网文爽文" },
  { value: "wuxia.classical", label: "武侠古典" },
  { value: "scifi.hard", label: "硬科幻" },
  { value: "romance.sweet", label: "甜蜜言情" },
  { value: "suspense.dark", label: "暗黑悬疑" },
  { value: "literary.modern", label: "现代文学" },
  { value: "lightnovel", label: "轻小说" },
];

const TEMPLATES = [
  { value: "cyclic_upgrade", label: "循环升级（玄幻/系统流）" },
  { value: "adventure_exploration", label: "冒险探索（开拓/寻宝）" },
  { value: "romance_conflict", label: "言情冲突（情感/虐恋）" },
  { value: "mystery_solving", label: "谜团解密（推理/悬疑）" },
  { value: "power_politics", label: "权谋争斗（宫斗/商战）" },
  { value: "multi_thread", label: "多线交织（群像/宫斗）" },
  { value: "classic_four_act", label: "经典四幕（武侠/文学）" },
];

const AUDIENCES = [
  { value: "通用", label: "通用" },
  { value: "男频", label: "男频" },
  { value: "女频", label: "女频" },
  { value: "青少年", label: "青少年" },
];

const inputCls =
  "w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-ink outline-none transition focus:border-accent focus:ring-1 focus:ring-accent/30";
const selectCls =
  "w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-ink outline-none transition focus:border-accent focus:ring-1 focus:ring-accent/30";
const labelCls = "block text-xs font-semibold uppercase tracking-[0.15em] text-slate-500 mb-1.5";

export default function CreatePage() {
  return (
    <>
      <PageHeader
        eyebrow="新建"
        title="开始创作"
        description="选择创作类型，填写参数，一键启动后台任务。"
      />
      <div className="grid gap-5 px-6 py-6 md:px-8 xl:grid-cols-3">
        <NovelCreateForm />
        <VideoCreateForm />
        <PPTCreateForm />
      </div>
    </>
  );
}

function NovelCreateForm() {
  const router = useRouter();
  const createMut = useCreateNovel();
  const [genre, setGenre] = useState("玄幻");
  const [theme, setTheme] = useState("");
  const [targetWords, setTargetWords] = useState(100000);
  const [style, setStyle] = useState("webnovel.shuangwen");
  const [template, setTemplate] = useState("cyclic_upgrade");
  const [customIdeas, setCustomIdeas] = useState("");
  const [authorName, setAuthorName] = useState("");
  const [audience, setAudience] = useState("通用");

  const handleSubmit = async () => {
    try {
      const result = await createMut.mutateAsync({
        genre,
        theme,
        target_words: targetWords,
        style,
        template,
        custom_ideas: customIdeas || undefined,
        author_name: authorName || undefined,
        target_audience: audience,
      });
      if (result?.task_id) {
        router.push(`/tasks`);
      }
    } catch {
      // error is available via createMut.error
    }
  };

  return (
    <Panel title="小说" description="设定题材、风格和模板，创建 AI 长篇小说项目。">
      <div className="space-y-4">
        <div className="flex items-center gap-2 text-accent">
          <BookOpenText className="h-5 w-5" />
          <span className="text-sm font-semibold">小说创作</span>
        </div>

        <div>
          <label className={labelCls}>题材</label>
          <select
            className={selectCls}
            value={genre}
            onChange={(e) => setGenre(e.target.value)}
          >
            {GENRES.map((g) => (
              <option key={g.value} value={g.value}>
                {g.label}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className={labelCls}>主题</label>
          <input
            className={inputCls}
            placeholder="例如：少年修炼逆天改命"
            value={theme}
            onChange={(e) => setTheme(e.target.value)}
          />
        </div>

        <div>
          <label className={labelCls}>
            目标字数：{(targetWords / 10000).toFixed(0)} 万字
          </label>
          <input
            type="range"
            min={50000}
            max={500000}
            step={10000}
            value={targetWords}
            onChange={(e) => setTargetWords(Number(e.target.value))}
            className="w-full accent-accent"
          />
          <div className="mt-1 flex justify-between text-xs text-slate-400">
            <span>5 万</span>
            <span>50 万</span>
          </div>
        </div>

        <div>
          <label className={labelCls}>风格</label>
          <select
            className={selectCls}
            value={style}
            onChange={(e) => setStyle(e.target.value)}
          >
            {STYLES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className={labelCls}>大纲模板</label>
          <select
            className={selectCls}
            value={template}
            onChange={(e) => setTemplate(e.target.value)}
          >
            {TEMPLATES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className={labelCls}>自定义想法（可选）</label>
          <textarea
            className={inputCls + " min-h-[60px] resize-y"}
            placeholder="补充设定、角色或剧情方向..."
            value={customIdeas}
            onChange={(e) => setCustomIdeas(e.target.value)}
            rows={2}
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>作者名（可选）</label>
            <input
              className={inputCls}
              placeholder="笔名"
              value={authorName}
              onChange={(e) => setAuthorName(e.target.value)}
            />
          </div>
          <div>
            <label className={labelCls}>目标读者</label>
            <select
              className={selectCls}
              value={audience}
              onChange={(e) => setAudience(e.target.value)}
            >
              {AUDIENCES.map((a) => (
                <option key={a.value} value={a.value}>
                  {a.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        {createMut.isError && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700">
            {(createMut.error as Error)?.message ?? "创建失败"}
          </div>
        )}

        <button
          onClick={handleSubmit}
          disabled={!theme.trim() || createMut.isPending}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-accent px-4 py-3 text-sm font-semibold text-white transition hover:bg-accent/90 disabled:opacity-50"
        >
          {createMut.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : null}
          创建小说项目
        </button>
      </div>
    </Panel>
  );
}

function VideoCreateForm() {
  const router = useRouter();
  const createMut = useCreateVideo();
  const [inspiration, setInspiration] = useState("");
  const [mode, setMode] = useState("director");
  const [budget, setBudget] = useState(false);

  const handleSubmit = async () => {
    try {
      await createMut.mutateAsync({
        inspiration,
        mode,
        budget_mode: budget,
      });
      router.push("/tasks");
    } catch {
      // error available via createMut.error
    }
  };

  return (
    <Panel
      title="视频"
      description="输入灵感创意，AI 导演自动规划并生成短视频。"
    >
      <div className="space-y-4">
        <div className="flex items-center gap-2 text-accent">
          <Clapperboard className="h-5 w-5" />
          <span className="text-sm font-semibold">视频制作</span>
        </div>

        <div>
          <label className={labelCls}>创意灵感</label>
          <textarea
            className={inputCls + " min-h-[80px] resize-y"}
            placeholder="例如：一个时间旅者回到唐朝..."
            value={inspiration}
            onChange={(e) => setInspiration(e.target.value)}
            rows={3}
          />
        </div>

        <div>
          <label className={labelCls}>制作模式</label>
          <select
            className={selectCls}
            value={mode}
            onChange={(e) => setMode(e.target.value)}
          >
            <option value="director">AI 导演模式（智能）</option>
            <option value="classic">经典模式（快速）</option>
          </select>
        </div>

        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input
            type="checkbox"
            checked={budget}
            onChange={(e) => setBudget(e.target.checked)}
            className="accent-accent"
          />
          省钱模式
        </label>

        {createMut.isError && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700">
            {(createMut.error as Error)?.message ?? "创建失败"}
          </div>
        )}

        <button
          onClick={handleSubmit}
          disabled={!inspiration.trim() || createMut.isPending}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-accent px-4 py-3 text-sm font-semibold text-white transition hover:bg-accent/90 disabled:opacity-50"
        >
          {createMut.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : null}
          开始制作
        </button>
      </div>
    </Panel>
  );
}

function PPTCreateForm() {
  const router = useRouter();
  const createMut = useCreatePPT();
  const [topic, setTopic] = useState("");
  const [theme, setTheme] = useState("professional");
  const [pages, setPages] = useState(10);

  const handleSubmit = async () => {
    try {
      await createMut.mutateAsync({
        topic,
        theme,
        target_pages: pages,
      });
      router.push("/tasks");
    } catch {
      // error available via createMut.error
    }
  };

  return (
    <Panel title="PPT" description="输入主题或文档内容，AI 自动生成演示文稿。">
      <div className="space-y-4">
        <div className="flex items-center gap-2 text-accent">
          <FileStack className="h-5 w-5" />
          <span className="text-sm font-semibold">PPT 生成</span>
        </div>

        <div>
          <label className={labelCls}>主题 / 内容</label>
          <textarea
            className={inputCls + " min-h-[80px] resize-y"}
            placeholder="例如：AI 技术在教育领域的应用..."
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            rows={3}
          />
        </div>

        <div>
          <label className={labelCls}>设计主题</label>
          <select
            className={selectCls}
            value={theme}
            onChange={(e) => setTheme(e.target.value)}
          >
            <option value="professional">商务专业</option>
            <option value="creative">创意设计</option>
            <option value="minimal">极简</option>
            <option value="dark">暗色</option>
          </select>
        </div>

        <div>
          <label className={labelCls}>目标页数：{pages} 页</label>
          <input
            type="range"
            min={5}
            max={30}
            step={1}
            value={pages}
            onChange={(e) => setPages(Number(e.target.value))}
            className="w-full accent-accent"
          />
          <div className="mt-1 flex justify-between text-xs text-slate-400">
            <span>5 页</span>
            <span>30 页</span>
          </div>
        </div>

        {createMut.isError && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700">
            {(createMut.error as Error)?.message ?? "创建失败"}
          </div>
        )}

        <button
          onClick={handleSubmit}
          disabled={!topic.trim() || createMut.isPending}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-accent px-4 py-3 text-sm font-semibold text-white transition hover:bg-accent/90 disabled:opacity-50"
        >
          {createMut.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : null}
          生成 PPT
        </button>
      </div>
    </Panel>
  );
}

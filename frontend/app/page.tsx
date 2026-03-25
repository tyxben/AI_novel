import Link from "next/link";
import {
  ArrowRight,
  BookOpenText,
  Clapperboard,
  FileStack,
  ListTodo,
} from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { MetricGrid } from "@/components/feature/metric-grid";
import { Panel } from "@/components/ui/panel";

const workspaces = [
  {
    href: "/novel",
    title: "小说工作台",
    description:
      "大纲、世界观、章节生成、编辑和反馈统一在一个工作区中管理。",
    icon: BookOpenText,
  },
  {
    href: "/video",
    title: "视频工作台",
    description:
      "AI 导演和短视频制作合并为一条创作流，灵感到视频一站完成。",
    icon: Clapperboard,
  },
  {
    href: "/ppt",
    title: "PPT 工作台",
    description:
      "从主题到大纲、HTML 预览和导出，清晰的 Deck 生成流程。",
    icon: FileStack,
  },
  {
    href: "/tasks",
    title: "任务中心",
    description:
      "所有后台任务的统一监控、进度查看和管理操作。",
    icon: ListTodo,
  },
];

export default function HomePage() {
  return (
    <>
      <PageHeader
        eyebrow="创作台"
        title="AI 创作工坊"
        description="小说、视频、PPT 多 Agent 驱动的一站式中文创作平台。实时任务监控，项目统一管理。"
        action={
          <Link
            href="/create"
            className="inline-flex items-center gap-2 rounded-full bg-ink px-5 py-3 text-sm font-semibold text-white"
          >
            开始创作
            <ArrowRight className="h-4 w-4" />
          </Link>
        }
      />

      <div className="space-y-6 px-6 py-6 md:px-8">
        <MetricGrid />

        <Panel
          title="核心工作区"
          description="按创作类型组织，每个工作区集合输入、运行状态和结果。"
        >
          <div className="grid gap-4 md:grid-cols-2">
            {workspaces.map(({ href, title, description, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                className="group rounded-[24px] border border-slate-200 bg-white p-5 transition hover:border-accent/40 hover:bg-shell"
              >
                <Icon className="h-6 w-6 text-accent" />
                <h3 className="mt-4 text-xl font-semibold text-ink">
                  {title}
                </h3>
                <p className="mt-2 text-sm leading-6 text-slate-600">
                  {description}
                </p>
                <div className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-accent">
                  进入工作区
                  <ArrowRight className="h-4 w-4 transition group-hover:translate-x-1" />
                </div>
              </Link>
            ))}
          </div>
        </Panel>
      </div>
    </>
  );
}

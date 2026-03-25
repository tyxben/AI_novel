import type { MetricCard, ProjectSummary, TaskSummary } from "@/lib/types";

export const metrics: MetricCard[] = [
  {
    label: "活跃项目",
    value: "12",
    detail: "小说、视频和 PPT 统一收口到一个前端外壳。"
  },
  {
    label: "运行中任务",
    value: "4",
    detail: "长任务集中放进任务中心，不再散落在各个页面里。"
  },
  {
    label: "前端目标",
    value: "工作台 UI",
    detail: "用清晰的工作区替代层层嵌套的 Gradio 标签页。"
  }
];

export const projects: ProjectSummary[] = [
  {
    id: "novel_7f3a",
    name: "霜港回响",
    kind: "novel",
    status: "running",
    updatedAt: "2 分钟前",
    progress: 62,
    summary: "章节生成、设定编辑和反馈重写都放在同一个小说工作区里。"
  },
  {
    id: "video_a918",
    name: "时间旅客短片",
    kind: "video",
    status: "paused",
    updatedAt: "18 分钟前",
    progress: 38,
    summary: "导演方案、分段、素材策略和最终合成统一在视频工作台里。"
  },
  {
    id: "ppt_31d0",
    name: "AI 创作工坊 Deck",
    kind: "ppt",
    status: "completed",
    updatedAt: "1 小时前",
    progress: 100,
    summary: "大纲、HTML 预览和导出质检统一在 PPT 工作台中查看。"
  }
];

export const tasks: TaskSummary[] = [
  {
    id: "task_001",
    title: "生成第 21-25 章",
    kind: "novel",
    status: "running",
    stage: "质量审查",
    updatedAt: "刚刚"
  },
  {
    id: "task_002",
    title: "渲染 PPT 预览",
    kind: "ppt",
    status: "completed",
    stage: "HTML 导出",
    updatedAt: "12 分钟前"
  },
  {
    id: "task_003",
    title: "合成短视频",
    kind: "video",
    status: "failed",
    stage: "FFmpeg 输出",
    updatedAt: "27 分钟前"
  }
];

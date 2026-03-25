export type WorkspaceKind = "novel" | "video" | "ppt";

export type ProjectSummary = {
  id: string;
  name: string;
  kind: WorkspaceKind;
  status: "idle" | "running" | "paused" | "completed";
  updatedAt: string;
  progress: number;
  summary: string;
};

export type TaskSummary = {
  id: string;
  title: string;
  kind: WorkspaceKind;
  status: "queued" | "running" | "failed" | "completed" | "pending" | "cancelled";
  stage: string;
  updatedAt: string;
};

export type MetricCard = {
  label: string;
  value: string;
  detail: string;
};

export type NovelProject = {
  id: string;
  title: string;
  genre: string;
  theme: string;
  status: "idle" | "creating" | "generating" | "paused" | "completed";
  style_name: string;
  target_words: number;
  current_chapter: number;
  total_chapters: number;
  progress: number;
  created_at: string;
  updated_at: string;
  outline: any;
  characters: CharacterSummary[];
  world_setting: any;
  chapters: ChapterSummary[];
};

export type CharacterSummary = {
  name: string;
  role: string;
  character_id?: string;
  description?: string;
};

export type ChapterSummary = {
  chapter_number: number;
  title: string;
  word_count?: number;
  status?: string;
  published?: boolean;
};

export type NovelCreateParams = {
  genre: string;
  theme: string;
  target_words: number;
  style: string;
  template: string;
  custom_ideas?: string;
  author_name?: string;
  target_audience?: string;
};

export type TaskDetail = {
  task_id: string;
  task_type: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  progress: number;
  progress_msg: string;
  params: Record<string, any>;
  result?: string;
  error?: string;
  created_at: string;
  started_at?: string;
  finished_at?: string;
};

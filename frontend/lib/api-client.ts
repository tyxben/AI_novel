import type {
  NovelCreateParams,
  NovelProject,
  ProjectSummary,
  TaskDetail,
} from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

function getStoredApiKeys(): string {
  if (typeof window === "undefined") return "";
  try {
    const raw = localStorage.getItem("ai-novel-settings");
    if (!raw) return "";
    const settings = JSON.parse(raw);
    const keys: Record<string, string> = {};
    const envKeys = [
      "GEMINI_API_KEY",
      "DEEPSEEK_API_KEY",
      "OPENAI_API_KEY",
      "SILICONFLOW_API_KEY",
      "DASHSCOPE_API_KEY",
    ];
    for (const envKey of envKeys) {
      const val = settings?.[envKey];
      if (val) keys[envKey] = val;
    }
    return Object.keys(keys).length > 0 ? JSON.stringify(keys) : "";
  } catch {
    return "";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const apiKeys = getStoredApiKeys();
  const extraHeaders: Record<string, string> = {};
  if (apiKeys) extraHeaders["x-api-keys"] = apiKeys;

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...extraHeaders,
        ...(init?.headers ?? {}),
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      0,
      "无法连接到后端服务，请确认服务器已启动。"
    );
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // ignore parse errors
    }
    throw new ApiError(response.status, `API ${response.status}: ${detail}`);
  }

  // 204 No Content
  if (response.status === 204) {
    return undefined as unknown as T;
  }

  return response.json() as Promise<T>;
}

export const api = {
  // Health
  health: () => request<{ status: string }>("/api/health"),

  // Projects (unified view)
  getProjects: () => request<ProjectSummary[]>("/api/projects"),

  // Tasks
  getTasks: (limit?: number) =>
    request<TaskDetail[]>(`/api/tasks?limit=${limit ?? 50}`),
  getTask: (id: string) => request<TaskDetail>(`/api/tasks/${id}`),
  cancelTask: (id: string) =>
    request<any>(`/api/tasks/${id}/cancel`, { method: "POST" }),
  deleteTask: (id: string) =>
    request<void>(`/api/tasks/${id}`, { method: "DELETE" }),

  // Novels
  listNovels: () => request<ProjectSummary[]>("/api/novels"),
  getNovel: (id: string) => request<NovelProject>(`/api/novels/${id}`),
  createNovel: (params: NovelCreateParams) =>
    request<{ task_id: string }>("/api/novels", {
      method: "POST",
      body: JSON.stringify(params),
    }),
  generateChapters: (id: string, params?: any) =>
    request<{ task_id: string }>(`/api/novels/${id}/generate`, {
      method: "POST",
      body: JSON.stringify(params ?? {}),
    }),
  polishChapters: (id: string, params?: any) =>
    request<{ task_id: string }>(`/api/novels/${id}/polish`, {
      method: "POST",
      body: JSON.stringify(params ?? {}),
    }),
  analyzeFeedback: (id: string, params: any) =>
    request<{ task_id: string }>(`/api/novels/${id}/feedback/analyze`, {
      method: "POST",
      body: JSON.stringify(params),
    }),
  applyFeedback: (id: string, params: any) =>
    request<{ task_id: string }>(`/api/novels/${id}/feedback/apply`, {
      method: "POST",
      body: JSON.stringify(params),
    }),
  editNovel: (id: string, params: any) =>
    request<any>(`/api/novels/${id}/edit`, {
      method: "POST",
      body: JSON.stringify(params),
    }),
  getChapter: (id: string, chNum: number) =>
    request<{ text: string }>(`/api/novels/${id}/chapters/${chNum}`),
  saveChapter: (id: string, chNum: number, text: string) =>
    request<{ char_count: number; old_char_count: number }>(
      `/api/novels/${id}/chapters/${chNum}`,
      { method: "PUT", body: JSON.stringify({ text }) }
    ),
  proofreadChapter: (id: string, chNum: number) =>
    request<{ issues: any[] }>(`/api/novels/${id}/chapters/${chNum}/proofread`, {
      method: "POST",
    }),
  applyFixes: (id: string, chNum: number, text: string, issues: any[], selectedIndices: number[]) =>
    request<{ text: string; failures: string[] }>(
      `/api/novels/${id}/chapters/${chNum}/apply-fixes`,
      {
        method: "POST",
        body: JSON.stringify({ text, issues, selected_indices: selectedIndices }),
      }
    ),
  getNovelSettings: (id: string) => request<any>(`/api/novels/${id}/settings`),
  saveNovelSettings: (id: string, settings: any) =>
    request<any>(`/api/novels/${id}/settings`, {
      method: "PUT",
      body: JSON.stringify(settings),
    }),
  analyzeSettingImpact: (id: string, params: any) =>
    request<any>(`/api/novels/${id}/settings/analyze-impact`, {
      method: "POST",
      body: JSON.stringify(params),
    }),
  rewriteAffected: (id: string, impact: any) =>
    request<any>(`/api/novels/${id}/settings/rewrite-affected`, {
      method: "POST",
      body: JSON.stringify(impact),
    }),
  getPolishDiff: (id: string, chNum: number) =>
    request<any>(`/api/novels/${id}/chapters/${chNum}/polish-diff`),
  resizeNovel: (id: string, newTotal: number) =>
    request<any>(`/api/novels/${id}/resize`, {
      method: "POST",
      body: JSON.stringify({ new_total: newTotal }),
    }),
  publishChapters: (id: string, chapters: number[], published: boolean) =>
    request<{ published_chapters: number[] }>(
      `/api/novels/${id}/chapters/publish`,
      {
        method: "POST",
        body: JSON.stringify({ chapters, published }),
      }
    ),
  agentChat: (id: string, message: string, contextChapters?: number[], history?: Array<{role: string; content: string}>) =>
    request<{ task_id: string }>(`/api/novels/${id}/agent-chat`, {
      method: "POST",
      body: JSON.stringify({ message, context_chapters: contextChapters, history }),
    }),
  exportNovel: (id: string) => request<any>(`/api/novels/${id}/export`),
  deleteNovel: (id: string) =>
    request<void>(`/api/novels/${id}`, { method: "DELETE" }),

  // Videos
  listVideos: () => request<ProjectSummary[]>("/api/videos"),
  getVideo: (id: string) => request<any>(`/api/videos/${id}`),
  createVideo: (params: any) =>
    request<{ task_id: string }>("/api/videos", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  // PPT
  listPPT: () => request<ProjectSummary[]>("/api/ppt"),
  getPPT: (id: string) => request<any>(`/api/ppt/${id}`),
  createPPT: (params: any) =>
    request<{ task_id: string }>("/api/ppt", {
      method: "POST",
      body: JSON.stringify(params),
    }),
  continuePPT: (id: string, params: any) =>
    request<{ task_id: string }>(`/api/ppt/${id}/generate`, {
      method: "POST",
      body: JSON.stringify(params),
    }),
  renderPPT: (id: string, params?: any) =>
    request<{ task_id: string }>(`/api/ppt/${id}/render`, {
      method: "POST",
      body: JSON.stringify(params ?? {}),
    }),
  exportPPT: (id: string) =>
    request<{ task_id: string }>(`/api/ppt/${id}/export`, {
      method: "POST",
    }),

  // Settings
  getSettings: () => request<any>("/api/settings"),
  updateSettings: (params: any) =>
    request<any>("/api/settings", {
      method: "PUT",
      body: JSON.stringify(params),
    }),
  testKey: (params: any) =>
    request<any>("/api/settings/test-key", {
      method: "POST",
      body: JSON.stringify(params),
    }),
};

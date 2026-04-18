import type {
  NovelCreateParams,
  NovelProject,
  ProjectSummary,
  TaskDetail,
} from "./types";

export interface Conversation {
  session_id: string;
  novel_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ToolStep {
  step?: number;
  thinking?: string;
  tool: string;
  args?: any;
  result?: any;
}

export interface ChatMessageData {
  message_id: string;
  session_id: string;
  role: "user" | "agent";
  content: string;
  steps?: ToolStep[];
  model?: string;
  created_at: string;
}

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
  planChapters: (id: string, params?: any) =>
    request<{ task_id: string }>(`/api/novels/${id}/plan-chapters`, {
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
  updateChapterMetadata: (id: string, chapterNum: number, data: { title?: string }) =>
    request<{ success: boolean }>(`/api/novels/${id}/chapters/${chapterNum}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
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
  agentChat: (id: string, message: string, contextChapters?: number[], history?: Array<{role: string; content: string}>, sessionId?: string) =>
    request<{ task_id: string; session_id?: string }>(`/api/novels/${id}/agent-chat`, {
      method: "POST",
      body: JSON.stringify({ message, context_chapters: contextChapters, history, session_id: sessionId }),
    }),
  exportNovel: (id: string) => request<any>(`/api/novels/${id}/export`),
  deleteNovel: (id: string) =>
    request<void>(`/api/novels/${id}`, { method: "DELETE" }),

  // Conversations
  getConversations: (novelId: string) =>
    request<Conversation[]>(`/api/novels/${novelId}/conversations`),
  createConversation: (novelId: string, title?: string) =>
    request<Conversation>(`/api/novels/${novelId}/conversations`, {
      method: "POST",
      body: JSON.stringify({ title: title || "新对话" }),
    }),
  getConversationMessages: (novelId: string, sessionId: string) =>
    request<ChatMessageData[]>(`/api/novels/${novelId}/conversations/${sessionId}/messages`),
  deleteConversation: (novelId: string, sessionId: string) =>
    request<void>(`/api/novels/${novelId}/conversations/${sessionId}`, {
      method: "DELETE",
    }),

  // NOTE: rebuildNarrative removed with NarrativeRebuildService
  // (architecture-rework-2026 Phase 0).

  // Narrative Control
  getNarrativeOverview: (id: string) => request<any>(`/api/novels/${id}/narrative/overview`),
  getNarrativeDebts: (id: string, status?: string) => {
    const q = status && status !== "all" ? `?status=${status}` : "";
    return request<any>(`/api/novels/${id}/narrative/debts${q}`);
  },
  addNarrativeDebt: (id: string, data: { description: string; source_chapter: number; debt_type: string }) =>
    request<any>(`/api/novels/${id}/narrative/debts`, { method: "POST", body: JSON.stringify(data) }),
  fulfillDebt: (id: string, debtId: string) =>
    request<any>(`/api/novels/${id}/narrative/debts/${debtId}/fulfill`, { method: "POST" }),
  getStoryArcs: (id: string) => request<any>(`/api/novels/${id}/narrative/arcs`),
  getChapterBrief: (id: string, chNum: number) => request<any>(`/api/novels/${id}/narrative/briefs/${chNum}`),
  getKnowledgeGraph: (id: string) => request<any>(`/api/novels/${id}/narrative/graph`),
  getVolumesSummary: (id: string) => request<any[]>(`/api/novels/${id}/narrative/volumes`),
  getSettlementBrief: (id: string, chapter: number) =>
    request<any>(`/api/novels/${id}/narrative/settlement?chapter=${chapter}`),

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

  // Prompts
  listBlocks: (params?: { agent?: string; block_type?: string; active_only?: boolean }) => {
    const qs = new URLSearchParams();
    if (params?.agent) qs.set("agent", params.agent);
    if (params?.block_type) qs.set("block_type", params.block_type);
    if (params?.active_only !== undefined) qs.set("active_only", String(params.active_only));
    const q = qs.toString();
    return request<any[]>(`/api/prompts/blocks${q ? "?" + q : ""}`);
  },
  getBlock: (baseId: string) => request<any>(`/api/prompts/blocks/${baseId}`),
  getBlockVersions: (baseId: string) => request<any[]>(`/api/prompts/blocks/${baseId}/versions`),
  createBlock: (data: { base_id: string; block_type: string; content: string; agent?: string; genre?: string; scene_type?: string }) =>
    request<any>("/api/prompts/blocks", { method: "POST", body: JSON.stringify(data) }),
  updateBlock: (baseId: string, content: string) =>
    request<any>(`/api/prompts/blocks/${baseId}`, { method: "PUT", body: JSON.stringify({ content }) }),
  rollbackBlock: (baseId: string, version: number) =>
    request<any>(`/api/prompts/blocks/${baseId}/rollback`, { method: "POST", body: JSON.stringify({ version }) }),
  listTemplates: (agentName?: string) => {
    const q = agentName ? `?agent_name=${agentName}` : "";
    return request<any[]>(`/api/prompts/templates${q}`);
  },
  getTemplate: (templateId: string) => request<any>(`/api/prompts/templates/${templateId}`),
  createTemplate: (data: { template_id: string; agent_name: string; block_refs: string[]; scenario?: string; genre?: string }) =>
    request<any>("/api/prompts/templates", { method: "POST", body: JSON.stringify(data) }),
  buildPrompt: (data: { agent_name: string; scenario?: string; genre?: string; context?: any }) =>
    request<{ prompt: string; length: number }>("/api/prompts/build", { method: "POST", body: JSON.stringify(data) }),
  getBlockStats: (baseId: string) => request<any>(`/api/prompts/stats/${baseId}`),
  seedPrompts: () => request<{ blocks_count: number; templates_count: number }>("/api/prompts/seed", { method: "POST" }),
};

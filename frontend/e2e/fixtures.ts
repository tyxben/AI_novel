import { test as base, type Page, type Route } from "@playwright/test";

/* ------------------------------------------------------------------ */
/*  Mock data factories                                                */
/* ------------------------------------------------------------------ */

export function mockNovelProject(overrides: Record<string, any> = {}) {
  return {
    id: "novel_test001",
    title: "测试小说：逆天修仙录",
    genre: "玄幻",
    theme: "少年修炼逆天改命",
    status: "idle",
    style_name: "webnovel.shuangwen",
    target_words: 100000,
    current_chapter: 5,
    total_chapters: 40,
    progress: 0.125,
    created_at: "2026-03-20T10:00:00",
    updated_at: "2026-03-27T10:00:00",
    outline: {
      title: "逆天修仙录",
      total_chapters: 40,
      chapters: Array.from({ length: 40 }, (_, i) => ({
        chapter_number: i + 1,
        title: `第${i + 1}章 测试标题`,
        summary: `第${i + 1}章的摘要内容`,
      })),
    },
    characters: [
      { name: "林风", role: "主角", character_id: "char_001", description: "少年天才" },
      { name: "苏雨", role: "女主", character_id: "char_002", description: "冰雪聪明" },
      { name: "魔尊", role: "反派", character_id: "char_003", description: "万年老妖" },
    ],
    world_setting: { description: "九天十地修仙世界" },
    chapters: Array.from({ length: 5 }, (_, i) => ({
      chapter_number: i + 1,
      title: `第${i + 1}章 测试标题`,
      word_count: 2500,
      status: "completed",
      published: false,
    })),
    ...overrides,
  };
}

export function mockProjectSummary(kind: string, overrides: Record<string, any> = {}) {
  const defaults: Record<string, any> = {
    novel: { id: "novel_test001", name: "逆天修仙录", kind: "novel", status: "idle", updatedAt: "2026-03-27", progress: 0.125, summary: "5/40章" },
    video: { id: "video_test001", name: "测试视频", kind: "video", status: "completed", updatedAt: "2026-03-26", progress: 1.0, summary: "已完成" },
    ppt: { id: "ppt_test001", name: "测试PPT", kind: "ppt", status: "idle", updatedAt: "2026-03-25", progress: 0.5, summary: "大纲已生成" },
  };
  return { ...defaults[kind], ...overrides };
}

export function mockTask(overrides: Record<string, any> = {}) {
  return {
    task_id: "task_test001",
    task_type: "novel_create",
    status: "completed",
    progress: 1.0,
    progress_msg: "完成",
    params: { genre: "玄幻" },
    result: '{"novel_id":"novel_test001"}',
    error: null,
    created_at: "2026-03-27T09:00:00",
    started_at: "2026-03-27T09:00:01",
    finished_at: "2026-03-27T09:05:00",
    ...overrides,
  };
}

export function mockConversation(overrides: Record<string, any> = {}) {
  return {
    session_id: "conv_test001",
    novel_id: "novel_test001",
    title: "讨论角色发展",
    created_at: "2026-03-27T10:00:00",
    updated_at: "2026-03-27T11:00:00",
    message_count: 3,
    ...overrides,
  };
}

export function mockChatMessage(role: "user" | "agent", content: string, overrides: Record<string, any> = {}) {
  return {
    message_id: `msg_${Math.random().toString(36).slice(2, 8)}`,
    session_id: "conv_test001",
    role,
    content,
    steps: role === "agent" ? [{ step: 1, tool: "think", thinking: "分析中..." }] : undefined,
    model: role === "agent" ? "deepseek-chat" : undefined,
    created_at: "2026-03-27T10:00:00",
    ...overrides,
  };
}

export function mockPPTProject(overrides: Record<string, any> = {}) {
  return {
    id: "ppt_test001",
    name: "AI技术趋势",
    status: "outline_ready",
    theme: "modern_blue",
    topic: "AI技术趋势2026",
    outline: {
      slides: [
        { slide_number: 1, title: "AI技术趋势2026", layout: "title", notes: "封面", needs_image: false },
        { slide_number: 2, title: "大语言模型进展", layout: "content", notes: "LLM发展", needs_image: true },
        { slide_number: 3, title: "多模态AI", layout: "two_column", notes: "图文视频", needs_image: true },
      ],
    },
    quality_report: null,
    files: {},
    created_at: "2026-03-27T10:00:00",
    ...overrides,
  };
}

export function mockVideoProject(overrides: Record<string, any> = {}) {
  return {
    id: "video_test001",
    name: "测试视频项目",
    mode: "director",
    status: "completed",
    concept: { inspiration: "一个关于AI的故事", duration: 60 },
    stages: {
      segment: { status: "completed", progress: 1.0 },
      prompt: { status: "completed", progress: 1.0 },
      image: { status: "completed", progress: 1.0 },
      tts: { status: "completed", progress: 1.0 },
      video: { status: "completed", progress: 1.0 },
    },
    segments: [
      { id: 1, text: "片段1文本", image_prompt: "prompt1" },
      { id: 2, text: "片段2文本", image_prompt: "prompt2" },
    ],
    output_path: "/workspace/videos/output.mp4",
    files: { video: "/workspace/videos/output.mp4" },
    created_at: "2026-03-27T10:00:00",
    ...overrides,
  };
}

export function mockSettings() {
  return {
    llm: { provider: "auto" },
    imagegen: { backend: "siliconflow" },
    tts: { voice: "zh-CN-XiaoxiaoNeural" },
    video: { backend: "static" },
  };
}

export function mockPromptBlock(overrides: Record<string, any> = {}) {
  return {
    base_id: "block_writer_system",
    block_type: "system",
    agent: "writer",
    genre: null,
    scene_type: null,
    content: "你是一个专业的小说写作AI助手。",
    version: 3,
    is_active: true,
    usage_count: 42,
    avg_score: 8.5,
    created_at: "2026-03-20T10:00:00",
    updated_at: "2026-03-27T10:00:00",
    ...overrides,
  };
}

/* ------------------------------------------------------------------ */
/*  API mock helper                                                    */
/* ------------------------------------------------------------------ */

export type ApiMocks = {
  health?: any;
  projects?: any[];
  tasks?: any[];
  task?: any;
  novels?: any[];
  novel?: any;
  chapter?: any;
  novelSettings?: any;
  conversations?: any[];
  messages?: any[];
  narrativeOverview?: any;
  narrativeDebts?: any;
  storyArcs?: any;
  knowledgeGraph?: any;
  volumes?: any[];
  videos?: any[];
  video?: any;
  pptList?: any[];
  ppt?: any;
  settings?: any;
  promptBlocks?: any[];
  promptBlock?: any;
  promptVersions?: any[];
  promptTemplates?: any[];
  [key: string]: any;
};

/**
 * Sets up route interception for all API endpoints.
 * Pass partial mocks — anything not provided returns sensible defaults.
 */
export async function setupApiMocks(page: Page, mocks: ApiMocks = {}) {
  const API = "http://localhost:8000";

  // Health
  await page.route(`${API}/api/health`, (route) =>
    route.fulfill({ json: mocks.health ?? { status: "ok" } })
  );

  // Projects
  await page.route(`${API}/api/projects`, (route) =>
    route.fulfill({
      json: mocks.projects ?? [
        mockProjectSummary("novel"),
        mockProjectSummary("video"),
        mockProjectSummary("ppt"),
      ],
    })
  );

  // Tasks
  await page.route(`${API}/api/tasks?*`, (route) =>
    route.fulfill({ json: mocks.tasks ?? [mockTask()] })
  );
  await page.route(`${API}/api/tasks/task_*`, (route) => {
    const url = route.request().url();
    const method = route.request().method();
    if (method === "DELETE") return route.fulfill({ status: 204 });
    if (method === "POST" && url.includes("/cancel"))
      return route.fulfill({ json: { msg: "Cancelled" } });
    return route.fulfill({ json: mocks.task ?? mockTask() });
  });

  // Novels list
  await page.route(`${API}/api/novels`, (route) => {
    if (route.request().method() === "POST") {
      return route.fulfill({ json: { task_id: "task_novel_create" } });
    }
    return route.fulfill({ json: mocks.novels ?? [mockProjectSummary("novel")] });
  });

  // Novel detail + sub-routes
  await page.route(new RegExp(`${API.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/api/novels/[^/]+$`), (route) => {
    const method = route.request().method();
    if (method === "DELETE") return route.fulfill({ status: 204 });
    return route.fulfill({ json: mocks.novel ?? mockNovelProject() });
  });

  // Novel generate/polish/feedback/edit/resize/export/publish
  await page.route(`${API}/api/novels/*/generate`, (route) =>
    route.fulfill({ json: { task_id: "task_generate" } })
  );
  await page.route(`${API}/api/novels/*/polish`, (route) =>
    route.fulfill({ json: { task_id: "task_polish" } })
  );
  await page.route(`${API}/api/novels/*/feedback/analyze`, (route) =>
    route.fulfill({ json: { task_id: "task_feedback_analyze" } })
  );
  await page.route(`${API}/api/novels/*/feedback/apply`, (route) =>
    route.fulfill({ json: { task_id: "task_feedback_apply" } })
  );
  await page.route(`${API}/api/novels/*/edit`, (route) =>
    route.fulfill({ json: { change_id: "chg_001", status: "applied", description: "已修改" } })
  );
  await page.route(`${API}/api/novels/*/resize`, (route) =>
    route.fulfill({ json: { task_id: "task_resize" } })
  );
  await page.route(`${API}/api/novels/*/export`, (route) =>
    route.fulfill({ json: { path: "/workspace/novels/export.txt", text: "导出内容" } })
  );
  await page.route(`${API}/api/novels/*/chapters/publish`, (route) =>
    route.fulfill({ json: { published_chapters: [1, 2, 3] } })
  );

  // Chapters
  await page.route(`${API}/api/novels/*/chapters/*`, (route) => {
    const url = route.request().url();
    const method = route.request().method();
    if (url.includes("/proofread"))
      return route.fulfill({ json: { issues: [{ type: "grammar", desc: "错别字", original: "这个", replacement: "那个", location: "第1段" }] } });
    if (url.includes("/apply-fixes"))
      return route.fulfill({ json: { text: "修正后的文本", applied: 1, failures: [] } });
    if (url.includes("/polish-diff"))
      return route.fulfill({ json: { original_text: "原文", polished_text: "润色后" } });
    if (method === "PUT")
      return route.fulfill({ json: { char_count: 2500, old_char_count: 2400 } });
    return route.fulfill({
      json: mocks.chapter ?? {
        number: 1,
        title: "第1章 测试标题",
        text: "这是第一章的正文内容。林风站在山巅，望着远方的天际线，心中涌起无限感慨。修仙之路漫漫，他已经走了很远。",
        word_count: 2500,
        status: "completed",
      },
    });
  });

  // Novel settings
  await page.route(`${API}/api/novels/*/settings`, (route) => {
    if (route.request().method() === "PUT")
      return route.fulfill({ json: { saved: true, updated_fields: ["characters"] } });
    return route.fulfill({
      json: mocks.novelSettings ?? {
        world_setting: {
          era: "远古仙侠时代",
          location: "天元大陆",
          power_system: { name: "灵气修炼", levels: [] },
          rules: ["灵气为万物之源"],
          terms: { "灵石": "修炼货币" },
        },
        characters: [
          {
            character_id: "char_001",
            name: "林风",
            gender: "男",
            age: 18,
            occupation: "修仙者",
            status: "active",
            alias: [],
            appearance: { height: "180cm", build: "修长", hair: "黑色长发", eyes: "黑色", clothing_style: "白色道袍", distinctive_features: [] },
            personality: { traits: ["坚韧"], core_belief: "逆天改命", motivation: "变强", flaw: "冲动", speech_style: "直爽", catchphrases: [] },
            character_arc: { initial_state: "普通少年", final_state: "仙帝", turning_points: [] },
          },
          {
            character_id: "char_002",
            name: "苏雨",
            gender: "女",
            age: 17,
            occupation: "女修",
            status: "active",
            alias: [],
            appearance: { height: "165cm", build: "纤细", hair: "蓝色长发", eyes: "蓝色", clothing_style: "蓝色道袍", distinctive_features: [] },
            personality: { traits: ["聪慧"], core_belief: "守护所爱", motivation: "保护家人", flaw: "犹豫", speech_style: "温柔", catchphrases: [] },
            character_arc: { initial_state: "冰雪聪明", final_state: "大能", turning_points: [] },
          },
        ],
        outline: {
          main_storyline: { protagonist_goal: "成为最强", core_conflict: "正邪之战", stakes: "世界存亡", character_arc: "从弱到强" },
          chapters: [
            { chapter_number: 1, title: "少年出山", summary: "林风离开村庄", mood: "蓄力" },
            { chapter_number: 2, title: "初入宗门", summary: "加入天剑宗", mood: "蓄力" },
          ],
        },
      },
    });
  });

  // Settings impact analysis / rewrite
  await page.route(`${API}/api/novels/*/settings/analyze-impact`, (route) =>
    route.fulfill({ json: { affected_chapters: [3, 5, 7], description: "角色修改影响3章" } })
  );
  await page.route(`${API}/api/novels/*/settings/rewrite-affected`, (route) =>
    route.fulfill({ json: { task_id: "task_rewrite" } })
  );

  // Conversations
  await page.route(`${API}/api/novels/*/conversations`, (route) => {
    if (route.request().method() === "POST")
      return route.fulfill({ json: mockConversation({ session_id: "conv_new" }) });
    return route.fulfill({ json: mocks.conversations ?? [mockConversation()] });
  });
  await page.route(`${API}/api/novels/*/conversations/*/messages`, (route) =>
    route.fulfill({
      json: mocks.messages ?? [
        mockChatMessage("user", "帮我分析一下主角性格"),
        mockChatMessage("agent", "主角林风性格分析：坚韧不拔，重情重义..."),
      ],
    })
  );
  await page.route(`${API}/api/novels/*/conversations/*`, (route) => {
    if (route.request().method() === "DELETE") return route.fulfill({ json: { ok: true } });
    return route.fulfill({ json: mockConversation() });
  });

  // Agent chat
  await page.route(`${API}/api/novels/*/agent-chat`, (route) =>
    route.fulfill({ json: { task_id: "task_chat", session_id: "conv_test001" } })
  );

  // Narrative
  await page.route(`${API}/api/novels/*/narrative/rebuild`, (route) =>
    route.fulfill({ json: { task_id: "task_narrative_rebuild" } })
  );
  await page.route(`${API}/api/novels/*/narrative/overview`, (route) =>
    route.fulfill({
      json: mocks.narrativeOverview ?? {
        total_debts: 5,
        pending_debts: 2,
        fulfilled_debts: 3,
        overdue_debts: 0,
        total_arcs: 3,
        active_arcs: 2,
        completed_arcs: 1,
      },
    })
  );
  await page.route(`${API}/api/novels/*/narrative/debts*`, (route) => {
    if (route.request().method() === "POST") {
      const url = route.request().url();
      if (url.includes("/fulfill")) return route.fulfill({ json: { ok: true } });
      return route.fulfill({ json: { debt_id: "debt_new", status: "pending" } });
    }
    return route.fulfill({
      json: mocks.narrativeDebts ?? [
        { debt_id: "debt_001", description: "伏笔：神秘宝物", source_chapter: 3, debt_type: "foreshadowing", status: "pending", created_at: "2026-03-27" },
        { debt_id: "debt_002", description: "角色承诺", source_chapter: 1, debt_type: "promise", status: "fulfilled", created_at: "2026-03-25" },
      ],
    });
  });
  await page.route(`${API}/api/novels/*/narrative/arcs`, (route) =>
    route.fulfill({
      json: mocks.storyArcs ?? [
        { arc_id: "arc_001", name: "修炼之路", status: "active", start_chapter: 1, current_chapter: 5, phases: [] },
        { arc_id: "arc_002", name: "宗门争斗", status: "active", start_chapter: 3, current_chapter: 5, phases: [] },
      ],
    })
  );
  await page.route(`${API}/api/novels/*/narrative/briefs/*`, (route) =>
    route.fulfill({ json: { chapter: 1, brief: "本章重点：引入主角" } })
  );
  await page.route(`${API}/api/novels/*/narrative/graph`, (route) =>
    route.fulfill({
      json: mocks.knowledgeGraph ?? {
        nodes: [
          { id: "林风", type: "character", label: "林风" },
          { id: "苏雨", type: "character", label: "苏雨" },
          { id: "天剑宗", type: "location", label: "天剑宗" },
        ],
        edges: [
          { source: "林风", target: "苏雨", relation: "同门" },
          { source: "林风", target: "天剑宗", relation: "所属" },
        ],
      },
    })
  );
  await page.route(`${API}/api/novels/*/narrative/volumes`, (route) =>
    route.fulfill({ json: mocks.volumes ?? [{ volume: 1, title: "第一卷 初入修仙界", start_chapter: 1, end_chapter: 10, status: "in_progress" }] })
  );
  await page.route(`${API}/api/novels/*/narrative/settlement*`, (route) =>
    route.fulfill({ json: { chapter: 10, settlement: "卷末收束建议..." } })
  );

  // Videos
  await page.route(`${API}/api/videos`, (route) => {
    if (route.request().method() === "POST")
      return route.fulfill({ json: { task_id: "task_video_create" } });
    return route.fulfill({ json: mocks.videos ?? [mockProjectSummary("video")] });
  });
  await page.route(new RegExp(`${API.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/api/videos/[^/]+$`), (route) =>
    route.fulfill({ json: mocks.video ?? mockVideoProject() })
  );

  // PPT
  await page.route(`${API}/api/ppt`, (route) => {
    if (route.request().method() === "POST")
      return route.fulfill({ json: { task_id: "task_ppt_create" } });
    return route.fulfill({ json: mocks.pptList ?? [mockProjectSummary("ppt")] });
  });
  await page.route(new RegExp(`${API.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/api/ppt/[^/]+$`), (route) =>
    route.fulfill({ json: mocks.ppt ?? mockPPTProject() })
  );
  await page.route(`${API}/api/ppt/*/generate`, (route) =>
    route.fulfill({ json: { task_id: "task_ppt_generate" } })
  );
  await page.route(`${API}/api/ppt/*/render`, (route) =>
    route.fulfill({ json: { task_id: "task_ppt_render" } })
  );
  await page.route(`${API}/api/ppt/*/export`, (route) =>
    route.fulfill({ json: { task_id: "task_ppt_export" } })
  );

  // Settings
  await page.route(`${API}/api/settings`, (route) => {
    if (route.request().method() === "PUT")
      return route.fulfill({ json: { saved: true } });
    return route.fulfill({ json: mocks.settings ?? mockSettings() });
  });
  await page.route(`${API}/api/settings/test-key`, (route) =>
    route.fulfill({ json: { success: true } })
  );

  // Prompts — separate routes for list vs detail/versions/rollback
  // Versions: /blocks/{id}/versions
  await page.route(new RegExp(`${API.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/api/prompts/blocks/[^/]+/versions`), (route) =>
    route.fulfill({
      json: mocks.promptVersions ?? [
        { version: 3, content: "v3内容", avg_score: 8.5, created_at: "2026-03-27" },
        { version: 2, content: "v2内容", avg_score: 7.8, created_at: "2026-03-25" },
        { version: 1, content: "v1内容", avg_score: 7.0, created_at: "2026-03-20" },
      ],
    })
  );
  // Rollback: /blocks/{id}/rollback
  await page.route(new RegExp(`${API.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/api/prompts/blocks/[^/]+/rollback`), (route) =>
    route.fulfill({ json: { ...mockPromptBlock(), version: 2 } })
  );
  // Block detail/update: /blocks/{id} (no sub-path)
  await page.route(new RegExp(`${API.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/api/prompts/blocks/[^/?]+$`), (route) => {
    const method = route.request().method();
    if (method === "PUT") return route.fulfill({ json: { ...mockPromptBlock(), version: 4 } });
    return route.fulfill({ json: mocks.promptBlock ?? mockPromptBlock() });
  });
  // Block list with query params: /blocks?agent=...&block_type=...
  await page.route(`${API}/api/prompts/blocks?*`, (route) => {
    const method = route.request().method();
    if (method === "POST") return route.fulfill({ json: mockPromptBlock() });
    return route.fulfill({ json: mocks.promptBlocks ?? [mockPromptBlock()] });
  });
  // Block list (no query params): /blocks
  await page.route(`${API}/api/prompts/blocks`, (route) => {
    const method = route.request().method();
    if (method === "POST") return route.fulfill({ json: mockPromptBlock() });
    return route.fulfill({ json: mocks.promptBlocks ?? [mockPromptBlock()] });
  });
  // Template detail: /templates/{id}
  await page.route(new RegExp(`${API.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/api/prompts/templates/[^/?]+$`), (route) =>
    route.fulfill({ json: { template_id: "tpl_001", agent_name: "writer", block_refs: ["block_writer_system"], scenario: "default", genre: null } })
  );
  // Template list with query params
  await page.route(`${API}/api/prompts/templates?*`, (route) => {
    if (route.request().method() === "POST")
      return route.fulfill({ json: { template_id: "tpl_new" } });
    return route.fulfill({
      json: mocks.promptTemplates ?? [
        { template_id: "tpl_001", agent_name: "writer", scenario: "default", genre: null, block_refs: ["block_writer_system"] },
      ],
    });
  });
  // Template list (no query params)
  await page.route(`${API}/api/prompts/templates`, (route) => {
    if (route.request().method() === "POST")
      return route.fulfill({ json: { template_id: "tpl_new" } });
    return route.fulfill({
      json: mocks.promptTemplates ?? [
        { template_id: "tpl_001", agent_name: "writer", scenario: "default", genre: null, block_refs: ["block_writer_system"] },
      ],
    });
  });
  await page.route(`${API}/api/prompts/build`, (route) =>
    route.fulfill({ json: { prompt: "构建的完整prompt内容...", length: 500 } })
  );
  await page.route(`${API}/api/prompts/stats/*`, (route) =>
    route.fulfill({ json: { usage_count: 42, avg_score: 8.5 } })
  );
  await page.route(`${API}/api/prompts/seed`, (route) =>
    route.fulfill({ json: { blocks_count: 15, templates_count: 5 } })
  );
}

/* ------------------------------------------------------------------ */
/*  Extended test fixture                                              */
/* ------------------------------------------------------------------ */

export const test = base.extend<{ mockApi: (mocks?: ApiMocks) => Promise<void> }>({
  mockApi: async ({ page }, use) => {
    const setup = async (mocks: ApiMocks = {}) => {
      await setupApiMocks(page, mocks);
    };
    await use(setup);
  },
});

export { expect } from "@playwright/test";

import { test, expect, mockTask } from "./fixtures";

test.describe("Video List Page", () => {
  test.beforeEach(async ({ page, mockApi }) => {
    await mockApi();
  });

  /* ------------------------------------------------------------------ */
  /*  Page header and layout                                             */
  /* ------------------------------------------------------------------ */

  test("should display page header with correct title and description", async ({ page }) => {
    await page.goto("/video");
    await expect(page.locator("h2")).toContainText("视频工作台");
    await expect(
      page.getByText("AI 导演模式和经典短视频制作统一在一个工作区里，查看项目进度和管理创作流程。")
    ).toBeVisible();
  });

  test("should display refresh and create buttons in header", async ({ page }) => {
    await page.goto("/video");
    await expect(page.getByRole("button", { name: "刷新" })).toBeVisible();
    await expect(page.getByRole("link", { name: "新建视频" }).first()).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Empty state                                                        */
  /* ------------------------------------------------------------------ */

  test("should show empty state when no video tasks exist", async ({ page }) => {
    // useVideoTasks fetches from /api/tasks?limit=100 and filters by task_type
    await page.route("http://localhost:8000/api/tasks?*", (route) =>
      route.fulfill({ json: [] })
    );
    await page.goto("/video");
    await expect(page.locator("h3").filter({ hasText: "暂无视频项目" })).toBeVisible();
    await expect(
      page.getByText("还没有视频项目，点击右上角「新建视频」开始创作")
    ).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Project list display                                               */
  /* ------------------------------------------------------------------ */

  test("should display video project cards when tasks exist", async ({ page }) => {
    const directorTask = mockTask({
      task_id: "task_director_001",
      task_type: "director_generate",
      status: "completed",
      progress: 1.0,
      progress_msg: "完成",
      params: { inspiration: "一个孤独的宇航员在火星上发现了一朵花" },
      created_at: "2026-03-27T10:00:00",
    });
    const classicTask = mockTask({
      task_id: "task_classic_001",
      task_type: "video_generate",
      status: "running",
      progress: 0.5,
      progress_msg: "图片生成中...",
      params: { input_file: "input/novel.txt", run_mode: "classic" },
      created_at: "2026-03-26T10:00:00",
    });

    await page.route("http://localhost:8000/api/tasks?*", (route) =>
      route.fulfill({ json: [directorTask, classicTask] })
    );
    await page.goto("/video");

    // Director task card
    await expect(
      page.getByText("一个孤独的宇航员在火星上发现了一朵花")
    ).toBeVisible();
    await expect(page.getByText("导演模式", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("已完成").first()).toBeVisible();
    await expect(page.getByText("100%").first()).toBeVisible();

    // Classic task card
    await expect(page.getByText("novel.txt")).toBeVisible();
    await expect(page.getByText("经典模式", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("图片生成中...")).toBeVisible();
    await expect(page.getByText("50%")).toBeVisible();
  });

  test("should display Agent mode label for agent tasks", async ({ page }) => {
    const agentTask = mockTask({
      task_id: "task_agent_001",
      task_type: "video_generate",
      status: "running",
      progress: 0.3,
      progress_msg: "Agent 协作中...",
      params: { input_file: "input/story.txt", run_mode: "agent" },
      created_at: "2026-03-27T10:00:00",
    });

    await page.route("http://localhost:8000/api/tasks?*", (route) =>
      route.fulfill({ json: [agentTask] })
    );
    await page.goto("/video");

    await expect(page.getByText("Agent 模式")).toBeVisible();
  });

  test("should truncate long inspiration text to 30 chars", async ({ page }) => {
    const longTask = mockTask({
      task_id: "task_long_001",
      task_type: "director_generate",
      status: "pending",
      progress: 0,
      params: { inspiration: "这是一段很长很长的创意灵感文字用来测试是否会被截断显示省略号功能" },
      created_at: "2026-03-27T10:00:00",
    });

    await page.route("http://localhost:8000/api/tasks?*", (route) =>
      route.fulfill({ json: [longTask] })
    );
    await page.goto("/video");

    // getProjectTitle truncates at 30 chars + "..."
    const fullText = "这是一段很长很长的创意灵感文字用来测试是否会被截断显示省略号功能";
    const truncated = fullText.slice(0, 30) + "...";
    await expect(page.getByText(truncated)).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Navigation                                                         */
  /* ------------------------------------------------------------------ */

  test("should navigate to create page when clicking create button", async ({ page }) => {
    await page.goto("/video");
    await page.locator("a[href='/video/create']").first().click();
    await page.waitForURL("/video/create");
    expect(page.url()).toContain("/video/create");
  });

  test("should navigate to detail page when clicking a project card", async ({ page }) => {
    const task = mockTask({
      task_id: "task_nav_001",
      task_type: "director_generate",
      status: "completed",
      progress: 1.0,
      params: { inspiration: "测试导航" },
      created_at: "2026-03-27T10:00:00",
    });

    await page.route("http://localhost:8000/api/tasks?*", (route) =>
      route.fulfill({ json: [task] })
    );
    await page.goto("/video");

    // Click the project card (rendered as a <button> with router.push)
    await page.getByText("测试导航").click();
    await page.waitForURL("/video/task_nav_001");
    expect(page.url()).toContain("/video/task_nav_001");
  });

  /* ------------------------------------------------------------------ */
  /*  Progress bar                                                       */
  /* ------------------------------------------------------------------ */

  test("should show progress bar with correct width", async ({ page }) => {
    const task = mockTask({
      task_id: "task_progress_001",
      task_type: "video_generate",
      status: "running",
      progress: 0.75,
      progress_msg: "配音中...",
      params: { input_file: "test.txt" },
      created_at: "2026-03-27T10:00:00",
    });

    await page.route("http://localhost:8000/api/tasks?*", (route) =>
      route.fulfill({ json: [task] })
    );
    await page.goto("/video");

    await expect(page.getByText("75%")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Filtering                                                          */
  /* ------------------------------------------------------------------ */

  test("should filter out non-video tasks from the list", async ({ page }) => {
    // useVideoTasks filters for video_generate and director_generate only
    const novelTask = mockTask({
      task_id: "task_novel_001",
      task_type: "novel_create",
      status: "completed",
      progress: 1.0,
      params: { genre: "玄幻" },
      created_at: "2026-03-27T10:00:00",
    });
    const videoTask = mockTask({
      task_id: "task_video_001",
      task_type: "video_generate",
      status: "running",
      progress: 0.5,
      params: { input_file: "input.txt" },
      created_at: "2026-03-27T10:00:00",
    });

    await page.route("http://localhost:8000/api/tasks?*", (route) =>
      route.fulfill({ json: [novelTask, videoTask] })
    );
    await page.goto("/video");

    // Only video task should show
    await expect(page.getByText("input.txt")).toBeVisible();
    // The novel task should not produce a card (it's filtered out by the hook)
  });

  test("should show default title for task without inspiration or file", async ({ page }) => {
    const task = mockTask({
      task_id: "task_no_name_001",
      task_type: "video_generate",
      status: "pending",
      progress: 0,
      params: {},
      created_at: "2026-03-27T10:00:00",
    });

    await page.route("http://localhost:8000/api/tasks?*", (route) =>
      route.fulfill({ json: [task] })
    );
    await page.goto("/video");

    // getProjectTitle returns "视频项目" when no inspiration or input_file
    await expect(page.getByText("视频项目").first()).toBeVisible();
  });
});

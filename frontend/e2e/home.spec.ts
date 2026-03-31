import { test, expect } from "./fixtures";

test.describe("Home Page", () => {
  test.beforeEach(async ({ page, mockApi }) => {
    await mockApi();
  });

  // ─── Page Header ───────────────────────────────────────────────────

  test("should display the page header with eyebrow, title, and description", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByText("创作台", { exact: true }).first()).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "AI 创作工坊" })
    ).toBeVisible();
    await expect(
      page.getByText(
        "小说、视频、PPT 多 Agent 驱动的一站式中文创作平台。实时任务监控，项目统一管理。"
      )
    ).toBeVisible();
  });

  test("should display the '开始创作' call-to-action link pointing to /create", async ({ page }) => {
    await page.goto("/");

    const ctaLink = page.getByRole("link", { name: /开始创作/ });
    await expect(ctaLink).toBeVisible();
    await expect(ctaLink).toHaveAttribute("href", "/create");
  });

  // ─── Metric Grid ──────────────────────────────────────────────────

  test("should display three metric cards after data loads", async ({ page }) => {
    await page.goto("/");

    // Wait for metrics to load (the mock returns 3 projects, 1 completed task, 0 running)
    await expect(page.getByText("活跃项目")).toBeVisible();
    await expect(page.getByText("运行中任务")).toBeVisible();
    await expect(page.getByText("已完成任务")).toBeVisible();

    // Check metric values from mock data
    // projects mock returns 3 items (novel, video, ppt)
    await expect(page.getByText("3").first()).toBeVisible();
    // tasks mock returns [mockTask()] with status "completed", so running=0
    await expect(page.getByText("0").first()).toBeVisible();
    // 1 completed task
    await expect(page.getByText("1").first()).toBeVisible();

    // Detail text
    await expect(page.getByText("小说、视频和 PPT 项目总数。")).toBeVisible();
    await expect(page.getByText("当前正在执行或排队的后台任务。")).toBeVisible();
    await expect(page.getByText("历史完成的任务总计。")).toBeVisible();
  });

  // ─── Workspace Cards ──────────────────────────────────────────────

  test("should display all four workspace cards", async ({ page }) => {
    await page.goto("/");

    // Section title
    await expect(
      page.getByRole("heading", { name: "核心工作区" })
    ).toBeVisible();
    await expect(
      page.getByText("按创作类型组织，每个工作区集合输入、运行状态和结果。")
    ).toBeVisible();

    // All four workspace titles
    await expect(page.getByRole("heading", { name: "小说工作台" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "视频工作台" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "PPT 工作台" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "任务中心" })).toBeVisible();
  });

  test("should display workspace descriptions", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.getByText("大纲、世界观、章节生成、编辑和反馈统一在一个工作区中管理。")
    ).toBeVisible();
    await expect(
      page.getByText(
        "AI 导演和短视频制作合并为一条创作流，灵感到视频一站完成。"
      )
    ).toBeVisible();
    await expect(
      page.getByText(
        "从主题到大纲、HTML 预览和导出，清晰的 Deck 生成流程。"
      )
    ).toBeVisible();
    await expect(
      page.getByText("所有后台任务的统一监控、进度查看和管理操作。")
    ).toBeVisible();
  });

  test("should show '进入工作区' text on every workspace card", async ({ page }) => {
    await page.goto("/");

    const enterLinks = page.getByText("进入工作区");
    await expect(enterLinks).toHaveCount(4);
  });

  test("workspace cards should link to correct routes", async ({ page }) => {
    await page.goto("/");

    // Locate each workspace card link by its heading text
    const novelCard = page.getByRole("link").filter({ hasText: "小说工作台" });
    await expect(novelCard).toHaveAttribute("href", "/novel");

    const videoCard = page.getByRole("link").filter({ hasText: "视频工作台" });
    await expect(videoCard).toHaveAttribute("href", "/video");

    const pptCard = page.getByRole("link").filter({ hasText: "PPT 工作台" });
    await expect(pptCard).toHaveAttribute("href", "/ppt");

    const tasksCard = page.getByRole("link").filter({ hasText: "任务中心" });
    await expect(tasksCard).toHaveAttribute("href", "/tasks");
  });

  // ─── Navigation from Home ─────────────────────────────────────────

  test("clicking '开始创作' navigates to /create", async ({ page }) => {
    await page.goto("/");

    await page.getByRole("link", { name: /开始创作/ }).click();
    await expect(page).toHaveURL("/create");
  });

  test("clicking a workspace card navigates to its route", async ({ page }) => {
    await page.goto("/");

    await page.getByRole("link").filter({ hasText: "小说工作台" }).click();
    await expect(page).toHaveURL("/novel");
  });

  // ─── Error State ──────────────────────────────────────────────────

  test("should display error banner when API is unreachable", async ({ page, mockApi }) => {
    // Override the mocks to make the projects/tasks endpoints fail
    await page.route("http://localhost:8000/api/projects", (route) =>
      route.abort("connectionrefused")
    );
    await page.route("http://localhost:8000/api/tasks?*", (route) =>
      route.abort("connectionrefused")
    );

    await page.goto("/");

    await expect(
      page.getByText("无法连接后端服务。请确认服务器已启动。")
    ).toBeVisible();
  });
});

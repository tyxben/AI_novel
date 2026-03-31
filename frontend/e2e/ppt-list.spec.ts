import { test, expect, mockProjectSummary } from "./fixtures";

test.describe("PPT List Page", () => {
  test.beforeEach(async ({ page, mockApi }) => {
    await mockApi();
  });

  /* ------------------------------------------------------------------ */
  /*  Page header and layout                                             */
  /* ------------------------------------------------------------------ */

  test("should display page header with correct title and description", async ({ page }) => {
    await page.goto("/ppt");
    await expect(page.locator("h2")).toContainText("PPT 工作台");
    await expect(
      page.getByText("管理 PPT 项目，从主题或文档生成幻灯片大纲、预览和导出。")
    ).toBeVisible();
  });

  test("should display refresh and create buttons", async ({ page }) => {
    await page.goto("/ppt");
    await expect(page.getByRole("button", { name: "刷新" })).toBeVisible();
    await expect(page.getByRole("link", { name: "新建 PPT" }).first()).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Empty state                                                        */
  /* ------------------------------------------------------------------ */

  test("should show empty state when no PPT projects exist", async ({ page }) => {
    // Override the /api/ppt GET route to return empty array
    await page.route("http://localhost:8000/api/ppt", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({ json: [] });
      }
      return route.fulfill({ json: { task_id: "task_ppt_create" } });
    });
    await page.goto("/ppt");

    // Panel title "暂无 PPT 项目"
    await expect(page.locator("h3").filter({ hasText: "暂无 PPT 项目" })).toBeVisible();
    await expect(
      page.getByText("还没有 PPT 项目，点击右上角「新建 PPT」开始创作")
    ).toBeVisible();
    // Create link inside empty state
    const emptyCreateLink = page.locator("a[href='/ppt/create']").last();
    await expect(emptyCreateLink).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Project list display                                               */
  /* ------------------------------------------------------------------ */

  test("should display PPT projects when they exist", async ({ page }) => {
    const projects = [
      mockProjectSummary("ppt", {
        id: "ppt_001",
        name: "AI技术趋势报告",
        status: "completed",
        progress: 1.0,
        summary: "15页幻灯片",
        updatedAt: "2026-03-27",
      }),
      mockProjectSummary("ppt", {
        id: "ppt_002",
        name: "产品发布会",
        status: "idle",
        progress: 0.3,
        summary: "大纲已生成",
        updatedAt: "2026-03-26",
      }),
    ];

    await page.route("http://localhost:8000/api/ppt", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({ json: projects });
      }
      return route.fulfill({ json: { task_id: "task_ppt_create" } });
    });
    await page.goto("/ppt");

    // Project names
    await expect(page.getByText("AI技术趋势报告")).toBeVisible();
    await expect(page.getByText("产品发布会")).toBeVisible();

    // Status badges: "已完成" for completed, "空闲" for idle
    await expect(page.getByText("已完成").first()).toBeVisible();
    await expect(page.getByText("空闲").first()).toBeVisible();

    // Progress
    await expect(page.getByText("100%").first()).toBeVisible();
    await expect(page.getByText("30%")).toBeVisible();

    // Summaries
    await expect(page.getByText("15页幻灯片")).toBeVisible();
    await expect(page.getByText("大纲已生成").first()).toBeVisible();
  });

  test("should display progress bar with correct percentage", async ({ page }) => {
    const projects = [
      mockProjectSummary("ppt", {
        id: "ppt_progress",
        name: "测试进度",
        status: "running",
        progress: 0.65,
        summary: "生成中",
        updatedAt: "2026-03-27",
      }),
    ];

    await page.route("http://localhost:8000/api/ppt", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({ json: projects });
      }
      return route.fulfill({ json: { task_id: "task_ppt_create" } });
    });
    await page.goto("/ppt");

    await expect(page.getByText("65%")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Navigation                                                         */
  /* ------------------------------------------------------------------ */

  test("should navigate to create page when clicking create button", async ({ page }) => {
    await page.goto("/ppt");
    await page.locator("a[href='/ppt/create']").first().click();
    await page.waitForURL("/ppt/create");
    expect(page.url()).toContain("/ppt/create");
  });

  test("should navigate to detail page when clicking a project card", async ({ page }) => {
    const projects = [
      mockProjectSummary("ppt", {
        id: "ppt_nav001",
        name: "导航测试PPT",
        status: "completed",
        progress: 1.0,
        summary: "10页",
        updatedAt: "2026-03-27",
      }),
    ];

    await page.route("http://localhost:8000/api/ppt", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({ json: projects });
      }
      return route.fulfill({ json: { task_id: "task_ppt_create" } });
    });
    await page.goto("/ppt");

    // Click the project card (rendered as a <button> with router.push)
    await page.getByText("导航测试PPT").click();
    await page.waitForURL("/ppt/ppt_nav001");
    expect(page.url()).toContain("/ppt/ppt_nav001");
  });

  /* ------------------------------------------------------------------ */
  /*  Error state                                                        */
  /* ------------------------------------------------------------------ */

  test("should show error state when API fails", async ({ page }) => {
    await page.route("http://localhost:8000/api/ppt", (route) =>
      route.fulfill({ status: 500, json: { detail: "Internal server error" } })
    );
    await page.goto("/ppt");

    await expect(page.locator("h3").filter({ hasText: "连接失败" })).toBeVisible();
    await expect(page.getByText("无法连接到后端服务")).toBeVisible();
  });
});

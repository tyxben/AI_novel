import { test, expect, mockTask } from "./fixtures";

test.describe("Projects Page", () => {
  test.beforeEach(async ({ page, mockApi }) => {
    await mockApi();
  });

  /* ------------------------------------------------------------------ */
  /*  Page header & structure                                            */
  /* ------------------------------------------------------------------ */

  test("should display page header with title and description", async ({ page }) => {
    await page.goto("/projects");
    await expect(page.locator("h2")).toContainText("项目中心");
    await expect(
      page.getByText("统一管理所有小说、视频和 PPT 项目，快速查看状态和进度。")
    ).toBeVisible();
  });

  test("should display refresh button in header", async ({ page }) => {
    await page.goto("/projects");
    await expect(page.getByRole("button", { name: "刷新" })).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Stats cards                                                        */
  /* ------------------------------------------------------------------ */

  test("should display stats cards", async ({ page }) => {
    await page.goto("/projects");
    // Default mock has 1 task (novel_create), total = 1, novel = 1
    await expect(page.getByText("全部项目")).toBeVisible();
    // Stats section shows "小说", "视频", "PPT" labels
    await expect(page.getByText("小说").first()).toBeVisible();
    await expect(page.getByText("视频").first()).toBeVisible();
    await expect(page.getByText("PPT").first()).toBeVisible();
  });

  test("should show correct stats for multiple tasks", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({ task_id: "t1", task_type: "novel_create", status: "completed" }),
        mockTask({ task_id: "t2", task_type: "novel_generate", status: "running" }),
        mockTask({ task_id: "t3", task_type: "video_generate", status: "completed" }),
        mockTask({ task_id: "t4", task_type: "ppt_generate", status: "completed" }),
        mockTask({ task_id: "t5", task_type: "ppt_export", status: "failed" }),
      ],
    });
    await page.goto("/projects");

    // Total: 5 projects - verify via the "全部项目" stat card
    // The stat card has the count as a <p> with text-2xl and a label underneath
    const totalCard = page.locator("[class*='text-center']").filter({ hasText: "全部项目" });
    await expect(totalCard.locator("p").first()).toHaveText("5");
  });

  /* ------------------------------------------------------------------ */
  /*  Filter tabs                                                        */
  /* ------------------------------------------------------------------ */

  test("should display kind filter buttons", async ({ page }) => {
    await page.goto("/projects");
    // Filter buttons: "全部", "小说", "视频", "PPT" are rounded-full buttons
    await expect(page.locator("button.rounded-full").filter({ hasText: "全部" })).toBeVisible();
  });

  test("should filter projects by kind", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({ task_id: "t1", task_type: "novel_create", status: "completed", params: { genre: "玄幻", theme: "修仙" } }),
        mockTask({ task_id: "t2", task_type: "video_generate", status: "completed", params: { inspiration: "AI短片" } }),
        mockTask({ task_id: "t3", task_type: "ppt_generate", status: "completed", params: { topic: "AI趋势" } }),
      ],
    });
    await page.goto("/projects");

    // All 3 projects visible
    await expect(page.getByText("玄幻 - 修仙")).toBeVisible();
    await expect(page.getByText("AI短片")).toBeVisible();
    await expect(page.getByText("AI趋势")).toBeVisible();

    // Click "小说" filter
    const novelFilterBtn = page.locator("button.rounded-full").filter({ hasText: "小说" });
    await novelFilterBtn.click();

    await expect(page.getByText("玄幻 - 修仙")).toBeVisible();
    await expect(page.getByText("AI短片")).not.toBeVisible();
    await expect(page.getByText("AI趋势")).not.toBeVisible();

    // Click "视频" filter
    const videoFilterBtn = page.locator("button.rounded-full").filter({ hasText: "视频" });
    await videoFilterBtn.click();

    await expect(page.getByText("玄幻 - 修仙")).not.toBeVisible();
    await expect(page.getByText("AI短片")).toBeVisible();
    await expect(page.getByText("AI趋势")).not.toBeVisible();

    // Click "PPT" filter
    const pptFilterBtn = page.locator("button.rounded-full").filter({ hasText: "PPT" });
    await pptFilterBtn.click();

    await expect(page.getByText("玄幻 - 修仙")).not.toBeVisible();
    await expect(page.getByText("AI短片")).not.toBeVisible();
    await expect(page.getByText("AI趋势")).toBeVisible();

    // Click "全部" to reset
    const allFilterBtn = page.locator("button.rounded-full").filter({ hasText: "全部" });
    await allFilterBtn.click();

    await expect(page.getByText("玄幻 - 修仙")).toBeVisible();
    await expect(page.getByText("AI短片")).toBeVisible();
    await expect(page.getByText("AI趋势")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Search                                                             */
  /* ------------------------------------------------------------------ */

  test("should display search input", async ({ page }) => {
    await page.goto("/projects");
    await expect(page.getByPlaceholder("搜索项目...")).toBeVisible();
  });

  test("should filter projects by search query", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({ task_id: "t1", task_type: "novel_create", status: "completed", params: { genre: "玄幻", theme: "修仙大陆" } }),
        mockTask({ task_id: "t2", task_type: "video_generate", status: "completed", params: { inspiration: "科幻太空" } }),
        mockTask({ task_id: "t3", task_type: "ppt_generate", status: "completed", params: { topic: "技术趋势" } }),
      ],
    });
    await page.goto("/projects");

    const searchInput = page.getByPlaceholder("搜索项目...");

    // Search for "玄幻"
    await searchInput.fill("玄幻");
    await expect(page.getByText("玄幻 - 修仙大陆")).toBeVisible();
    await expect(page.getByText("科幻太空")).not.toBeVisible();
    await expect(page.getByText("技术趋势")).not.toBeVisible();

    // Search for "科幻"
    await searchInput.fill("科幻");
    await expect(page.getByText("玄幻 - 修仙大陆")).not.toBeVisible();
    await expect(page.getByText("科幻太空")).toBeVisible();

    // Clear search to show all
    await searchInput.fill("");
    await expect(page.getByText("玄幻 - 修仙大陆")).toBeVisible();
    await expect(page.getByText("科幻太空")).toBeVisible();
    await expect(page.getByText("技术趋势")).toBeVisible();
  });

  test("should search by task type", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({ task_id: "t1", task_type: "novel_create", status: "completed", params: { genre: "玄幻", theme: "修仙" } }),
        mockTask({ task_id: "t2", task_type: "director_generate", status: "completed", params: { inspiration: "导演作品" } }),
      ],
    });
    await page.goto("/projects");

    const searchInput = page.getByPlaceholder("搜索项目...");

    // Search by task_type
    await searchInput.fill("director");
    await expect(page.getByText("玄幻 - 修仙")).not.toBeVisible();
    await expect(page.getByText("导演作品")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Project cards                                                      */
  /* ------------------------------------------------------------------ */

  test("should display project card with title and status", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({ task_id: "t1", task_type: "novel_create", status: "completed", params: { genre: "玄幻", theme: "修仙" } }),
      ],
    });
    await page.goto("/projects");
    // getTitle: genre + " - " + theme
    await expect(page.getByText("玄幻 - 修仙")).toBeVisible();
    // StatusBadge: "已完成"
    await expect(page.getByText("已完成")).toBeVisible();
    // getTaskTypeLabel: "创建小说"
    await expect(page.getByText("创建小说")).toBeVisible();
  });

  test("should display kind badge with correct label", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({ task_id: "t1", task_type: "novel_create", status: "completed", params: { genre: "测试", theme: "标签" } }),
      ],
    });
    await page.goto("/projects");
    // Kind badge shows "小说" for novel types
    const kindBadge = page.locator("span.rounded-full").filter({ hasText: "小说" });
    await expect(kindBadge.first()).toBeVisible();
  });

  test("should display progress bar and percentage", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({ task_id: "t1", task_type: "novel_generate", status: "running", progress: 0.75, params: { project_id: "novel_001" } }),
      ],
    });
    await page.goto("/projects");
    await expect(page.getByText("75%")).toBeVisible();
    await expect(page.getByText("进度").first()).toBeVisible();
  });

  test("should display progress message", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({
          task_id: "t1",
          task_type: "novel_generate",
          status: "running",
          progress: 0.5,
          progress_msg: "生成第10章中...",
          params: { project_id: "novel_001" },
        }),
      ],
    });
    await page.goto("/projects");
    await expect(page.getByText("生成第10章中...")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Project title derivation                                           */
  /* ------------------------------------------------------------------ */

  test("should derive title from inspiration param", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({ task_id: "t1", task_type: "video_generate", status: "completed", params: { inspiration: "一个关于AI觉醒的故事" } }),
      ],
    });
    await page.goto("/projects");
    await expect(page.getByText("一个关于AI觉醒的故事")).toBeVisible();
  });

  test("should derive title from topic param", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({ task_id: "t1", task_type: "ppt_generate", status: "completed", params: { topic: "2026年AI发展报告" } }),
      ],
    });
    await page.goto("/projects");
    await expect(page.getByText("2026年AI发展报告")).toBeVisible();
  });

  test("should truncate long titles", async ({ page, mockApi }) => {
    // Must be longer than 50 characters to trigger truncation in getTitle()
    const longTitle = "这是一个非常非常非常长的灵感描述，超过了五十个字符的限制所以应该被截断显示省略号，还需要更多文字才能超过五十个字符的长度限制";
    await mockApi({
      tasks: [
        mockTask({ task_id: "t1", task_type: "video_generate", status: "completed", params: { inspiration: longTitle } }),
      ],
    });
    await page.goto("/projects");
    // Title should be truncated to 50 chars + "..."
    await expect(page.getByText(longTitle.slice(0, 50) + "...")).toBeVisible();
  });

  test("should fallback to task_id when no meaningful params", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({ task_id: "task_abc12345", task_type: "novel_create", status: "completed", params: {} }),
      ],
    });
    await page.goto("/projects");
    // Falls back to "任务 task_abc" (first 8 chars of task_id)
    await expect(page.getByText("任务 task_abc")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Task type labels                                                   */
  /* ------------------------------------------------------------------ */

  test("should display correct task type labels", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({ task_id: "t1", task_type: "novel_create", status: "completed", params: { genre: "A", theme: "B" } }),
        mockTask({ task_id: "t2", task_type: "director_generate", status: "completed", params: { inspiration: "X" } }),
        mockTask({ task_id: "t3", task_type: "ppt_export", status: "completed", params: { topic: "Y" } }),
      ],
    });
    await page.goto("/projects");
    await expect(page.getByText("创建小说")).toBeVisible();
    await expect(page.getByText("导演模式")).toBeVisible();
    await expect(page.getByText("PPTX 导出")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Empty and loading states                                           */
  /* ------------------------------------------------------------------ */

  test("should show loading state", async ({ page }) => {
    const API = "http://localhost:8000";
    await page.route(`${API}/api/tasks?*`, async (route) => {
      await new Promise((r) => setTimeout(r, 5000));
      await route.fulfill({ json: [] });
    });
    await page.route(`${API}/api/health`, (route) =>
      route.fulfill({ json: { status: "ok" } })
    );
    await page.goto("/projects");
    await expect(page.getByText("正在获取项目列表...")).toBeVisible();
  });

  test("should show empty state when no projects", async ({ page, mockApi }) => {
    await mockApi({ tasks: [] });
    await page.goto("/projects");
    await expect(page.getByText("还没有任何项目")).toBeVisible();
  });

  test("should show no match message when filter yields no results", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({ task_id: "t1", task_type: "novel_create", status: "completed", params: { genre: "玄幻", theme: "修仙" } }),
      ],
    });
    await page.goto("/projects");

    // Search for something that does not match
    const searchInput = page.getByPlaceholder("搜索项目...");
    await searchInput.fill("zzzznoMatch");

    await expect(page.getByText("没有匹配的项目")).toBeVisible();
  });

  test("should show error state when API fails", async ({ page }) => {
    const API = "http://localhost:8000";
    await page.route(`${API}/api/tasks?*`, (route) =>
      route.fulfill({ status: 500, json: { detail: "Internal error" } })
    );
    await page.route(`${API}/api/health`, (route) =>
      route.fulfill({ json: { status: "ok" } })
    );
    await page.goto("/projects");
    await expect(page.getByText("无法连接到后端服务")).toBeVisible();
    await expect(
      page.getByText("请确认任务队列服务已启动 (python -m src.task_queue.server)")
    ).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Running tasks summary                                              */
  /* ------------------------------------------------------------------ */

  test("should show running tasks summary when tasks are active", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({ task_id: "t1", task_type: "novel_generate", status: "running", progress: 0.5, params: { project_id: "n1" } }),
        mockTask({ task_id: "t2", task_type: "video_generate", status: "running", progress: 0.3, params: { inspiration: "测试" } }),
        mockTask({ task_id: "t3", task_type: "ppt_generate", status: "completed", params: { topic: "Done" } }),
      ],
    });
    await page.goto("/projects");
    await expect(page.getByText("2 个任务正在运行中")).toBeVisible();
  });

  test("should not show running summary when no active tasks", async ({ page }) => {
    await page.goto("/projects");
    // Default task is completed
    await expect(page.getByText(/个任务正在运行中/)).not.toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Refresh button                                                     */
  /* ------------------------------------------------------------------ */

  test("should refetch when clicking refresh button", async ({ page }) => {
    let fetchCount = 0;
    const API = "http://localhost:8000";
    await page.route(`${API}/api/tasks?*`, (route) => {
      fetchCount++;
      return route.fulfill({ json: [mockTask()] });
    });
    await page.route(`${API}/api/health`, (route) =>
      route.fulfill({ json: { status: "ok" } })
    );

    await page.goto("/projects");
    await page.waitForTimeout(500);
    const initialCount = fetchCount;

    await page.getByRole("button", { name: "刷新" }).click();
    await page.waitForTimeout(500);

    expect(fetchCount).toBeGreaterThan(initialCount);
  });

  /* ------------------------------------------------------------------ */
  /*  Navigation on click                                                */
  /* ------------------------------------------------------------------ */

  test("should navigate to project detail on card click", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({ task_id: "task_novel_001", task_type: "novel_create", status: "completed", params: { genre: "玄幻", theme: "导航测试" } }),
      ],
    });
    await page.goto("/projects");

    // Click the project card
    await page.getByText("玄幻 - 导航测试").click();

    // getRoute: /novel/task_novel_001
    await page.waitForURL("**/novel/task_novel_001");
    expect(page.url()).toContain("/novel/task_novel_001");
  });

  test("should navigate to video route for video tasks", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({ task_id: "task_video_001", task_type: "video_generate", status: "completed", params: { inspiration: "视频项目" } }),
      ],
    });
    await page.goto("/projects");

    await page.getByText("视频项目").first().click();
    await page.waitForURL("**/video/task_video_001");
    expect(page.url()).toContain("/video/task_video_001");
  });

  test("should navigate to ppt route for ppt tasks", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({ task_id: "task_ppt_001", task_type: "ppt_generate", status: "completed", params: { topic: "PPT项目" } }),
      ],
    });
    await page.goto("/projects");

    await page.getByText("PPT项目").click();
    await page.waitForURL("**/ppt/task_ppt_001");
    expect(page.url()).toContain("/ppt/task_ppt_001");
  });

  /* ------------------------------------------------------------------ */
  /*  Combined search + filter                                           */
  /* ------------------------------------------------------------------ */

  test("should combine search and kind filter", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({ task_id: "t1", task_type: "novel_create", status: "completed", params: { genre: "玄幻", theme: "修仙之路" } }),
        mockTask({ task_id: "t2", task_type: "novel_generate", status: "running", params: { project_path: "novel_sci" }, progress: 0.5 }),
        mockTask({ task_id: "t3", task_type: "video_generate", status: "completed", params: { inspiration: "修仙视频" } }),
      ],
    });
    await page.goto("/projects");

    // First filter by "小说"
    const novelFilterBtn = page.locator("button.rounded-full").filter({ hasText: "小说" });
    await novelFilterBtn.click();

    // Only novel tasks visible
    await expect(page.getByText("玄幻 - 修仙之路")).toBeVisible();
    await expect(page.getByText("修仙视频")).not.toBeVisible();

    // Now search for "修仙"
    const searchInput = page.getByPlaceholder("搜索项目...");
    await searchInput.fill("修仙");

    // Only the novel with "修仙" in title should be visible
    await expect(page.getByText("玄幻 - 修仙之路")).toBeVisible();
    // novel_sci doesn't match search
    await expect(page.getByText("novel_sci")).not.toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Status badges                                                      */
  /* ------------------------------------------------------------------ */

  test("should display correct status badges", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({ task_id: "t1", task_type: "novel_create", status: "completed", params: { genre: "A", theme: "完成" } }),
        mockTask({ task_id: "t2", task_type: "novel_generate", status: "running", params: { project_id: "n1" }, progress: 0.5 }),
        mockTask({ task_id: "t3", task_type: "ppt_generate", status: "failed", params: { topic: "失败项目" }, error: "error" }),
        mockTask({ task_id: "t4", task_type: "video_generate", status: "pending", params: { inspiration: "等待中项目" }, progress: 0 }),
      ],
    });
    await page.goto("/projects");
    // StatusBadge labels
    await expect(page.getByText("已完成").first()).toBeVisible();
    await expect(page.getByText("运行中").first()).toBeVisible();
    await expect(page.getByText("失败").first()).toBeVisible();
    await expect(page.getByText("等待中").first()).toBeVisible();
  });
});

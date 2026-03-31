import { test, expect, mockPPTProject, mockTask } from "./fixtures";

test.describe("PPT Detail Page", () => {
  test.beforeEach(async ({ page, mockApi }) => {
    await mockApi();
  });

  /* ------------------------------------------------------------------ */
  /*  Loading and error states                                           */
  /* ------------------------------------------------------------------ */

  test("should show loading state initially", async ({ page }) => {
    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_slow001$"),
      async (route) => {
        await new Promise((r) => setTimeout(r, 2000));
        route.fulfill({ json: mockPPTProject({ id: "ppt_slow001" }) });
      }
    );
    await page.goto("/ppt/ppt_slow001");
    // PageHeader renders title as <h2>
    await expect(page.locator("h2")).toContainText("加载中...");
  });

  test("should show error state when PPT fetch fails", async ({ page }) => {
    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_bad001$"),
      (route) => route.fulfill({ status: 500, json: { detail: "Not found" } })
    );
    await page.goto("/ppt/ppt_bad001");
    await expect(page.locator("h2")).toContainText("加载失败");
    await expect(page.locator("a[href='/ppt']").filter({ hasText: "返回列表" })).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Outline ready state                                                */
  /* ------------------------------------------------------------------ */

  test("should display project header with name and status", async ({ page }) => {
    const ppt = mockPPTProject({
      id: "ppt_header001",
      name: "AI技术趋势2026",
      status: "outline_ready",
    });

    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_header001$"),
      (route) => route.fulfill({ json: ppt })
    );
    await page.goto("/ppt/ppt_header001");

    await expect(page.locator("h2")).toContainText("AI技术趋势2026");
    // StatusBadge renders "大纲就绪" for outline_ready
    await expect(page.getByText("大纲就绪").first()).toBeVisible();
  });

  test("should show status description for outline_ready", async ({ page }) => {
    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_test001$"),
      (route) =>
        route.fulfill({
          json: mockPPTProject({ status: "outline_ready" }),
        })
    );
    await page.goto("/ppt/ppt_test001");

    await expect(
      page.getByText("大纲已就绪，可编辑后生成完整 PPT")
    ).toBeVisible();
  });

  test("should show edit and generate buttons when outline is ready", async ({ page }) => {
    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_test001$"),
      (route) =>
        route.fulfill({
          json: mockPPTProject({ status: "outline_ready" }),
        })
    );
    await page.goto("/ppt/ppt_test001");

    await expect(page.getByRole("button", { name: "编辑大纲" })).toBeVisible();
    await expect(page.getByRole("button", { name: "直接生成 PPT" })).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Outline display (read-only)                                        */
  /* ------------------------------------------------------------------ */

  test("should display outline slides in read-only view", async ({ page }) => {
    const ppt = mockPPTProject({
      id: "ppt_outline001",
      status: "outline_ready",
      outline: [
        {
          page_number: 1,
          title: "AI技术趋势2026",
          layout: "title_slide",
          purpose: "封面页",
          needs_image: false,
        },
        {
          page_number: 2,
          title: "大语言模型进展",
          layout: "content",
          purpose: "介绍LLM最新进展",
          needs_image: true,
        },
        {
          page_number: 3,
          title: "多模态AI",
          layout: "two_column",
          purpose: "图文视频融合",
          needs_image: true,
        },
      ],
    });

    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_outline001$"),
      (route) => route.fulfill({ json: ppt })
    );
    await page.goto("/ppt/ppt_outline001");

    // Panel title and description
    await expect(page.locator("h3").filter({ hasText: "大纲结构" })).toBeVisible();
    await expect(page.getByText("共 3 页幻灯片")).toBeVisible();

    // Slide titles (use first() for "AI技术趋势2026" since it also appears in h2)
    await expect(page.getByText("AI技术趋势2026").first()).toBeVisible();
    await expect(page.getByText("大语言模型进展")).toBeVisible();
    await expect(page.getByText("多模态AI")).toBeVisible();

    // Layout badges
    await expect(page.getByText("title_slide")).toBeVisible();
    await expect(page.getByText("content").first()).toBeVisible();
    await expect(page.getByText("two_column")).toBeVisible();

    // Purpose text
    await expect(page.getByText("封面页")).toBeVisible();
    await expect(page.getByText("介绍LLM最新进展")).toBeVisible();

    // Needs image badge
    await expect(page.getByText("需要图片").first()).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Outline editor                                                     */
  /* ------------------------------------------------------------------ */

  test("should enter editing mode when clicking edit button", async ({ page }) => {
    const ppt = mockPPTProject({
      id: "ppt_edit001",
      status: "outline_ready",
      outline: [
        { page_number: 1, title: "封面", layout: "title_slide", purpose: "封面页", needs_image: false },
        { page_number: 2, title: "内容页", layout: "content", purpose: "主要内容", needs_image: true },
      ],
    });

    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_edit001$"),
      (route) => route.fulfill({ json: ppt })
    );
    await page.goto("/ppt/ppt_edit001");

    await page.getByRole("button", { name: "编辑大纲" }).click();

    // Editing UI should appear - Panel title "编辑大纲" and description
    await expect(page.getByText("编辑后点击「确认并生成 PPT」")).toBeVisible();

    // Theme selector in editor
    await expect(page.getByText("主题风格").first()).toBeVisible();

    // Generate AI images checkbox
    await expect(page.getByText("生成 AI 配图")).toBeVisible();

    // Slide title inputs
    const titleInputs = page.locator("input[type='text']");
    await expect(titleInputs.first()).toHaveValue("封面");

    // Layout selectors
    await expect(page.locator("select").first()).toBeVisible();

    // Action buttons
    await expect(page.getByRole("button", { name: "新增一页" })).toBeVisible();
    await expect(page.getByRole("button", { name: "取消" })).toBeVisible();
    await expect(page.getByRole("button", { name: "确认并生成 PPT" })).toBeVisible();
  });

  test("should cancel editing and return to read-only view", async ({ page }) => {
    const ppt = mockPPTProject({
      id: "ppt_cancel001",
      status: "outline_ready",
      outline: [
        { page_number: 1, title: "封面", layout: "title_slide", needs_image: false },
      ],
    });

    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_cancel001$"),
      (route) => route.fulfill({ json: ppt })
    );
    await page.goto("/ppt/ppt_cancel001");

    // Enter editing mode
    await page.getByRole("button", { name: "编辑大纲" }).click();
    await expect(page.getByText("编辑后点击「确认并生成 PPT」")).toBeVisible();

    // Cancel editing
    await page.getByRole("button", { name: "取消" }).click();

    // Should return to read-only
    await expect(page.locator("h3").filter({ hasText: "大纲结构" })).toBeVisible();
    await expect(page.getByText("编辑后点击「确认并生成 PPT」")).not.toBeVisible();
  });

  test("should add a new slide in editor", async ({ page }) => {
    const ppt = mockPPTProject({
      id: "ppt_add001",
      status: "outline_ready",
      outline: [
        { page_number: 1, title: "封面", layout: "title_slide", needs_image: false },
      ],
    });

    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_add001$"),
      (route) => route.fulfill({ json: ppt })
    );
    await page.goto("/ppt/ppt_add001");

    await page.getByRole("button", { name: "编辑大纲" }).click();

    // Click add button
    await page.getByRole("button", { name: "新增一页" }).click();

    // Now should have a new slide with title "新页面"
    await expect(page.locator("input[value='新页面']")).toBeVisible();
  });

  test("should delete a slide in editor", async ({ page }) => {
    const ppt = mockPPTProject({
      id: "ppt_del001",
      status: "outline_ready",
      outline: [
        { page_number: 1, title: "封面页", layout: "title_slide", needs_image: false },
        { page_number: 2, title: "内容页A", layout: "content", needs_image: false },
        { page_number: 3, title: "内容页B", layout: "content", needs_image: true },
      ],
    });

    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_del001$"),
      (route) => route.fulfill({ json: ppt })
    );
    await page.goto("/ppt/ppt_del001");

    await page.getByRole("button", { name: "编辑大纲" }).first().click();

    // Verify all 3 slides exist
    await expect(page.locator("input[value='封面页']")).toBeVisible();
    await expect(page.locator("input[value='内容页A']")).toBeVisible();
    await expect(page.locator("input[value='内容页B']")).toBeVisible();

    // Delete the second slide. Each slide has a small button with hover:text-rose styling.
    // Lucide icons render with class "lucide lucide-trash-2" on the SVG element.
    const deleteButtons = page.locator("button").filter({ has: page.locator("svg[class*='lucide-trash']") });
    await deleteButtons.nth(1).click();

    // "内容页A" should be removed
    await expect(page.locator("input[value='内容页A']")).not.toBeVisible();
    await expect(page.locator("input[value='封面页']")).toBeVisible();
    await expect(page.locator("input[value='内容页B']")).toBeVisible();
  });

  test("should edit slide title in editor", async ({ page }) => {
    const ppt = mockPPTProject({
      id: "ppt_editfield001",
      status: "outline_ready",
      outline: [
        { page_number: 1, title: "旧标题", layout: "content", purpose: "旧说明", needs_image: false },
      ],
    });

    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_editfield001$"),
      (route) => route.fulfill({ json: ppt })
    );
    await page.goto("/ppt/ppt_editfield001");

    await page.getByRole("button", { name: "编辑大纲" }).first().click();

    // Change title - locate the first text input under the "标题" label
    const titleInput = page.locator("input[value='旧标题']");
    await expect(titleInput).toBeVisible();
    await titleInput.fill("新标题");
    await expect(page.locator("input[value='新标题']")).toBeVisible();
  });

  test("should submit edited outline for generation", async ({ page }) => {
    const ppt = mockPPTProject({
      id: "ppt_submit001",
      status: "outline_ready",
      outline: [
        { page_number: 1, title: "封面", layout: "title_slide", needs_image: false },
      ],
    });

    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_submit001$"),
      (route) => route.fulfill({ json: ppt })
    );
    await page.route("http://localhost:8000/api/ppt/ppt_submit001/generate", (route) =>
      route.fulfill({ json: { task_id: "task_ppt_gen_001" } })
    );
    await page.goto("/ppt/ppt_submit001");

    await page.getByRole("button", { name: "编辑大纲" }).click();
    await page.getByRole("button", { name: "确认并生成 PPT" }).click();

    // Should exit editing mode after submission
    await expect(page.getByText("编辑后点击「确认并生成 PPT」")).not.toBeVisible();
  });

  test("should submit directly without editing", async ({ page }) => {
    const ppt = mockPPTProject({
      id: "ppt_direct001",
      status: "outline_ready",
      outline: [
        { page_number: 1, title: "封面", layout: "title_slide", needs_image: false },
      ],
    });

    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_direct001$"),
      (route) => route.fulfill({ json: ppt })
    );
    await page.route("http://localhost:8000/api/ppt/ppt_direct001/generate", (route) =>
      route.fulfill({ json: { task_id: "task_ppt_gen_002" } })
    );
    await page.goto("/ppt/ppt_direct001");

    await page.getByRole("button", { name: "直接生成 PPT" }).click();

    // The button should not fail; the generation should be triggered
  });

  /* ------------------------------------------------------------------ */
  /*  Completed state: render and export                                 */
  /* ------------------------------------------------------------------ */

  test("should show render button for completed project without HTML", async ({ page }) => {
    const ppt = mockPPTProject({
      id: "ppt_completed001",
      status: "completed",
      output_html: null,
      output_pptx: null,
      outline: [
        { page_number: 1, title: "封面", layout: "title_slide" },
      ],
    });

    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_completed001$"),
      (route) => route.fulfill({ json: ppt })
    );
    await page.goto("/ppt/ppt_completed001");

    await expect(page.getByText("生成完成")).toBeVisible();
    await expect(page.getByRole("button", { name: "渲染预览" })).toBeVisible();
  });

  test("should show export button when HTML exists but no PPTX", async ({ page }) => {
    const ppt = mockPPTProject({
      id: "ppt_export001",
      status: "completed",
      output_html: "/workspace/ppt/preview.html",
      output_pptx: null,
      outline: [
        { page_number: 1, title: "封面", layout: "title_slide" },
      ],
    });

    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_export001$"),
      (route) => route.fulfill({ json: ppt })
    );
    await page.goto("/ppt/ppt_export001");

    await expect(page.getByRole("button", { name: "导出 PPTX" })).toBeVisible();
    // HTML preview section
    await expect(page.locator("h3").filter({ hasText: "HTML 预览" })).toBeVisible();
    await expect(page.getByText("预览文件已生成")).toBeVisible();
    await expect(page.getByText("/workspace/ppt/preview.html")).toBeVisible();
    await expect(page.getByText("打开预览")).toBeVisible();
  });

  test("should trigger render when clicking render button", async ({ page }) => {
    const ppt = mockPPTProject({
      id: "ppt_render001",
      status: "completed",
      output_html: null,
      output_pptx: null,
      outline: [{ page_number: 1, title: "封面", layout: "title_slide" }],
    });

    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_render001$"),
      (route) => route.fulfill({ json: ppt })
    );
    await page.route("http://localhost:8000/api/ppt/ppt_render001/render", (route) =>
      route.fulfill({ json: { task_id: "task_render_001" } })
    );
    // Mock the task polling
    await page.route("http://localhost:8000/api/tasks/task_render_001", (route) =>
      route.fulfill({
        json: mockTask({
          task_id: "task_render_001",
          status: "running",
          progress: 0.5,
          progress_msg: "渲染中...",
        }),
      })
    );
    await page.goto("/ppt/ppt_render001");

    await page.getByRole("button", { name: "渲染预览" }).click();

    // Task progress panel should appear
    await expect(page.locator("h3").filter({ hasText: "任务进度" })).toBeVisible();
    await expect(page.getByText("渲染中...")).toBeVisible();
  });

  test("should trigger export when clicking export button", async ({ page }) => {
    const ppt = mockPPTProject({
      id: "ppt_doexport001",
      status: "completed",
      output_html: "/preview.html",
      output_pptx: null,
      outline: [{ page_number: 1, title: "封面", layout: "title_slide" }],
    });

    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_doexport001$"),
      (route) => route.fulfill({ json: ppt })
    );
    await page.route("http://localhost:8000/api/ppt/ppt_doexport001/export", (route) =>
      route.fulfill({ json: { task_id: "task_export_001" } })
    );
    await page.route("http://localhost:8000/api/tasks/task_export_001", (route) =>
      route.fulfill({
        json: mockTask({
          task_id: "task_export_001",
          status: "completed",
          progress: 1.0,
          progress_msg: "导出完成",
        }),
      })
    );
    await page.goto("/ppt/ppt_doexport001");

    await page.getByRole("button", { name: "导出 PPTX" }).click();

    // Task completed panel should show
    await expect(page.locator("h3").filter({ hasText: "任务完成" })).toBeVisible();
    await expect(page.getByText("任务已完成，点击刷新查看最新结果。")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Task progress and completion                                       */
  /* ------------------------------------------------------------------ */

  test("should show task completed message with refresh button", async ({ page }) => {
    const ppt = mockPPTProject({
      id: "ppt_taskdone001",
      status: "completed",
      output_html: "/preview.html",
      output_pptx: null,
      outline: [{ page_number: 1, title: "封面", layout: "title_slide" }],
    });

    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_taskdone001$"),
      (route) => route.fulfill({ json: ppt })
    );
    await page.route("http://localhost:8000/api/ppt/ppt_taskdone001/export", (route) =>
      route.fulfill({ json: { task_id: "task_completed_001" } })
    );
    await page.route("http://localhost:8000/api/tasks/task_completed_001", (route) =>
      route.fulfill({
        json: mockTask({
          task_id: "task_completed_001",
          status: "completed",
          progress: 1.0,
        }),
      })
    );
    await page.goto("/ppt/ppt_taskdone001");

    await page.getByRole("button", { name: "导出 PPTX" }).click();

    await expect(page.locator("h3").filter({ hasText: "任务完成" })).toBeVisible();
    await expect(page.getByText("任务已完成，点击刷新查看最新结果。")).toBeVisible();
    // Refresh button inside task completed panel
    const taskRefreshBtn = page.getByRole("button", { name: "刷新" }).last();
    await expect(taskRefreshBtn).toBeVisible();
  });

  test("should show task failed message", async ({ page }) => {
    const ppt = mockPPTProject({
      id: "ppt_taskfail001",
      status: "completed",
      output_html: null,
      output_pptx: null,
      outline: [{ page_number: 1, title: "封面", layout: "title_slide" }],
    });

    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_taskfail001$"),
      (route) => route.fulfill({ json: ppt })
    );
    await page.route("http://localhost:8000/api/ppt/ppt_taskfail001/render", (route) =>
      route.fulfill({ json: { task_id: "task_failed_001" } })
    );
    await page.route("http://localhost:8000/api/tasks/task_failed_001", (route) =>
      route.fulfill({
        json: mockTask({
          task_id: "task_failed_001",
          status: "failed",
          progress: 0.3,
          error: "Rendering engine crashed",
        }),
      })
    );
    await page.goto("/ppt/ppt_taskfail001");

    await page.getByRole("button", { name: "渲染预览" }).click();

    await expect(page.locator("h3").filter({ hasText: "任务失败" })).toBeVisible();
    await expect(page.getByText("Rendering engine crashed")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Quality report                                                     */
  /* ------------------------------------------------------------------ */

  test("should display quality report when available", async ({ page }) => {
    const ppt = mockPPTProject({
      id: "ppt_quality001",
      status: "completed",
      outline: [{ page_number: 1, title: "封面", layout: "title_slide" }],
      quality_report: {
        overall_score: 8.5,
        issues: ["部分页面文字过多", "配色对比度不足"],
        suggestions: ["减少单页文字量", "增加图表比例"],
      },
    });

    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_quality001$"),
      (route) => route.fulfill({ json: ppt })
    );
    await page.goto("/ppt/ppt_quality001");

    await expect(page.locator("h3").filter({ hasText: "质量报告" })).toBeVisible();
    await expect(page.getByText("8.5")).toBeVisible();
    await expect(page.getByText("/ 10")).toBeVisible();

    // Issues
    await expect(page.getByText("部分页面文字过多")).toBeVisible();
    await expect(page.getByText("配色对比度不足")).toBeVisible();

    // Suggestions
    await expect(page.getByText("改进建议")).toBeVisible();
    await expect(page.getByText("减少单页文字量")).toBeVisible();
    await expect(page.getByText("增加图表比例")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Output files                                                       */
  /* ------------------------------------------------------------------ */

  test("should display output PPTX file path", async ({ page }) => {
    const ppt = mockPPTProject({
      id: "ppt_pptx001",
      status: "completed",
      output_pptx: "/workspace/ppt/output.pptx",
      outline: [{ page_number: 1, title: "封面", layout: "title_slide" }],
    });

    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_pptx001$"),
      (route) => route.fulfill({ json: ppt })
    );
    await page.goto("/ppt/ppt_pptx001");

    await expect(page.locator("h3").filter({ hasText: "输出文件" })).toBeVisible();
    await expect(page.getByText("/workspace/ppt/output.pptx")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Project info sidebar                                               */
  /* ------------------------------------------------------------------ */

  test("should display project info in sidebar", async ({ page }) => {
    const ppt = mockPPTProject({
      id: "ppt_info001",
      name: "测试PPT项目",
      status: "outline_ready",
      total_pages: 15,
    });

    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_info001$"),
      (route) => route.fulfill({ json: ppt })
    );
    await page.goto("/ppt/ppt_info001");

    await expect(page.locator("h3").filter({ hasText: "项目信息" })).toBeVisible();
    await expect(page.getByText("项目 ID", { exact: true })).toBeVisible();
    await expect(page.getByText("ppt_info001")).toBeVisible();
    await expect(page.getByText("页数", { exact: true })).toBeVisible();
    await expect(page.getByText("15 页").first()).toBeVisible();
  });

  test("should display project files when available", async ({ page }) => {
    const ppt = mockPPTProject({
      id: "ppt_files001",
      status: "completed",
      outline: [{ page_number: 1, title: "封面", layout: "title_slide" }],
      files: [
        { name: "output.pptx", path: "/workspace/output.pptx", size: 2048576 },
        { name: "preview.html", path: "/workspace/preview.html", size: 512 },
      ],
    });

    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_files001$"),
      (route) => route.fulfill({ json: ppt })
    );
    await page.goto("/ppt/ppt_files001");

    await expect(page.locator("h3").filter({ hasText: "项目文件" })).toBeVisible();
    await expect(page.getByText("/workspace/output.pptx")).toBeVisible();
    await expect(page.getByText("2.0 MB")).toBeVisible();
    await expect(page.getByText("/workspace/preview.html")).toBeVisible();
    await expect(page.getByText("512 B")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Navigation                                                         */
  /* ------------------------------------------------------------------ */

  test("should have back link and refresh button", async ({ page }) => {
    await page.goto("/ppt/ppt_test001");
    await expect(page.locator("a[href='/ppt']").filter({ hasText: "返回列表" })).toBeVisible();
    await expect(page.getByRole("button", { name: "刷新" }).first()).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Editor: theme and image options                                    */
  /* ------------------------------------------------------------------ */

  test("should show theme selector in outline editor", async ({ page }) => {
    const ppt = mockPPTProject({
      id: "ppt_edittheme001",
      status: "outline_ready",
      outline: [
        { page_number: 1, title: "封面", layout: "title_slide", needs_image: false },
      ],
    });

    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_edittheme001$"),
      (route) => route.fulfill({ json: ppt })
    );
    await page.goto("/ppt/ppt_edittheme001");

    await page.getByRole("button", { name: "编辑大纲" }).first().click();

    // Theme selector with options
    const themeSelect = page.locator("select").first();
    await expect(themeSelect).toBeVisible();

    // Check options exist (options are hidden inside select, use toBeAttached)
    await expect(page.locator("option").filter({ hasText: "现代" })).toBeAttached();
    await expect(page.locator("option").filter({ hasText: "科技" })).toBeAttached();
  });

  test("should toggle generate images checkbox in editor", async ({ page }) => {
    const ppt = mockPPTProject({
      id: "ppt_imgcheck001",
      status: "outline_ready",
      outline: [
        { page_number: 1, title: "封面", layout: "title_slide", needs_image: false },
      ],
    });

    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_imgcheck001$"),
      (route) => route.fulfill({ json: ppt })
    );
    await page.goto("/ppt/ppt_imgcheck001");

    await page.getByRole("button", { name: "编辑大纲" }).click();

    // The generate images checkbox should be checked by default
    const aiImageCheckbox = page.locator("label").filter({ hasText: "生成 AI 配图" }).locator("input[type='checkbox']");
    await expect(aiImageCheckbox).toBeChecked();

    // Uncheck it
    await aiImageCheckbox.uncheck();
    await expect(aiImageCheckbox).not.toBeChecked();
  });

  /* ------------------------------------------------------------------ */
  /*  Completed with edit outline (re-edit)                              */
  /* ------------------------------------------------------------------ */

  test("should allow re-editing outline even after completion", async ({ page }) => {
    const ppt = mockPPTProject({
      id: "ppt_reedit001",
      status: "completed",
      output_html: null,
      output_pptx: null,
      outline: [
        { page_number: 1, title: "封面", layout: "title_slide", needs_image: false },
        { page_number: 2, title: "内容", layout: "content", needs_image: true },
      ],
    });

    await page.route(
      new RegExp("http://localhost:8000/api/ppt/ppt_reedit001$"),
      (route) => route.fulfill({ json: ppt })
    );
    await page.goto("/ppt/ppt_reedit001");

    // Edit button should be available for completed projects with outline
    await expect(page.getByRole("button", { name: "编辑大纲" })).toBeVisible();
    await page.getByRole("button", { name: "编辑大纲" }).click();

    // Should enter editing mode
    await expect(page.getByText("编辑后点击「确认并生成 PPT」")).toBeVisible();
  });
});

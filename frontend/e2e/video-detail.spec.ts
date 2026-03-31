import { test, expect, mockTask } from "./fixtures";

test.describe("Video Detail Page", () => {
  test.beforeEach(async ({ page, mockApi }) => {
    await mockApi();
  });

  /* ------------------------------------------------------------------ */
  /*  Loading and error states                                           */
  /* ------------------------------------------------------------------ */

  test("should show loading state initially", async ({ page }) => {
    // Add delay to task API to observe loading
    await page.route("http://localhost:8000/api/tasks/task_slow001", async (route) => {
      await new Promise((r) => setTimeout(r, 2000));
      route.fulfill({
        json: mockTask({ task_id: "task_slow001", task_type: "director_generate" }),
      });
    });
    await page.goto("/video/task_slow001");
    // PageHeader renders title as <h2>
    await expect(page.locator("h2")).toContainText("加载中...");
  });

  test("should show error state when task fetch fails", async ({ page }) => {
    await page.route("http://localhost:8000/api/tasks/task_bad001", (route) =>
      route.fulfill({ status: 500, json: { detail: "服务器错误" } })
    );
    await page.goto("/video/task_bad001");
    await expect(page.locator("h2")).toContainText("加载失败");
    await expect(page.locator("a[href='/video']").filter({ hasText: "返回列表" })).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Completed director mode project                                    */
  /* ------------------------------------------------------------------ */

  test("should display director mode task details", async ({ page }) => {
    const task = mockTask({
      task_id: "task_director001",
      task_type: "director_generate",
      status: "completed",
      progress: 1.0,
      progress_msg: "完成",
      params: {
        inspiration: "一个关于AI觉醒的故事",
        target_duration: 120,
        budget: "medium",
      },
      result: JSON.stringify({
        output: "/workspace/videos/output.mp4",
        concept: { title: "AI觉醒", visual_style: "赛博朋克" },
        segments: [
          { text: "第一幕：AI诞生", prompt: "cyberpunk AI birth" },
          { text: "第二幕：AI觉醒", prompt: "AI awakening" },
        ],
      }),
      created_at: "2026-03-27T10:00:00",
      started_at: "2026-03-27T10:00:01",
      finished_at: "2026-03-27T10:05:00",
    });

    await page.route("http://localhost:8000/api/tasks/task_director001", (route) =>
      route.fulfill({ json: task })
    );
    await page.goto("/video/task_director001");

    // Page header: getTitle returns the inspiration text
    await expect(page.locator("h2")).toContainText("一个关于AI觉醒的故事");
    // Mode label appears in description and sidebar
    await expect(page.getByText("AI 导演模式").first()).toBeVisible();

    // Status panel
    await expect(page.locator("h3").filter({ hasText: "项目状态" })).toBeVisible();
    await expect(page.getByText("已完成").first()).toBeVisible();

    // Action buttons for completed project with output
    await expect(page.getByRole("button", { name: "预览" })).toBeVisible();
    await expect(page.getByRole("button", { name: "导出" })).toBeVisible();

    // Back link
    await expect(page.locator("a[href='/video']").filter({ hasText: "返回列表" })).toBeVisible();
  });

  test("should display pipeline stages for a completed task", async ({ page }) => {
    const task = mockTask({
      task_id: "task_stages001",
      task_type: "video_generate",
      status: "completed",
      progress: 1.0,
      params: { input_file: "input.txt" },
      result: JSON.stringify({ output: "/output.mp4" }),
      created_at: "2026-03-27T10:00:00",
    });

    await page.route("http://localhost:8000/api/tasks/task_stages001", (route) =>
      route.fulfill({ json: task })
    );
    await page.goto("/video/task_stages001");

    // All 5 pipeline stages should show
    await expect(page.locator("h3").filter({ hasText: "流水线阶段" })).toBeVisible();
    await expect(page.getByText("分段", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Prompt 生成")).toBeVisible();
    await expect(page.getByText("图片/视频生成")).toBeVisible();
    await expect(page.getByText("配音合成")).toBeVisible();
    await expect(page.getByText("视频合成")).toBeVisible();

    // All stages should be completed (progress=1.0)
    await expect(page.getByText("已完成").first()).toBeVisible();
  });

  test("should show correct stage statuses for partial progress", async ({ page }) => {
    const task = mockTask({
      task_id: "task_partial001",
      task_type: "video_generate",
      status: "running",
      progress: 0.5,
      progress_msg: "图片生成中...",
      params: { input_file: "novel.txt" },
      created_at: "2026-03-27T10:00:00",
    });

    await page.route("http://localhost:8000/api/tasks/task_partial001", (route) =>
      route.fulfill({ json: task })
    );
    await page.goto("/video/task_partial001");

    // Progress 0.5: segment(0-0.2)=done, prompt(0.2-0.4)=done, image(0.4-0.6)=running,
    // tts(0.6-0.8)=pending, video(0.8-1.0)=pending
    await expect(page.getByText("等待中").first()).toBeVisible();
    await expect(page.getByText("进行中").first()).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Segments and output                                                */
  /* ------------------------------------------------------------------ */

  test("should display segments when result has them", async ({ page }) => {
    const task = mockTask({
      task_id: "task_segments001",
      task_type: "director_generate",
      status: "completed",
      progress: 1.0,
      params: { inspiration: "测试片段" },
      result: JSON.stringify({
        output: "/output.mp4",
        segments: [
          { text: "旁白：清晨的阳光...", prompt: "morning sunlight" },
          { text: "旁白：街道上行人...", prompt: "crowded street" },
          { text: "旁白：少年抬起头...", prompt: "boy looking up" },
        ],
      }),
      created_at: "2026-03-27T10:00:00",
    });

    await page.route("http://localhost:8000/api/tasks/task_segments001", (route) =>
      route.fulfill({ json: task })
    );
    await page.goto("/video/task_segments001");

    await expect(page.locator("h3").filter({ hasText: "分段内容" })).toBeVisible();
    await expect(page.getByText("共 3 个片段")).toBeVisible();
    await expect(page.getByText("旁白：清晨的阳光...")).toBeVisible();
    await expect(page.getByText("Prompt: morning sunlight")).toBeVisible();
    await expect(page.getByText("旁白：街道上行人...")).toBeVisible();
    await expect(page.getByText("旁白：少年抬起头...")).toBeVisible();
  });

  test("should display output path when available", async ({ page }) => {
    const task = mockTask({
      task_id: "task_output001",
      task_type: "video_generate",
      status: "completed",
      progress: 1.0,
      params: { input_file: "test.txt" },
      result: JSON.stringify({ output_path: "/workspace/videos/final.mp4" }),
      created_at: "2026-03-27T10:00:00",
    });

    await page.route("http://localhost:8000/api/tasks/task_output001", (route) =>
      route.fulfill({ json: task })
    );
    await page.goto("/video/task_output001");

    await expect(page.locator("h3").filter({ hasText: "输出文件" })).toBeVisible();
    await expect(page.getByText("/workspace/videos/final.mp4")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Running task: real-time progress                                   */
  /* ------------------------------------------------------------------ */

  test("should show real-time progress panel for running task", async ({ page }) => {
    const task = mockTask({
      task_id: "task_running001",
      task_type: "video_generate",
      status: "running",
      progress: 0.35,
      progress_msg: "生成图片 3/10...",
      params: { input_file: "story.txt" },
      created_at: "2026-03-27T10:00:00",
    });

    await page.route("http://localhost:8000/api/tasks/task_running001", (route) =>
      route.fulfill({ json: task })
    );
    await page.goto("/video/task_running001");

    await expect(page.locator("h3").filter({ hasText: "实时进度" })).toBeVisible();
    // progress_msg appears in both the status panel and real-time progress panel, use first()
    await expect(page.getByText("生成图片 3/10...").first()).toBeVisible();
    await expect(page.getByText("35% 完成")).toBeVisible();
  });

  test("should show pending button for pending task", async ({ page }) => {
    const task = mockTask({
      task_id: "task_pending001",
      task_type: "video_generate",
      status: "pending",
      progress: 0,
      params: { input_file: "test.txt" },
      created_at: "2026-03-27T10:00:00",
    });

    await page.route("http://localhost:8000/api/tasks/task_pending001", (route) =>
      route.fulfill({ json: task })
    );
    await page.goto("/video/task_pending001");

    // Pending task shows "生成视频" button
    await expect(page.getByRole("button", { name: "生成视频" })).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Project info sidebar                                               */
  /* ------------------------------------------------------------------ */

  test("should display project info in sidebar", async ({ page }) => {
    const task = mockTask({
      task_id: "task_info001",
      task_type: "director_generate",
      status: "completed",
      progress: 1.0,
      params: {
        inspiration: "AI故事",
        target_duration: 90,
        budget: "high",
      },
      created_at: "2026-03-27T10:00:00",
      started_at: "2026-03-27T10:00:05",
      finished_at: "2026-03-27T10:10:00",
    });

    await page.route("http://localhost:8000/api/tasks/task_info001", (route) =>
      route.fulfill({ json: task })
    );
    await page.goto("/video/task_info001");

    await expect(page.locator("h3").filter({ hasText: "项目信息" })).toBeVisible();
    await expect(page.getByText("模式", { exact: true })).toBeVisible();
    await expect(page.getByText("AI 导演模式").first()).toBeVisible();
    await expect(page.getByText("目标时长", { exact: true })).toBeVisible();
    await expect(page.getByText("90 秒", { exact: true })).toBeVisible();
    await expect(page.getByText("预算", { exact: true })).toBeVisible();
    // budget "high" renders as "高"
    await expect(page.getByText("高", { exact: true }).first()).toBeVisible();
  });

  test("should display input file info for classic mode", async ({ page }) => {
    const task = mockTask({
      task_id: "task_classic001",
      task_type: "video_generate",
      status: "completed",
      progress: 1.0,
      params: { input_file: "input/my_novel.txt" },
      result: JSON.stringify({ output: "/output.mp4" }),
      created_at: "2026-03-27T10:00:00",
    });

    await page.route("http://localhost:8000/api/tasks/task_classic001", (route) =>
      route.fulfill({ json: task })
    );
    await page.goto("/video/task_classic001");

    await expect(page.getByText("输入文件", { exact: true })).toBeVisible();
    await expect(page.getByText("input/my_novel.txt")).toBeVisible();
    // getMode: not director_generate and no run_mode=agent, so "经典模式"
    await expect(page.getByText("经典模式").first()).toBeVisible();
  });

  test("should display director concept in sidebar", async ({ page }) => {
    const task = mockTask({
      task_id: "task_concept001",
      task_type: "director_generate",
      status: "completed",
      progress: 1.0,
      params: { inspiration: "科幻故事" },
      result: JSON.stringify({
        output: "/output.mp4",
        concept: { title: "星际迷途", visual_style: "写实CG" },
      }),
      created_at: "2026-03-27T10:00:00",
    });

    await page.route("http://localhost:8000/api/tasks/task_concept001", (route) =>
      route.fulfill({ json: task })
    );
    await page.goto("/video/task_concept001");

    await expect(page.locator("h3").filter({ hasText: "导演方案" })).toBeVisible();
    await expect(page.getByText("星际迷途")).toBeVisible();
    await expect(page.getByText("写实CG")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Error display                                                      */
  /* ------------------------------------------------------------------ */

  test("should display error message for failed task", async ({ page }) => {
    const task = mockTask({
      task_id: "task_failed001",
      task_type: "video_generate",
      status: "failed",
      progress: 0.4,
      params: { input_file: "test.txt" },
      error: "ImageGen API quota exceeded",
      created_at: "2026-03-27T10:00:00",
    });

    await page.route("http://localhost:8000/api/tasks/task_failed001", (route) =>
      route.fulfill({ json: task })
    );
    await page.goto("/video/task_failed001");

    await expect(page.locator("h3").filter({ hasText: "错误信息" })).toBeVisible();
    await expect(page.getByText("ImageGen API quota exceeded")).toBeVisible();
    // StatusBadge shows "失败"
    await expect(page.getByText("失败").first()).toBeVisible();
  });

  test("should show failed stage in pipeline for failed task", async ({ page }) => {
    // Progress 0.35 means segment (0-0.2) done, prompt (0.2-0.4) in failed range
    const task = mockTask({
      task_id: "task_failstage001",
      task_type: "video_generate",
      status: "failed",
      progress: 0.35,
      params: { input_file: "test.txt" },
      error: "Prompt generation failed",
      created_at: "2026-03-27T10:00:00",
    });

    await page.route("http://localhost:8000/api/tasks/task_failstage001", (route) =>
      route.fulfill({ json: task })
    );
    await page.goto("/video/task_failstage001");

    // Pipeline should show "失败" for the prompt stage
    await expect(page.getByText("失败").first()).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Navigation                                                         */
  /* ------------------------------------------------------------------ */

  test("should have back link to video list", async ({ page }) => {
    await page.goto("/video/task_test001");
    const backLink = page.locator("a[href='/video']").filter({ hasText: "返回列表" });
    await expect(backLink).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Time display                                                       */
  /* ------------------------------------------------------------------ */

  test("should display timestamps in sidebar", async ({ page }) => {
    const task = mockTask({
      task_id: "task_time001",
      task_type: "video_generate",
      status: "completed",
      progress: 1.0,
      params: { input_file: "test.txt" },
      result: JSON.stringify({ output: "/output.mp4" }),
      created_at: "2026-03-27T10:00:00",
      started_at: "2026-03-27T10:00:05",
      finished_at: "2026-03-27T10:10:00",
    });

    await page.route("http://localhost:8000/api/tasks/task_time001", (route) =>
      route.fulfill({ json: task })
    );
    await page.goto("/video/task_time001");

    await expect(page.getByText("创建时间：")).toBeVisible();
    await expect(page.getByText("开始时间：")).toBeVisible();
    await expect(page.getByText("完成时间：")).toBeVisible();
  });
});

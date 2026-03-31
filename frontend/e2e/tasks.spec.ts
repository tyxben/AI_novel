import { test, expect, mockTask } from "./fixtures";

test.describe("Tasks Page", () => {
  test.beforeEach(async ({ page, mockApi }) => {
    await mockApi();
  });

  /* ------------------------------------------------------------------ */
  /*  Page header & structure                                            */
  /* ------------------------------------------------------------------ */

  test("should display page header with eyebrow, title, and description", async ({ page }) => {
    await page.goto("/tasks");
    // PageHeader renders eyebrow as uppercase <p>, title as <h2>
    await expect(page.locator("h2").filter({ hasText: "任务中心" })).toBeVisible();
    await expect(
      page.getByText("查看所有后台任务的运行状态、进度和结果。运行中任务自动刷新。")
    ).toBeVisible();
  });

  test("should display filter tab buttons", async ({ page }) => {
    await page.goto("/tasks");
    await expect(page.getByRole("button", { name: "全部" })).toBeVisible();
    await expect(page.getByRole("button", { name: "小说" })).toBeVisible();
    await expect(page.getByRole("button", { name: "视频" })).toBeVisible();
    await expect(page.getByRole("button", { name: "PPT" })).toBeVisible();
  });

  test("should display task list panel with title", async ({ page }) => {
    await page.goto("/tasks");
    // Panel title
    await expect(page.locator("h3").filter({ hasText: "任务列表" })).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Task rendering                                                     */
  /* ------------------------------------------------------------------ */

  test("should display a completed task with type label and status badge", async ({ page }) => {
    await page.goto("/tasks");
    // Default mock: task_type=novel_create -> label "创建小说"
    await expect(page.getByText("创建小说")).toBeVisible();
    // StatusBadge maps "completed" -> "已完成"
    await expect(page.getByText("已完成")).toBeVisible();
    // taskKindFromType: novel_create -> "小说", progress_msg "完成" renders as "小说 - 完成"
    await expect(page.getByText("小说 - 完成")).toBeVisible();
  });

  test("should display progress message in task subtitle", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [mockTask({ progress_msg: "正在生成第3章" })],
    });
    await page.goto("/tasks");
    await expect(page.getByText("正在生成第3章")).toBeVisible();
  });

  test("should show loading spinner when tasks are being fetched", async ({ page }) => {
    const API = "http://localhost:8000";
    // Delay the tasks API response to keep loading state visible
    await page.route(`${API}/api/tasks?*`, async (route) => {
      await new Promise((r) => setTimeout(r, 5000));
      await route.fulfill({ json: [mockTask()] });
    });
    await page.goto("/tasks");
    // TaskList renders "加载中..." with a Loader2 spinner
    await expect(page.getByText("加载中...")).toBeVisible();
  });

  test("should show empty state when no tasks exist", async ({ page, mockApi }) => {
    await mockApi({ tasks: [] });
    await page.goto("/tasks");
    // TaskList renders ListX icon + "暂无任务"
    await expect(page.getByText("暂无任务")).toBeVisible();
  });

  test("should show error message when API returns 500", async ({ page }) => {
    const API = "http://localhost:8000";
    await page.route(`${API}/api/tasks?*`, (route) =>
      route.fulfill({ status: 500, json: { detail: "Server error" } })
    );
    await page.route(`${API}/api/health`, (route) =>
      route.fulfill({ json: { status: "ok" } })
    );
    await page.goto("/tasks");
    // TaskList error state shows "加载失败"
    await expect(page.getByText("加载失败")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Multiple tasks                                                     */
  /* ------------------------------------------------------------------ */

  test("should display multiple tasks with different types and statuses", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({ task_id: "task_001", task_type: "novel_create", status: "completed" }),
        mockTask({
          task_id: "task_002",
          task_type: "video_generate",
          status: "running",
          progress: 0.5,
          progress_msg: "渲染中",
        }),
        mockTask({
          task_id: "task_003",
          task_type: "ppt_generate",
          status: "failed",
          error: "GPU 内存不足\n详细日志...",
        }),
      ],
    });
    await page.goto("/tasks");
    // Type labels
    await expect(page.getByText("创建小说")).toBeVisible();
    await expect(page.getByText("生成视频")).toBeVisible();
    await expect(page.getByText("生成PPT")).toBeVisible();
    // Running task shows progress message
    await expect(page.getByText("渲染中")).toBeVisible();
    // Failed task shows first line of error (split by \n)
    await expect(page.getByText("GPU 内存不足")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Filter tabs                                                        */
  /* ------------------------------------------------------------------ */

  test("should filter tasks by kind when clicking filter tabs", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({ task_id: "task_n1", task_type: "novel_create", status: "completed" }),
        mockTask({ task_id: "task_v1", task_type: "video_generate", status: "completed" }),
        mockTask({ task_id: "task_p1", task_type: "ppt_generate", status: "completed" }),
      ],
    });
    await page.goto("/tasks");

    // All tasks visible initially (filterKind = "")
    await expect(page.getByText("创建小说")).toBeVisible();
    await expect(page.getByText("生成视频")).toBeVisible();
    await expect(page.getByText("生成PPT")).toBeVisible();

    // Click "小说" filter - shows only novel tasks
    await page.getByRole("button", { name: "小说" }).click();
    await expect(page.getByText("创建小说")).toBeVisible();
    await expect(page.getByText("生成视频")).not.toBeVisible();
    await expect(page.getByText("生成PPT")).not.toBeVisible();

    // Click "视频" filter - shows only video tasks
    await page.getByRole("button", { name: "视频" }).click();
    await expect(page.getByText("创建小说")).not.toBeVisible();
    await expect(page.getByText("生成视频")).toBeVisible();
    await expect(page.getByText("生成PPT")).not.toBeVisible();

    // Click "PPT" filter - shows only PPT tasks
    await page.getByRole("button", { name: "PPT" }).click();
    await expect(page.getByText("创建小说")).not.toBeVisible();
    await expect(page.getByText("生成视频")).not.toBeVisible();
    await expect(page.getByText("生成PPT")).toBeVisible();

    // Click "全部" to reset
    await page.getByRole("button", { name: "全部" }).click();
    await expect(page.getByText("创建小说")).toBeVisible();
    await expect(page.getByText("生成视频")).toBeVisible();
    await expect(page.getByText("生成PPT")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Cancel button (running/pending tasks)                              */
  /* ------------------------------------------------------------------ */

  test("should show cancel button for running tasks", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({
          task_id: "task_running",
          task_type: "novel_generate",
          status: "running",
          progress: 0.3,
        }),
      ],
    });
    await page.goto("/tasks");
    // Cancel button has title="取消任务"
    await expect(page.getByTitle("取消任务")).toBeVisible();
  });

  test("should show cancel button for pending tasks", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({
          task_id: "task_pending",
          task_type: "novel_generate",
          status: "pending",
          progress: 0,
        }),
      ],
    });
    await page.goto("/tasks");
    await expect(page.getByTitle("取消任务")).toBeVisible();
  });

  test("should not show cancel button for completed tasks", async ({ page }) => {
    await page.goto("/tasks");
    // Default task is completed -> no cancel button
    await expect(page.getByTitle("取消任务")).not.toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Delete button (completed/failed/cancelled tasks)                   */
  /* ------------------------------------------------------------------ */

  test("should show delete button for completed tasks", async ({ page }) => {
    await page.goto("/tasks");
    // Delete button has title="删除任务"
    await expect(page.getByTitle("删除任务")).toBeVisible();
  });

  test("should show delete confirmation dialog on click", async ({ page }) => {
    await page.goto("/tasks");
    await page.getByTitle("删除任务").click();

    // Confirmation shows "确认" and "取消" buttons
    await expect(page.getByRole("button", { name: "确认" })).toBeVisible();
    await expect(page.getByRole("button", { name: "取消" })).toBeVisible();
  });

  test("should dismiss confirmation when cancel is clicked", async ({ page }) => {
    await page.goto("/tasks");
    await page.getByTitle("删除任务").click();

    // Click "取消" in the confirmation
    await page.getByRole("button", { name: "取消" }).click();

    // Confirmation buttons gone, delete button reappears
    await expect(page.getByTitle("删除任务")).toBeVisible();
    await expect(page.getByRole("button", { name: "确认" })).not.toBeVisible();
  });

  test("should send DELETE request when confirm is clicked", async ({ page }) => {
    let deleteRequested = false;
    const API = "http://localhost:8000";

    await page.route(`${API}/api/tasks/task_*`, (route) => {
      const method = route.request().method();
      if (method === "DELETE") {
        deleteRequested = true;
        return route.fulfill({ status: 204 });
      }
      if (method === "POST" && route.request().url().includes("/cancel"))
        return route.fulfill({ json: { msg: "Cancelled" } });
      return route.fulfill({ json: mockTask() });
    });

    await page.goto("/tasks");
    await page.getByTitle("删除任务").click();
    await page.getByRole("button", { name: "确认" }).click();

    await page.waitForTimeout(500);
    expect(deleteRequested).toBe(true);
  });

  test("should show delete button for failed tasks", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({ task_id: "task_fail", status: "failed", error: "Something went wrong" }),
      ],
    });
    await page.goto("/tasks");
    await expect(page.getByTitle("删除任务")).toBeVisible();
  });

  test("should show delete button for cancelled tasks", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({ task_id: "task_cancelled", status: "cancelled" }),
      ],
    });
    await page.goto("/tasks");
    await expect(page.getByTitle("删除任务")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Progress bar                                                       */
  /* ------------------------------------------------------------------ */

  test("should render progress bar for running task with correct width", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({
          task_id: "task_run",
          status: "running",
          progress: 0.6,
          finished_at: null,
        }),
      ],
    });
    await page.goto("/tasks");
    // Progress bar inner div uses inline style width: Math.round(0.6*100)% = 60%
    const progressBar = page.locator('[style*="width: 60%"]');
    await expect(progressBar).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Task type label mapping                                            */
  /* ------------------------------------------------------------------ */

  test("should display correct Chinese labels for all task types", async ({ page, mockApi }) => {
    const taskTypes = [
      { type: "novel_create", label: "创建小说" },
      { type: "novel_generate", label: "生成章节" },
      { type: "novel_polish", label: "精修润色" },
      { type: "novel_feedback", label: "反馈重写" },
      { type: "video_generate", label: "生成视频" },
      { type: "director_generate", label: "导演模式" },
      { type: "ppt_generate", label: "生成PPT" },
    ];

    await mockApi({
      tasks: taskTypes.map((t, i) =>
        mockTask({ task_id: `task_${i}`, task_type: t.type, status: "completed" })
      ),
    });
    await page.goto("/tasks");

    for (const t of taskTypes) {
      await expect(page.getByText(t.label).first()).toBeVisible();
    }
  });

  /* ------------------------------------------------------------------ */
  /*  Status badge labels                                                */
  /* ------------------------------------------------------------------ */

  test("should display correct status badge labels", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        mockTask({ task_id: "task_r", task_type: "novel_create", status: "running", progress: 0.5 }),
        mockTask({ task_id: "task_p", task_type: "novel_create", status: "pending", progress: 0 }),
        mockTask({ task_id: "task_c", task_type: "novel_create", status: "completed" }),
        mockTask({ task_id: "task_f", task_type: "novel_create", status: "failed", error: "err" }),
      ],
    });
    await page.goto("/tasks");
    // StatusBadge renders: running -> "运行中", pending -> "等待中", completed -> "已完成", failed -> "失败"
    await expect(page.getByText("运行中")).toBeVisible();
    await expect(page.getByText("等待中")).toBeVisible();
    await expect(page.getByText("已完成")).toBeVisible();
    await expect(page.getByText("失败")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Auto-refresh polling                                               */
  /* ------------------------------------------------------------------ */

  test("should auto-refresh when active tasks exist (3s interval)", async ({ page }) => {
    let fetchCount = 0;
    const API = "http://localhost:8000";

    await page.route(`${API}/api/tasks?*`, (route) => {
      fetchCount++;
      return route.fulfill({
        json: [
          mockTask({
            task_id: "task_active",
            status: "running",
            progress: 0.5,
          }),
        ],
      });
    });
    await page.route(`${API}/api/health`, (route) =>
      route.fulfill({ json: { status: "ok" } })
    );

    await page.goto("/tasks");
    await page.waitForTimeout(4000);

    // useTasks refetchInterval is 3000ms when hasActive is true
    // Should have initial fetch + at least 1 refetch
    expect(fetchCount).toBeGreaterThanOrEqual(2);
  });
});

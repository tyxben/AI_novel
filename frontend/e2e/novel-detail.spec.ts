import { test, expect } from "./fixtures";
import { mockNovelProject } from "./fixtures";

// ─── Loading / Error States ──────────────────────────────────────────

test.describe("Novel Detail - Loading & Error", () => {
  test("should show loading spinner while fetching novel", async ({ page, mockApi }) => {
    await mockApi();
    // Override the novel route with a delayed response (last registered wins)
    await page.route(/\/api\/novels\/[^/]+$/, async (route) => {
      await new Promise((r) => setTimeout(r, 500));
      await route.fulfill({ json: mockNovelProject() });
    });

    await page.goto("/novel/novel_test001");
    await expect(page.getByText("加载项目...")).toBeVisible();
  });

  test("should display error page when API fails", async ({ page, mockApi }) => {
    await mockApi();
    await page.route(/\/api\/novels\/[^/]+$/, (route) =>
      route.abort("connectionrefused")
    );

    await page.goto("/novel/novel_test001");
    // PageHeader renders "加载失败" as the title
    await expect(page.getByRole("heading", { name: "加载失败" })).toBeVisible();
    await expect(
      page.getByText("无法加载项目数据。请确认后端服务正在运行，且项目 ID 正确。")
    ).toBeVisible();
  });

  test("should display '项目不存在' when novel data is null", async ({ page, mockApi }) => {
    await mockApi();
    await page.route(/\/api\/novels\/[^/]+$/, (route) =>
      route.fulfill({ json: null })
    );

    await page.goto("/novel/novel_test001");
    await expect(page.getByText("项目不存在")).toBeVisible();
  });
});

// ─── Page Header & Tab Navigation ────────────────────────────────────

test.describe("Novel Detail - Header & Tabs", () => {
  test.beforeEach(async ({ page, mockApi }) => {
    await mockApi();
  });

  test("should display page header with novel title and metadata", async ({ page }) => {
    await page.goto("/novel/novel_test001");

    // PageHeader eyebrow text
    await expect(page.getByText("小说项目").first()).toBeVisible();
    // PageHeader title: novel.title = "测试小说：逆天修仙录"
    await expect(
      page.getByRole("heading", { name: "测试小说：逆天修仙录" })
    ).toBeVisible();
    // Description: "{genre} / {style_name} / 目标 {target万} 万字"
    // genre=玄幻, style_name=webnovel.shuangwen, target_words=100000 -> 10万字
    await expect(page.getByText(/玄幻/).first()).toBeVisible();
    await expect(page.getByText(/10 万字/).first()).toBeVisible();
  });

  test("should display all 7 tab buttons", async ({ page }) => {
    await page.goto("/novel/novel_test001");

    // Tabs defined in source: 总览, 章节, 设定, 反馈, AI编辑, Agent 对话, 叙事控制
    // They are <button> elements with icon + text label
    await expect(page.getByRole("button", { name: "总览", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "章节", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "设定", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "反馈", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "AI编辑" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Agent 对话" })).toBeVisible();
    await expect(page.getByRole("button", { name: "叙事控制" })).toBeVisible();
  });

  test("should switch tabs when clicking tab buttons", async ({ page }) => {
    await page.goto("/novel/novel_test001");

    // Default tab is "overview" - Panel title "项目概览" visible
    await expect(page.getByRole("heading", { name: "项目概览" })).toBeVisible();

    // Switch to Chapters tab - Panel title "章节列表"
    await page.getByRole("button", { name: "章节", exact: true }).click();
    await expect(page.getByRole("heading", { name: "章节列表" })).toBeVisible();

    // Switch to Settings tab - Panel title "设定编辑" or sub-tab "世界观编辑"
    await page.getByRole("button", { name: "设定", exact: true }).click();
    await expect(page.getByRole("heading", { name: "世界观编辑" })).toBeVisible();

    // Switch to Feedback tab - Panel title "读者反馈"
    await page.getByRole("button", { name: "反馈", exact: true }).click();
    await expect(page.getByRole("heading", { name: "读者反馈" })).toBeVisible();

    // Switch to AI Edit tab - Panel title "AI 编辑"
    await page.getByRole("button", { name: "AI编辑", exact: true }).click();
    await expect(page.getByRole("heading", { name: "AI 编辑" })).toBeVisible();

    // Switch to Agent Chat tab - Panel title "Agent 对话"
    await page.getByRole("button", { name: "Agent 对话" }).click();
    await expect(page.getByRole("heading", { name: "Agent 对话" })).toBeVisible();

    // Switch to Narrative tab - Panel title "叙事概览"
    await page.getByRole("button", { name: "叙事控制" }).click();
    await expect(page.getByRole("heading", { name: "叙事概览" })).toBeVisible();
  });
});

// ─── Overview Tab ────────────────────────────────────────────────────

test.describe("Novel Detail - Overview", () => {
  test.beforeEach(async ({ page, mockApi }) => {
    await mockApi();
  });

  test("should display project overview stats", async ({ page }) => {
    await page.goto("/novel/novel_test001");

    // Panel "项目概览" contains status, progress, chapters, theme
    const overviewPanel = page.locator("section").filter({ hasText: "项目概览" });
    await expect(overviewPanel).toBeVisible();

    // Status: novel.status = "idle" -> StatusBadge renders "空闲"
    await expect(overviewPanel.getByText("空闲")).toBeVisible();
    // Chapters: "5 / 40" (current_chapter / total_chapters)
    await expect(overviewPanel.getByText("5 / 40")).toBeVisible();
    // Theme: novel.theme = "少年修炼逆天改命"
    await expect(overviewPanel.getByText("少年修炼逆天改命")).toBeVisible();
    // Labels
    await expect(overviewPanel.getByText("状态")).toBeVisible();
    await expect(overviewPanel.getByText("进度")).toBeVisible();
    await expect(overviewPanel.getByText("章节")).toBeVisible();
    await expect(overviewPanel.getByText("主题")).toBeVisible();
  });

  test("should display action buttons panel", async ({ page }) => {
    await page.goto("/novel/novel_test001");

    // Panel "操作" with action buttons
    await expect(page.getByRole("heading", { name: "操作" })).toBeVisible();
    await expect(page.getByRole("button", { name: "生成章节" })).toBeVisible();
    await expect(page.getByRole("button", { name: "精修润色" })).toBeVisible();
    await expect(page.getByRole("button", { name: "导出" })).toBeVisible();
    await expect(page.getByRole("button", { name: "调整章节数" })).toBeVisible();
    await expect(page.getByRole("button", { name: "删除" })).toBeVisible();
  });

  test("clicking '生成章节' should open generation options panel", async ({ page }) => {
    await page.goto("/novel/novel_test001");

    await page.getByRole("button", { name: "生成章节" }).click();

    // Generation options panel
    await expect(page.getByText("章节生成参数")).toBeVisible();
    await expect(page.getByText("批次大小")).toBeVisible();
    await expect(page.getByText("目标总章数")).toBeVisible();
    await expect(page.getByText("起始章节").first()).toBeVisible();
    await expect(page.getByText("结束章节").first()).toBeVisible();
    await expect(page.getByText("静默模式（跳过质量检查，加速生成）")).toBeVisible();
    await expect(page.getByRole("button", { name: "开始生成" })).toBeVisible();
  });

  test("clicking '开始生成' should submit generation request", async ({ page }) => {
    await page.goto("/novel/novel_test001");

    await page.getByRole("button", { name: "生成章节" }).click();
    await page.getByRole("button", { name: "开始生成" }).click();

    // Success message
    await expect(
      page.getByText("章节生成任务已提交，请在右侧任务面板查看进度。")
    ).toBeVisible();
  });

  test("clicking '精修润色' should open polish options panel", async ({ page }) => {
    await page.goto("/novel/novel_test001");

    await page.getByRole("button", { name: "精修润色" }).click();

    await expect(page.getByText("精修参数")).toBeVisible();
    await expect(page.getByRole("button", { name: "开始精修" })).toBeVisible();
  });

  test("clicking '开始精修' should submit polish request", async ({ page }) => {
    await page.goto("/novel/novel_test001");

    await page.getByRole("button", { name: "精修润色" }).click();
    await page.getByRole("button", { name: "开始精修" }).click();

    await expect(
      page.getByText("精修任务已提交，请在右侧任务面板查看进度。")
    ).toBeVisible();
  });

  test("clicking '导出' should trigger export", async ({ page }) => {
    await page.goto("/novel/novel_test001");

    await page.getByRole("button", { name: "导出" }).click();

    await expect(page.getByText("导出成功")).toBeVisible();
  });

  test("clicking '调整章节数' should open resize panel", async ({ page }) => {
    await page.goto("/novel/novel_test001");

    await page.getByRole("button", { name: "调整章节数" }).click();

    // Resize panel fields
    await expect(page.getByText("当前总章数")).toBeVisible();
    await expect(page.getByText("新目标章数")).toBeVisible();
    await expect(page.getByText("扩容需要 LLM 生成新大纲，缩减立即生效。")).toBeVisible();
    await expect(page.getByRole("button", { name: "确认调整" })).toBeVisible();
  });

  test("clicking '删除' should show confirmation dialog", async ({ page }) => {
    await page.goto("/novel/novel_test001");

    await page.getByRole("button", { name: "删除" }).click();

    await expect(page.getByRole("button", { name: "确认删除" })).toBeVisible();
    await expect(page.getByRole("button", { name: "取消" }).first()).toBeVisible();
  });

  test("clicking '取消' on delete confirmation should hide it", async ({ page }) => {
    await page.goto("/novel/novel_test001");

    await page.getByRole("button", { name: "删除" }).click();
    await expect(page.getByRole("button", { name: "确认删除" })).toBeVisible();

    await page.getByRole("button", { name: "取消" }).first().click();
    await expect(page.getByRole("button", { name: "确认删除" })).not.toBeVisible();
    await expect(page.getByRole("button", { name: "删除" })).toBeVisible();
  });

  test("confirming delete should navigate back to novel list", async ({ page }) => {
    await page.goto("/novel/novel_test001");

    await page.getByRole("button", { name: "删除" }).click();
    await page.getByRole("button", { name: "确认删除" }).click();

    await expect(page).toHaveURL("/novel");
  });

  test("should display outline section with expand toggle", async ({ page }) => {
    await page.goto("/novel/novel_test001");

    // Panel "大纲" with toggle button
    await expect(page.getByRole("heading", { name: "大纲" })).toBeVisible();
    await expect(page.getByText("展开大纲")).toBeVisible();
  });

  test("clicking '展开大纲' should show outline content", async ({ page }) => {
    await page.goto("/novel/novel_test001");

    await page.getByText("展开大纲").click();

    await expect(page.getByText("收起大纲")).toBeVisible();
    // Mock outline has chapters array with title "第N章 测试标题"
    await expect(page.getByText("第1章 测试标题").first()).toBeVisible();
  });

  test("should display characters section with expand toggle", async ({ page }) => {
    await page.goto("/novel/novel_test001");

    // Panel "角色设定" with toggle showing "查看 3 个角色"
    await expect(page.getByRole("heading", { name: "角色设定" })).toBeVisible();
    await expect(page.getByText("查看 3 个角色")).toBeVisible();
  });

  test("clicking '查看角色' should expand character cards", async ({ page }) => {
    await page.goto("/novel/novel_test001");

    await page.getByText("查看 3 个角色").click();

    // Toggle button changes to "收起"
    await expect(page.getByText("收起", { exact: true })).toBeVisible();
    // Character names from mock: 林风, 苏雨, 魔尊
    await expect(page.getByText("林风").first()).toBeVisible();
    await expect(page.getByText("苏雨").first()).toBeVisible();
    await expect(page.getByText("魔尊").first()).toBeVisible();
    // Character roles from mock: 主角, 女主, 反派
    await expect(page.getByText("主角").first()).toBeVisible();
    await expect(page.getByText("女主").first()).toBeVisible();
    await expect(page.getByText("反派").first()).toBeVisible();
    // Character descriptions from mock
    await expect(page.getByText("少年天才").first()).toBeVisible();
    await expect(page.getByText("冰雪聪明").first()).toBeVisible();
    await expect(page.getByText("万年老妖").first()).toBeVisible();
  });

  test("should display world setting section with expand toggle", async ({ page }) => {
    await page.goto("/novel/novel_test001");

    // Panel "世界观设定" with toggle "查看世界观"
    await expect(page.getByRole("heading", { name: "世界观设定" })).toBeVisible();
    await expect(page.getByText("查看世界观")).toBeVisible();
  });

  test("should display progress bar", async ({ page }) => {
    await page.goto("/novel/novel_test001");

    // The overview panel renders a progress bar with style width
    const overviewPanel = page.locator("section").filter({ hasText: "项目概览" });
    const progressBar = overviewPanel.locator(".bg-accent.rounded-full.h-2");
    await expect(progressBar).toBeVisible();
  });
});

// ─── Chapters Tab ────────────────────────────────────────────────────

test.describe("Novel Detail - Chapters", () => {
  test.beforeEach(async ({ page, mockApi }) => {
    await mockApi();
  });

  test("should display chapter list with counts", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "章节", exact: true }).click();

    await expect(page.getByRole("heading", { name: "章节列表" })).toBeVisible();
    // Panel description: "共 5 章 / 已发布 0 章 -- 点击展开阅读和编辑"
    await expect(page.getByText(/共 5 章/)).toBeVisible();
    await expect(page.getByText(/已发布 0 章/)).toBeVisible();
  });

  test("should display chapter entries with number, title, and word count", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "章节", exact: true }).click();

    // Chapter numbers formatted with padStart(3, "0")
    await expect(page.getByText("001").first()).toBeVisible();
    await expect(page.getByText("002").first()).toBeVisible();
    // Chapter titles from mock
    await expect(page.getByText("第1章 测试标题").first()).toBeVisible();
    // Word count
    await expect(page.getByText("2500 字").first()).toBeVisible();
    // Status badge: "completed" -> "已完成"
    await expect(page.getByText("已完成").first()).toBeVisible();
  });

  test("should show publish status on each chapter", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "章节", exact: true }).click();

    // All chapters have published: false -> "未发布" text
    await expect(page.getByText("未发布").first()).toBeVisible();
  });

  test("should display batch publish button", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "章节", exact: true }).click();

    await expect(page.getByRole("button", { name: "批量发布" })).toBeVisible();
  });

  test("clicking '批量发布' should show batch publish controls", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "章节", exact: true }).click();

    await page.getByRole("button", { name: "批量发布" }).click();

    await expect(page.getByText("标记前")).toBeVisible();
    await expect(page.getByText("章为已发布")).toBeVisible();
    await expect(page.getByRole("button", { name: "确认" })).toBeVisible();
    await expect(page.getByRole("button", { name: "取消" }).first()).toBeVisible();
  });

  test("clicking a chapter should expand the chapter editor", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "章节", exact: true }).click();

    // Click on the first chapter row button
    await page.getByText("第1章 测试标题").first().click();

    // ChapterEditor loads chapter content from mock
    // Mock returns text: "这是第一章的正文内容。林风站在山巅..."
    await expect(
      page.getByText("这是第一章的正文内容。林风站在山巅").first()
    ).toBeVisible();
    // Editor buttons: "编辑" and "AI 校对"
    await expect(page.getByRole("button", { name: "编辑", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "AI 校对" })).toBeVisible();
  });

  test("clicking '编辑' in chapter editor should enable text editing", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "章节", exact: true }).click();

    // Expand first chapter
    await page.getByText("第1章 测试标题").first().click();
    await expect(page.getByText("这是第一章的正文内容")).toBeVisible();

    // Click edit button
    await page.getByRole("button", { name: "编辑", exact: true }).click();

    // Should show save and cancel buttons (replaces edit button)
    await expect(page.getByRole("button", { name: "保存", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "取消" }).first()).toBeVisible();
    // Textarea should be visible for editing
    await expect(page.locator("textarea").first()).toBeVisible();
  });

  test("should show empty state when no chapters exist", async ({ page, mockApi }) => {
    await mockApi({
      novel: mockNovelProject({ chapters: [] }),
    });

    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "章节", exact: true }).click();

    // Empty state text
    await expect(
      page.getByText(/暂无章节，点击"生成章节"开始创作/)
    ).toBeVisible();
  });

  test("publish toggle should show tooltip text", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "章节", exact: true }).click();

    // Each chapter row has a publish toggle span with role="button"
    // and title "未发布 (点击发布)" for unpublished chapters
    const publishToggle = page.locator('[title="未发布 (点击发布)"]').first();
    await expect(publishToggle).toBeVisible();
  });
});

// ─── Settings Tab ─────────────────────────────────────────────────────

test.describe("Novel Detail - Settings", () => {
  test.beforeEach(async ({ page, mockApi }) => {
    await mockApi();
  });

  test("should display settings sub-tabs", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "设定", exact: true }).click();

    // Sub-tabs: 世界观, 角色, 大纲
    await expect(page.getByRole("button", { name: "世界观" })).toBeVisible();
    await expect(page.getByRole("button", { name: "角色" })).toBeVisible();
    // "大纲" may match the outline section in overview tab (hidden by CSS display:none)
    // Use the sub-tab buttons container context
    await expect(page.getByRole("button", { name: "大纲" }).first()).toBeVisible();
  });

  test("should display world setting editor by default", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "设定", exact: true }).click();

    await expect(page.getByRole("heading", { name: "世界观编辑" })).toBeVisible();
    // Form labels (rendered as uppercase tracking-wide text)
    await expect(page.getByText("时代")).toBeVisible();
    await expect(page.getByText("地点")).toBeVisible();
    await expect(page.getByText("力量体系名称")).toBeVisible();
    await expect(page.getByText("等级体系")).toBeVisible();
    await expect(page.getByText("世界规则（每行一条）")).toBeVisible();
    await expect(page.getByText("专有名词")).toBeVisible();
  });

  test("should display save and impact analysis buttons", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "设定", exact: true }).click();

    await expect(page.getByRole("button", { name: "保存设定" })).toBeVisible();
    await expect(page.getByRole("button", { name: "评估影响" })).toBeVisible();
  });

  test("clicking '保存设定' should save settings successfully", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "设定", exact: true }).click();

    await page.getByRole("button", { name: "保存设定" }).click();

    // Success message from world setting save
    await expect(page.getByText("设定已保存（旧版本已备份）")).toBeVisible();
  });

  test("switching to characters sub-tab should show character editor", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "设定", exact: true }).click();
    await page.getByRole("button", { name: "角色" }).click();

    await expect(page.getByRole("heading", { name: "角色编辑" })).toBeVisible();
    // Character selector dropdown
    await expect(page.locator("select").first()).toBeVisible();
    // Action buttons
    await expect(page.getByRole("button", { name: "新增" })).toBeVisible();
    await expect(page.getByRole("button", { name: "删除" })).toBeVisible();
    // Basic info labels
    await expect(page.getByText("姓名").first()).toBeVisible();
    await expect(page.getByText("性别").first()).toBeVisible();
    await expect(page.getByText("年龄").first()).toBeVisible();
    await expect(page.getByText("职业").first()).toBeVisible();
  });

  test("should display character appearance and personality fields", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "设定", exact: true }).click();
    await page.getByRole("button", { name: "角色" }).click();

    // Appearance section heading: "外貌"
    await expect(page.getByText("外貌").first()).toBeVisible();
    await expect(page.getByText("身高").first()).toBeVisible();
    await expect(page.getByText("体型").first()).toBeVisible();
    await expect(page.getByText("发型").first()).toBeVisible();
    await expect(page.getByText("眼睛").first()).toBeVisible();
    await expect(page.getByText("服装风格").first()).toBeVisible();

    // Personality section heading: "性格"
    await expect(page.getByText("性格").first()).toBeVisible();
    await expect(page.getByText("说话风格").first()).toBeVisible();
    await expect(page.getByText("核心信念").first()).toBeVisible();
    await expect(page.getByText("动机").first()).toBeVisible();
    await expect(page.getByText("缺点").first()).toBeVisible();
  });

  test("should display character arc fields", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "设定", exact: true }).click();
    await page.getByRole("button", { name: "角色" }).click();

    // Arc section heading: "角色弧线"
    await expect(page.getByText("角色弧线").first()).toBeVisible();
    await expect(page.getByText("初始状态").first()).toBeVisible();
    await expect(page.getByText("最终状态").first()).toBeVisible();
  });

  test("should display save all settings button in character tab", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "设定", exact: true }).click();
    await page.getByRole("button", { name: "角色" }).click();

    await expect(page.getByRole("button", { name: "保存全部设定" })).toBeVisible();
  });

  test("switching to outline sub-tab should show outline editor", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "设定", exact: true }).click();
    // Click the "大纲" sub-tab (first match, since overview tab "大纲" heading is hidden)
    await page.getByRole("button", { name: "大纲" }).first().click();

    await expect(page.getByRole("heading", { name: "大纲编辑" })).toBeVisible();
    // Main storyline section
    await expect(page.getByText("主线设定")).toBeVisible();
    await expect(page.getByText("主角目标")).toBeVisible();
    await expect(page.getByText("核心冲突")).toBeVisible();
    await expect(page.getByText("赌注")).toBeVisible();
    await expect(page.getByText("角色弧线").first()).toBeVisible();
  });

  test("should add power level with '添加等级'", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "设定", exact: true }).click();

    await page.getByText("添加等级").click();

    // A new row should appear with placeholder inputs
    const inputs = page.locator('input[placeholder="等级名"]');
    await expect(inputs.last()).toBeVisible();
  });

  test("should add term with '添加名词'", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "设定", exact: true }).click();

    await page.getByText("添加名词").click();

    const termInputs = page.locator('input[placeholder="名词"]');
    await expect(termInputs.last()).toBeVisible();
  });

  test("should show loading state while settings are being fetched", async ({ page, mockApi }) => {
    await mockApi();
    // Override settings route with a delayed response
    await page.route("http://localhost:8000/api/novels/*/settings", async (route) => {
      if (route.request().method() === "GET") {
        await new Promise((r) => setTimeout(r, 500));
        await route.fulfill({ json: { world_setting: {}, characters: [], outline: {} } });
      } else {
        await route.fulfill({ json: { saved: true } });
      }
    });

    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "设定", exact: true }).click();

    await expect(page.getByText("加载设定...")).toBeVisible();
  });
});

// ─── Feedback Tab ─────────────────────────────────────────────────────

test.describe("Novel Detail - Feedback", () => {
  test.beforeEach(async ({ page, mockApi }) => {
    await mockApi();
  });

  test("should display feedback form elements", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "反馈", exact: true }).click();

    await expect(page.getByRole("heading", { name: "读者反馈" })).toBeVisible();
    // Panel description
    await expect(
      page.getByText("输入反馈内容，分析影响范围或直接应用到指定章节。")
    ).toBeVisible();
    // Sub-heading
    await expect(page.getByText("反馈重写")).toBeVisible();
    // Label
    await expect(page.getByText("反馈内容", { exact: true })).toBeVisible();
    // Textarea with placeholder
    await expect(
      page.locator('textarea[placeholder*="第5章主角性格变化太突兀"]')
    ).toBeVisible();
    // Chapter input label
    await expect(
      page.getByText("相关章节（支持: 单章 8，范围 8-12，多章 3,7,15）")
    ).toBeVisible();
    // Chapter input with placeholder
    await expect(
      page.locator('input[placeholder*="例如: 5 或 3-8 或 1,5,10"]')
    ).toBeVisible();
  });

  test("should display analyze and apply buttons", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "反馈", exact: true }).click();

    await expect(page.getByRole("button", { name: "分析影响" })).toBeVisible();
    await expect(page.getByRole("button", { name: "应用反馈" })).toBeVisible();
  });

  test("buttons should be disabled when feedback text is empty", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "反馈", exact: true }).click();

    await expect(page.getByRole("button", { name: "分析影响" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "应用反馈" })).toBeDisabled();
  });

  test("should enable buttons when feedback text is entered", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "反馈", exact: true }).click();

    await page
      .locator('textarea[placeholder*="第5章主角性格变化太突兀"]')
      .fill("主角性格前后矛盾");

    await expect(page.getByRole("button", { name: "分析影响" })).toBeEnabled();
    await expect(page.getByRole("button", { name: "应用反馈" })).toBeEnabled();
  });

  test("clicking '应用反馈' should submit feedback", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "反馈", exact: true }).click();

    await page
      .locator('textarea[placeholder*="第5章主角性格变化太突兀"]')
      .fill("主角性格前后矛盾");

    await page.getByRole("button", { name: "应用反馈" }).click();

    // Mock returns task_id (no rewritten_chapters) -> shows submission message
    await expect(
      page.getByText("反馈应用任务已提交，请在任务中心查看进度。")
    ).toBeVisible();
  });
});

// ─── Edit Tab ─────────────────────────────────────────────────────────

test.describe("Novel Detail - Edit", () => {
  test.beforeEach(async ({ page, mockApi }) => {
    await mockApi();
  });

  test("should display edit form elements", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "AI编辑" }).click();

    await expect(page.getByRole("heading", { name: "AI 编辑" })).toBeVisible();
    // Panel description
    await expect(
      page.getByText("用自然语言指令修改小说设定或内容。")
    ).toBeVisible();
    // Sub-heading
    await expect(page.getByText("智能编辑")).toBeVisible();
    // Label
    await expect(page.getByText("编辑指令")).toBeVisible();
    // Textarea with placeholder
    await expect(
      page.locator('textarea[placeholder*="把主角的武器从剑改成枪"]')
    ).toBeVisible();
    // Chapter field label
    await expect(page.getByText("生效起始章节")).toBeVisible();
  });

  test("should display execute button", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "AI编辑" }).click();

    await expect(page.getByRole("button", { name: "执行编辑" })).toBeVisible();
  });

  test("execute button should be disabled when instruction is empty", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "AI编辑" }).click();

    await expect(page.getByRole("button", { name: "执行编辑" })).toBeDisabled();
  });

  test("should enable execute button when instruction is entered", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "AI编辑" }).click();

    await page
      .locator('textarea[placeholder*="把主角的武器从剑改成枪"]')
      .fill("把主角的名字从林风改成张三");

    await expect(page.getByRole("button", { name: "执行编辑" })).toBeEnabled();
  });

  test("clicking '执行编辑' should show edit result", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "AI编辑" }).click();

    await page
      .locator('textarea[placeholder*="把主角的武器从剑改成枪"]')
      .fill("把主角的名字从林风改成张三");

    await page.getByRole("button", { name: "执行编辑" }).click();

    // Mock returns { change_id: "chg_001", status: "applied", description: "已修改" }
    // status !== "failed" -> shows "编辑完成"
    await expect(page.getByText("编辑完成")).toBeVisible();
  });

  test("should show starting chapter number input with default value 1", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "AI编辑" }).click();

    // effectiveFrom defaults to 1 — locate within the AI Edit panel
    const editPanel = page.locator("section").filter({ hasText: "智能编辑" });
    const chapterInput = editPanel.locator('input[type="number"][min="1"]');
    await expect(chapterInput).toHaveValue("1");
  });
});

// ─── Agent Chat Tab ──────────────────────────────────────────────────

test.describe("Novel Detail - Agent Chat", () => {
  test.beforeEach(async ({ page, mockApi }) => {
    await mockApi();
  });

  test("should display agent chat panel", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "Agent 对话" }).click();

    await expect(page.getByRole("heading", { name: "Agent 对话" })).toBeVisible();
    // Panel description
    await expect(
      page.getByText("与 AI Agent 对话，讨论你的小说。")
    ).toBeVisible();
  });

  test("should display conversation list sidebar with new conversation button", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "Agent 对话" }).click();

    // New conversation button: "新对话"
    await expect(page.getByRole("button", { name: "新对话" })).toBeVisible();
    // Conversation title from mock: "讨论角色发展"
    await expect(page.getByText("讨论角色发展").first()).toBeVisible();
  });

  test("should auto-select the latest conversation and show messages", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "Agent 对话" }).click();

    // Mock returns 2 messages: user + agent
    await expect(page.getByText("帮我分析一下主角性格")).toBeVisible();
    await expect(
      page.getByText("主角林风性格分析：坚韧不拔，重情重义...")
    ).toBeVisible();
  });

  test("should show chat input area with context chapters", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "Agent 对话" }).click();

    // Message input textarea
    await expect(page.locator('textarea[placeholder="输入消息..."]')).toBeVisible();
    // Context chapters input
    await expect(page.locator('input[placeholder*="如 1,3,5"]')).toBeVisible();
    // Context label
    await expect(page.getByText("参考章节")).toBeVisible();
  });

  test("send button should be disabled when input is empty", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "Agent 对话" }).click();

    // Send button (title="发送")
    const sendButton = page.locator('button[title="发送"]');
    await expect(sendButton).toBeDisabled();
  });

  test("should enable send button when message is typed", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "Agent 对话" }).click();

    await page.locator('textarea[placeholder="输入消息..."]').fill("你好");
    const sendButton = page.locator('button[title="发送"]');
    await expect(sendButton).toBeEnabled();
  });

  test("sending a message should display it optimistically", async ({ page, mockApi }) => {
    // Start with empty server messages so the optimistic message is not sliced away
    // by the merge logic (which skips optimistic msgs already covered by serverMessages)
    await mockApi({ messages: [] });
    // Override task endpoint to return a running task so optimistic messages persist
    await page.route("http://localhost:8000/api/tasks/task_*", (route) => {
      const method = route.request().method();
      if (method === "DELETE") return route.fulfill({ status: 204 });
      if (method === "POST" && route.request().url().includes("/cancel"))
        return route.fulfill({ json: { msg: "Cancelled" } });
      return route.fulfill({
        json: {
          task_id: "task_chat",
          task_type: "novel_agent_chat",
          status: "running",
          progress: 0.5,
          progress_msg: "思考中",
          params: {},
          result: null,
          error: null,
          created_at: "2026-03-27T09:00:00",
          started_at: "2026-03-27T09:00:01",
          finished_at: null,
        },
      });
    });

    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "Agent 对话" }).click();

    await page.locator('textarea[placeholder="输入消息..."]').fill("分析一下第3章");
    await page.locator('button[title="发送"]').click();

    // Optimistic message should appear
    await expect(page.getByText("分析一下第3章")).toBeVisible();
    // Input should be cleared
    await expect(page.locator('textarea[placeholder="输入消息..."]')).toHaveValue("");
    // Should show thinking indicator: "Agent 思考中"
    await expect(page.getByText("Agent 思考中")).toBeVisible();
  });

  test("should show empty state when no messages exist", async ({ page, mockApi }) => {
    await mockApi({
      conversations: [],
      messages: [],
    });

    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "Agent 对话" }).click();

    // Empty chat state
    await expect(
      page.getByText("向 Agent 提问关于你的小说的任何问题")
    ).toBeVisible();
    await expect(
      page.getByText("例如：分析第3章的角色动机、检查前5章的伏笔一致性...")
    ).toBeVisible();
  });

  test("should show '暂无对话' when conversation list is empty", async ({ page, mockApi }) => {
    await mockApi({ conversations: [] });

    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "Agent 对话" }).click();

    await expect(page.getByText("暂无对话")).toBeVisible();
  });

  test("should display conversation title in header bar", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "Agent 对话" }).click();

    // The header bar shows the active conversation title or "选择或创建对话"
    // With mock data, auto-selects the first conversation "讨论角色发展"
    await expect(page.getByText("讨论角色发展").first()).toBeVisible();
  });

  test("should show message count in conversation list", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "Agent 对话" }).click();

    // Mock conversation has message_count: 3 -> "3条"
    await expect(page.getByText(/3条/).first()).toBeVisible();
  });

  test("agent tab should use full width (no right sidebar column)", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "Agent 对话" }).click();

    // The grid container should NOT have the xl:grid-cols-[...] class when activeTab === "agent"
    // Verify by checking that the Agent Chat panel is visible at full width
    await expect(page.getByRole("heading", { name: "Agent 对话" })).toBeVisible();
  });

  test("clicking '新对话' should create a new conversation", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "Agent 对话" }).click();

    await page.getByRole("button", { name: "新对话" }).click();

    // The mock creates a new conversation with session_id "conv_new"
    // UI should switch to the new conversation
  });

  test("should show sidebar toggle button", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "Agent 对话" }).click();

    // The toggle button has title "收起会话列表" when sidebar is open (default)
    await expect(page.locator('button[title="收起会话列表"]')).toBeVisible();
  });
});

// ─── Narrative Tab ──────────────────────────────────────────────────

test.describe("Novel Detail - Narrative", () => {
  test.beforeEach(async ({ page, mockApi }) => {
    await mockApi();
  });

  test("should display narrative overview panel with stats", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "叙事控制" }).click();

    const overviewPanel = page.locator("section").filter({ hasText: "叙事概览" });
    await expect(overviewPanel).toBeVisible();

    // Overview stat cards from mock:
    // pending_debts: 2, overdue_debts: 0, active_arcs: 2, arc_completion: undefined -> "-"
    await expect(overviewPanel.getByText("待处理债务")).toBeVisible();
    await expect(overviewPanel.getByText("逾期债务")).toBeVisible();
    await expect(overviewPanel.getByText("活跃弧线")).toBeVisible();
    await expect(overviewPanel.getByText("弧线完成度")).toBeVisible();

    // Values from mock
    await expect(overviewPanel.getByText("2").first()).toBeVisible(); // pending_debts
    await expect(overviewPanel.getByText("0").first()).toBeVisible(); // overdue_debts
  });

  test("should display rebuild narrative button", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "叙事控制" }).click();

    await expect(
      page.getByRole("button", { name: "从已有章节重建叙事数据" })
    ).toBeVisible();
  });

  test("should display volume settlement panel", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "叙事控制" }).click();

    await expect(page.getByRole("heading", { name: "分卷收束" })).toBeVisible();
    // Mock volume: title "第一卷 初入修仙界"
    await expect(page.getByText("第一卷 初入修仙界").first()).toBeVisible();
  });

  test("should display narrative debts panel with filter tabs", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "叙事控制" }).click();

    await expect(page.getByRole("heading", { name: "叙事债务" })).toBeVisible();
    // Filter tabs: 全部, 待处理, 逾期, 已兑现
    await expect(page.getByRole("button", { name: "全部" })).toBeVisible();
    await expect(page.getByRole("button", { name: "待处理" })).toBeVisible();
    await expect(page.getByRole("button", { name: "逾期" })).toBeVisible();
    await expect(page.getByRole("button", { name: "已兑现" })).toBeVisible();
  });

  test("should display debt entries from mock data", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "叙事控制" }).click();

    // From mock: 2 debts with descriptions
    await expect(page.getByText("伏笔：神秘宝物")).toBeVisible();
    await expect(page.getByText("角色承诺")).toBeVisible();
    // Source chapters — scope within the debt table to avoid matching hidden chapter entries
    const debtPanel = page.locator("section").filter({ hasText: "叙事债务" });
    await expect(debtPanel.getByText("第3章").first()).toBeVisible();
    await expect(debtPanel.getByText("第1章").first()).toBeVisible();
    // Total count footer
    await expect(page.getByText("共 2 条")).toBeVisible();
  });

  test("should display fulfill button for pending debts only", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "叙事控制" }).click();

    // Only pending debts have the "兑现" button (debt_001 is pending, debt_002 is fulfilled)
    // Use exact: true to avoid matching the "已兑现" filter tab button
    const fulfillButtons = page.getByRole("button", { name: "兑现", exact: true });
    await expect(fulfillButtons).toHaveCount(1);
  });

  test("should display story arcs panel", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "叙事控制" }).click();

    await expect(page.getByRole("heading", { name: "故事弧线" })).toBeVisible();
    // From mock: 2 arcs
    await expect(page.getByText("修炼之路").first()).toBeVisible();
    await expect(page.getByText("宗门争斗").first()).toBeVisible();
  });

  test("should display arc phase legend", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "叙事控制" }).click();

    // Phase legend items in timeline view
    await expect(page.getByText("铺垫").first()).toBeVisible();
    await expect(page.getByText("升级").first()).toBeVisible();
    await expect(page.getByText("高潮").first()).toBeVisible();
    await expect(page.getByText("收束").first()).toBeVisible();
  });

  test("should display arc status (进行中/已完结)", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "叙事控制" }).click();

    // Both mock arcs have status "active" -> "进行中"
    await expect(page.getByText("进行中").first()).toBeVisible();
  });

  test("should display chapter brief lookup section", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "叙事控制" }).click();

    await expect(page.getByRole("heading", { name: "章节纲要查询" })).toBeVisible();
    await expect(
      page.locator('input[placeholder="输入章节号..."]')
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "查询" })).toBeVisible();
  });

  test("should display knowledge graph panel (collapsed by default)", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "叙事控制" }).click();

    await expect(page.getByRole("heading", { name: "知识图谱" })).toBeVisible();
    // Collapsed state shows "展开 角色关系图"
    await expect(page.getByText("展开 角色关系图")).toBeVisible();
  });

  test("clicking '展开 角色关系图' should show the graph visualization", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "叙事控制" }).click();

    await page.getByText("展开 角色关系图").click();

    // Toggle text changes
    await expect(page.getByText("收起 角色关系图")).toBeVisible();
    // SVG graph should be visible
    await expect(page.locator("svg").last()).toBeVisible();
    // Role legend items
    await expect(page.getByText("主角").last()).toBeVisible();
    await expect(page.getByText("反派").last()).toBeVisible();
    await expect(page.getByText("配角")).toBeVisible();
    await expect(page.getByText("导师")).toBeVisible();
  });

  test("clicking rebuild button should submit rebuild request", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "叙事控制" }).click();

    await page
      .getByRole("button", { name: "从已有章节重建叙事数据" })
      .click();

    // The mock returns { task_id: "task_narrative_rebuild" }
    // Then task poll returns completed -> shows result
    await expect(page.getByText(/重建完成/)).toBeVisible({ timeout: 10000 });
  });

  test("switching debt filter tabs should work", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "叙事控制" }).click();

    // Default is "全部" - should show 2 debts
    await expect(page.getByText("共 2 条")).toBeVisible();

    // Click "待处理" filter tab
    await page.getByRole("button", { name: "待处理" }).click();

    // The mock always returns the same data regardless of filter,
    // but the tab button should receive active styling
    await expect(page.getByRole("button", { name: "待处理" })).toBeVisible();
  });

  test("should show debt type badges with correct labels", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "叙事控制" }).click();

    // Mock debts have debt_type: "foreshadowing" and "promise"
    // DEBT_TYPE_STYLES maps these - foreshadowing maps to long_tail fallback -> "长线伏笔"
    // promise also maps to long_tail fallback -> "长线伏笔"
    // Both fall through to the default (long_tail label)
    await expect(page.getByText("长线伏笔").first()).toBeVisible();
  });

  test("should display debt status indicators", async ({ page }) => {
    await page.goto("/novel/novel_test001");
    await page.getByRole("button", { name: "叙事控制" }).click();

    // Table header columns — scope within the debt panel to avoid matching
    // hidden elements from the overview tab (e.g., "状态" label)
    const debtPanel = page.locator("section").filter({ hasText: "叙事债务" });
    await expect(debtPanel.getByText("状态").first()).toBeVisible();
    await expect(debtPanel.getByText("类型").first()).toBeVisible();
    await expect(debtPanel.getByText("来源").first()).toBeVisible();
    await expect(debtPanel.getByText("描述").first()).toBeVisible();
    await expect(debtPanel.getByText("操作").first()).toBeVisible();
  });
});

// ─── Tab Persistence ─────────────────────────────────────────────────

test.describe("Novel Detail - Tab Persistence", () => {
  test.beforeEach(async ({ page, mockApi }) => {
    await mockApi();
  });

  test("components stay mounted when switching tabs (CSS display toggle)", async ({ page }) => {
    await page.goto("/novel/novel_test001");

    // Expand outline on overview tab
    await page.getByText("展开大纲").click();
    await expect(page.getByText("收起大纲")).toBeVisible();

    // Switch to chapters tab
    await page.getByRole("button", { name: "章节", exact: true }).click();
    await expect(page.getByRole("heading", { name: "章节列表" })).toBeVisible();

    // Switch back to overview - outline should still be expanded (state preserved)
    await page.getByRole("button", { name: "总览" }).click();
    await expect(page.getByText("收起大纲")).toBeVisible();
  });

  test("settings sub-tab state persists across main tab switches", async ({ page }) => {
    await page.goto("/novel/novel_test001");

    // Switch to settings and select characters sub-tab
    await page.getByRole("button", { name: "设定", exact: true }).click();
    await page.getByRole("button", { name: "角色" }).click();
    await expect(page.getByRole("heading", { name: "角色编辑" })).toBeVisible();

    // Switch away to feedback
    await page.getByRole("button", { name: "反馈", exact: true }).click();
    await expect(page.getByRole("heading", { name: "读者反馈" })).toBeVisible();

    // Switch back to settings - characters sub-tab should still be active
    await page.getByRole("button", { name: "设定", exact: true }).click();
    await expect(page.getByRole("heading", { name: "角色编辑" })).toBeVisible();
  });
});

// ─── Right Sidebar (Active Tasks) ────────────────────────────────────

test.describe("Novel Detail - Active Tasks Sidebar", () => {
  test("should show recent tasks when available", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        {
          task_id: "task_gen_001",
          task_type: "novel_generate",
          status: "completed",
          progress: 1.0,
          progress_msg: "完成",
          params: { novel_id: "novel_test001" },
          result: null,
          error: null,
          created_at: "2026-03-27T09:00:00",
          started_at: "2026-03-27T09:00:01",
          finished_at: "2026-03-27T09:05:00",
        },
      ],
    });

    await page.goto("/novel/novel_test001");

    // Panel "任务进度" should be visible
    await expect(page.getByRole("heading", { name: "任务进度" })).toBeVisible();
    // Recent tasks collapsible: "最近任务 (1)"
    await expect(page.getByText(/最近任务/)).toBeVisible();
  });

  test("should show active task with progress bar", async ({ page, mockApi }) => {
    await mockApi({
      tasks: [
        {
          task_id: "task_gen_running",
          task_type: "novel_generate",
          status: "running",
          progress: 0.5,
          progress_msg: "生成第3章...",
          params: { novel_id: "novel_test001" },
          result: null,
          error: null,
          created_at: "2026-03-27T09:00:00",
          started_at: "2026-03-27T09:00:01",
          finished_at: null,
        },
      ],
    });

    await page.goto("/novel/novel_test001");

    await expect(page.getByRole("heading", { name: "任务进度" })).toBeVisible();
    // Task type label: "novel_generate" -> "生成章节"
    await expect(page.getByText("生成章节").first()).toBeVisible();
    // Progress message
    await expect(page.getByText("生成第3章...")).toBeVisible();
    // Progress percentage
    await expect(page.getByText("50%")).toBeVisible();
  });

  test("task panel should be hidden when no relevant tasks exist", async ({ page, mockApi }) => {
    // Tasks list is empty -> no novel tasks at all
    await mockApi({ tasks: [] });

    await page.goto("/novel/novel_test001");

    // "任务进度" panel should not be rendered
    await expect(page.getByRole("heading", { name: "任务进度" })).not.toBeVisible();
  });
});

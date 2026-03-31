import { test, expect, mockPromptBlock } from "./fixtures";

test.describe("Prompts Page", () => {
  test.beforeEach(async ({ page, mockApi }) => {
    await mockApi();
  });

  /* ------------------------------------------------------------------ */
  /*  Page header & structure                                            */
  /* ------------------------------------------------------------------ */

  test("should display page header with eyebrow, title, and description", async ({ page }) => {
    await page.goto("/prompts");
    // PageHeader eyebrow (uppercase tracking text)
    await expect(page.getByText("PROMPT REGISTRY")).toBeVisible();
    // PageHeader title (h2)
    await expect(page.locator("h2").filter({ hasText: "Prompt 管理" })).toBeVisible();
    // PageHeader description
    await expect(
      page.getByText(
        "管理 Prompt Block 版本、模板组装和 A/B 测试。支持按 Agent、类型筛选，编辑保存自动创建新版本。"
      )
    ).toBeVisible();
  });

  test("should display main panels", async ({ page }) => {
    await page.goto("/prompts");
    // Panel titles rendered as <h3>
    await expect(page.locator("h3").filter({ hasText: "Prompt Blocks" })).toBeVisible();
    await expect(page.locator("h3").filter({ hasText: "Prompt 模板" })).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Block list                                                         */
  /* ------------------------------------------------------------------ */

  test("should display block list with type badge, agent badge, version, and score", async ({ page }) => {
    await page.goto("/prompts");
    // Default mock has one block: block_writer_system
    const blockItem = page.locator("button").filter({ hasText: "block_writer_system" });
    await expect(blockItem.first()).toBeVisible();

    // Block type badge (rounded-full span)
    await expect(blockItem.locator("span.rounded-full").filter({ hasText: "system" }).first()).toBeVisible();
    // Agent badge
    await expect(blockItem.locator("span.rounded-full").filter({ hasText: "writer" }).first()).toBeVisible();
    // Version text "v3"
    await expect(blockItem.getByText("v3")).toBeVisible();
    // Score "8.5"
    await expect(blockItem.getByText("8.5")).toBeVisible();
    // Usage count
    await expect(blockItem.getByText("42 次使用")).toBeVisible();
  });

  test("should display multiple blocks", async ({ page, mockApi }) => {
    await mockApi({
      promptBlocks: [
        mockPromptBlock({ base_id: "block_writer_system", block_type: "system", agent: "writer" }),
        mockPromptBlock({ base_id: "block_style_guide", block_type: "style_guide", agent: "style_keeper", version: 2, avg_score: 7.5, usage_count: 10 }),
        mockPromptBlock({ base_id: "block_anti_pattern", block_type: "anti_pattern", agent: "universal", version: 1, avg_score: null, usage_count: 0 }),
      ],
    });
    await page.goto("/prompts");
    await expect(page.getByText("block_writer_system")).toBeVisible();
    await expect(page.getByText("block_style_guide")).toBeVisible();
    await expect(page.getByText("block_anti_pattern")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Block list filters                                                 */
  /* ------------------------------------------------------------------ */

  test("should have agent and type filter dropdowns", async ({ page }) => {
    await page.goto("/prompts");
    // Two <select> elements for agent and type filters
    const selects = page.locator("select");
    await expect(selects.first()).toBeVisible();
    await expect(selects.nth(1)).toBeVisible();
  });

  test("should filter blocks by agent via API query param", async ({ page, mockApi }) => {
    let lastRequestUrl = "";
    const API = "http://localhost:8000";

    // Override blocks route to track query params
    await page.route(`${API}/api/prompts/blocks*`, (route) => {
      lastRequestUrl = route.request().url();
      const url = route.request().url();
      if (url.match(/\/blocks\/[^/?]+$/) && !url.includes("versions")) {
        return route.fulfill({ json: mockPromptBlock() });
      }
      if (url.includes("/versions")) {
        return route.fulfill({ json: [] });
      }
      return route.fulfill({ json: [mockPromptBlock()] });
    });

    await page.goto("/prompts");

    // Select "Writer" from agent filter (first select)
    const agentSelect = page.locator("select").first();
    await agentSelect.selectOption("writer");

    await page.waitForTimeout(500);
    expect(lastRequestUrl).toContain("agent=writer");
  });

  test("should filter blocks by type via API query param", async ({ page, mockApi }) => {
    let lastRequestUrl = "";
    const API = "http://localhost:8000";

    await page.route(`${API}/api/prompts/blocks*`, (route) => {
      lastRequestUrl = route.request().url();
      const url = route.request().url();
      if (url.match(/\/blocks\/[^/?]+$/) && !url.includes("versions")) {
        return route.fulfill({ json: mockPromptBlock() });
      }
      if (url.includes("/versions")) {
        return route.fulfill({ json: [] });
      }
      return route.fulfill({ json: [mockPromptBlock()] });
    });

    await page.goto("/prompts");

    // Select "anti_pattern" from type filter (second select)
    const typeSelect = page.locator("select").nth(1);
    await typeSelect.selectOption("anti_pattern");

    await page.waitForTimeout(500);
    expect(lastRequestUrl).toContain("block_type=anti_pattern");
  });

  /* ------------------------------------------------------------------ */
  /*  Empty state with seed button                                       */
  /* ------------------------------------------------------------------ */

  test("should show empty state with seed button when no blocks exist", async ({ page, mockApi }) => {
    await mockApi({ promptBlocks: [] });
    await page.goto("/prompts");
    // Empty state text
    await expect(page.getByText("暂无 Prompt Block 数据")).toBeVisible();
    // Seed button
    await expect(page.getByRole("button", { name: "初始化种子数据" })).toBeVisible();
  });

  test("should call seed API and show creation counts", async ({ page, mockApi }) => {
    await mockApi({ promptBlocks: [] });
    await page.goto("/prompts");

    await page.getByRole("button", { name: "初始化种子数据" }).click();

    // Success message shows count from mock: { blocks_count: 15, templates_count: 5 }
    await expect(page.getByText(/已创建 15 个 Block，5 个模板/)).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Block detail: no selection                                         */
  /* ------------------------------------------------------------------ */

  test("should show placeholder when no block is selected", async ({ page }) => {
    await page.goto("/prompts");
    await expect(page.getByText("从左侧列表选择一个 Block 查看详情")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Block detail: selected                                             */
  /* ------------------------------------------------------------------ */

  test("should show block detail with stats and editor when clicked", async ({ page }) => {
    await page.goto("/prompts");
    // Click the block in the list
    await page.getByText("block_writer_system").first().click();

    // Wait for detail to load (textarea appears)
    const textarea = page.locator("textarea");
    await expect(textarea).toBeVisible({ timeout: 10000 });

    // Detail stats badges
    await expect(page.getByText(/Agent:.*writer/)).toBeVisible();
    await expect(page.getByText("使用 42 次")).toBeVisible();
    await expect(page.getByText(/评分.*8\.5/)).toBeVisible();

    // Editor label
    await expect(page.getByText("内容 (编辑后保存将创建新版本)")).toBeVisible();
    // Textarea contains the block content
    await expect(textarea).toHaveValue("你是一个专业的小说写作AI助手。");
  });

  test("should show block_type and version in detail panel description", async ({ page }) => {
    await page.goto("/prompts");
    await page.getByText("block_writer_system").first().click();
    await expect(page.locator("textarea")).toBeVisible({ timeout: 10000 });
    // Panel description shows "block_type | vN"
    await expect(page.getByText("system | v3")).toBeVisible();
  });

  test("should show created date in detail", async ({ page }) => {
    await page.goto("/prompts");
    await page.getByText("block_writer_system").first().click();
    await expect(page.locator("textarea")).toBeVisible({ timeout: 10000 });
    // created_at: "2026-03-20T10:00:00" rendered via toLocaleDateString("zh-CN")
    await expect(page.getByText(/创建于/)).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Block editing                                                      */
  /* ------------------------------------------------------------------ */

  test("should enable save button only when content is modified", async ({ page }) => {
    await page.goto("/prompts");
    await page.getByText("block_writer_system").first().click();

    const textarea = page.locator("textarea");
    await expect(textarea).toBeVisible({ timeout: 10000 });

    // Save button disabled initially (editDirty=false)
    const saveBtn = page.getByRole("button", { name: "保存新版本" });
    await expect(saveBtn).toBeDisabled();

    // Edit the content
    await textarea.fill("修改后的内容");

    // Now enabled
    await expect(saveBtn).toBeEnabled();
  });

  test("should save content and show success message", async ({ page }) => {
    await page.goto("/prompts");
    await page.getByText("block_writer_system").first().click();

    const textarea = page.locator("textarea");
    await expect(textarea).toBeVisible({ timeout: 10000 });

    await textarea.fill("修改后的内容");

    const saveBtn = page.getByRole("button", { name: "保存新版本" });
    await saveBtn.click();

    // updateBlock.isSuccess shows "已保存"
    await expect(page.getByText("已保存")).toBeVisible();
  });

  test("should disable save button after successful save", async ({ page }) => {
    await page.goto("/prompts");
    await page.getByText("block_writer_system").first().click();

    const textarea = page.locator("textarea");
    await expect(textarea).toBeVisible({ timeout: 10000 });

    await textarea.fill("新内容");

    const saveBtn = page.getByRole("button", { name: "保存新版本" });
    await saveBtn.click();

    await expect(page.getByText("已保存")).toBeVisible();
    // editDirty is reset to false after save -> button disabled
    await expect(saveBtn).toBeDisabled();
  });

  /* ------------------------------------------------------------------ */
  /*  Version history                                                    */
  /* ------------------------------------------------------------------ */

  test("should display version history panel when block is selected", async ({ page }) => {
    await page.goto("/prompts");
    await page.getByText("block_writer_system").first().click();
    await expect(page.locator("textarea")).toBeVisible({ timeout: 10000 });

    // Version history panel
    await expect(page.locator("h3").filter({ hasText: "版本历史" })).toBeVisible();
    await expect(page.getByText("点击回滚到指定版本")).toBeVisible();

    // Versions v3, v2, v1 from mock data
    const versionPanel = page.locator("section").filter({ hasText: "版本历史" }).filter({ hasText: "点击回滚到指定版本" });
    await expect(versionPanel.getByText("v3")).toBeVisible();
    await expect(versionPanel.getByText("v2")).toBeVisible();
    await expect(versionPanel.getByText("v1")).toBeVisible();
  });

  test("should mark current version with a badge instead of rollback button", async ({ page }) => {
    await page.goto("/prompts");
    await page.getByText("block_writer_system").first().click();
    await expect(page.locator("textarea")).toBeVisible({ timeout: 10000 });

    // v3 is current (matches detail.version=3) -> shows "当前" badge
    await expect(page.getByText("当前")).toBeVisible();
  });

  test("should show rollback buttons for non-current versions", async ({ page }) => {
    await page.goto("/prompts");
    await page.getByText("block_writer_system").first().click();
    await expect(page.locator("textarea")).toBeVisible({ timeout: 10000 });

    // v2 and v1 should have rollback buttons (v3 is current)
    const rollbackButtons = page.getByRole("button", { name: "回滚" });
    await expect(rollbackButtons).toHaveCount(2);
  });

  test("should send rollback request when clicking rollback button", async ({ page }) => {
    let rollbackRequested = false;

    await page.route(/\/api\/prompts\/blocks\/[^/]+\/rollback/, (route) => {
      rollbackRequested = true;
      return route.fulfill({ json: { ...mockPromptBlock(), version: 2 } });
    });

    await page.goto("/prompts");
    await page.getByText("block_writer_system").first().click();
    await expect(page.locator("textarea")).toBeVisible({ timeout: 10000 });

    // Click the first rollback button (for v2)
    const rollbackButtons = page.getByRole("button", { name: "回滚" });
    await rollbackButtons.first().click();

    await page.waitForTimeout(500);
    expect(rollbackRequested).toBe(true);
  });

  test("should display version scores in version history", async ({ page }) => {
    await page.goto("/prompts");
    await page.getByText("block_writer_system").first().click();
    await expect(page.locator("textarea")).toBeVisible({ timeout: 10000 });

    // Version scores: v3=8.5, v2=7.8, v1=7.0
    const versionPanel = page.locator("section").filter({ hasText: "版本历史" }).filter({ hasText: "点击回滚到指定版本" });
    await expect(versionPanel.getByText("8.5")).toBeVisible();
    await expect(versionPanel.getByText("7.8")).toBeVisible();
    await expect(versionPanel.getByText("7.0")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Preview / Build Prompt                                             */
  /* ------------------------------------------------------------------ */

  test("should display preview panel when block is selected", async ({ page }) => {
    await page.goto("/prompts");
    await page.getByText("block_writer_system").first().click();
    await expect(page.locator("textarea")).toBeVisible({ timeout: 10000 });

    await expect(page.locator("h3").filter({ hasText: "预览组装" })).toBeVisible();
    await expect(
      page.getByText("选择 Agent + 场景 + 类型，预览最终拼装的 Prompt")
    ).toBeVisible();
  });

  test("should have preview form with Agent select, scenario input, and genre input", async ({ page }) => {
    await page.goto("/prompts");
    await page.getByText("block_writer_system").first().click();
    await expect(page.locator("textarea")).toBeVisible({ timeout: 10000 });

    // Scenario placeholder
    await expect(page.getByPlaceholder("如: chapter_write")).toBeVisible();
    // Genre placeholder
    await expect(page.getByPlaceholder("如: 玄幻")).toBeVisible();
    // Preview button
    await expect(page.getByRole("button", { name: "预览组装结果" })).toBeVisible();
  });

  test("should build and display preview result with character count", async ({ page }) => {
    await page.goto("/prompts");
    await page.getByText("block_writer_system").first().click();
    await expect(page.locator("textarea")).toBeVisible({ timeout: 10000 });

    // Fill scenario and genre
    await page.getByPlaceholder("如: chapter_write").fill("chapter_write");
    await page.getByPlaceholder("如: 玄幻").fill("玄幻");

    // Click preview button
    await page.getByRole("button", { name: "预览组装结果" }).click();

    // Preview result area shows "组装结果" heading (distinct from button text)
    await expect(page.getByText("组装结果", { exact: true })).toBeVisible();
    // Mock returns { prompt: "构建的完整prompt内容...", length: 500 }
    await expect(page.getByText("构建的完整prompt内容...")).toBeVisible();
    // Character count display
    await expect(page.getByText(/\d+ 字符/)).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Templates section                                                  */
  /* ------------------------------------------------------------------ */

  test("should display templates table with headers", async ({ page }) => {
    await page.goto("/prompts");

    await expect(page.locator("h3").filter({ hasText: "Prompt 模板" })).toBeVisible();
    await expect(
      page.getByText("模板定义了 Agent 在特定场景下使用的 Block 组合")
    ).toBeVisible();

    // Table headers
    await expect(page.getByText("模板 ID")).toBeVisible();
    // Template data from mock
    await expect(page.getByText("tpl_001")).toBeVisible();
    await expect(page.getByText("1 个 Block")).toBeVisible();
  });

  test("should show empty templates message when no templates exist", async ({ page, mockApi }) => {
    await mockApi({ promptTemplates: [] });
    await page.goto("/prompts");
    await expect(page.getByText("暂无模板数据，请先初始化种子数据")).toBeVisible();
  });

  test("should expand template row to show block refs on click", async ({ page }) => {
    await page.goto("/prompts");

    // Click the template row
    await page.getByText("tpl_001").click();

    // Should reveal block ref button
    await expect(
      page.getByRole("button", { name: "block_writer_system", exact: true })
    ).toBeVisible();
  });

  test("should select block when clicking block ref in expanded template", async ({ page }) => {
    await page.goto("/prompts");

    // Expand template
    await page.getByText("tpl_001").click();

    // Click the block ref button (distinct from the block list item)
    await page.getByRole("button", { name: "block_writer_system", exact: true }).click();

    // Should load block detail -> textarea appears with block content
    const textarea = page.locator("textarea");
    await expect(textarea).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/Agent:.*writer/)).toBeVisible();
    await expect(textarea).toHaveValue("你是一个专业的小说写作AI助手。");
  });

  test("should display template fields correctly for multi-block template", async ({ page, mockApi }) => {
    await mockApi({
      promptTemplates: [
        {
          template_id: "tpl_fantasy",
          agent_name: "writer",
          scenario: "chapter_write",
          genre: "玄幻",
          block_refs: ["block_writer_system", "block_fantasy_style"],
        },
      ],
    });
    await page.goto("/prompts");

    await expect(page.getByText("tpl_fantasy")).toBeVisible();
    await expect(page.getByText("chapter_write")).toBeVisible();
    await expect(page.getByText("玄幻")).toBeVisible();
    await expect(page.getByText("2 个 Block")).toBeVisible();
  });

  test("should show dash for null scenario and genre in template row", async ({ page }) => {
    await page.goto("/prompts");
    // Default template: scenario="default", genre=null
    // genre null renders as "-" in the <td>
    const templateRow = page.locator("tr").filter({ hasText: "tpl_001" });
    await expect(templateRow.getByText("-")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Loading state                                                      */
  /* ------------------------------------------------------------------ */

  test("should render block list after loading", async ({ page }) => {
    const API = "http://localhost:8000";
    await page.route(`${API}/api/prompts/blocks*`, async (route) => {
      const url = route.request().url();
      // Delay only the list request
      if (!url.match(/\/blocks\/[^/?]+/) && !url.includes("versions") && !url.includes("rollback")) {
        await new Promise((r) => setTimeout(r, 5000));
      }
      return route.fulfill({ json: [mockPromptBlock()] });
    });
    await page.route(`${API}/api/prompts/templates*`, (route) =>
      route.fulfill({ json: [] })
    );
    await page.route(`${API}/api/health`, (route) =>
      route.fulfill({ json: { status: "ok" } })
    );

    await page.goto("/prompts");
    // Eventually the block list renders
    await expect(page.getByText("block_writer_system").first()).toBeVisible({ timeout: 10000 });
  });

  /* ------------------------------------------------------------------ */
  /*  Block selection state management                                   */
  /* ------------------------------------------------------------------ */

  test("should clear preview result when switching blocks", async ({ page, mockApi }) => {
    await mockApi({
      promptBlocks: [
        mockPromptBlock({ base_id: "block_a", block_type: "system", agent: "writer" }),
        mockPromptBlock({ base_id: "block_b", block_type: "style_guide", agent: "style_keeper" }),
      ],
    });
    await page.goto("/prompts");

    // Select first block
    await page.getByText("block_a").click();
    await expect(page.locator("textarea")).toBeVisible({ timeout: 10000 });

    // Build a preview
    await page.getByRole("button", { name: "预览组装结果" }).click();
    await expect(page.getByText("组装结果", { exact: true })).toBeVisible();

    // Switch to second block -> preview result should clear
    await page.getByText("block_b").click();
    await expect(page.getByText("组装结果", { exact: true })).not.toBeVisible();
  });

  test("should reset dirty state when switching blocks", async ({ page, mockApi }) => {
    await mockApi({
      promptBlocks: [
        mockPromptBlock({ base_id: "block_a" }),
        mockPromptBlock({ base_id: "block_b" }),
      ],
    });
    await page.goto("/prompts");

    // Select first block and edit content
    await page.getByText("block_a").click();
    const textarea = page.locator("textarea");
    await expect(textarea).toBeVisible({ timeout: 10000 });
    await textarea.fill("edited content");
    const saveBtn = page.getByRole("button", { name: "保存新版本" });
    await expect(saveBtn).toBeEnabled();

    // Switch to second block -> dirty state resets
    await page.getByText("block_b").click();
    await expect(saveBtn).toBeDisabled();
  });
});

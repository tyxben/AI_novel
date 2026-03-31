import { test, expect } from "./fixtures";

test.describe("Video Create Page", () => {
  test.beforeEach(async ({ page, mockApi }) => {
    await mockApi();
  });

  /* ------------------------------------------------------------------ */
  /*  Page header and layout                                             */
  /* ------------------------------------------------------------------ */

  test("should display page header with correct title and description", async ({ page }) => {
    await page.goto("/video/create");
    await expect(page.locator("h2")).toContainText("创建视频项目");
    await expect(
      page.getByText("选择创作模式，输入内容后提交到任务队列自动生成视频。")
    ).toBeVisible();
  });

  test("should show back link to video list", async ({ page }) => {
    await page.goto("/video/create");
    const backLink = page.locator("a[href='/video']").filter({ hasText: "返回列表" });
    await expect(backLink).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Mode selector                                                      */
  /* ------------------------------------------------------------------ */

  test("should default to director mode", async ({ page }) => {
    await page.goto("/video/create");
    // Director mode Panel should be visible (Panel title "AI 导演模式")
    // The mode selector also has an h3 with "AI 导演模式", so use first()
    await expect(page.locator("h3").filter({ hasText: "AI 导演模式" }).first()).toBeVisible();
    await expect(page.getByText("创意灵感", { exact: true })).toBeVisible();
  });

  test("should show both mode selector buttons", async ({ page }) => {
    await page.goto("/video/create");
    await expect(page.locator("h3").filter({ hasText: "AI 导演模式" }).first()).toBeVisible();
    await expect(page.locator("h3").filter({ hasText: "经典模式" }).first()).toBeVisible();
  });

  test("should show director mode description", async ({ page }) => {
    await page.goto("/video/create");
    await expect(
      page.getByText("输入一句创意灵感，AI 自动规划脚本、生成素材并合成视频。")
    ).toBeVisible();
  });

  test("should show classic mode description", async ({ page }) => {
    await page.goto("/video/create");
    await expect(
      page.getByText("提供一个文本文件，按照传统流水线分段、生图、配音、合成。")
    ).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Director mode                                                      */
  /* ------------------------------------------------------------------ */

  test("should show director mode fields by default", async ({ page }) => {
    await page.goto("/video/create");
    await expect(page.getByText("创意灵感", { exact: true })).toBeVisible();
    await expect(page.locator("textarea")).toBeVisible();
    await expect(page.getByText("目标时长：60 秒")).toBeVisible();
    await expect(page.getByText("预算级别", { exact: true })).toBeVisible();
  });

  test("should show inspiration textarea with placeholder", async ({ page }) => {
    await page.goto("/video/create");
    const textarea = page.locator("textarea");
    await expect(textarea).toHaveAttribute(
      "placeholder",
      "例如：一个孤独的宇航员在火星上发现了一朵花..."
    );
  });

  test("should display budget level options", async ({ page }) => {
    await page.goto("/video/create");
    await expect(page.getByText("纯图片 + TTS")).toBeVisible();
    await expect(page.getByText("图片 + AI 视频片段")).toBeVisible();
    await expect(page.getByText("全 AI 视频片段")).toBeVisible();
  });

  test("should show duration range slider with min/max labels", async ({ page }) => {
    await page.goto("/video/create");
    await expect(page.getByText("30 秒").first()).toBeVisible();
    await expect(page.getByText("180 秒")).toBeVisible();
  });

  test("should validate empty inspiration in director mode", async ({ page }) => {
    await page.goto("/video/create");
    // Submit without entering anything
    await page.locator("button[type='submit']").click();
    await expect(page.getByText("请输入创意灵感")).toBeVisible();
  });

  test("should submit director mode form and navigate to detail", async ({ page }) => {
    await page.goto("/video/create");

    // Fill inspiration
    await page.locator("textarea").fill("一个关于AI的未来世界故事");

    // Submit
    await page.locator("button[type='submit']").click();

    // Should navigate to the task detail page
    await page.waitForURL(/\/video\/task_video_create/);
    expect(page.url()).toContain("/video/task_video_create");
  });

  /* ------------------------------------------------------------------ */
  /*  Classic mode                                                       */
  /* ------------------------------------------------------------------ */

  test("should switch to classic mode when clicking classic button", async ({ page }) => {
    await page.goto("/video/create");

    // Click classic mode -- the mode selector h3 appears first
    await page.locator("h3").filter({ hasText: "经典模式" }).first().click();

    // Classic fields should appear
    await expect(page.getByText("文本文件路径", { exact: true })).toBeVisible();
    await expect(page.getByText("运行模式", { exact: true })).toBeVisible();
    // Director-specific fields should be hidden
    await expect(page.getByText("创意灵感", { exact: true })).not.toBeVisible();
  });

  test("should show classic mode panel with correct description", async ({ page }) => {
    await page.goto("/video/create");
    await page.locator("h3").filter({ hasText: "经典模式" }).first().click();

    await expect(page.getByText("指定文本文件和运行配置")).toBeVisible();
  });

  test("should show file path input with placeholder", async ({ page }) => {
    await page.goto("/video/create");
    await page.locator("h3").filter({ hasText: "经典模式" }).first().click();

    const fileInput = page.locator("input[placeholder='例如：input/novel.txt']");
    await expect(fileInput).toBeVisible();
    await expect(page.getByText("输入服务器上的文件路径")).toBeVisible();
  });

  test("should show run mode options in classic mode", async ({ page }) => {
    await page.goto("/video/create");
    await page.locator("h3").filter({ hasText: "经典模式" }).first().click();

    await expect(page.getByText("经典流水线")).toBeVisible();
    await expect(page.locator("button").filter({ hasText: "Agent 模式" })).toBeVisible();
    await expect(page.getByText("顺序执行各阶段")).toBeVisible();
    await expect(page.getByText("多 Agent 协作决策")).toBeVisible();
  });

  test("should show agent options when agent run mode is selected", async ({ page }) => {
    await page.goto("/video/create");
    await page.locator("h3").filter({ hasText: "经典模式" }).first().click();

    // Agent options should not be visible initially
    await expect(page.getByText("Agent 模式选项")).not.toBeVisible();

    // Select Agent mode
    await page.locator("button").filter({ hasText: "Agent 模式" }).click();

    // Agent-specific options should appear
    await expect(page.getByText("Agent 模式选项")).toBeVisible();
    await expect(page.getByText("省钱模式（减少 LLM 调用）")).toBeVisible();
    await expect(page.getByText("质量阈值：7.0")).toBeVisible();
  });

  test("should show quality threshold slider with labels in agent mode", async ({ page }) => {
    await page.goto("/video/create");
    await page.locator("h3").filter({ hasText: "经典模式" }).first().click();
    await page.locator("button").filter({ hasText: "Agent 模式" }).click();

    await expect(page.getByText("1.0（宽松）")).toBeVisible();
    await expect(page.getByText("10.0（严格）")).toBeVisible();
  });

  test("should validate empty input in classic mode", async ({ page }) => {
    await page.goto("/video/create");
    await page.locator("h3").filter({ hasText: "经典模式" }).first().click();

    // Submit without entering anything
    await page.locator("button[type='submit']").click();
    await expect(page.getByText("请输入文本内容或文本文件路径")).toBeVisible();
  });

  test("should submit classic mode form with file path", async ({ page }) => {
    await page.goto("/video/create");
    await page.locator("h3").filter({ hasText: "经典模式" }).first().click();

    // Fill file path
    await page.locator("input[placeholder='例如：input/novel.txt']").fill("input/story.txt");

    // Submit
    await page.locator("button[type='submit']").click();

    // Should navigate
    await page.waitForURL(/\/video\/task_video_create/);
    expect(page.url()).toContain("/video/task_video_create");
  });

  /* ------------------------------------------------------------------ */
  /*  Advanced settings                                                  */
  /* ------------------------------------------------------------------ */

  test("should toggle advanced settings accordion", async ({ page }) => {
    await page.goto("/video/create");

    // Advanced settings should be collapsed initially
    await expect(page.getByText("高级设置")).toBeVisible();
    await expect(page.getByText("画风、配音、画质、分辨率、编码器、AI视频")).toBeVisible();

    // Style dropdown should not be visible
    await expect(page.getByText("画风", { exact: true })).not.toBeVisible();

    // Click to expand
    await page.locator("button").filter({ hasText: "高级设置" }).click();

    // Style dropdown should now be visible
    await expect(page.getByText("画风", { exact: true })).toBeVisible();
    await expect(page.getByText("配音", { exact: true })).toBeVisible();
    await expect(page.getByText("语速", { exact: true })).toBeVisible();
  });

  test("should show all advanced setting fields when expanded", async ({ page }) => {
    await page.goto("/video/create");
    await page.locator("button").filter({ hasText: "高级设置" }).click();

    for (const label of ["画风", "配音", "语速", "图片生成后端", "LLM 服务", "分辨率", "画质", "编码器", "视频素材模式"]) {
      await expect(page.getByText(label, { exact: true })).toBeVisible();
    }
  });

  test("should show AI video backend selector when ai_video mode is chosen", async ({ page }) => {
    await page.goto("/video/create");
    await page.locator("button").filter({ hasText: "高级设置" }).click();

    // AI video backend should not be visible initially (default is static)
    await expect(page.getByText("AI 视频后端", { exact: true })).not.toBeVisible();

    // Select AI video mode via the select element next to "视频素材模式" label
    const videoModeSelect = page.locator("label").filter({ hasText: "视频素材模式" }).locator("..").locator("select");
    await videoModeSelect.selectOption("ai_video");

    // Now the AI video backend selector should appear
    await expect(page.getByText("AI 视频后端", { exact: true })).toBeVisible();
  });

  test("should have correct default values for advanced settings", async ({ page }) => {
    await page.goto("/video/create");
    await page.locator("button").filter({ hasText: "高级设置" }).click();

    // Check default select values
    const styleSelect = page.locator("label").filter({ hasText: "画风" }).locator("..").locator("select");
    await expect(styleSelect).toHaveValue("anime");

    const voiceSelect = page.locator("label").filter({ hasText: "配音" }).locator("..").locator("select");
    await expect(voiceSelect).toHaveValue("zh-CN-YunxiNeural");

    const rateSelect = page.locator("label").filter({ hasText: "语速" }).locator("..").locator("select");
    await expect(rateSelect).toHaveValue("+0%");

    const resolutionSelect = page.locator("label").filter({ hasText: "分辨率" }).locator("..").locator("select");
    await expect(resolutionSelect).toHaveValue("9:16");

    const codecSelect = page.locator("label").filter({ hasText: "编码器" }).locator("..").locator("select");
    await expect(codecSelect).toHaveValue("libx265");
  });

  test("should show submit button with correct text", async ({ page }) => {
    await page.goto("/video/create");
    const submitBtn = page.locator("button[type='submit']");
    await expect(submitBtn).toContainText("开始创建");
  });

  /* ------------------------------------------------------------------ */
  /*  Mode switching preserves form isolation                            */
  /* ------------------------------------------------------------------ */

  test("should switch between modes without losing advanced settings", async ({ page }) => {
    await page.goto("/video/create");

    // Open advanced and change style
    await page.locator("button").filter({ hasText: "高级设置" }).click();
    await page.locator("label").filter({ hasText: "画风" }).locator("..").locator("select").selectOption("realistic");

    // Switch to classic
    await page.locator("h3").filter({ hasText: "经典模式" }).first().click();
    await expect(page.getByText("文本文件路径", { exact: true })).toBeVisible();

    // Advanced style should still be realistic
    const styleSelect = page.locator("label").filter({ hasText: "画风" }).locator("..").locator("select");
    await expect(styleSelect).toHaveValue("realistic");

    // Switch back to director
    await page.locator("h3").filter({ hasText: "AI 导演模式" }).first().click();
    await expect(page.getByText("创意灵感", { exact: true })).toBeVisible();

    // Style should still be realistic
    await expect(styleSelect).toHaveValue("realistic");
  });
});

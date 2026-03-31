import { test, expect } from "./fixtures";

test.describe("PPT Create Page", () => {
  test.beforeEach(async ({ page, mockApi }) => {
    await mockApi();
  });

  /* ------------------------------------------------------------------ */
  /*  Page header and layout                                             */
  /* ------------------------------------------------------------------ */

  test("should display page header with correct title and description", async ({ page }) => {
    await page.goto("/ppt/create");
    await expect(page.locator("h2")).toContainText("创建 PPT 项目");
    await expect(
      page.getByText("选择输入方式，设置主题和参数后提交到任务队列自动生成幻灯片大纲。")
    ).toBeVisible();
  });

  test("should show back link to PPT list", async ({ page }) => {
    await page.goto("/ppt/create");
    const backLink = page.locator("a[href='/ppt']").filter({ hasText: "返回列表" });
    await expect(backLink).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Mode selector                                                      */
  /* ------------------------------------------------------------------ */

  test("should default to topic mode", async ({ page }) => {
    await page.goto("/ppt/create");
    // Topic mode panel should be visible with its Panel title "主题设置"
    await expect(page.locator("h3").filter({ hasText: "主题设置" })).toBeVisible();
    await expect(page.getByText("演示主题", { exact: true }).first()).toBeVisible();
  });

  test("should show both mode buttons with descriptions", async ({ page }) => {
    await page.goto("/ppt/create");
    await expect(page.locator("h3").filter({ hasText: "主题模式" })).toBeVisible();
    await expect(
      page.getByText("输入演示主题和受众类型，AI 自动生成结构化大纲和内容。")
    ).toBeVisible();
    await expect(page.locator("h3").filter({ hasText: "文档模式" })).toBeVisible();
    await expect(
      page.getByText("粘贴已有文档文本，AI 自动提取关键信息并生成幻灯片。")
    ).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Topic mode                                                         */
  /* ------------------------------------------------------------------ */

  test("should show topic mode fields", async ({ page }) => {
    await page.goto("/ppt/create");
    await expect(page.getByText("演示主题", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("受众类型", { exact: true })).toBeVisible();
    await expect(page.getByText("演示场景", { exact: true })).toBeVisible();
  });

  test("should show topic textarea with placeholder", async ({ page }) => {
    await page.goto("/ppt/create");
    const textarea = page.locator(
      "textarea[placeholder='例如：2024年Q3产品运营数据复盘及Q4增长策略']"
    );
    await expect(textarea).toBeVisible();
  });

  test("should display all audience type options", async ({ page }) => {
    await page.goto("/ppt/create");
    for (const label of ["商务人士", "技术人员", "教育场景", "创意人群", "通用"]) {
      await expect(page.locator("button").filter({ hasText: label })).toBeVisible();
    }
  });

  test("should display all scenario options", async ({ page }) => {
    await page.goto("/ppt/create");
    for (const label of ["季度汇报", "产品发布", "技术分享", "课程讲义", "融资路演", "工作坊", "进度更新"]) {
      await expect(page.locator("button").filter({ hasText: label })).toBeVisible();
    }
  });

  test("should select different audience type", async ({ page }) => {
    await page.goto("/ppt/create");

    // Default is business ("商务人士"), click technical ("技术人员")
    const techButton = page.locator("button").filter({ hasText: "技术人员" });
    await techButton.click();

    // Check it has the selected style (border-accent)
    await expect(techButton).toHaveClass(/border-accent/);
  });

  test("should select different scenario", async ({ page }) => {
    await page.goto("/ppt/create");

    const productButton = page.locator("button").filter({ hasText: "产品发布" });
    await productButton.click();
    await expect(productButton).toHaveClass(/border-accent/);
  });

  test("should validate empty topic in topic mode", async ({ page }) => {
    await page.goto("/ppt/create");
    await page.locator("button[type='submit']").click();
    await expect(page.getByText("请输入演示主题")).toBeVisible();
  });

  test("should submit topic mode form and navigate to detail", async ({ page }) => {
    await page.goto("/ppt/create");

    // Fill topic
    await page
      .locator("textarea[placeholder='例如：2024年Q3产品运营数据复盘及Q4增长策略']")
      .fill("2026年AI发展趋势分析");

    // Submit
    await page.locator("button[type='submit']").click();

    // Should navigate to the PPT task page
    await page.waitForURL(/\/ppt\/task_ppt_create/);
    expect(page.url()).toContain("/ppt/task_ppt_create");
  });

  /* ------------------------------------------------------------------ */
  /*  Document mode                                                      */
  /* ------------------------------------------------------------------ */

  test("should switch to document mode when clicking document button", async ({ page }) => {
    await page.goto("/ppt/create");
    // Click the mode button (the h3 is inside the button)
    await page.locator("h3").filter({ hasText: "文档模式" }).click();

    // Document panel should appear with Panel title "文档输入"
    await expect(page.locator("h3").filter({ hasText: "文档输入" })).toBeVisible();
    await expect(page.getByText("文档内容", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("粘贴文档内容")).toBeVisible();

    // Topic-specific fields should be hidden
    await expect(page.locator("h3").filter({ hasText: "主题设置" })).not.toBeVisible();
  });

  test("should show document textarea with placeholder", async ({ page }) => {
    await page.goto("/ppt/create");
    await page.locator("h3").filter({ hasText: "文档模式" }).click();

    const textarea = page.locator(
      "textarea[placeholder='在这里粘贴要转换为 PPT 的文档文本...']"
    );
    await expect(textarea).toBeVisible();
  });

  test("should validate empty document text in document mode", async ({ page }) => {
    await page.goto("/ppt/create");
    await page.locator("h3").filter({ hasText: "文档模式" }).click();

    await page.locator("button[type='submit']").click();
    await expect(page.getByText("请输入文档内容")).toBeVisible();
  });

  test("should submit document mode form and navigate", async ({ page }) => {
    await page.goto("/ppt/create");
    await page.locator("h3").filter({ hasText: "文档模式" }).click();

    await page
      .locator("textarea[placeholder='在这里粘贴要转换为 PPT 的文档文本...']")
      .fill("这是一份关于AI技术发展的详细文档，包含多个章节...");

    await page.locator("button[type='submit']").click();
    await page.waitForURL(/\/ppt\/task_ppt_create/);
    expect(page.url()).toContain("/ppt/task_ppt_create");
  });

  /* ------------------------------------------------------------------ */
  /*  Common settings (theme + page count)                               */
  /* ------------------------------------------------------------------ */

  test("should display theme style options", async ({ page }) => {
    await page.goto("/ppt/create");

    await expect(page.locator("h3").filter({ hasText: "通用设置" })).toBeVisible();
    await expect(page.getByText("主题风格", { exact: true })).toBeVisible();

    // All 5 theme options
    for (const label of ["简约现代", "商务正式", "创意活泼", "科技极客", "教育清新"]) {
      await expect(page.locator("button").filter({ hasText: label })).toBeVisible();
    }
  });

  test("should display theme descriptions", async ({ page }) => {
    await page.goto("/ppt/create");
    for (const desc of ["简洁专业", "稳重大方", "色彩丰富", "硬核风格", "温和友好"]) {
      await expect(page.getByText(desc)).toBeVisible();
    }
  });

  test("should select different theme", async ({ page }) => {
    await page.goto("/ppt/create");

    const techButton = page.locator("button").filter({ hasText: "科技极客" });
    await techButton.click();
    await expect(techButton).toHaveClass(/border-accent/);
  });

  test("should show target pages slider with labels", async ({ page }) => {
    await page.goto("/ppt/create");

    // Default target pages is 15
    await expect(page.getByText("目标页数：15 页")).toBeVisible();
    await expect(page.getByText("自动").first()).toBeVisible();
    await expect(page.getByText("30 页")).toBeVisible();
  });

  test("should show auto label when slider is at 0", async ({ page }) => {
    await page.goto("/ppt/create");

    // Change slider to 0
    const slider = page.locator("input[type='range'][min='0'][max='30']");
    await slider.fill("0");

    await expect(page.getByText("目标页数：自动")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Submit button                                                      */
  /* ------------------------------------------------------------------ */

  test("should display submit button with correct text", async ({ page }) => {
    await page.goto("/ppt/create");
    const submitBtn = page.locator("button[type='submit']");
    await expect(submitBtn).toContainText("生成大纲");
  });

  /* ------------------------------------------------------------------ */
  /*  Mode switching                                                     */
  /* ------------------------------------------------------------------ */

  test("should preserve common settings when switching modes", async ({ page }) => {
    await page.goto("/ppt/create");

    // Select a different theme
    await page.locator("button").filter({ hasText: "科技极客" }).click();

    // Switch to document mode
    await page.locator("h3").filter({ hasText: "文档模式" }).click();
    await expect(page.getByText("文档内容", { exact: true }).first()).toBeVisible();

    // Theme should still be selected
    const techButton = page.locator("button").filter({ hasText: "科技极客" });
    await expect(techButton).toHaveClass(/border-accent/);

    // Switch back to topic mode
    await page.locator("h3").filter({ hasText: "主题模式" }).click();
    await expect(page.getByText("演示主题", { exact: true }).first()).toBeVisible();

    // Theme should still be selected
    await expect(techButton).toHaveClass(/border-accent/);
  });
});

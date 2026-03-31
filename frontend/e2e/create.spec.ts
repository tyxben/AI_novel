import { test, expect } from "./fixtures";

test.describe("Create Page", () => {
  test.beforeEach(async ({ page, mockApi }) => {
    await mockApi();
  });

  // ─── Page Header ───────────────────────────────────────────────────

  test("should display the page header", async ({ page }) => {
    await page.goto("/create");

    await expect(page.getByText("新建", { exact: true }).first()).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "开始创作" })
    ).toBeVisible();
    await expect(
      page.getByText("选择创作类型，填写参数，一键启动后台任务。")
    ).toBeVisible();
  });

  // ─── Three Creation Panels ─────────────────────────────────────────

  test("should display all three creation panels", async ({ page }) => {
    await page.goto("/create");

    // Panel titles (from Panel component's h3) — use exact to avoid matching sidebar h1
    await expect(page.getByRole("heading", { name: "小说", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "视频", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "PPT", exact: true })).toBeVisible();

    // Panel descriptions
    await expect(
      page.getByText("设定题材、风格和模板，创建 AI 长篇小说项目。")
    ).toBeVisible();
    await expect(
      page.getByText("输入灵感创意，AI 导演自动规划并生成短视频。")
    ).toBeVisible();
    await expect(
      page.getByText("输入主题或文档内容，AI 自动生成演示文稿。")
    ).toBeVisible();
  });

  test("should display section icons with labels", async ({ page }) => {
    await page.goto("/create");

    await expect(page.getByText("小说创作")).toBeVisible();
    await expect(page.getByText("视频制作")).toBeVisible();
    await expect(page.getByText("PPT 生成")).toBeVisible();
  });

  // ─── Novel Creation Form ───────────────────────────────────────────

  test.describe("Novel Form", () => {
    test("should display all form fields with correct labels", async ({ page }) => {
      await page.goto("/create");

      // Labels (uppercase tracking CSS class) — use exact to avoid matching panel descriptions
      await expect(page.getByText("题材", { exact: true })).toBeVisible();
      await expect(page.getByText("主题", { exact: true }).first()).toBeVisible();
      // "目标字数：10 万字" (100000 / 10000 = 10)
      await expect(page.getByText(/目标字数：10 万字/)).toBeVisible();
      await expect(page.getByText("风格").first()).toBeVisible();
      await expect(page.getByText("大纲模板")).toBeVisible();
      await expect(page.getByText("自定义想法（可选）")).toBeVisible();
      await expect(page.getByText("作者名（可选）")).toBeVisible();
      await expect(page.getByText("目标读者")).toBeVisible();
    });

    test("should have genre select with all options", async ({ page }) => {
      await page.goto("/create");

      const genreSelect = page.locator("select").first();
      const options = genreSelect.locator("option");

      // 9 genres: 玄幻, 仙侠, 都市, 科幻, 悬疑, 历史, 言情, 武侠, 轻小说
      await expect(options).toHaveCount(9);
      await expect(options.nth(0)).toHaveText("玄幻");
      await expect(options.nth(1)).toHaveText("仙侠");
      await expect(options.nth(2)).toHaveText("都市");
      await expect(options.nth(3)).toHaveText("科幻");
      await expect(options.nth(4)).toHaveText("悬疑");
      await expect(options.nth(5)).toHaveText("历史");
      await expect(options.nth(6)).toHaveText("言情");
      await expect(options.nth(7)).toHaveText("武侠");
      await expect(options.nth(8)).toHaveText("轻小说");
    });

    test("should have style select with all options", async ({ page }) => {
      await page.goto("/create");

      // Style is the third select (genre, ???, style) -- find by option content
      const styleSelect = page.locator("select").filter({ hasText: "网文爽文" });
      const options = styleSelect.locator("option");

      await expect(options).toHaveCount(7);
      await expect(options.nth(0)).toHaveText("网文爽文");
      await expect(options.nth(1)).toHaveText("武侠古典");
      await expect(options.nth(6)).toHaveText("轻小说");
    });

    test("should have template select with all options", async ({ page }) => {
      await page.goto("/create");

      const templateSelect = page.locator("select").filter({ hasText: "循环升级" });
      const options = templateSelect.locator("option");

      await expect(options).toHaveCount(7);
      await expect(options.nth(0)).toHaveText("循环升级（玄幻/系统流）");
      await expect(options.nth(6)).toHaveText("经典四幕（武侠/文学）");
    });

    test("should have audience select with all options", async ({ page }) => {
      await page.goto("/create");

      const audienceSelect = page.locator("select").filter({ hasText: "通用" }).last();
      const options = audienceSelect.locator("option");

      await expect(options).toHaveCount(4);
      await expect(options.nth(0)).toHaveText("通用");
      await expect(options.nth(1)).toHaveText("男频");
      await expect(options.nth(2)).toHaveText("女频");
      await expect(options.nth(3)).toHaveText("青少年");
    });

    test("should have a theme input with placeholder", async ({ page }) => {
      await page.goto("/create");

      const themeInput = page.getByPlaceholder("例如：少年修炼逆天改命");
      await expect(themeInput).toBeVisible();
      await expect(themeInput).toHaveValue("");
    });

    test("should have a custom ideas textarea", async ({ page }) => {
      await page.goto("/create");

      const textarea = page.getByPlaceholder("补充设定、角色或剧情方向...");
      await expect(textarea).toBeVisible();
    });

    test("should have an author name input", async ({ page }) => {
      await page.goto("/create");

      const authorInput = page.getByPlaceholder("笔名");
      await expect(authorInput).toBeVisible();
    });

    test("should have a word count range slider with min/max labels", async ({ page }) => {
      await page.goto("/create");

      const slider = page.locator('input[type="range"]').first();
      await expect(slider).toBeVisible();
      await expect(slider).toHaveAttribute("min", "50000");
      await expect(slider).toHaveAttribute("max", "500000");
      await expect(slider).toHaveAttribute("step", "10000");

      // Range labels
      await expect(page.getByText("5 万").first()).toBeVisible();
      await expect(page.getByText("50 万").first()).toBeVisible();
    });

    test("submit button should be disabled when theme is empty", async ({ page }) => {
      await page.goto("/create");

      const submitBtn = page.getByRole("button", { name: "创建小说项目" });
      await expect(submitBtn).toBeVisible();
      await expect(submitBtn).toBeDisabled();
    });

    test("submit button should be enabled after entering a theme", async ({ page }) => {
      await page.goto("/create");

      await page.getByPlaceholder("例如：少年修炼逆天改命").fill("少年修炼逆天改命");

      const submitBtn = page.getByRole("button", { name: "创建小说项目" });
      await expect(submitBtn).toBeEnabled();
    });

    test("should change genre selection", async ({ page }) => {
      await page.goto("/create");

      const genreSelect = page.locator("select").first();
      await genreSelect.selectOption("科幻");
      await expect(genreSelect).toHaveValue("科幻");
    });

    test("submitting the novel form should call the API and navigate to /tasks", async ({ page }) => {
      await page.goto("/create");

      // Fill required field
      await page.getByPlaceholder("例如：少年修炼逆天改命").fill("少年修炼");

      // Submit
      await page.getByRole("button", { name: "创建小说项目" }).click();

      // Should navigate to tasks page after successful creation
      await expect(page).toHaveURL("/tasks");
    });
  });

  // ─── Video Creation Form ──────────────────────────────────────────

  test.describe("Video Form", () => {
    test("should display all form fields", async ({ page }) => {
      await page.goto("/create");

      await expect(page.getByText("创意灵感")).toBeVisible();
      await expect(page.getByText("制作模式")).toBeVisible();
      await expect(page.getByText("省钱模式")).toBeVisible();
    });

    test("should have an inspiration textarea with placeholder", async ({ page }) => {
      await page.goto("/create");

      const textarea = page.getByPlaceholder("例如：一个时间旅者回到唐朝...");
      await expect(textarea).toBeVisible();
    });

    test("should have mode select with two options", async ({ page }) => {
      await page.goto("/create");

      const modeSelect = page.locator("select").filter({ hasText: "AI 导演模式" });
      const options = modeSelect.locator("option");

      await expect(options).toHaveCount(2);
      await expect(options.nth(0)).toHaveText("AI 导演模式（智能）");
      await expect(options.nth(1)).toHaveText("经典模式（快速）");
    });

    test("should have a budget mode checkbox (unchecked by default)", async ({ page }) => {
      await page.goto("/create");

      const checkbox = page.getByRole("checkbox");
      await expect(checkbox).toBeVisible();
      await expect(checkbox).not.toBeChecked();
    });

    test("should toggle budget mode checkbox", async ({ page }) => {
      await page.goto("/create");

      const checkbox = page.getByRole("checkbox");
      await checkbox.check();
      await expect(checkbox).toBeChecked();

      await checkbox.uncheck();
      await expect(checkbox).not.toBeChecked();
    });

    test("submit button should be disabled when inspiration is empty", async ({ page }) => {
      await page.goto("/create");

      const submitBtn = page.getByRole("button", { name: "开始制作" });
      await expect(submitBtn).toBeVisible();
      await expect(submitBtn).toBeDisabled();
    });

    test("submit button should be enabled after entering inspiration", async ({ page }) => {
      await page.goto("/create");

      await page.getByPlaceholder("例如：一个时间旅者回到唐朝...").fill("AI改变世界");

      const submitBtn = page.getByRole("button", { name: "开始制作" });
      await expect(submitBtn).toBeEnabled();
    });

    test("submitting the video form should call the API and navigate to /tasks", async ({ page }) => {
      await page.goto("/create");

      await page.getByPlaceholder("例如：一个时间旅者回到唐朝...").fill("AI改变世界");
      await page.getByRole("button", { name: "开始制作" }).click();

      await expect(page).toHaveURL("/tasks");
    });
  });

  // ─── PPT Creation Form ────────────────────────────────────────────

  test.describe("PPT Form", () => {
    test("should display all form fields", async ({ page }) => {
      await page.goto("/create");

      await expect(page.getByText("主题 / 内容")).toBeVisible();
      await expect(page.getByText("设计主题")).toBeVisible();
      // "目标页数：10 页" (default pages = 10)
      await expect(page.getByText(/目标页数：10 页/)).toBeVisible();
    });

    test("should have a topic textarea with placeholder", async ({ page }) => {
      await page.goto("/create");

      const textarea = page.getByPlaceholder(
        "例如：AI 技术在教育领域的应用..."
      );
      await expect(textarea).toBeVisible();
    });

    test("should have design theme select with four options", async ({ page }) => {
      await page.goto("/create");

      const themeSelect = page.locator("select").filter({ hasText: "商务专业" });
      const options = themeSelect.locator("option");

      await expect(options).toHaveCount(4);
      await expect(options.nth(0)).toHaveText("商务专业");
      await expect(options.nth(1)).toHaveText("创意设计");
      await expect(options.nth(2)).toHaveText("极简");
      await expect(options.nth(3)).toHaveText("暗色");
    });

    test("should have a pages range slider with min/max labels", async ({ page }) => {
      await page.goto("/create");

      // The PPT range slider is the second range input on the page
      const sliders = page.locator('input[type="range"]');
      const pptSlider = sliders.nth(1);
      await expect(pptSlider).toBeVisible();
      await expect(pptSlider).toHaveAttribute("min", "5");
      await expect(pptSlider).toHaveAttribute("max", "30");
      await expect(pptSlider).toHaveAttribute("step", "1");

      // Range labels
      await expect(page.getByText("5 页")).toBeVisible();
      await expect(page.getByText("30 页")).toBeVisible();
    });

    test("submit button should be disabled when topic is empty", async ({ page }) => {
      await page.goto("/create");

      const submitBtn = page.getByRole("button", { name: "生成 PPT" });
      await expect(submitBtn).toBeVisible();
      await expect(submitBtn).toBeDisabled();
    });

    test("submit button should be enabled after entering a topic", async ({ page }) => {
      await page.goto("/create");

      await page
        .getByPlaceholder("例如：AI 技术在教育领域的应用...")
        .fill("AI技术趋势");

      const submitBtn = page.getByRole("button", { name: "生成 PPT" });
      await expect(submitBtn).toBeEnabled();
    });

    test("submitting the PPT form should call the API and navigate to /tasks", async ({ page }) => {
      await page.goto("/create");

      await page
        .getByPlaceholder("例如：AI 技术在教育领域的应用...")
        .fill("AI技术趋势");
      await page.getByRole("button", { name: "生成 PPT" }).click();

      await expect(page).toHaveURL("/tasks");
    });
  });

  // ─── Form Interactions ─────────────────────────────────────────────

  test("should allow filling all novel form fields together", async ({ page }) => {
    await page.goto("/create");

    // Genre
    const genreSelect = page.locator("select").first();
    await genreSelect.selectOption("科幻");
    await expect(genreSelect).toHaveValue("科幻");

    // Theme
    const themeInput = page.getByPlaceholder("例如：少年修炼逆天改命");
    await themeInput.fill("AI觉醒之后人类何去何从");
    await expect(themeInput).toHaveValue("AI觉醒之后人类何去何从");

    // Style
    const styleSelect = page.locator("select").filter({ hasText: "网文爽文" });
    await styleSelect.selectOption("scifi.hard");
    await expect(styleSelect).toHaveValue("scifi.hard");

    // Template
    const templateSelect = page.locator("select").filter({ hasText: "循环升级" });
    await templateSelect.selectOption("mystery_solving");
    await expect(templateSelect).toHaveValue("mystery_solving");

    // Custom ideas
    const customIdeas = page.getByPlaceholder("补充设定、角色或剧情方向...");
    await customIdeas.fill("主角是一个AI研究员");
    await expect(customIdeas).toHaveValue("主角是一个AI研究员");

    // Author name
    const authorInput = page.getByPlaceholder("笔名");
    await authorInput.fill("测试作者");
    await expect(authorInput).toHaveValue("测试作者");

    // Audience
    const audienceSelect = page.locator("select").filter({ hasText: "通用" }).last();
    await audienceSelect.selectOption("男频");
    await expect(audienceSelect).toHaveValue("男频");

    // Submit should be enabled now
    const submitBtn = page.getByRole("button", { name: "创建小说项目" });
    await expect(submitBtn).toBeEnabled();
  });

  test("should allow changing video mode to classic", async ({ page }) => {
    await page.goto("/create");

    const modeSelect = page.locator("select").filter({ hasText: "AI 导演模式" });
    await modeSelect.selectOption("classic");
    await expect(modeSelect).toHaveValue("classic");
  });

  test("should allow changing PPT design theme", async ({ page }) => {
    await page.goto("/create");

    const themeSelect = page.locator("select").filter({ hasText: "商务专业" });
    await themeSelect.selectOption("dark");
    await expect(themeSelect).toHaveValue("dark");
  });
});

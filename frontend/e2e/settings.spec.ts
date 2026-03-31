import { test, expect } from "./fixtures";

test.describe("Settings Page", () => {
  test.beforeEach(async ({ page, mockApi }) => {
    await mockApi();
  });

  /* ------------------------------------------------------------------ */
  /*  Page header & structure                                            */
  /* ------------------------------------------------------------------ */

  test("should display page header with eyebrow, title, and description", async ({ page }) => {
    await page.goto("/settings");
    // PageHeader eyebrow
    await expect(page.locator("p.uppercase").filter({ hasText: "设置" })).toBeVisible();
    // PageHeader title (h2)
    await expect(page.locator("h2").filter({ hasText: "系统设置" })).toBeVisible();
    // PageHeader description
    await expect(
      page.getByText(
        "管理 API 密钥、默认配置和后端服务状态。密钥保存在浏览器本地，通过请求头传递给后端。"
      )
    ).toBeVisible();
  });

  test("should display all three panels", async ({ page }) => {
    await page.goto("/settings");
    // Panel titles are rendered as <h3> inside <section>
    await expect(page.locator("h3").filter({ hasText: "服务商密钥" })).toBeVisible();
    await expect(page.locator("h3").filter({ hasText: "默认配置" })).toBeVisible();
    await expect(page.locator("h3").filter({ hasText: "系统信息" })).toBeVisible();
  });

  test("should display panel descriptions", async ({ page }) => {
    await page.goto("/settings");
    await expect(
      page.getByText("配置各服务商的 API Key，密钥仅保存在浏览器 localStorage 中")
    ).toBeVisible();
    await expect(page.getByText("模型和生成服务的默认选择")).toBeVisible();
    await expect(page.getByText("后端服务健康状态和任务队列")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  API Key rows                                                       */
  /* ------------------------------------------------------------------ */

  test("should display all five API key labels", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.getByText("Gemini API Key")).toBeVisible();
    await expect(page.getByText("DeepSeek API Key")).toBeVisible();
    await expect(page.getByText("OpenAI API Key")).toBeVisible();
    await expect(page.getByText("SiliconFlow API Key")).toBeVisible();
    await expect(page.getByText("阿里云 DashScope API Key")).toBeVisible();
  });

  test("should display environment variable names under each key label", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.getByText("GEMINI_API_KEY")).toBeVisible();
    await expect(page.getByText("DEEPSEEK_API_KEY")).toBeVisible();
    await expect(page.getByText("OPENAI_API_KEY")).toBeVisible();
    await expect(page.getByText("SILICONFLOW_API_KEY")).toBeVisible();
    await expect(page.getByText("DASHSCOPE_API_KEY")).toBeVisible();
  });

  test("should render all key inputs as password type by default", async ({ page }) => {
    await page.goto("/settings");
    const passwordInputs = page.locator('input[type="password"]');
    await expect(passwordInputs).toHaveCount(5);
  });

  test("should toggle key visibility between password and text", async ({ page }) => {
    await page.goto("/settings");
    // All 5 keys have a "显示" toggle button initially
    const showButtons = page.getByRole("button", { name: "显示" });
    await expect(showButtons).toHaveCount(5);

    // Click the first "显示" button to reveal the key
    await showButtons.first().click();

    // One input is now visible (type=text), one "隐藏" button appears
    await expect(page.getByRole("button", { name: "隐藏" })).toHaveCount(1);
    await expect(page.getByRole("button", { name: "显示" })).toHaveCount(4);

    // Click "隐藏" to hide again
    await page.getByRole("button", { name: "隐藏" }).click();
    await expect(page.getByRole("button", { name: "显示" })).toHaveCount(5);
  });

  /* ------------------------------------------------------------------ */
  /*  API key test connection                                            */
  /* ------------------------------------------------------------------ */

  test("should have disabled test buttons when inputs are empty", async ({ page }) => {
    await page.goto("/settings");
    const testButtons = page.getByRole("button", { name: "测试连接" });
    await expect(testButtons).toHaveCount(5);
    for (let i = 0; i < 5; i++) {
      await expect(testButtons.nth(i)).toBeDisabled();
    }
  });

  test("should enable test button when a key value is entered", async ({ page }) => {
    await page.goto("/settings");
    // Gemini has placeholder "AIza..."
    const geminiInput = page.locator('input[placeholder="AIza..."]');
    await geminiInput.fill("AIzaSyTestKey123");

    const testButtons = page.getByRole("button", { name: "测试连接" });
    await expect(testButtons.first()).toBeEnabled();
  });

  test("should show success for valid Gemini key format (starts with AIza)", async ({ page }) => {
    await page.goto("/settings");
    const geminiInput = page.locator('input[placeholder="AIza..."]');
    await geminiInput.fill("AIzaSyTestKey123");

    const testButtons = page.getByRole("button", { name: "测试连接" });
    await testButtons.first().click();

    await expect(page.getByText("密钥格式正确，已保存到本地")).toBeVisible();
  });

  test("should show error for invalid Gemini key format", async ({ page }) => {
    await page.goto("/settings");
    const geminiInput = page.locator('input[placeholder="AIza..."]');
    await geminiInput.fill("invalid-key-format");

    const testButtons = page.getByRole("button", { name: "测试连接" });
    await testButtons.first().click();

    await expect(page.getByText("Gemini 密钥通常以 AIza 开头")).toBeVisible();
  });

  test("should show error for DeepSeek key not starting with sk-", async ({ page }) => {
    await page.goto("/settings");
    // DeepSeek is the second password input
    const inputs = page.locator('input[type="password"]');
    await inputs.nth(1).fill("invalid-deepseek-key");

    const testButtons = page.getByRole("button", { name: "测试连接" });
    await testButtons.nth(1).click();

    await expect(page.getByText("密钥格式不正确，通常以 sk- 开头")).toBeVisible();
  });

  test("should show success for valid DeepSeek key format (starts with sk-)", async ({ page }) => {
    await page.goto("/settings");
    const inputs = page.locator('input[type="password"]');
    await inputs.nth(1).fill("sk-test-deepseek-key");

    const testButtons = page.getByRole("button", { name: "测试连接" });
    await testButtons.nth(1).click();

    await expect(page.getByText("密钥格式正确，已保存到本地")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Default configuration selects                                      */
  /* ------------------------------------------------------------------ */

  test("should display LLM provider select defaulting to auto", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.getByText("LLM 服务商")).toBeVisible();
    // The LLM select is the first <select> on the page (within "默认配置" panel)
    const llmSelect = page.locator("select").first();
    await expect(llmSelect).toHaveValue("auto");
  });

  test("should have all five LLM provider options", async ({ page }) => {
    await page.goto("/settings");
    const llmSelect = page.locator("select").first();
    const options = llmSelect.locator("option");
    // auto, gemini, deepseek, openai, ollama
    await expect(options).toHaveCount(5);
  });

  test("should allow changing LLM provider selection", async ({ page }) => {
    await page.goto("/settings");
    const llmSelect = page.locator("select").first();
    await llmSelect.selectOption("deepseek");
    await expect(llmSelect).toHaveValue("deepseek");
  });

  test("should display image backend select defaulting to siliconflow", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.getByText("图片生成后端")).toBeVisible();
    const imageSelect = page.locator("select").nth(1);
    await expect(imageSelect).toHaveValue("siliconflow");
  });

  test("should display video backend select defaulting to none", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.getByText("视频生成后端")).toBeVisible();
    const videoSelect = page.locator("select").nth(2);
    await expect(videoSelect).toHaveValue("none");
  });

  test("should display auto-detect priority hint text", async ({ page }) => {
    await page.goto("/settings");
    // The > is rendered from &gt; in JSX
    await expect(
      page.getByText("自动检测优先级：Gemini > DeepSeek > OpenAI > Ollama")
    ).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Workers slider                                                     */
  /* ------------------------------------------------------------------ */

  test("should display worker count slider with range 1-4", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.getByText(/任务队列 Worker 数量：\d/)).toBeVisible();
    const slider = page.locator('input[type="range"]');
    await expect(slider).toBeVisible();
    await expect(slider).toHaveAttribute("min", "1");
    await expect(slider).toHaveAttribute("max", "4");
  });

  /* ------------------------------------------------------------------ */
  /*  Health check (系统信息 panel)                                       */
  /* ------------------------------------------------------------------ */

  test("should show healthy backend status when /api/health returns ok", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.getByText("后端服务状态", { exact: true })).toBeVisible();
    // The mocked /api/health returns { status: "ok" } -> shows "正常运行"
    await expect(page.getByText("正常运行")).toBeVisible();
  });

  test("should show error status and startup hint when health check fails", async ({ page }) => {
    const API = "http://localhost:8000";
    // Override health to return 500
    await page.route(`${API}/api/health`, (route) =>
      route.fulfill({ status: 500 })
    );
    // Tasks endpoint also fails when backend is down
    await page.route(`${API}/api/tasks?*`, (route) =>
      route.abort()
    );
    await page.route(`${API}/api/settings`, (route) =>
      route.fulfill({ json: { llm: { provider: "auto" } } })
    );

    await page.goto("/settings");
    await expect(page.getByText("无法连接")).toBeVisible();
    // Startup hint block appears when healthStatus === "error"
    await expect(page.getByText("启动后端服务")).toBeVisible();
    await expect(page.getByText("python -m src.task_queue.server")).toBeVisible();
  });

  test("should display task queue count from /api/tasks", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.getByText("任务队列", { exact: true })).toBeVisible();
    // Default mock returns array with 1 task -> "共 1 个任务"
    await expect(page.getByText("共 1 个任务")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Connection info                                                    */
  /* ------------------------------------------------------------------ */

  test("should display connection info with API base URL", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.getByText("连接信息")).toBeVisible();
    await expect(page.getByText("API 地址：")).toBeVisible();
    await expect(page.getByText("http://localhost:8000", { exact: true })).toBeVisible();
    await expect(page.getByText("NEXT_PUBLIC_API_BASE_URL")).toBeVisible();
  });

  /* ------------------------------------------------------------------ */
  /*  Refresh health check                                               */
  /* ------------------------------------------------------------------ */

  test("should re-check health when refresh button is clicked", async ({ page }) => {
    let healthCallCount = 0;
    const API = "http://localhost:8000";
    await page.route(`${API}/api/health`, (route) => {
      healthCallCount++;
      return route.fulfill({ json: { status: "ok" } });
    });

    await page.goto("/settings");
    // Wait for initial health check
    await page.waitForTimeout(500);
    const initialCount = healthCallCount;

    // The RefreshCw button is inside the health check card
    // Find the health card container then locate the button
    const healthCard = page.locator("text=后端服务状态").locator("..").locator("..").locator("..");
    const refreshBtn = healthCard.locator("button").last();
    await refreshBtn.click();

    await page.waitForTimeout(500);
    expect(healthCallCount).toBeGreaterThan(initialCount);
  });

  /* ------------------------------------------------------------------ */
  /*  localStorage persistence                                           */
  /* ------------------------------------------------------------------ */

  test("should persist API keys and settings to localStorage", async ({ page }) => {
    await page.goto("/settings");

    // Fill a Gemini key
    const geminiInput = page.locator('input[placeholder="AIza..."]');
    await geminiInput.fill("AIzaSyTestKey123");

    // Change LLM provider
    const llmSelect = page.locator("select").first();
    await llmSelect.selectOption("gemini");

    // Wait for useEffect to persist
    await page.waitForTimeout(500);

    // Verify localStorage contents
    const stored = await page.evaluate(() =>
      JSON.parse(localStorage.getItem("ai-novel-settings") ?? "{}")
    );
    expect(stored.GEMINI_API_KEY).toBe("AIzaSyTestKey123");
    expect(stored._llmProvider).toBe("gemini");
  });

  test("should restore settings from localStorage on page load", async ({ page }) => {
    // Pre-populate localStorage
    await page.goto("/settings");
    await page.evaluate(() => {
      localStorage.setItem(
        "ai-novel-settings",
        JSON.stringify({
          GEMINI_API_KEY: "AIzaPreloaded",
          _llmProvider: "deepseek",
          _imageBackend: "dashscope",
          _videoBackend: "kling",
          _workers: "3",
        })
      );
    });

    // Reload to trigger useEffect loading from localStorage
    await page.reload();

    // Reveal the Gemini key to check value
    await page.getByRole("button", { name: "显示" }).first().click();
    const geminiInput = page.locator('input[type="text"][placeholder="AIza..."]');
    await expect(geminiInput).toHaveValue("AIzaPreloaded");

    // Verify select values
    const llmSelect = page.locator("select").first();
    await expect(llmSelect).toHaveValue("deepseek");

    const imageSelect = page.locator("select").nth(1);
    await expect(imageSelect).toHaveValue("dashscope");

    const videoSelect = page.locator("select").nth(2);
    await expect(videoSelect).toHaveValue("kling");
  });
});

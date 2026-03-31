import { test, expect } from "./fixtures";

test.describe("Sidebar Navigation", () => {
  test.beforeEach(async ({ page, mockApi }) => {
    await mockApi();
  });

  // ─── Sidebar Branding ─────────────────────────────────────────────

  test("should display the sidebar branding text", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.locator("aside").getByText("AI 创作工坊")
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "小说、视频、PPT 一站创作" })
    ).toBeVisible();
    await expect(
      page.getByText("多 Agent 驱动的中文创作平台，统一管理所有创作项目和后台任务。")
    ).toBeVisible();
  });

  test("should display the bottom info card", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByText("Next.js 前端")).toBeVisible();
    await expect(
      page.getByText("独立前端应用，通过 REST API 对接后端任务队列和项目接口。")
    ).toBeVisible();
  });

  // ─── Navigation Items ─────────────────────────────────────────────

  test("should display all seven navigation items", async ({ page }) => {
    await page.goto("/");

    const nav = page.locator("nav");

    await expect(nav.getByRole("link", { name: "创作台" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "小说" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "视频" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "PPT" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "任务" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Prompt" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "设置" })).toBeVisible();
  });

  test("nav items should link to correct routes", async ({ page }) => {
    await page.goto("/");

    const nav = page.locator("nav");

    await expect(nav.getByRole("link", { name: "创作台" })).toHaveAttribute("href", "/");
    await expect(nav.getByRole("link", { name: "小说" })).toHaveAttribute("href", "/novel");
    await expect(nav.getByRole("link", { name: "视频" })).toHaveAttribute("href", "/video");
    await expect(nav.getByRole("link", { name: "PPT" })).toHaveAttribute("href", "/ppt");
    await expect(nav.getByRole("link", { name: "任务" })).toHaveAttribute("href", "/tasks");
    await expect(nav.getByRole("link", { name: "Prompt" })).toHaveAttribute("href", "/prompts");
    await expect(nav.getByRole("link", { name: "设置" })).toHaveAttribute("href", "/settings");
  });

  // ─── Active State ─────────────────────────────────────────────────

  test("should highlight '创作台' when on the home page", async ({ page }) => {
    await page.goto("/");

    const nav = page.locator("nav");
    const homeLink = nav.getByRole("link", { name: "创作台" });

    // Active link should have the accent color class
    await expect(homeLink).toHaveClass(/text-accent/);

    // Other links should NOT have the accent class
    const novelLink = nav.getByRole("link", { name: "小说" });
    await expect(novelLink).not.toHaveClass(/bg-accent/);
  });

  test("should highlight '小说' when on the /novel page", async ({ page }) => {
    await page.goto("/novel");

    const nav = page.locator("nav");
    const novelLink = nav.getByRole("link", { name: "小说" });
    await expect(novelLink).toHaveClass(/text-accent/);

    // Home link should not be highlighted
    const homeLink = nav.getByRole("link", { name: "创作台" });
    await expect(homeLink).not.toHaveClass(/bg-accent/);
  });

  test("should highlight '视频' when on the /video page", async ({ page }) => {
    await page.goto("/video");

    const nav = page.locator("nav");
    const videoLink = nav.getByRole("link", { name: "视频" });
    await expect(videoLink).toHaveClass(/text-accent/);
  });

  test("should highlight '任务' when on the /tasks page", async ({ page }) => {
    await page.goto("/tasks");

    const nav = page.locator("nav");
    const tasksLink = nav.getByRole("link", { name: "任务" });
    await expect(tasksLink).toHaveClass(/text-accent/);
  });

  test("should highlight '设置' when on the /settings page", async ({ page }) => {
    await page.goto("/settings");

    const nav = page.locator("nav");
    const settingsLink = nav.getByRole("link", { name: "设置" });
    await expect(settingsLink).toHaveClass(/text-accent/);
  });

  // ─── Navigation Clicks ────────────────────────────────────────────

  test("clicking '小说' navigates to /novel", async ({ page }) => {
    await page.goto("/");

    const nav = page.locator("nav");
    await nav.getByRole("link", { name: "小说" }).click();
    await expect(page).toHaveURL("/novel");
  });

  test("clicking '视频' navigates to /video", async ({ page }) => {
    await page.goto("/");

    const nav = page.locator("nav");
    await nav.getByRole("link", { name: "视频" }).click();
    await expect(page).toHaveURL("/video");
  });

  test("clicking 'PPT' navigates to /ppt", async ({ page }) => {
    await page.goto("/");

    const nav = page.locator("nav");
    await nav.getByRole("link", { name: "PPT" }).click();
    await expect(page).toHaveURL("/ppt");
  });

  test("clicking '任务' navigates to /tasks", async ({ page }) => {
    await page.goto("/");

    const nav = page.locator("nav");
    await nav.getByRole("link", { name: "任务" }).click();
    await expect(page).toHaveURL("/tasks");
  });

  test("clicking 'Prompt' navigates to /prompts", async ({ page }) => {
    await page.goto("/");

    const nav = page.locator("nav");
    await nav.getByRole("link", { name: "Prompt" }).click();
    await expect(page).toHaveURL("/prompts");
  });

  test("clicking '设置' navigates to /settings", async ({ page }) => {
    await page.goto("/");

    const nav = page.locator("nav");
    await nav.getByRole("link", { name: "设置" }).click();
    await expect(page).toHaveURL("/settings");
  });

  test("clicking '创作台' from another page navigates back to /", async ({ page }) => {
    await page.goto("/novel");

    const nav = page.locator("nav");
    await nav.getByRole("link", { name: "创作台" }).click();
    await expect(page).toHaveURL("/");
  });

  // ─── Sidebar Persistence ──────────────────────────────────────────

  test("sidebar should remain visible across page navigations", async ({ page }) => {
    await page.goto("/");

    const sidebar = page.locator("aside");
    await expect(sidebar).toBeVisible();

    // Navigate to novel page
    await page.locator("nav").getByRole("link", { name: "小说" }).click();
    await expect(page).toHaveURL("/novel");
    await expect(sidebar).toBeVisible();

    // Navigate to create page
    await page.goto("/create");
    await expect(sidebar).toBeVisible();

    // Navigate to settings
    await page.locator("nav").getByRole("link", { name: "设置" }).click();
    await expect(page).toHaveURL("/settings");
    await expect(sidebar).toBeVisible();
  });

  // ─── Layout Structure ─────────────────────────────────────────────

  test("should have aside and main elements in the layout", async ({ page }) => {
    await page.goto("/");

    await expect(page.locator("aside")).toBeVisible();
    await expect(page.locator("main")).toBeVisible();
  });

  test("nav should contain exactly 7 links", async ({ page }) => {
    await page.goto("/");

    const navLinks = page.locator("nav").getByRole("link");
    await expect(navLinks).toHaveCount(7);
  });
});

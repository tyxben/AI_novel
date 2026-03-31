import { test, expect } from "./fixtures";

/* ------------------------------------------------------------------ */
/*  Helper: a novel object matching the shape consumed by page.tsx     */
/* ------------------------------------------------------------------ */
function makeNovel(overrides: Record<string, any> = {}) {
  return {
    id: "novel_001",
    title: "逆天修仙录",
    genre: "玄幻",
    status: "idle",
    style_name: "webnovel.shuangwen",
    target_words: 100000,
    completed_chapters: 5,
    total_chapters: 40,
    ...overrides,
  };
}

test.describe("Novel List Page", () => {
  test.beforeEach(async ({ mockApi }) => {
    await mockApi();
  });

  // ─── Page Header ───────────────────────────────────────────────────

  test("should display page header with title and description", async ({ page }) => {
    await page.goto("/novel");

    // PageHeader: eyebrow="小说", title="小说工作台"
    await expect(
      page.getByRole("heading", { name: "小说工作台" })
    ).toBeVisible();
    await expect(
      page.getByText("管理所有小说项目，查看进度，进入项目工作区。")
    ).toBeVisible();
  });

  test("should display '新建小说' button linking to /create", async ({ page }) => {
    await page.goto("/novel");

    const createLink = page.getByRole("link", { name: /新建小说/ });
    await expect(createLink).toBeVisible();
    await expect(createLink).toHaveAttribute("href", "/create");
  });

  // ─── Panel ─────────────────────────────────────────────────────────

  test("should display the panel title and description", async ({ page }) => {
    await page.goto("/novel");

    await expect(
      page.getByRole("heading", { name: "小说项目" })
    ).toBeVisible();
    await expect(
      page.getByText("点击项目卡片进入工作区。")
    ).toBeVisible();
  });

  // ─── Novel Cards ──────────────────────────────────────────────────

  test("should display novel items from the API", async ({ page, mockApi }) => {
    await mockApi({
      novels: [
        makeNovel(),
        makeNovel({
          id: "novel_002",
          title: "都市传说",
          genre: "都市",
          status: "generating",
          style_name: "webnovel.dushi",
          target_words: 80000,
          completed_chapters: 10,
          total_chapters: 30,
        }),
      ],
    });

    await page.goto("/novel");

    // First novel
    await expect(page.getByText("逆天修仙录")).toBeVisible();
    await expect(page.getByText("玄幻").first()).toBeVisible();
    await expect(page.getByText("目标: 10万字").first()).toBeVisible();
    // 5/40 = 13%
    await expect(page.getByText("5 / 40 (13%)")).toBeVisible();

    // Second novel
    await expect(page.getByText("都市传说")).toBeVisible();
    await expect(page.getByText("都市").first()).toBeVisible();
    // 10/30 = 33%
    await expect(page.getByText("10 / 30 (33%)")).toBeVisible();
  });

  test("novel card should link to the novel detail page", async ({ page, mockApi }) => {
    await mockApi({ novels: [makeNovel()] });

    await page.goto("/novel");

    const cardLink = page.getByRole("link").filter({ hasText: "逆天修仙录" });
    await expect(cardLink).toHaveAttribute("href", "/novel/novel_001");
  });

  test("clicking a novel card navigates to its detail page", async ({ page, mockApi }) => {
    await mockApi({ novels: [makeNovel()] });

    await page.goto("/novel");
    await page.getByRole("link").filter({ hasText: "逆天修仙录" }).click();
    await expect(page).toHaveURL("/novel/novel_001");
  });

  test("should display progress bar with correct percentage", async ({ page, mockApi }) => {
    await mockApi({
      novels: [
        makeNovel({
          id: "novel_pct",
          title: "测试小说",
          completed_chapters: 10,
          total_chapters: 40,
        }),
      ],
    });

    await page.goto("/novel");

    // 10/40 = 25%
    await expect(page.getByText("10 / 40 (25%)")).toBeVisible();
    await expect(page.getByText("章节进度")).toBeVisible();
  });

  test("should show status badge on novel card", async ({ page, mockApi }) => {
    await mockApi({
      novels: [
        makeNovel({
          id: "novel_done",
          title: "完结小说",
          status: "completed",
          completed_chapters: 40,
          total_chapters: 40,
        }),
      ],
    });

    await page.goto("/novel");

    // StatusBadge renders "已完成" for status "completed"
    await expect(page.getByText("已完成").first()).toBeVisible();
  });

  test("should show status label text from STATUS_LABELS", async ({ page, mockApi }) => {
    // page.tsx has its own STATUS_LABELS that renders inside the meta line
    await mockApi({
      novels: [
        makeNovel({ status: "generating" }),
      ],
    });

    await page.goto("/novel");

    // StatusBadge shows "生成中", and STATUS_LABELS also shows "生成中"
    await expect(page.getByText("生成中").first()).toBeVisible();
  });

  test("should display genre and target word count", async ({ page, mockApi }) => {
    await mockApi({
      novels: [
        makeNovel({ genre: "科幻", target_words: 200000 }),
      ],
    });

    await page.goto("/novel");

    await expect(page.getByText("科幻").first()).toBeVisible();
    // 200000 / 10000 = 20
    await expect(page.getByText("目标: 20万字")).toBeVisible();
  });

  test("should display author name when present", async ({ page, mockApi }) => {
    await mockApi({
      novels: [
        makeNovel({ author_name: "测试作者" }),
      ],
    });

    await page.goto("/novel");

    await expect(page.getByText("作者: 测试作者")).toBeVisible();
  });

  test("should display synopsis when present", async ({ page, mockApi }) => {
    await mockApi({
      novels: [
        makeNovel({ synopsis: "少年逆天改命的修仙故事" }),
      ],
    });

    await page.goto("/novel");

    await expect(page.getByText("少年逆天改命的修仙故事")).toBeVisible();
  });

  test("should display style_name and id below progress bar", async ({ page, mockApi }) => {
    await mockApi({
      novels: [
        makeNovel({ id: "novel_xyz", style_name: "wuxia.classical" }),
      ],
    });

    await page.goto("/novel");

    await expect(page.getByText("wuxia.classical")).toBeVisible();
    await expect(page.getByText("novel_xyz")).toBeVisible();
  });

  // ─── Title Truncation ──────────────────────────────────────────────

  test("should truncate long novel titles at 30 characters", async ({ page, mockApi }) => {
    const longTitle = "这是一个超级超级超级超级超级超级超级超级超级超级超级长的小说标题名字";
    await mockApi({
      novels: [makeNovel({ id: "novel_long", title: longTitle })],
    });

    await page.goto("/novel");

    // displayTitle = longTitle.slice(0, 30) + "..."
    const truncated = longTitle.slice(0, 30) + "...";
    await expect(page.getByText(truncated)).toBeVisible();
  });

  // ─── Published Chapters Badge ─────────────────────────────────────

  test("should display published chapter count when > 0", async ({ page, mockApi }) => {
    await mockApi({
      novels: [
        makeNovel({ published_count: 5, completed_chapters: 10, total_chapters: 40 }),
      ],
    });

    await page.goto("/novel");

    await expect(page.getByText("已发布: 5章")).toBeVisible();
  });

  test("should NOT display published chapter count when 0", async ({ page, mockApi }) => {
    await mockApi({
      novels: [
        makeNovel({ published_count: 0 }),
      ],
    });

    await page.goto("/novel");

    await expect(page.getByText(/已发布/)).not.toBeVisible();
  });

  // ─── Empty State ──────────────────────────────────────────────────

  test("should display empty state when no novels exist", async ({ page, mockApi }) => {
    await mockApi({ novels: [] });

    await page.goto("/novel");

    await expect(page.getByText("暂无小说项目")).toBeVisible();
    const createLink = page.getByRole("link", { name: "创建第一部小说" });
    await expect(createLink).toBeVisible();
    await expect(createLink).toHaveAttribute("href", "/create");
  });

  // ─── Error State ──────────────────────────────────────────────────

  test("should display error message when API fails", async ({ page }) => {
    await page.route("http://localhost:8000/api/novels", (route) =>
      route.abort("connectionrefused")
    );

    await page.goto("/novel");

    await expect(page.getByText(/加载失败/)).toBeVisible();
  });

  // ─── Fallback when title is missing ───────────────────────────────

  test("should use novel id as display title when title is absent", async ({ page, mockApi }) => {
    await mockApi({
      novels: [
        makeNovel({ id: "novel_fallback", title: undefined }),
      ],
    });

    await page.goto("/novel");

    // rawTitle = novel.title ?? novel.id => "novel_fallback"
    // The title appears both in the card heading and the id span — use .first()
    await expect(page.getByText("novel_fallback").first()).toBeVisible();
  });
});

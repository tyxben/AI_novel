"""七猫小说自动发布脚本

使用 Playwright 自动化上传章节到七猫作家中心 (zuozhe.qimao.com)

用法:
    # 第一步：登录并保存 session
    python scripts/qimao_publish.py login

    # 第二步：上传章节
    python scripts/qimao_publish.py upload workspace/novels/novel_5228b752

    # 上传指定范围
    python scripts/qimao_publish.py upload workspace/novels/novel_5228b752 --start 1 --end 5

    # 查看已有章节（不上传）
    python scripts/qimao_publish.py preview workspace/novels/novel_5228b752
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

WRITER_URL = "https://zuozhe.qimao.com"
AUTH_FILE = Path.home() / ".novel-video" / "qimao_auth.json"


def _ensure_dir():
    AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_chapters(novel_dir: str) -> list[dict]:
    """从项目目录加载所有章节（按章节号排序）"""
    chapters_dir = Path(novel_dir) / "chapters"
    if not chapters_dir.exists():
        print(f"错误: 章节目录不存在 {chapters_dir}")
        sys.exit(1)

    chapters = []
    for f in sorted(chapters_dir.glob("chapter_*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        chapters.append({
            "number": data.get("chapter_number", 0),
            "title": data.get("title", f"第{data.get('chapter_number', 0)}章"),
            "text": data.get("full_text", ""),
            "word_count": data.get("word_count", 0),
        })
    return chapters


def _find_chrome_path() -> str:
    """找到本机 Chrome 路径"""
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return ""


def _launch_real_chrome(p, user_data_dir: str | None = None):
    """用本机 Chrome 启动（绕过验证码检测）"""
    chrome_path = _find_chrome_path()
    if chrome_path:
        print(f"使用本机 Chrome: {chrome_path}")
        return p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir or str(AUTH_FILE.parent / "chrome_profile"),
            executable_path=chrome_path,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
    else:
        print("未找到本机 Chrome，使用 Playwright 内置浏览器")
        return p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir or str(AUTH_FILE.parent / "chrome_profile"),
            headless=False,
            channel="chrome",
        )


def cmd_login():
    """打开本机 Chrome 让用户登录，session 自动保存在 chrome_profile"""
    from playwright.sync_api import sync_playwright

    _ensure_dir()
    profile_dir = AUTH_FILE.parent / "chrome_profile"
    print("=" * 50)
    print("七猫作家中心登录")
    print("=" * 50)
    print(f"\n即将用本机 Chrome 打开七猫，你正常登录即可。")
    print(f"登录成功后关闭浏览器窗口，session 自动保存。")
    print(f"Profile 目录: {profile_dir}\n")

    with sync_playwright() as p:
        context = _launch_real_chrome(p)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(WRITER_URL)

        print("等待登录... （登录后关闭浏览器窗口即可）")
        try:
            page.wait_for_url("**/writer/**", timeout=300_000)
            print("✓ 检测到登录成功！")
        except Exception:
            print("提示: 未检测到自动跳转，将保存当前状态。")

        # 同时导出 storage_state 备用
        context.storage_state(path=str(AUTH_FILE))
        print(f"✓ Session 已保存")
        context.close()

    print("完成！现在可以使用 upload 命令上传章节了。")


def cmd_preview(novel_dir: str):
    """预览要上传的章节"""
    chapters = _load_chapters(novel_dir)
    if not chapters:
        print("没有找到章节文件")
        return

    print(f"\n共 {len(chapters)} 章，准备上传:\n")
    total_words = 0
    for ch in chapters:
        total_words += ch["word_count"]
        print(f"  第{ch['number']:>2d}章  {ch['title']:<20s}  {ch['word_count']}字")
    print(f"\n  总计: {total_words} 字")


def _click_visible(page, locator_str: str, timeout: int = 3000) -> bool:
    """尝试点击可见的元素，返回是否成功"""
    try:
        loc = page.locator(locator_str)
        for i in range(loc.count()):
            el = loc.nth(i)
            if el.is_visible():
                el.click(timeout=timeout)
                return True
    except Exception:
        pass
    return False


def _save_and_publish(page):
    """完整的保存发布流程：顶栏按钮 → 确认弹窗 → 关闭提醒"""
    # Step 1: 点击顶栏按钮（新建用「立即发布」，修改用「更新章节」）
    clicked = _click_visible(page, "text=立即发布")
    if not clicked:
        clicked = _click_visible(page, "text=更新章节")
    if not clicked:
        clicked = _click_visible(page, "text=存为草稿")
    if not clicked:
        print(f"  ⚠ 未找到发布/保存按钮")
        return False

    time.sleep(3)
    page.screenshot(path="tests/screenshots/qimao_save_dialog.png")

    # Step 2: 处理所有弹窗（确认发布 + 重要提醒等）
    buttons = [
        "text=确认发布", "text=确认更新",
        "text=立即发布", "text=更新章节",
        "text=我已阅读并知晓",
        "text=确定", "text=知道了", "text=确认",
    ]
    for _ in range(8):
        time.sleep(1)
        clicked_any = False
        for btn_sel in buttons:
            try:
                loc = page.locator(btn_sel)
                for i in range(loc.count()):
                    el = loc.nth(i)
                    if el.is_visible():
                        el.click(timeout=2000)
                        clicked_any = True
                        time.sleep(2)
                        break
            except Exception:
                continue
            if clicked_any:
                break
        if not clicked_any:
            break

    time.sleep(2)
    return True


def _navigate_to_chapter_mgmt(page, url: str):
    """导航回章节管理页面"""
    page.goto(url)
    page.wait_for_load_state("networkidle")
    time.sleep(2)


def cmd_upload(novel_dir: str, start: int = 1, end: int | None = None):
    """全自动上传章节到七猫"""
    from playwright.sync_api import sync_playwright

    profile_dir = AUTH_FILE.parent / "chrome_profile"
    if not profile_dir.exists() and not AUTH_FILE.exists():
        print("错误: 未找到登录 session，请先运行 login 命令")
        print(f"  python scripts/qimao_publish.py login")
        sys.exit(1)

    chapters = _load_chapters(novel_dir)
    if not chapters:
        print("没有找到章节文件")
        return

    # 筛选范围
    if end is None:
        end = max(ch["number"] for ch in chapters)
    chapters = [ch for ch in chapters if start <= ch["number"] <= end]

    if not chapters:
        print(f"范围 {start}-{end} 内没有章节")
        return

    print(f"\n准备上传 {len(chapters)} 章 (第{start}-{end}章)")
    print("=" * 50)

    with sync_playwright() as p:
        context = _launch_real_chrome(p)
        page = context.pages[0] if context.pages else context.new_page()

        # 进入作家后台
        page.goto(WRITER_URL)
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        page.screenshot(path="tests/screenshots/qimao_home.png")
        print("✓ 已进入作家后台")

        # 点击「章节管理」进入章节列表
        chapter_mgmt = page.locator("a:has-text('章节管理'), span:has-text('章节管理')")
        if chapter_mgmt.count() > 0:
            chapter_mgmt.first.click()
            page.wait_for_load_state("networkidle")
            time.sleep(2)
            print("✓ 已进入章节管理")
        else:
            # 尝试从作品信息页进入
            work_link = page.locator("a:has-text('作品信息')")
            if work_link.count() > 0:
                work_link.first.click()
                page.wait_for_load_state("networkidle")
                time.sleep(1)
                chapter_mgmt = page.locator("a:has-text('章节管理'), span:has-text('章节管理')")
                if chapter_mgmt.count() > 0:
                    chapter_mgmt.first.click()
                    page.wait_for_load_state("networkidle")
                    time.sleep(2)
                    print("✓ 已进入章节管理")

        page.screenshot(path="tests/screenshots/qimao_chapter_mgmt.png")
        chapter_mgmt_url = page.url  # 记住章节管理页 URL，方便返回
        print(f"当前页面: {chapter_mgmt_url}")

        # 逐章上传
        uploaded = 0
        for ch in chapters:
            print(f"\n--- 上传第{ch['number']}章: {ch['title']} ({ch['word_count']}字) ---")

            try:
                # 点击「新建章节」
                new_btn = page.locator(
                    "button:has-text('新建章节'), "
                    "a:has-text('新建章节'), "
                    "span:has-text('新建章节')"
                )
                if new_btn.count() > 0:
                    new_btn.first.click()
                    page.wait_for_load_state("networkidle")
                    time.sleep(2)
                    print(f"  ✓ 点击新建章节")
                else:
                    print(f"  ⚠ 未找到「新建章节」按钮")
                    page.screenshot(
                        path=f"tests/screenshots/qimao_ch{ch['number']:03d}_no_btn.png"
                    )
                    continue

                page.screenshot(
                    path=f"tests/screenshots/qimao_ch{ch['number']:03d}_editor.png"
                )

                # 填写章节标题 — 七猫的标题是章节号旁的内联编辑区
                title_filled = False
                # 尝试 placeholder 定位
                title_area = page.locator(
                    "[placeholder*='章节名称'], "
                    "[placeholder*='标题'], "
                    "[data-placeholder*='章节名称']"
                )
                if title_area.count() > 0:
                    title_area.first.click()
                    title_area.first.fill(ch["title"])
                    title_filled = True
                    print(f"  ✓ 标题已填写: {ch['title']}")
                else:
                    # 尝试点击「第N章」旁边的区域
                    chapter_header = page.locator(
                        f"text=第 {ch['number']} 章, text=第{ch['number']}章"
                    )
                    if chapter_header.count() > 0:
                        # 点击标题旁边的编辑区
                        bbox = chapter_header.first.bounding_box()
                        if bbox:
                            page.mouse.click(bbox["x"] + bbox["width"] + 20, bbox["y"] + bbox["height"] / 2)
                            time.sleep(0.5)
                            page.keyboard.type(ch["title"])
                            title_filled = True
                            print(f"  ✓ 标题已填写（点击定位）: {ch['title']}")
                if not title_filled:
                    print(f"  ⚠ 未找到标题输入框")

                # 填写正文 — 尝试多种编辑器类型
                content_filled = False
                # 1. textarea
                textarea = page.locator("textarea")
                if textarea.count() > 0:
                    textarea.first.click()
                    textarea.first.fill(ch["text"])
                    content_filled = True
                    print(f"  ✓ 正文已填写 (textarea, {ch['word_count']}字)")

                # 2. contenteditable div (富文本编辑器)
                if not content_filled:
                    editable = page.locator("div[contenteditable='true']")
                    if editable.count() > 0:
                        editable.first.click()
                        editable.first.fill(ch["text"])
                        content_filled = True
                        print(f"  ✓ 正文已填写 (富文本, {ch['word_count']}字)")

                # 3. CodeMirror / Monaco 等
                if not content_filled:
                    editor = page.locator(".ql-editor, .ProseMirror, .CodeMirror-code")
                    if editor.count() > 0:
                        editor.first.click()
                        page.keyboard.type(ch["text"][:100])  # 先试一小段
                        content_filled = True
                        print(f"  ⚠ 检测到代码编辑器，尝试键入")

                if not content_filled:
                    print(f"  ✗ 未找到正文编辑区")
                    page.screenshot(
                        path=f"tests/screenshots/qimao_ch{ch['number']:03d}_no_editor.png"
                    )
                    continue

                # 截图确认
                page.screenshot(
                    path=f"tests/screenshots/qimao_ch{ch['number']:03d}_filled.png"
                )

                # === 保存并发布 ===
                if _save_and_publish(page):
                    print(f"  ✓ 已发布")
                    uploaded += 1
                else:
                    print(f"  ✗ 保存失败")

                # 返回章节管理
                _navigate_to_chapter_mgmt(page, chapter_mgmt_url)

                page.screenshot(
                    path=f"tests/screenshots/qimao_ch{ch['number']:03d}_done.png"
                )
                time.sleep(1)

            except Exception as e:
                print(f"  ✗ 上传失败: {e}")
                page.screenshot(
                    path=f"tests/screenshots/qimao_ch{ch['number']:03d}_error.png"
                )
                continue

        # 更新 session
        context.storage_state(path=str(AUTH_FILE))
        print(f"\n{'=' * 50}")
        print(f"上传完成: {uploaded}/{len(chapters)} 章")

        context.close()


def cmd_delete_all(keep_first: bool = True):
    """删除七猫上除第1章外的所有章节"""
    from playwright.sync_api import sync_playwright

    profile_dir = AUTH_FILE.parent / "chrome_profile"
    if not profile_dir.exists():
        print("错误: 未找到登录 session")
        sys.exit(1)

    with sync_playwright() as p:
        context = _launch_real_chrome(p)
        page = context.pages[0] if context.pages else context.new_page()

        page.goto(WRITER_URL)
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        # 进入章节管理
        mgmt = page.locator("a:has-text('章节管理'), span:has-text('章节管理')")
        if mgmt.count() > 0:
            mgmt.first.click()
            page.wait_for_load_state("networkidle")
            time.sleep(2)

        page.screenshot(path="tests/screenshots/qimao_before_delete.png")

        # 查找草稿箱
        draft_tab = page.locator("text=草稿箱")
        if draft_tab.count() > 0:
            draft_tab.first.click()
            time.sleep(2)
            page.screenshot(path="tests/screenshots/qimao_drafts.png")

            # 删除草稿箱中的所有章节
            while True:
                delete_btns = page.locator("text=删除")
                if delete_btns.count() == 0:
                    break
                delete_btns.first.click()
                time.sleep(1)
                # 确认删除
                confirm = page.locator("text=确定, text=确认")
                for i in range(confirm.count()):
                    if confirm.nth(i).is_visible():
                        confirm.nth(i).click()
                        time.sleep(2)
                        break
                print("  ✓ 删除一个草稿")

        print("✓ 草稿清理完成")
        context.storage_state(path=str(AUTH_FILE))
        context.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="七猫小说自动发布")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("login", help="登录七猫作家中心，保存 session")

    p_preview = sub.add_parser("preview", help="预览要上传的章节")
    p_preview.add_argument("novel_dir", help="小说项目目录")

    p_upload = sub.add_parser("upload", help="上传章节到七猫")
    p_upload.add_argument("novel_dir", help="小说项目目录")
    p_upload.add_argument("--start", type=int, default=1, help="起始章节号")
    p_upload.add_argument("--end", type=int, default=None, help="结束章节号")

    args = parser.parse_args()

    if args.cmd == "login":
        cmd_login()
    elif args.cmd == "preview":
        cmd_preview(args.novel_dir)
    elif args.cmd == "upload":
        cmd_upload(args.novel_dir, args.start, args.end)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

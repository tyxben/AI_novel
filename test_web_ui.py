"""Standalone Playwright smoke tests for the current Gradio UI."""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

import web

SCREENSHOTS_DIR = "test_screenshots"


def setup():
    Path(SCREENSHOTS_DIR).mkdir(exist_ok=True)


def _launch_server():
    app = web.create_ui()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    server_thread = threading.Thread(
        target=lambda: app.launch(
            server_name="127.0.0.1",
            server_port=port,
            share=False,
            prevent_thread_lock=True,
            inbrowser=False,
            quiet=True,
            css=web.CUSTOM_CSS,
            head=web.DROPDOWN_FIX_HEAD,
        ),
        daemon=True,
    )
    server_thread.start()
    time.sleep(5)
    return app, f"http://127.0.0.1:{port}"


def _open_accordion(page, title: str):
    acc = page.locator("button.label-wrap", has_text=title)
    expect(acc.first).to_be_visible()
    cls = acc.first.get_attribute("class") or ""
    if "open" not in cls:
        acc.first.click()
        time.sleep(0.3)


def test_page_loads(page, base_url):
    page.goto(base_url)
    page.wait_for_load_state("networkidle")
    expect(page.locator(".hero-section")).to_be_visible()
    expect(page.get_by_role("button", name="生成视频")).to_be_visible()
    page.screenshot(path=f"{SCREENSHOTS_DIR}/01_homepage.png", full_page=True)
    print("PASS: page loads")


def test_advanced_options_and_mode_toggle(page, base_url):
    page.goto(base_url)
    page.wait_for_load_state("networkidle")
    _open_accordion(page, "高级选项")

    expect(page.get_by_label("画面风格")).to_be_visible()
    expect(page.get_by_label("配音")).to_be_visible()

    page.get_by_text("Agent模式（智能质控）", exact=True).click()
    time.sleep(0.5)
    expect(page.get_by_text("省钱模式")).to_be_visible()

    page.get_by_text("经典模式（快速）", exact=True).click()
    time.sleep(0.5)
    assert not page.get_by_text("省钱模式").is_visible()
    print("PASS: advanced options and mode toggle")


def test_prompt_editor(page, base_url):
    page.goto(base_url)
    page.wait_for_load_state("networkidle")
    _open_accordion(page, "自定义提示词")

    prompt_field = page.get_by_label("系统提示词（控制 AI 写作风格）")
    expect(prompt_field).to_be_visible()
    prompt_field.fill("你是一个恐怖故事写手。")
    assert prompt_field.input_value() == "你是一个恐怖故事写手。"
    page.screenshot(path=f"{SCREENSHOTS_DIR}/02_prompt_editor.png", full_page=True)
    print("PASS: custom prompt editor")


def test_settings_tab(page, base_url):
    page.goto(base_url)
    page.wait_for_load_state("networkidle")
    page.get_by_role("tab", name="设置").click()
    time.sleep(0.5)

    expect(page.get_by_label("LLM 后端")).to_be_visible()
    expect(page.get_by_label("图片生成后端")).to_be_visible()
    expect(page.get_by_text("视频编码")).to_be_visible()
    page.screenshot(path=f"{SCREENSHOTS_DIR}/03_settings.png", full_page=True)
    print("PASS: settings tab controls")


def test_empty_text_error(page, base_url):
    page.goto(base_url)
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="生成视频").click()
    page.wait_for_selector(".toast-wrap, .error, [role='alert']", timeout=5000)
    print("PASS: empty text shows error")


def test_responsive(page, base_url):
    page.goto(base_url)
    page.wait_for_load_state("networkidle")
    for name, w, h in [("desktop", 1280, 900), ("mobile", 375, 812)]:
        page.set_viewport_size({"width": w, "height": h})
        time.sleep(0.5)
        page.screenshot(path=f"{SCREENSHOTS_DIR}/04_{name}.png", full_page=True)
    print("PASS: responsive")


def main():
    setup()
    passed = failed = 0
    tests = [
        test_page_loads,
        test_advanced_options_and_mode_toggle,
        test_prompt_editor,
        test_settings_tab,
        test_empty_text_error,
        test_responsive,
    ]

    app, base_url = _launch_server()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        for test in tests:
            try:
                test(page, base_url)
                passed += 1
            except Exception as e:
                failed += 1
                print(f"FAIL: {test.__name__}: {e}")
        browser.close()

    try:
        app.close()
    except Exception:
        pass

    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    return failed


if __name__ == "__main__":
    raise SystemExit(main())

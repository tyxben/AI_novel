"""Playwright UI tests for web.py"""

from playwright.sync_api import sync_playwright, expect
import time

BASE_URL = "http://localhost:7860"
SCREENSHOTS_DIR = "test_screenshots"


def setup():
    from pathlib import Path
    Path(SCREENSHOTS_DIR).mkdir(exist_ok=True)


def _open_config_accordion(page):
    """Open the '配置 AI 服务' accordion if collapsed."""
    acc = page.locator("button.label-wrap", has_text="配置 AI 服务")
    if acc.count() > 0:
        cls = acc.first.get_attribute("class") or ""
        if "open" not in cls:
            acc.first.click()
            time.sleep(0.5)


def test_page_loads(page):
    """Page loads with hero."""
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    hero = page.locator(".hero-section")
    expect(hero).to_be_visible()
    page.screenshot(path=f"{SCREENSHOTS_DIR}/01_homepage.png", full_page=True)
    print("PASS: page loads")


def test_quick_config_llm_select(page):
    """Quick config: LLM radio switches key fields."""
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    _open_config_accordion(page)

    # Click through all LLM options and verify key field changes
    for label, expected_key_label in [
        ("Gemini（免费推荐）", "Gemini API Key"),
        ("DeepSeek", "DeepSeek API Key"),
        ("OpenAI", "OpenAI API Key"),
    ]:
        page.locator(f"[data-testid='{label}-radio-label']").first.click(force=True)
        time.sleep(1)
        field = page.get_by_label(expected_key_label)
        expect(field).to_be_visible()

    page.screenshot(path=f"{SCREENSHOTS_DIR}/02_llm_radio.png", full_page=True)

    # Click Ollama - LLM key field should hide (image key may still be visible)
    page.locator("[data-testid='Ollama（本地免费）-radio-label']").first.click(force=True)
    time.sleep(1)
    # Verify no LLM-specific key label is visible
    for kl in ["Gemini API Key", "DeepSeek API Key", "OpenAI API Key"]:
        assert page.get_by_label(kl).count() == 0, f"Ollama: {kl} should be hidden"
    page.screenshot(path=f"{SCREENSHOTS_DIR}/03_llm_ollama.png", full_page=True)

    # Switch back to verify key field reappears
    page.locator("[data-testid='Gemini（免费推荐）-radio-label']").first.click(force=True)
    time.sleep(1)
    expect(page.get_by_label("Gemini API Key")).to_be_visible()

    print("PASS: LLM radio toggles correct key fields")


def test_quick_config_img_select(page):
    """Quick config: image radio switches key fields."""
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    _open_config_accordion(page)

    # Switch to SiliconFlow
    page.locator("[data-testid='SiliconFlow-radio-label']").first.click(force=True)
    time.sleep(1)
    expect(page.get_by_label("SiliconFlow API Key")).to_be_visible()
    page.screenshot(path=f"{SCREENSHOTS_DIR}/04_img_siliconflow.png", full_page=True)

    # Switch to 阿里云通义
    page.locator("[data-testid='阿里云通义-radio-label']").first.click(force=True)
    time.sleep(1)
    expect(page.get_by_label("阿里云 DashScope API Key")).to_be_visible()
    page.screenshot(path=f"{SCREENSHOTS_DIR}/05_img_dashscope.png", full_page=True)

    # Switch to Pollinations - key fields should hide
    page.locator("[data-testid='Pollinations（完全免费）-radio-label']").first.click(force=True)
    time.sleep(1)
    for kl in ["SiliconFlow API Key", "阿里云 DashScope API Key"]:
        assert page.get_by_label(kl).count() == 0, f"Pollinations: {kl} should be hidden"
    page.screenshot(path=f"{SCREENSHOTS_DIR}/06_img_pollinations.png", full_page=True)

    # Switch back to verify key reappears
    page.locator("[data-testid='SiliconFlow-radio-label']").first.click(force=True)
    time.sleep(1)
    expect(page.get_by_label("SiliconFlow API Key")).to_be_visible()

    print("PASS: image radio toggles correct key fields")


def test_video_controls(page):
    """Video controls visible."""
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    expect(page.get_by_label("画面风格")).to_be_visible()
    expect(page.get_by_label("配音")).to_be_visible()
    expect(page.get_by_role("button", name="生成视频")).to_be_visible()
    print("PASS: video controls visible")


def test_custom_prompt(page):
    """Custom prompt accordion and editor."""
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    # Open custom prompt accordion
    prompt_acc = page.locator("button.label-wrap", has_text="自定义提示词")
    expect(prompt_acc).to_be_visible()
    prompt_acc.first.click()
    time.sleep(0.3)

    prompt_field = page.get_by_label("系统提示词")
    expect(prompt_field).to_be_visible()

    # Should contain default prompt text
    val = prompt_field.input_value()
    assert "短视频" in val, f"Default prompt should mention 短视频, got: {val[:50]}"

    # User can edit
    prompt_field.fill("你是一个恐怖故事写手。写出让人毛骨悚然的故事。")
    time.sleep(0.3)
    page.screenshot(path=f"{SCREENSHOTS_DIR}/07_custom_prompt.png", full_page=True)
    print("PASS: custom prompt editor")


def test_refine_controls(page):
    """Refine story controls exist."""
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    refine_input = page.get_by_label("优化意见")
    expect(refine_input).to_be_visible()

    refine_btn = page.get_by_role("button", name="优化故事")
    expect(refine_btn).to_be_visible()

    page.screenshot(path=f"{SCREENSHOTS_DIR}/08_refine_controls.png", full_page=True)
    print("PASS: refine controls visible")


def test_fill_topic(page):
    """Fill topic and screenshot."""
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    topic = page.locator("textarea").first
    topic.fill("凌晨三点，外卖骑手接到一个送往废弃医院的订单")
    time.sleep(0.3)
    page.screenshot(path=f"{SCREENSHOTS_DIR}/09_filled.png", full_page=True)
    print("PASS: topic filled")


def test_responsive(page):
    """Responsive at desktop & mobile."""
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    for name, w, h in [("desktop", 1280, 900), ("mobile", 375, 812)]:
        page.set_viewport_size({"width": w, "height": h})
        time.sleep(0.5)
        page.screenshot(path=f"{SCREENSHOTS_DIR}/10_{name}.png", full_page=True)
    print("PASS: responsive")


def main():
    setup()
    passed = failed = 0
    tests = [
        test_page_loads,
        test_quick_config_llm_select,
        test_quick_config_img_select,
        test_video_controls,
        test_custom_prompt,
        test_refine_controls,
        test_fill_topic,
        test_responsive,
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        for test in tests:
            try:
                test(page)
                passed += 1
            except Exception as e:
                failed += 1
                print(f"FAIL: {test.__name__}: {e}")
        browser.close()

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    return failed


if __name__ == "__main__":
    exit(main())

"""端到端 Playwright 测试：生成故事 → 优化故事 → 生成视频 → 输出完整视频文件。

需要 Gradio 服务在 localhost:7860 运行，且至少配置了一个 LLM API Key。
"""

from playwright.sync_api import sync_playwright, expect
import time
import os

BASE_URL = "http://localhost:7860"
SCREENSHOTS_DIR = "test_screenshots"
# 整个视频生成流水线可能需要几分钟
VIDEO_TIMEOUT = 300_000  # 5 min


def setup():
    from pathlib import Path
    Path(SCREENSHOTS_DIR).mkdir(exist_ok=True)


def _open_config_accordion(page):
    acc = page.locator("button.label-wrap", has_text="配置 AI 服务")
    if acc.count() > 0:
        cls = acc.first.get_attribute("class") or ""
        if "open" not in cls:
            acc.first.click()
            time.sleep(0.5)


def _ensure_siliconflow_selected(page):
    """确保图片后端选了 SiliconFlow（Pollinations 免费服务不稳定）。"""
    acc = page.locator("button.label-wrap", has_text="配置 AI 服务")
    if acc.count() > 0:
        cls = acc.first.get_attribute("class") or ""
        if "open" not in cls:
            acc.first.click()
            time.sleep(0.5)

    sf_radio = page.locator("[data-testid='SiliconFlow-radio-label']")
    if sf_radio.count() > 0:
        sf_radio.first.click(force=True)
        time.sleep(1)


def test_e2e_full_pipeline(page):
    """完整流程：写故事 → 优化 → 生成视频 → 得到 mp4 文件。"""

    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    # ---- Step 0: 选 SiliconFlow 做图片后端 ----
    _ensure_siliconflow_selected(page)

    # ---- Step 1: 填写主题，生成故事 ----
    print("Step 1: 生成故事...")
    topic = page.get_by_label("你的灵感 / 故事主题")
    topic.fill("深夜外卖骑手接到一个送往废弃医院的订单")

    story_btn = page.get_by_role("button", name="AI 生成故事")
    story_btn.click()

    # 等待故事文本出现（LLM 可能需要 10-30 秒）
    txt_area = page.get_by_label("故事文本")
    expect(txt_area).not_to_have_value("", timeout=60_000)
    story_text = txt_area.input_value()
    assert len(story_text) > 30, f"故事太短: {len(story_text)} 字"
    print(f"  故事生成完成: {len(story_text)} 字")
    page.screenshot(path=f"{SCREENSHOTS_DIR}/e2e_01_story.png", full_page=True)

    # ---- Step 2: 优化故事 ----
    print("Step 2: 优化故事...")
    refine_input = page.get_by_label("优化意见")
    refine_input.fill("结尾要更加出人意料，加强悬疑感")

    refine_btn = page.get_by_role("button", name="优化故事")
    refine_btn.click()

    # 等待文本更新（和之前不一样就说明优化了）
    time.sleep(3)
    # 等到故事文本变化 — 轮询检查
    deadline = time.time() + 60
    refined_text = story_text
    while time.time() < deadline:
        refined_text = txt_area.input_value()
        if refined_text != story_text and len(refined_text) > 30:
            break
        time.sleep(2)

    assert refined_text != story_text, "故事优化后文本应该有变化"
    print(f"  故事优化完成: {len(refined_text)} 字")
    page.screenshot(path=f"{SCREENSHOTS_DIR}/e2e_02_refined.png", full_page=True)

    # ---- Step 3: 生成视频 ----
    print("Step 3: 生成视频（这一步较慢，请耐心等待）...")
    generate_btn = page.get_by_role("button", name="生成视频")
    generate_btn.click()

    # 等待状态框出现 "生成完成"
    status_box = page.get_by_label("当前状态")
    deadline = time.time() + VIDEO_TIMEOUT / 1000
    status_text = ""
    last_status = ""
    while time.time() < deadline:
        status_text = status_box.input_value()
        if status_text != last_status and status_text.strip():
            print(f"  状态: {status_text.strip()[:60]}")
            last_status = status_text
        if "生成完成" in status_text:
            break
        # 检查是否有 Error toast（Gradio 用多种 class）
        error_toast = page.locator(".toast-body.error, .toast-wrap .error, .error-text")
        if error_toast.count() > 0 and error_toast.first.is_visible():
            error_msg = error_toast.first.inner_text()
            raise AssertionError(f"生成失败: {error_msg}")
        time.sleep(3)

    assert "生成完成" in status_text, f"视频未在 {VIDEO_TIMEOUT//1000}s 内完成，最后状态: {status_text}"
    print(f"  视频生成完成!")
    page.screenshot(path=f"{SCREENSHOTS_DIR}/e2e_03_video.png", full_page=True)

    # ---- Step 4: 检查输出文件 ----
    print("Step 4: 检查视频文件...")
    # status_box 应该包含输出路径
    assert ".mp4" in status_text or "output" in status_text, f"状态文本应包含输出路径: {status_text}"

    # Video 组件应该有内容
    video_el = page.locator("video")
    expect(video_el.first).to_be_visible(timeout=10_000)

    # 下载区域应该可见（gr.File 渲染为带链接的区域）
    download_area = page.locator("a[download]")
    if download_area.count() > 0:
        print(f"  下载链接可用")
    else:
        print(f"  下载区域未检测到链接（视频组件已显示，可直接播放）")

    # 检查实际输出文件
    import re
    mp4_match = re.search(r"(output/\S+\.mp4)", status_text)
    if mp4_match:
        mp4_path = mp4_match.group(1)
        file_size = os.path.getsize(mp4_path) if os.path.exists(mp4_path) else 0
        assert file_size > 10_000, f"视频文件太小: {file_size} bytes"
        print(f"  视频文件: {mp4_path} ({file_size // 1024} KB)")

    page.screenshot(path=f"{SCREENSHOTS_DIR}/e2e_04_done.png", full_page=True)

    print("PASS: 端到端全流程测试通过!")


def main():
    setup()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        try:
            test_e2e_full_pipeline(page)
            print("\n" + "=" * 50)
            print("E2E 测试: PASSED")
            return 0
        except Exception as e:
            page.screenshot(path=f"{SCREENSHOTS_DIR}/e2e_FAIL.png", full_page=True)
            print(f"\nFAIL: {e}")
            print("\n" + "=" * 50)
            print("E2E 测试: FAILED")
            return 1
        finally:
            browser.close()


if __name__ == "__main__":
    exit(main())

"""Playwright E2E 测试 — 通过前端完整跑通 Agent 模式视频生成。

运行方式:
    export OPENAI_API_KEY="..."
    export SILICONFLOW_API_KEY="..."
    pytest tests/test_web_e2e.py -m e2e -v --timeout=300
"""
from __future__ import annotations

import os
import socket
import threading
import time

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.integration]

_skip_no_api = pytest.mark.skipif(
    not (os.environ.get("OPENAI_API_KEY") and os.environ.get("SILICONFLOW_API_KEY")),
    reason="需要 OPENAI_API_KEY 和 SILICONFLOW_API_KEY",
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def gradio_server():
    """启动 Gradio server，测试完成后关闭。"""
    import web

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
    time.sleep(5)  # 等待 Gradio 完全启动

    yield f"http://127.0.0.1:{port}"

    try:
        app.close()
    except Exception:
        pass


@pytest.fixture()
def browser_page(gradio_server):
    """创建 Playwright 浏览器页面。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(gradio_server, timeout=15000)
        page.wait_for_load_state("networkidle")
        yield page
        browser.close()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _input_story_text(page, text: str):
    """在故事文本框中输入文本。"""
    textarea = page.get_by_label("故事文本")
    textarea.fill(text)
    time.sleep(0.3)


def _select_agent_mode(page):
    """选择 Agent 模式。"""
    _open_advanced_options(page)
    page.get_by_text("Agent模式（智能质控）", exact=True).click()
    time.sleep(0.5)


def _click_generate(page):
    """点击生成视频按钮。"""
    page.get_by_text("生成视频", exact=True).click()


def _open_advanced_options(page):
    advanced = page.locator("button.label-wrap", has_text="高级选项")
    if advanced.count() == 0:
        return
    cls = advanced.first.get_attribute("class") or ""
    if "open" not in cls:
        advanced.first.click()
        time.sleep(0.3)


def _get_status_text(page) -> str:
    """获取状态栏文本，兼容不同 Gradio 版本的 DOM 结构。"""
    # Gradio 用 elem_classes="status-area" 渲染为容器，内含 textarea
    locator = page.locator(".status-area textarea")
    if locator.count() > 0:
        return locator.first.input_value()
    # fallback: 尝试 aria-label
    locator = page.locator("textarea[aria-label='当前状态']")
    if locator.count() > 0:
        return locator.first.input_value()
    # fallback: 找 label 文本对应的 textarea
    locator = page.locator("label:has-text('当前状态')").locator("..").locator("textarea")
    if locator.count() > 0:
        return locator.first.input_value()
    return ""


def _wait_for_completion(page, timeout: int = 300000):
    """等待状态栏出现"完成"字样。"""
    page.wait_for_function(
        """() => {
            // 尝试多种选择器
            const selectors = [
                '.status-area textarea',
                'textarea[aria-label="当前状态"]',
            ];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el && el.value && el.value.includes('完成')) return true;
            }
            return false;
        }""",
        timeout=timeout,
    )


def _fill_api_keys_quick(page):
    """通过设置页填入 API keys。"""
    page.get_by_role("tab", name="设置").click()
    time.sleep(0.5)

    page.get_by_label("OpenAI").fill(os.environ["OPENAI_API_KEY"])
    page.get_by_label("SiliconFlow (图片)").fill(os.environ["SILICONFLOW_API_KEY"])
    time.sleep(0.3)

    page.get_by_label("LLM 后端").click()
    page.get_by_role("option", name="OpenAI", exact=True).click()
    page.get_by_label("图片生成后端").click()
    page.get_by_role("option", name="SiliconFlow", exact=True).click()
    time.sleep(0.3)

    page.get_by_role("tab", name="短视频制作").click()
    time.sleep(0.3)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWebUIQuickCheck:
    """不依赖 API 的 UI 交互回归。"""

    def test_page_loads(self, browser_page):
        """页面能正常加载，关键元素都在。"""
        page = browser_page
        assert page.title() == "AI 创作工坊"

        # 检查关键按钮存在
        assert page.get_by_text("生成视频").is_visible()
        assert page.get_by_text("AI 生成故事").is_visible()

    def test_advanced_options_hidden_by_default(self, browser_page):
        page = browser_page

        assert page.get_by_text("省钱模式").count() == 0
        assert page.get_by_text("画面风格").count() == 0

    def test_mode_toggle_shows_hides_options(self, browser_page):
        """模式切换应正确显隐 Agent 选项。"""
        page = browser_page
        _open_advanced_options(page)

        assert page.get_by_text("经典模式（快速）").is_visible()
        assert page.get_by_text("Agent模式（智能质控）").is_visible()
        _select_agent_mode(page)
        assert page.get_by_text("省钱模式").is_visible()

        page.get_by_text("经典模式（快速）", exact=True).click()
        time.sleep(0.5)
        assert not page.get_by_text("省钱模式").is_visible()

    def test_empty_text_shows_error(self, browser_page):
        """空文本点生成应该弹错误。"""
        page = browser_page
        _click_generate(page)
        page.wait_for_selector(".toast-wrap, .error, [role='alert']", timeout=5000)

    def test_story_prompt_editor_is_editable(self, browser_page):
        page = browser_page

        prompt_acc = page.locator("button.label-wrap", has_text="自定义提示词")
        prompt_acc.first.click()
        time.sleep(0.3)

        prompt_field = page.get_by_label("系统提示词（控制 AI 写作风格）")
        assert prompt_field.is_visible()
        prompt_field.fill("你是一个悬疑故事写手。")
        assert prompt_field.input_value() == "你是一个悬疑故事写手。"

    def test_settings_tab_has_backend_controls(self, browser_page):
        page = browser_page
        page.get_by_role("tab", name="设置").click()
        time.sleep(0.5)

        assert page.get_by_label("LLM 后端").is_visible()
        assert page.get_by_label("图片生成后端").is_visible()
        assert page.get_by_text("视频编码").is_visible()


@_skip_no_api
class TestWebUIAgentMode:
    """通过 Playwright 测试 Web UI Agent 模式完整流程。"""

    def test_classic_mode_generates_video(self, browser_page):
        """经典模式：输入文本 → 生成视频 → 验证输出。"""
        page = browser_page
        _input_story_text(page, "月光如水，少年拔剑而立。")
        _fill_api_keys_quick(page)
        _click_generate(page)
        _wait_for_completion(page)
        status = _get_status_text(page)
        assert "完成" in status

    def test_agent_mode_full_flow(self, browser_page):
        """Agent 模式：输入文本 → 选Agent → 生成 → 验证输出+决策日志。"""
        page = browser_page

        # 输入武侠短文
        test_text = "少年站在山顶，望着远方的云海。他拔出长剑，剑身闪烁着寒光。"
        _input_story_text(page, test_text)

        # 配置 API keys
        _fill_api_keys_quick(page)

        # 选择 Agent 模式
        _select_agent_mode(page)
        time.sleep(0.5)

        # 点击生成
        _click_generate(page)

        # 等待生成完成（最多 5 分钟）
        _wait_for_completion(page)

        # 验证状态
        status = _get_status_text(page)
        assert "完成" in status

        # 验证 Agent 分析 Tab 出现了（Gradio 可能渲染多个同名元素，用 first）
        agent_tab = page.get_by_role("tab", name="Agent 分析")
        assert agent_tab.first.is_visible()

        # 点击 Agent 分析 Tab 查看内容
        agent_tab.first.click()
        time.sleep(1)

        # 验证决策日志 Tab 出现了
        decision_tab = page.get_by_role("tab", name="决策日志")
        assert decision_tab.first.is_visible()

        # 验证质量报告 Tab 出现了
        quality_tab = page.get_by_role("tab", name="质量报告")
        assert quality_tab.first.is_visible()

        # 截图保存
        page.screenshot(path="tests/screenshots/agent_mode_result.png")

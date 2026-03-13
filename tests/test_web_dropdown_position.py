from __future__ import annotations

import threading
import time
import socket

import pytest


@pytest.fixture(scope="module")
def gradio_server():
    """Launch the local Gradio app for UI regression tests."""
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
    time.sleep(5)

    yield f"http://127.0.0.1:{port}"

    try:
        app.close()
    except Exception:
        pass


@pytest.fixture()
def browser_page(gradio_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.goto(gradio_server, timeout=15000)
        page.wait_for_load_state("networkidle")
        yield page
        browser.close()


def _open_dropdown(page, label_text: str) -> None:
    opened = page.evaluate(
        """(targetLabel) => {
            const label = Array.from(document.querySelectorAll('[data-testid="block-info"]'))
                .find((node) => node.textContent.trim() === targetLabel);
            if (!label) return false;

            const root = label.closest('.container');
            const input = root ? root.querySelector('input[role="listbox"]') : null;
            if (!input) return false;

            input.focus();
            input.click();
            return true;
        }""",
        label_text,
    )
    assert opened, f"could not open dropdown for label: {label_text}"


def _measure_dropdown_alignment(page) -> dict[str, float]:
    metrics = page.evaluate(
        """() => {
            const isVisible = (el) => {
                if (!el || el.classList.contains('hide')) return false;
                const style = window.getComputedStyle(el);
                return style.display !== 'none' && style.visibility !== 'hidden';
            };

            const label = Array.from(document.querySelectorAll('[data-testid="block-info"]'))
                .find((node) => node.textContent.trim() === '类型');
            const root = label ? label.closest('.container') : null;
            const wrap = root ? root.querySelector('.wrap') : null;
            const list = Array.from(document.querySelectorAll('ul.options')).find(isVisible);

            if (!wrap || !list) {
                return null;
            }

            const wrapRect = wrap.getBoundingClientRect();
            const listRect = list.getBoundingClientRect();
            return {
                wrapBottom: wrapRect.bottom,
                wrapLeft: wrapRect.left,
                wrapWidth: wrapRect.width,
                listTop: listRect.top,
                listLeft: listRect.left,
                listWidth: listRect.width,
                gap: listRect.top - wrapRect.bottom,
                leftDelta: listRect.left - wrapRect.left,
                widthDelta: listRect.width - wrapRect.width,
            };
        }"""
    )
    assert metrics is not None, "dropdown should be open and measurable"
    return metrics


def test_dropdown_tracks_trigger_after_scroll(browser_page):
    page = browser_page

    _open_dropdown(page, "类型")
    page.keyboard.press("ArrowDown")
    page.wait_for_selector("ul.options:not(.hide)", state="visible", timeout=5000)

    before = _measure_dropdown_alignment(page)

    page.evaluate("window.scrollTo(0, 220)")
    time.sleep(0.3)

    after = _measure_dropdown_alignment(page)

    assert abs(after["gap"] - before["gap"]) <= 4
    assert abs(after["leftDelta"] - before["leftDelta"]) <= 4
    assert abs(after["widthDelta"]) <= 4

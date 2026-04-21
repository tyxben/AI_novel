"""Shared pytest configuration for the whole tests/ tree.

Phase 5 新增：``--run-real`` CLI option + collection modifier，用于在默认
pytest 运行时自动跳过需要真机 LLM 的 marker 标记测试（``llm_judge`` /
``real_run`` / ``regression``）。

设计要点
--------
- 现有 4370+ 测试不受影响：没有相关 marker 的用例正常跑。
- CI 或本地想跑真机回归时加 ``--run-real`` 即可打开。
- 与 ``integration`` / ``e2e`` marker 正交（它们已经有独立的 opt-in 机制）。
"""

from __future__ import annotations

import pytest


_REAL_RUN_MARKERS = ("llm_judge", "real_run", "regression")


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register ``--run-real`` so real-LLM suites are opt-in."""
    parser.addoption(
        "--run-real",
        action="store_true",
        default=False,
        help="Run tests that require real LLM API calls",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Skip real-LLM marked tests unless ``--run-real`` was passed."""
    if config.getoption("--run-real"):
        return

    skip_real = pytest.mark.skip(reason="need --run-real to run")
    for item in items:
        keywords = item.keywords
        if any(marker in keywords for marker in _REAL_RUN_MARKERS):
            item.add_marker(skip_real)

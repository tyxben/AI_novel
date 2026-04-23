"""阶段 3: 跑 NovelPipeline.generate_chapters 重生 ch19 + ch28-32."""

from __future__ import annotations
import os
import sys
from pathlib import Path

_ROOT = Path("/Users/ty/self/AI_novel")
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_env_path = _ROOT / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            _k = _k.strip()
            _v = _v.strip().strip("'\"")
            if _k and _k not in os.environ:
                os.environ[_k] = _v

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

from src.novel.pipeline import NovelPipeline

PROJECT = "workspace/novels/novel_12e1c974"

pipe = NovelPipeline(workspace="workspace")

# --- 第一段: ch19 单章 ---
print("=" * 60)
print("[stage 3a] generate_chapters(start=19, end=19)")
print("=" * 60)
result_19 = pipe.generate_chapters(
    project_path=PROJECT,
    start_chapter=19,
    end_chapter=19,
    silent=True,
)
print(f"ch19 result: status={result_19.get('status')} chapters_written={result_19.get('chapters_written')}")
if result_19.get("errors"):
    print(f"  errors: {result_19['errors'][:3]}")

# --- 第二段: ch28-32 ---
print("=" * 60)
print("[stage 3b] generate_chapters(start=28, end=32)")
print("=" * 60)
result_28_32 = pipe.generate_chapters(
    project_path=PROJECT,
    start_chapter=28,
    end_chapter=32,
    silent=True,
)
print(f"ch28-32 result: status={result_28_32.get('status')} chapters_written={result_28_32.get('chapters_written')}")
if result_28_32.get("errors"):
    print(f"  errors: {result_28_32['errors'][:3]}")

# --- vol1/vol2 settle ---
print("=" * 60)
print("[stage 3c] settle volumes")
print("=" * 60)
for vn in (1, 2):
    try:
        rep = pipe.settle_volume(project_path=PROJECT, volume_number=vn)
        print(f"vol{vn} settle: {rep}")
    except Exception as exc:
        print(f"vol{vn} settle failed: {exc}")

print("\n=== STAGE 3 DONE ===")

"""De-bias 反向对照：把 Phase 4 放到 a 位置、Phase 3 放到 b 位置，检查 judge 是否有 position bias。

判读：
- 反向结果接近镜像 (40a/60b) → 原 A/B 是真信号
- 反向结果仍偏 a (>50%) → 存在 position bias，原 A/B 不可独立解读
- 双向一致的 (genre, ch) 才是 de-biased 真信号

2026-04-21 Phase 5 首次 Phase 3 vs Phase 4 对比发现 gpt-4o-mini 有强 position bias
(Run 1: 60% a / Run 2: 93% a)，确认单向 A/B 不可信。未来 Phase N 对比必须跑双向。

前置：workspace_quality_phase3/ 和 workspace_quality_baseline/ 已存在对应体裁项目。
"""

import sys
from pathlib import Path
from collections import Counter

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

# 加载 .env
_env = _ROOT / ".env"
if _env.exists():
    import os
    for line in _env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip("'\"")
            if k and k not in os.environ:
                os.environ[k] = v

from src.novel.quality.ab_compare import pairwise_judge
from src.novel.quality.judge import JudgeConfig


PHASE3_ROOT = _ROOT / "workspace_quality_phase3" / "novels"
PHASE4_ROOT = _ROOT / "workspace_quality_baseline" / "novels"

GENRE_MAP = {
    "玄幻": "xuanhuan",
    "悬疑": "suspense",
    "现代言情": "romance",
    "科幻": "scifi",
    "武侠": "wuxia",
}


def load_projects(root: Path) -> dict[str, Path]:
    import json
    result = {}
    for novel_dir in sorted(root.iterdir()):
        if not novel_dir.is_dir():
            continue
        novel_json = novel_dir / "novel.json"
        if not novel_json.exists():
            continue
        data = json.loads(novel_json.read_text(encoding="utf-8"))
        genre = data.get("genre", "")
        key = GENRE_MAP.get(genre)
        if key:
            result[key] = novel_dir
    return result


def load_chapter(project_dir: Path, ch_num: int) -> str:
    p = project_dir / "chapters" / f"chapter_{ch_num:03d}.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def main():
    phase3 = load_projects(PHASE3_ROOT)
    phase4 = load_projects(PHASE4_ROOT)
    common = sorted(set(phase3) & set(phase4))
    print(f"Genres: {common}")

    # 用 gpt-4o-mini 保持与原 A/B 一致
    config = JudgeConfig(
        model="gpt-4o-mini",
        temperature=0.1,
        provider="openai",
        max_tokens=2048,
        same_source=False,
    )

    winners = Counter()
    dim_winners = {d: Counter() for d in (
        "narrative_flow", "character_consistency", "plot_advancement",
        "dialogue_quality", "chapter_hook",
    )}
    results = []

    for g in common:
        for ch in (1, 2, 3):
            t3 = load_chapter(phase3[g], ch)
            t4 = load_chapter(phase4[g], ch)
            if not t3 or not t4:
                print(f"skip {g} ch{ch}: missing text")
                continue
            # SWAP: Phase 4 做 a, Phase 3 做 b
            r = pairwise_judge(
                text_a=t4, text_b=t3,
                genre=g, chapter_number=ch,
                commit_a="phase4-e3eaf58", commit_b="phase3-8fcd7be",
                config=config,
            )
            winners[r.winner] += 1
            for d, pref in r.dimension_preferences.items():
                if d in dim_winners:
                    dim_winners[d][pref] += 1
            print(f"{g} ch{ch}: winner={r.winner}")
            results.append((g, ch, r.winner, r.dimension_preferences))

    total = sum(winners.values())
    print("\n=== REVERSE A/B (a=Phase4, b=Phase3) ===")
    print(f"Total: {total}")
    print(f"a (Phase 4): {winners['a']} ({100*winners['a']/total:.0f}%)")
    print(f"b (Phase 3): {winners['b']} ({100*winners['b']/total:.0f}%)")
    print(f"tie: {winners['tie']} ({100*winners['tie']/total:.0f}%)")
    print("\nPer-dimension:")
    for d, c in dim_winners.items():
        print(f"  {d}: a={c['a']} b={c['b']} tie={c['tie']}")


if __name__ == "__main__":
    main()

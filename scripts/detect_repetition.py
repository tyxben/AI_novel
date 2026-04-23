"""跨章 / 章内重复检测 — 用现有 dedup_dialogue 服务 + 简单 shingle.

用法::

    python scripts/detect_repetition.py --novel-id novel_12e1c974 \\
        --start 18 --end 32

检测项
------
1. 章内重复段（复用 src/novel/services/dedup_dialogue
   .strip_repeated_paragraph_blocks 算法的判定逻辑，但不剥离，仅报告）
2. 跨章 5-gram shingle Jaccard 相似度矩阵
3. 跨章首段 / 末段相似度（开头/结尾套路）
4. 跨章共享高频短语（≥4-gram，命中 ≥3 章）
5. 跨章共享段落（normalize 后整段一致）

输出
----
- workspace/quality_reports/audit/<novel_id>_repetition_ch<start>-<end>.md
- 控制台 Rich Table 摘要
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.novel.storage.file_manager import FileManager
from src.novel.services.dedup_dialogue import (
    _MAX_BLOCK_GAP,
    _MAX_BLOCK_SIZE,
    _MIN_BLOCK_PARA_LEN,
    _count_chinese_chars,
    _normalize,
)


# 中文字符正则
_CN_RE = re.compile(r"[一-鿿]")


def _to_chinese_chars(s: str) -> str:
    return "".join(_CN_RE.findall(s or ""))


def _shingles(text: str, n: int) -> set[str]:
    s = _to_chinese_chars(text)
    if len(s) < n:
        return set()
    return {s[i : i + n] for i in range(len(s) - n + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


@dataclass
class IntraChapterDup:
    chapter_number: int
    repeated_blocks: list[tuple[int, int, int, str]]  # (start_para, length, gap, sample)


def _find_intra_chapter_dups(text: str) -> list[tuple[int, int, int, str]]:
    """复用 dedup_dialogue 的判定参数，但只报告不删除。"""
    paragraphs = _split_paragraphs(text)
    norm = [_normalize(p) for p in paragraphs]
    is_long = [
        _count_chinese_chars(p) >= _MIN_BLOCK_PARA_LEN for p in paragraphs
    ]
    found: list[tuple[int, int, int, str]] = []
    seen_blocks: set[tuple[int, int]] = set()
    for block_size in range(_MAX_BLOCK_SIZE, 0, -1):
        for i in range(len(paragraphs) - block_size + 1):
            block = tuple(norm[i : i + block_size])
            if not all(is_long[j] for j in range(i, i + block_size)):
                continue
            if not all(b for b in block):
                continue
            # 是否在 earliest..i 之间有同样 block
            earliest = max(0, i - block_size - _MAX_BLOCK_GAP)
            for j in range(earliest, i):
                if j + block_size > i:
                    break
                cand = tuple(norm[j : j + block_size])
                if cand == block:
                    key = (j, i)
                    if key in seen_blocks:
                        continue
                    seen_blocks.add(key)
                    found.append(
                        (
                            i + 1,  # 1-based
                            block_size,
                            i - (j + block_size),
                            paragraphs[i][:60],
                        )
                    )
                    break
    return found


def _opening(text: str) -> str:
    paras = _split_paragraphs(text)
    return _to_chinese_chars(paras[0]) if paras else ""


def _ending(text: str) -> str:
    paras = _split_paragraphs(text)
    return _to_chinese_chars(paras[-1]) if paras else ""


def _ngrams(text: str, n: int) -> Counter:
    s = _to_chinese_chars(text)
    if len(s) < n:
        return Counter()
    return Counter(s[i : i + n] for i in range(len(s) - n + 1))


def _shared_paragraphs(
    chapters: dict[int, str], min_len: int = 30
) -> list[tuple[str, list[int]]]:
    """跨章 normalize 后整段一致的段落。"""
    para_to_chs: dict[str, list[int]] = defaultdict(list)
    for ch_num, text in chapters.items():
        for p in _split_paragraphs(text):
            norm = _normalize(p)
            if _count_chinese_chars(norm) >= min_len:
                para_to_chs[norm].append(ch_num)
    out: list[tuple[str, list[int]]] = []
    for norm, chs in para_to_chs.items():
        if len(set(chs)) >= 2:
            out.append((norm[:120], sorted(set(chs))))
    out.sort(key=lambda t: -len(t[1]))
    return out


def _shared_phrases(
    chapters: dict[int, str], n: int = 6, min_total: int = 6, min_chs: int = 3
) -> list[tuple[str, int, list[int]]]:
    """≥3 章命中、累计 ≥6 次的 n-gram。"""
    per_chapter_counts: dict[int, Counter] = {
        ch: _ngrams(text, n) for ch, text in chapters.items()
    }
    # 全局总频次 + 章命中数
    total = Counter()
    chs_per_phrase: dict[str, set[int]] = defaultdict(set)
    for ch, cnt in per_chapter_counts.items():
        for ph, c in cnt.items():
            total[ph] += c
            chs_per_phrase[ph].add(ch)
    out: list[tuple[str, int, list[int]]] = []
    for ph, total_c in total.most_common():
        chs = chs_per_phrase[ph]
        if total_c >= min_total and len(chs) >= min_chs:
            out.append((ph, total_c, sorted(chs)))
    return out[:80]


def _build_jaccard_matrix(
    chapters: dict[int, str], n: int = 5
) -> tuple[list[int], list[set[str]], list[list[float]]]:
    nums = sorted(chapters.keys())
    sh_list = [_shingles(chapters[c], n) for c in nums]
    matrix: list[list[float]] = []
    for i, a in enumerate(sh_list):
        row = []
        for j, b in enumerate(sh_list):
            row.append(_jaccard(a, b) if i != j else 1.0)
        matrix.append(row)
    return nums, sh_list, matrix


def _opening_ending_similarity(
    chapters: dict[int, str], n: int = 4
) -> tuple[list[tuple[int, int, float, str, str]], list[tuple[int, int, float, str, str]]]:
    nums = sorted(chapters.keys())
    op_pairs: list[tuple[int, int, float, str, str]] = []
    en_pairs: list[tuple[int, int, float, str, str]] = []
    op_sh = {c: _shingles(_opening(chapters[c]), n) for c in nums}
    en_sh = {c: _shingles(_ending(chapters[c]), n) for c in nums}
    for i, a in enumerate(nums):
        for b in nums[i + 1 :]:
            j_op = _jaccard(op_sh[a], op_sh[b])
            j_en = _jaccard(en_sh[a], en_sh[b])
            if j_op >= 0.25:
                op_pairs.append((a, b, j_op, _opening(chapters[a])[:60], _opening(chapters[b])[:60]))
            if j_en >= 0.25:
                en_pairs.append((a, b, j_en, _ending(chapters[a])[:60], _ending(chapters[b])[:60]))
    op_pairs.sort(key=lambda t: -t[2])
    en_pairs.sort(key=lambda t: -t[2])
    return op_pairs, en_pairs


def _render_md(
    novel_id: str,
    nums: list[int],
    matrix: list[list[float]],
    intra: dict[int, list[tuple[int, int, int, str]]],
    op_pairs,
    en_pairs,
    shared_paras,
    shared_phrases,
) -> str:
    lines: list[str] = []
    lines.append(f"# 重复检测报告 — {novel_id}")
    lines.append(f"章节范围: ch{nums[0]}–ch{nums[-1]}")
    lines.append("")
    lines.append("## 1. 跨章 5-gram Jaccard 相似度（>=0.10 标黄, >=0.20 标红）")
    lines.append("")
    header = "| ch | " + " | ".join(str(c) for c in nums) + " |"
    sep = "|---" + "|---" * len(nums) + "|"
    lines.append(header)
    lines.append(sep)
    for i, c in enumerate(nums):
        cells = []
        for j, _ in enumerate(nums):
            v = matrix[i][j]
            if i == j:
                cells.append("-")
            elif v >= 0.20:
                cells.append(f"**{v:.2f}**")
            elif v >= 0.10:
                cells.append(f"_{v:.2f}_")
            else:
                cells.append(f"{v:.2f}")
        lines.append(f"| {c} | " + " | ".join(cells) + " |")
    lines.append("")

    # 高相似度对
    high_pairs = []
    for i, a in enumerate(nums):
        for j, b in enumerate(nums[i + 1 :], start=i + 1):
            v = matrix[i][j]
            if v >= 0.10:
                high_pairs.append((v, a, b))
    high_pairs.sort(reverse=True)
    if high_pairs:
        lines.append("### 高相似度章节对（Jaccard >= 0.10）")
        for v, a, b in high_pairs[:30]:
            lines.append(f"- ch{a} vs ch{b}: **{v:.3f}**")
        lines.append("")

    lines.append("## 2. 章内段落复读（dedup_dialogue 阈值）")
    any_intra = False
    for c in nums:
        dups = intra.get(c) or []
        if not dups:
            continue
        any_intra = True
        lines.append(f"\n### 第{c}章 ({len(dups)} 处)")
        for start_para, blk, gap, sample in dups[:8]:
            lines.append(
                f"- 段{start_para} block={blk} gap={gap}: `{sample}`"
            )
    if not any_intra:
        lines.append("(无)\n")

    lines.append("## 3. 章节开头相似（首段）")
    if op_pairs:
        for a, b, v, sa, sb in op_pairs[:15]:
            lines.append(f"- ch{a}↔ch{b} jaccard={v:.2f}")
            lines.append(f"  - ch{a}: `{sa}`")
            lines.append(f"  - ch{b}: `{sb}`")
    else:
        lines.append("(无)")
    lines.append("")

    lines.append("## 4. 章节结尾相似（末段）")
    if en_pairs:
        for a, b, v, sa, sb in en_pairs[:15]:
            lines.append(f"- ch{a}↔ch{b} jaccard={v:.2f}")
            lines.append(f"  - ch{a}: `{sa}`")
            lines.append(f"  - ch{b}: `{sb}`")
    else:
        lines.append("(无)")
    lines.append("")

    lines.append("## 5. 跨章一致段落（normalize 后整段一致）")
    if shared_paras:
        for sample, chs in shared_paras[:30]:
            lines.append(f"- ch{chs}: `{sample}`")
    else:
        lines.append("(无)")
    lines.append("")

    lines.append("## 6. 跨章共享 6-gram（≥3 章, ≥6 次）")
    if shared_phrases:
        lines.append("")
        lines.append("| 短语 | 累计 | 章节 |")
        lines.append("|---|---:|---|")
        for ph, total_c, chs in shared_phrases[:60]:
            lines.append(f"| `{ph}` | {total_c} | {chs} |")
    else:
        lines.append("(无)")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default="workspace")
    parser.add_argument("--novel-id", required=True)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--shingle-n", type=int, default=5)
    args = parser.parse_args()

    fm = FileManager(args.workspace)
    chapters: dict[int, str] = {}
    for ch in range(args.start, args.end + 1):
        text = fm.load_chapter_text(args.novel_id, ch)
        if text:
            chapters[ch] = text
    if not chapters:
        print("no chapters loaded", file=sys.stderr)
        return 2

    nums, _shings, matrix = _build_jaccard_matrix(chapters, n=args.shingle_n)
    intra = {ch: _find_intra_chapter_dups(text) for ch, text in chapters.items()}
    op_pairs, en_pairs = _opening_ending_similarity(chapters, n=4)
    shared_paras = _shared_paragraphs(chapters, min_len=30)
    shared_phrases = _shared_phrases(chapters, n=6, min_total=6, min_chs=3)

    md = _render_md(
        args.novel_id,
        nums,
        matrix,
        intra,
        op_pairs,
        en_pairs,
        shared_paras,
        shared_phrases,
    )

    out_dir = Path(args.workspace) / "quality_reports" / "audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.novel_id}_repetition_ch{args.start}-{args.end}.md"
    out_path.write_text(md, encoding="utf-8")

    # 控制台输出关键摘要
    try:
        from rich.console import Console
        from rich.table import Table
    except Exception:
        Console = None  # type: ignore[assignment]

    print(f"\nMD: {out_path}\n")

    high_pairs = []
    for i, a in enumerate(nums):
        for j, b in enumerate(nums[i + 1 :], start=i + 1):
            v = matrix[i][j]
            if v >= 0.10:
                high_pairs.append((v, a, b))
    high_pairs.sort(reverse=True)

    if Console is not None:
        cs = Console()
        # 5-gram 矩阵
        t = Table(title=f"{args.shingle_n}-gram Jaccard 矩阵")
        t.add_column("ch")
        for c in nums:
            t.add_column(str(c), justify="right")
        for i, c in enumerate(nums):
            row = [str(c)]
            for j, _ in enumerate(nums):
                v = matrix[i][j]
                if i == j:
                    row.append("-")
                else:
                    style = (
                        "red"
                        if v >= 0.20
                        else "yellow"
                        if v >= 0.10
                        else "white"
                    )
                    row.append(f"[{style}]{v:.2f}[/]")
            t.add_row(*row)
        cs.print(t)

        if high_pairs:
            cs.print(f"\n[bold]高相似度章节对（>= 0.10）[/]：")
            for v, a, b in high_pairs[:20]:
                cs.print(f"  ch{a} vs ch{b}: {v:.3f}")
        intra_with_dups = [(c, len(d)) for c, d in intra.items() if d]
        if intra_with_dups:
            cs.print(f"\n[bold]章内复读章节[/]：{intra_with_dups}")
        cs.print(
            f"\n首段相似对: {len(op_pairs)}; 末段相似对: {len(en_pairs)}; "
            f"跨章共享段落: {len(shared_paras)}; 共享 6-gram: {len(shared_phrases)}"
        )
    else:
        for v, a, b in high_pairs[:20]:
            print(f"ch{a} vs ch{b}: {v:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

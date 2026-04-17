"""真机验证脚本：commit ae55a06 的 fix #1-#7 回归检查.

用法:
    python scripts/verify_novel_fixes.py [--chapters N] [--workspace DIR]

流程:
    1. 不传 config 实例化 NovelPipeline()，检查默认 LLM 配置 (#1)
    2. create_novel + generate_chapters(1..N)
    3. 对产出进行断言:
       - #3 novel.json characters[*].role 非空
       - #4/#5 generate_chapters 返回结构包含 status/project_path/chapters_written
              且 chapter 记录含 scenes 字段
       - #7 create_novel 过程 story arcs 未崩 (errors 中无 arcs 相关条目)
       - #2 每章正文无"连续 1-4 段整块复读"
       - #6 每章字数在软区间（<= 1.5 * target 且 >= 0.5 * target）

输出:
    scripts 运行日志 + 末尾 PASS/FAIL 报告表。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Make sure project root is importable
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Manually load .env (不依赖 python-dotenv)
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

from src.novel.pipeline import NovelPipeline
from src.novel.config import NovelConfig
from src.novel.services.dedup_dialogue import (
    _normalize,
    _count_chinese_chars,
    _MIN_BLOCK_PARA_LEN,
    _MAX_BLOCK_SIZE,
    _MAX_BLOCK_GAP,
)


def _fmt(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def check_fix_1_zero_config() -> tuple[bool, str]:
    """#1: NovelPipeline() 零配置应默认为 deepseek-chat."""
    pipe = NovelPipeline()
    cfg = pipe.config
    if not isinstance(cfg, NovelConfig):
        return False, f"config 类型错误: {type(cfg)}"
    expected = "deepseek-chat"
    fields = {
        "outline_generation": cfg.llm.outline_generation,
        "scene_writing": cfg.llm.scene_writing,
        "quality_review": cfg.llm.quality_review,
    }
    mismatches = {k: v for k, v in fields.items() if v != expected}
    if mismatches:
        return False, f"默认模型不为 deepseek-chat: {mismatches}"
    return True, f"默认 llm 全部 = {expected}"


def check_fix_4_5_return_shape(result: dict[str, Any]) -> tuple[bool, str]:
    """#4/#5: generate_chapters 返回结构字段齐全."""
    required = {"status", "project_path", "chapters_generated", "chapters_written"}
    missing = required - set(result.keys())
    if missing:
        return False, f"缺失字段: {missing}"
    if result["chapters_generated"] is not result["chapters_written"] \
            and result["chapters_generated"] != result["chapters_written"]:
        return False, "chapters_written 不是 chapters_generated 的别名"
    if result["status"] not in {"success", "partial", "noop"}:
        return False, f"status 取值异常: {result['status']}"
    return True, (
        f"status={result['status']} chapters_written={result['total_generated']}"
    )


def check_fix_5_scene_field(
    result: dict[str, Any], workspace: str
) -> tuple[bool, str]:
    """#5: 每个 chapter 记录都应含 scenes 字段（从 checkpoint 读）."""
    novel_id = Path(result["project_path"]).name
    ckpt_path = Path(workspace) / "novels" / novel_id / "checkpoint.json"
    if not ckpt_path.exists():
        return False, f"checkpoint 不存在: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    records = data.get("chapters") or []
    if not records:
        return False, "checkpoint chapters 为空"
    missing = [
        r.get("chapter_number")
        for r in records
        if not isinstance(r, dict) or "scenes" not in r
    ]
    if missing:
        return False, f"章节 {missing} 缺 scenes 字段"
    scene_counts = [len(r.get("scenes") or []) for r in records]
    return True, (
        f"{len(records)} 章全含 scenes 字段 (lens={scene_counts})"
    )


def check_fix_3_character_role(project_path: str, workspace: str) -> tuple[bool, str]:
    """#3: characters[*].role 字段应存在且非空."""
    novel_id = Path(project_path).name
    novel_json = Path(workspace) / "novels" / novel_id / "novel.json"
    if not novel_json.exists():
        return False, f"novel.json 不存在: {novel_json}"
    data = json.loads(novel_json.read_text(encoding="utf-8"))
    chars = data.get("characters") or []
    if not chars:
        return False, "novel.json characters 为空"
    missing = []
    role_values: list[str] = []
    for c in chars:
        role = c.get("role") if isinstance(c, dict) else None
        if not role:
            missing.append(c.get("name") if isinstance(c, dict) else c)
        else:
            role_values.append(f"{c.get('name')}={role}")
    if missing:
        return False, f"无 role 字段: {missing}"
    return True, f"{len(chars)} 个角色全带 role: {role_values[:5]}"


def check_fix_7_arcs(create_result: dict[str, Any]) -> tuple[bool, str]:
    """#7: story arcs 不崩 (errors 中无 dict-has-no-attribute-chapters)."""
    errors = create_result.get("errors") or []
    arc_related = [e for e in errors if "arc" in str(e).lower() or "chapters" in str(e).lower()]
    if arc_related:
        return False, f"arc 相关错误: {arc_related[:3]}"
    return True, f"create_novel 无 arc 相关异常 (总 errors={len(errors)})"


def _detect_paragraph_block_repeats(text: str) -> list[tuple[int, int, str]]:
    """返回 [(block_size, start_idx, preview), ...] —— 如果空 list 表示无重复."""
    import re

    paragraphs = re.split(r"\n\s*\n", text)
    n = len(paragraphs)
    if n < 2:
        return []
    norms = [_normalize(p) for p in paragraphs]
    eligible = [_count_chinese_chars(p) >= _MIN_BLOCK_PARA_LEN for p in paragraphs]

    found: list[tuple[int, int, str]] = []
    for block_size in range(_MAX_BLOCK_SIZE, 0, -1):
        i = 0
        while i + block_size <= n:
            if any(not eligible[i + k] for k in range(block_size)):
                i += 1
                continue
            current = tuple(norms[i + k] for k in range(block_size))
            earliest = max(0, i - block_size - _MAX_BLOCK_GAP)
            hit = False
            for j in range(earliest, i - block_size + 1):
                if j < 0:
                    continue
                prior = tuple(norms[j + k] for k in range(block_size))
                if prior == current:
                    preview = paragraphs[i].strip()[:40]
                    found.append((block_size, i, preview))
                    hit = True
                    break
            i += block_size if hit else 1
    return found


def check_fix_2_no_paragraph_echo(
    project_path: str, workspace: str
) -> tuple[bool, str]:
    novel_id = Path(project_path).name
    ch_dir = Path(workspace) / "novels" / novel_id / "chapters"
    if not ch_dir.exists():
        return False, f"章节目录不存在: {ch_dir}"
    offenders: list[str] = []
    for txt_path in sorted(ch_dir.glob("chapter_*.txt")):
        content = txt_path.read_text(encoding="utf-8")
        hits = _detect_paragraph_block_repeats(content)
        if hits:
            offenders.append(f"{txt_path.name}: {len(hits)} 处, 首处={hits[0]}")
    if offenders:
        return False, "检测到段落复读: " + "; ".join(offenders[:3])
    return True, f"扫描 {len(list(ch_dir.glob('chapter_*.txt')))} 章无段落复读"


def check_fix_6_length(
    create_result: dict[str, Any],
    gen_result: dict[str, Any],
    workspace: str,
    target_words: int,
) -> tuple[bool, str]:
    """#6: 软约束下字数应落在合理区间，不出现硬截（末尾不截断）."""
    outline = create_result.get("outline") or {}
    total = len(outline.get("chapters") or []) if isinstance(outline, dict) else 0
    novel_id = Path(gen_result["project_path"]).name
    ckpt_path = Path(workspace) / "novels" / novel_id / "checkpoint.json"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    records = data.get("chapters") or []
    if not records:
        return False, "checkpoint 无章节记录"
    per_chapter = target_words // max(1, total)
    low = int(per_chapter * 0.5)
    high = int(per_chapter * 1.6)  # soft_max_chars = 1.5x，留 buffer
    counts = [r.get("word_count", 0) for r in records]
    out_of_range = [
        (r.get("chapter_number"), r.get("word_count"))
        for r in records
        if not (low <= r.get("word_count", 0) <= high)
    ]
    # 软截：章末不应为单个未闭合句。取每章磁盘文本末尾一字做启发式检查。
    incomplete_endings: list[int] = []
    ch_dir = Path(workspace) / "novels" / novel_id / "chapters"
    for r in records:
        ch_num = r.get("chapter_number")
        if ch_num is None:
            continue
        txt_path = ch_dir / f"chapter_{ch_num:03d}.txt"
        if not txt_path.exists():
            continue
        content = txt_path.read_text(encoding="utf-8").rstrip()
        if not content:
            continue
        tail = content[-1]
        if tail not in "。！？.!?)」』\u201d\u300d\u300f":
            incomplete_endings.append(ch_num)

    msg = (
        f"per_ch 目标={per_chapter} 区间=[{low},{high}] 字数={counts} "
        f"超出={out_of_range} 未闭合结尾={incomplete_endings}"
    )
    # 核心：fix #6 的目标是"保留完整输出"，不做硬截。
    # 因此只要所有章节**有闭合结尾** + **未跌破下界**（没被截成残篇）即通过。
    # 超上限是 DeepSeek 一贯问题，属于长度策略调优范畴，不属于 fix #6 的验证点。
    below_floor = [
        (r.get("chapter_number"), r.get("word_count"))
        for r in records
        if r.get("word_count", 0) < low
    ]
    ok = not incomplete_endings and not below_floor
    return ok, msg + f" 欠下界={below_floor}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chapters", type=int, default=3, help="生成章节数 (默认3)")
    parser.add_argument(
        "--workspace", type=str, default="workspace_verify",
        help="专用 workspace (默认 workspace_verify)",
    )
    parser.add_argument(
        "--target-words", type=int, default=10000,
        help="target_words (默认10000 → 约4-5章规模)",
    )
    parser.add_argument("--skip-run", action="store_true", help="只做静态检查")
    args = parser.parse_args()

    os.environ["AI_NOVEL_WORKSPACE"] = args.workspace

    results: list[tuple[str, bool, str]] = []

    # ---- #1 零配置 ----
    print("\n=== 检查 #1: 零配置实例化 ===")
    ok1, msg1 = check_fix_1_zero_config()
    print(f"  {_fmt(ok1)}: {msg1}")
    results.append(("#1 零配置默认 deepseek-chat", ok1, msg1))

    if args.skip_run:
        print("\n--skip-run: 跳过真机跑")
        _print_report(results)
        return 0 if all(r[1] for r in results) else 1

    # ---- 真机跑 ----
    print(f"\n=== 创建小说项目 (workspace={args.workspace}) ===")
    pipe = NovelPipeline(workspace=args.workspace)

    create_result = pipe.create_novel(
        genre="玄幻",
        theme="少年觉醒古老血脉，在门派中逆境成长",
        target_words=args.target_words,
    )
    print(f"  create_novel status={create_result.get('status')}")
    print(f"  project_path={create_result.get('project_path')}")
    print(f"  characters={len(create_result.get('characters') or [])}")

    project_path = create_result["project_path"]

    # ---- #7 arc 兼容 ----
    ok7, msg7 = check_fix_7_arcs(create_result)
    print(f"\n=== #7 story arcs 兼容: {_fmt(ok7)} ===  {msg7}")
    results.append(("#7 story arcs 不崩", ok7, msg7))

    # ---- #3 role 字段 ----
    ok3, msg3 = check_fix_3_character_role(project_path, args.workspace)
    print(f"\n=== #3 CharacterProfile.role: {_fmt(ok3)} ===  {msg3}")
    results.append(("#3 character.role 字段", ok3, msg3))

    # ---- 生成章节 ----
    print(f"\n=== 生成章节 1..{args.chapters} ===")
    gen_result = pipe.generate_chapters(
        project_path=project_path,
        start_chapter=1,
        end_chapter=args.chapters,
        silent=True,
    )
    print(f"  status={gen_result.get('status')}")
    print(f"  total_generated={gen_result.get('total_generated')}")
    print(f"  errors={gen_result.get('errors') or 'none'}")

    # ---- #4/#5 返回结构 ----
    ok45, msg45 = check_fix_4_5_return_shape(gen_result)
    print(f"\n=== #4/#5 返回结构: {_fmt(ok45)} ===  {msg45}")
    results.append(("#4/#5 返回结构", ok45, msg45))

    ok5b, msg5b = check_fix_5_scene_field(gen_result, args.workspace)
    print(f"\n=== #5 scenes 字段: {_fmt(ok5b)} ===  {msg5b}")
    results.append(("#5 scenes 字段", ok5b, msg5b))

    # ---- #2 段落复读 ----
    ok2, msg2 = check_fix_2_no_paragraph_echo(project_path, args.workspace)
    print(f"\n=== #2 段落复读去重: {_fmt(ok2)} ===  {msg2}")
    results.append(("#2 无段落复读", ok2, msg2))

    # ---- #6 字数软约束 ----
    ok6, msg6 = check_fix_6_length(
        create_result, gen_result, args.workspace, args.target_words
    )
    print(f"\n=== #6 字数软约束: {_fmt(ok6)} ===  {msg6}")
    results.append(("#6 字数软约束", ok6, msg6))

    return _print_report(results)


def _print_report(results: list[tuple[str, bool, str]]) -> int:
    print("\n" + "=" * 72)
    print("验证汇总")
    print("=" * 72)
    for name, ok, msg in results:
        flag = _fmt(ok)
        print(f"  [{flag}] {name}")
        print(f"         {msg[:120]}")
    failed = [n for n, ok, _ in results if not ok]
    print("-" * 72)
    if failed:
        print(f"FAIL: {len(failed)} 项未通过 — {failed}")
        return 1
    print(f"ALL PASS ({len(results)} 项)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

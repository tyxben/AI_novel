"""accept vol2 outline proposal + 善后（阶段 1 收尾）.

善后 3 件事：
1. `vol2.chapters` / `vol2.volume_outline` 恢复到 `[26..60]`（proposal 只含 28-32）
2. `vol2.volume_goal` 回到原值（空字符串；canonical vision 走 theme 字段，不被 LLM 窄目标盖掉）
3. 删临时备份字段 `vol2._chapters_full`
ch28-32 的 chapter_outlines 作为新条目 merge 进 outline.chapters 替换 placeholder，
这一步保留不动。
"""

from __future__ import annotations
import json
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

from src.novel.services.tool_facade import NovelToolFacade

NOVEL_ID = "novel_12e1c974"
WORKSPACE = "workspace"
PROJECT = str(Path(WORKSPACE) / "novels" / NOVEL_ID)
PROPOSAL_PATH = Path("workspace/quality_reports/audit/novel_12e1c974_vol2_proposal.json")

with open(PROPOSAL_PATH) as f:
    proposal = json.load(f)

proposal_id = proposal["proposal_id"]
data = proposal["data"]
print(f"[1/3] accept vol2 outline proposal_id={proposal_id}")
print(f"      ch outlines: {[c['chapter_number'] for c in data['chapter_outlines']]}")

facade = NovelToolFacade(workspace=WORKSPACE)
result = facade.accept_proposal(
    project_path=PROJECT,
    proposal_type="volume_outline",
    data=data,
    proposal_id=proposal_id,
)
print(f"      status={result.status} path={result.project_path}")

# --- post-accept cleanup ---
print(f"\n[2/3] 善后 vol2.chapters / volume_outline / volume_goal / _chapters_full")
novel_path = Path(PROJECT) / "novel.json"
nd = json.load(open(novel_path))
vols = nd["outline"]["volumes"]
vol2 = next(v for v in vols if v.get("volume_number") == 2)

before = {
    "chapters_len": len(vol2.get("chapters") or []),
    "volume_outline": vol2.get("volume_outline"),
    "volume_goal": (vol2.get("volume_goal") or "")[:60],
    "_chapters_full_present": "_chapters_full" in vol2,
}
print(f"      before: {before}")

chapters_full = vol2.get("_chapters_full") or list(range(26, 61))
vol2["chapters"] = list(chapters_full)
vol2["volume_outline"] = list(chapters_full)
# canonical vision 在 theme 字段；清空 LLM 产出的窄目标
vol2["volume_goal"] = ""
vol2.pop("_chapters_full", None)

after = {
    "chapters_len": len(vol2["chapters"]),
    "volume_outline_len": len(vol2["volume_outline"]),
    "volume_goal": vol2["volume_goal"],
    "_chapters_full_present": "_chapters_full" in vol2,
}
print(f"      after : {after}")

# sanity check ch28-32 merged as real entries (not placeholders)
chs = nd["outline"]["chapters"]
for n in (28, 29, 30, 31, 32):
    ch = next((c for c in chs if c.get("chapter_number") == n), None)
    if not ch:
        print(f"      !! ch{n} 缺失于 outline.chapters")
        continue
    goal = (ch.get("goal") or "")[:40]
    is_placeholder = goal == "待规划" or not goal
    status = "OK" if not is_placeholder else "PLACEHOLDER"
    print(f"      ch{n}: [{status}] title={ch.get('title','')[:20]} goal={goal}")

json.dump(nd, open(novel_path, "w"), ensure_ascii=False, indent=2)
print(f"\n[3/3] novel.json saved -> {novel_path}")
print("=== ACCEPT+CLEANUP DONE ===")

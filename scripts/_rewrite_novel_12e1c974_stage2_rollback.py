"""阶段 2: 回滚 ch19 + ch28-32 的 state.

操作清单（仅在 user 确认 vol2 outline 后执行）:
1. chapters/chapter_{019,028,029,030,031,032}.{json,txt} → 移除（已备份）
2. checkpoint.json:
   - current_chapter 32 → 17（让 pipeline 从最后未受影响的章节重新开始；
     ch20-27 仍存在，pipeline.generate_chapters(start=N) 不会重生 N 之前的章节）
   - chapters[] 列表移除 ch_number ∈ {19, 28, 29, 30, 31, 32} 的条目
   - chapters_text 字典 pop 同样的 ch_number key
3. novel.json: outline.chapters[N].actual_summary 清空 for N ∈ {19, 28, 29, 30, 31, 32}
4. memory.db: 清 chapter_summaries / character_states / facts where chapter_number IN (19, 28..32)
5. graph.json (KG): 清 ≥ ch28 标记的伏笔节点；ch19 节点也清
6. vectors/: 清 ch19 + ch28-32 的 embedding（VectorStore.delete by metadata）
7. changelog 写一条
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

from src.novel.storage.file_manager import FileManager
from src.novel.storage.novel_memory import NovelMemory
from src.novel.services.changelog_manager import ChangeLogManager

NOVEL_ID = "novel_12e1c974"
WORKSPACE = "workspace"
TARGETS = [19, 28, 29, 30, 31, 32]
PROJECT = Path(WORKSPACE) / "novels" / NOVEL_ID

# --- 1. 删除 chapter 文件 ---
removed_files: list[str] = []
for n in TARGETS:
    for ext in (".json", ".txt"):
        path = PROJECT / "chapters" / f"chapter_{n:03d}{ext}"
        if path.exists():
            path.unlink()
            removed_files.append(str(path))
            print(f"  removed {path}")

# --- 2. checkpoint.json 修正 ---
ckpt_path = PROJECT / "checkpoint.json"
ckpt = json.load(open(ckpt_path))
ckpt_changes: dict = {}

orig_current = ckpt.get("current_chapter")
ckpt["current_chapter"] = 18  # 已写到的最后一个不动的章节（ch18 OK）
ckpt_changes["current_chapter"] = (orig_current, 18)

# Drop entries from chapters list
orig_count = len(ckpt.get("chapters", []))
ckpt["chapters"] = [
    c for c in ckpt.get("chapters", [])
    if c.get("chapter_number") not in TARGETS
]
ckpt_changes["chapters_len"] = (orig_count, len(ckpt["chapters"]))

# Drop chapters_text entries
chs_text = ckpt.get("chapters_text", {}) or {}
orig_keys = set()
for k in list(chs_text.keys()):
    try:
        kn = int(k)
    except (TypeError, ValueError):
        continue
    if kn in TARGETS:
        orig_keys.add(kn)
        chs_text.pop(k, None)
ckpt["chapters_text"] = chs_text
ckpt_changes["chapters_text_dropped"] = sorted(orig_keys)

# Clear current_chapter_text/quality so pipeline doesn't think there's a draft
for k in ("current_chapter_text", "current_chapter_quality", "current_scenes",
          "current_chapter_outline", "current_chapter_brief"):
    if ckpt.get(k):
        ckpt[k] = None

json.dump(ckpt, open(ckpt_path, "w"), ensure_ascii=False, indent=2)
print(f"\ncheckpoint.json updated: {ckpt_changes}")

# --- 3. novel.json: 清 actual_summary ---
novel_path = PROJECT / "novel.json"
novel_data = json.load(open(novel_path))
cleared: list[int] = []
for ch in novel_data.get("outline", {}).get("chapters", []):
    if ch.get("chapter_number") in TARGETS and ch.get("actual_summary"):
        ch["actual_summary"] = ""
        cleared.append(ch["chapter_number"])
json.dump(novel_data, open(novel_path, "w"), ensure_ascii=False, indent=2)
print(f"novel.json: cleared actual_summary for {cleared}")

# --- 4. memory.db ---
mem = NovelMemory(novel_id=NOVEL_ID, workspace_dir=WORKSPACE)
db = mem.structured_db

# Identify tables with chapter_number columns
con = db._conn
tables = [r[0] for r in con.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
).fetchall()]
db_changes: dict[str, int] = {}
placeholder = ",".join("?" * len(TARGETS))
for t in tables:
    cols = [c[1] for c in con.execute(f"PRAGMA table_info({t})").fetchall()]
    if "chapter_number" in cols:
        n = con.execute(
            f"SELECT COUNT(*) FROM {t} WHERE chapter_number IN ({placeholder})",
            TARGETS,
        ).fetchone()[0]
        if n:
            con.execute(
                f"DELETE FROM {t} WHERE chapter_number IN ({placeholder})",
                TARGETS,
            )
            db_changes[t] = n
con.commit()
print(f"memory.db: deleted rows from {db_changes}")

# --- 5. KnowledgeGraph (graph.json): drop foreshadowing nodes planted in TARGETS ---
kg = mem.knowledge_graph
g = kg.graph
nodes_to_remove: list[str] = []
for nid, attrs in g.nodes(data=True):
    pc = attrs.get("planted_chapter")
    if pc is not None and int(pc) in TARGETS:
        nodes_to_remove.append(nid)
    # also drop any node whose primary chapter matches
    elif attrs.get("chapter_number") is not None and int(attrs["chapter_number"]) in TARGETS:
        nodes_to_remove.append(nid)
for nid in nodes_to_remove:
    g.remove_node(nid)
mem.save()
print(f"graph.json: removed {len(nodes_to_remove)} nodes")

# --- 6. VectorStore (Chroma): drop embeddings tagged with TARGETS ---
vs = mem.vector_store
removed_vecs = 0
try:
    coll = vs._get_or_create(NOVEL_ID)
    for n in TARGETS:
        # 用 metadata 过滤删除
        try:
            res = coll.get(where={"chapter_number": n}, limit=10000)
            ids = res.get("ids") or []
            if ids:
                coll.delete(ids=ids)
                removed_vecs += len(ids)
        except Exception as exc:
            print(f"  vector delete ch{n} failed: {exc}")
except Exception as exc:
    print(f"  vector store access failed: {exc}")
print(f"vectors/: removed {removed_vecs} embeddings")

# --- 7. changelog ---
mgr = ChangeLogManager(workspace=WORKSPACE)
entry = mgr.record(
    novel_id=NOVEL_ID,
    change_type="rollback",
    entity_type="chapter_text",
    description=(
        f"阶段 2 state 回滚: 删除 ch{TARGETS} 文件 + 清 checkpoint/novel.json/"
        f"memory.db/graph.json/vectors。备份在 chapters/_backup_20260422_211139/。"
        f"准备阶段 3 通过 pipeline.generate_chapters 重生。"
    ),
    old_value={"current_chapter": orig_current, "removed_chapters": TARGETS},
    new_value={
        "current_chapter": 18,
        "db_rows_deleted": db_changes,
        "kg_nodes_removed": len(nodes_to_remove),
        "vectors_removed": removed_vecs,
    },
    author="ai",
    effective_from_chapter=19,
)
print(f"\nchangelog: {entry.change_id}")
mem.close()
print("\n=== ROLLBACK COMPLETE ===")

"""阶段 2b 补漏：stage2 原脚本用了错的列名 + 错的 VectorStore API

- memory.db 实际列名是 `chapter`（不是 chapter_number）；debts 表是 `source_chapter`
- VectorStore 接口是 create_collection(novel_id) → 访问 _collection
- 实体（entities）不删，只删 entity_mentions（映射 chapter）
"""

from __future__ import annotations
import os
import sqlite3
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

from src.novel.storage.vector_store import VectorStore
from src.novel.services.changelog_manager import ChangeLogManager

NOVEL_ID = "novel_12e1c974"
WORKSPACE = "workspace"
PROJECT = Path(WORKSPACE) / "novels" / NOVEL_ID
TARGETS = [19, 28, 29, 30, 31, 32]
placeholder = ",".join("?" * len(TARGETS))

# --- memory.db ---
db_changes: dict[str, int] = {}
db_path = PROJECT / "memory.db"
con = sqlite3.connect(db_path)
con.execute("PRAGMA foreign_keys = ON")

# (table, column) 对
chapter_tables = [
    ("character_states", "chapter"),
    ("facts", "chapter"),
    ("chapter_summaries", "chapter"),
    ("timeline", "chapter"),
    ("power_tracking", "chapter"),
    ("entity_mentions", "chapter"),
    ("chapter_debts", "source_chapter"),
    ("narrative_debts", "source_chapter"),
]
for table, col in chapter_tables:
    try:
        n = con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {col} IN ({placeholder})",
            TARGETS,
        ).fetchone()[0]
    except sqlite3.OperationalError as exc:
        print(f"  {table}: {exc}")
        continue
    if n:
        con.execute(
            f"DELETE FROM {table} WHERE {col} IN ({placeholder})",
            TARGETS,
        )
        db_changes[table] = n

con.commit()
con.close()
print(f"memory.db: deleted rows = {db_changes}")

# --- vectors/ ---
# 真实路径是 workspace/novels/<novel_id>/vectors/
vec_dir = PROJECT / "vectors"
removed_vecs = 0
if vec_dir.exists():
    vs = VectorStore(persist_directory=str(vec_dir))
    try:
        vs.create_collection(NOVEL_ID)
        coll = vs._collection
        # Chroma 支持 $in 操作符
        for n in TARGETS:
            res = coll.get(where={"chapter": n}, limit=10000)
            ids = res.get("ids") or []
            if ids:
                coll.delete(ids=ids)
                removed_vecs += len(ids)
                print(f"  ch{n}: removed {len(ids)} vectors")
    except Exception as exc:
        print(f"  vector cleanup failed: {exc}")
print(f"vectors/: removed {removed_vecs} total")

# --- changelog ---
mgr = ChangeLogManager(workspace=WORKSPACE)
entry = mgr.record(
    novel_id=NOVEL_ID,
    change_type="rollback",
    entity_type="memory_state",
    description=(
        f"阶段 2b 补漏清理: 用正确列名/API 清 memory.db + vectors。"
        f"原 stage2 脚本用了 chapter_number + _get_or_create 错误接口"
    ),
    old_value={"targets": TARGETS},
    new_value={
        "db_rows_deleted": db_changes,
        "vectors_removed": removed_vecs,
    },
    author="ai",
    effective_from_chapter=19,
)
print(f"\nchangelog: {entry.change_id}")
print("=== STAGE 2b FIXUP DONE ===")

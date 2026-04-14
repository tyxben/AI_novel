"""小说导入服务 - 导入已有稿件为小说项目

支持：
- 自动章节分割（检测 "第X章" / "Chapter X" 等标题）
- LLM 提取角色信息
- LLM 提取世界观信息
- 创建完整小说项目目录结构
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

log = logging.getLogger("novel")

# ---------------------------------------------------------------------------
# Chapter splitting patterns
# ---------------------------------------------------------------------------

# Chinese chapter titles: 第X章, 第X节, 第X回
_CHINESE_CHAPTER_RE = re.compile(
    r"^\s*(第\s*[零一二三四五六七八九十百千万\d]+\s*[章节回卷][^\n]{0,30})\s*$",
    re.MULTILINE,
)

# English chapter titles: Chapter 1, CHAPTER ONE, Chapter I
_ENGLISH_CHAPTER_RE = re.compile(
    r"^\s*(Chapter\s+\w+[^\n]{0,50})\s*$",
    re.MULTILINE | re.IGNORECASE,
)

# Numeric chapter titles: 1. Title, 1、Title
_NUMERIC_CHAPTER_RE = re.compile(
    r"^\s*(\d+\s*[.、]\s*\S[^\n]{0,50})\s*$",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# JSON extraction helpers — canonical implementation in
# ``src.novel.utils.json_extract``. Backward-compat aliases kept so existing
# tests that import these private names keep working.
# ---------------------------------------------------------------------------


from src.novel.utils.json_extract import (
    extract_json_array as _shared_extract_json_array,
    extract_json_obj as _shared_extract_json_obj,
)


def _extract_json_obj(text: str | None) -> dict | None:
    """Deprecated: delegates to :func:`src.novel.utils.json_extract.extract_json_obj`."""
    return _shared_extract_json_obj(text)


def _extract_json_array(text: str | None) -> list | None:
    """Deprecated: delegates to :func:`src.novel.utils.json_extract.extract_json_array`.

    Preserves the historical behaviour of unwrapping only ``{"characters": [...]}``
    so existing callers observe identical results.
    """
    return _shared_extract_json_array(text, unwrap_keys=("characters",))


# ---------------------------------------------------------------------------
# ImportService
# ---------------------------------------------------------------------------


class ImportService:
    """导入已有小说稿件，创建小说项目。"""

    MAX_RETRIES = 2

    def __init__(self, llm_client: Any) -> None:
        """
        Args:
            llm_client: LLMClient instance with ``chat(messages, ...)`` method.
        """
        self.llm = llm_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def import_existing_draft(
        self,
        file_path: str,
        genre: str = "通用",
        auto_split: bool = True,
        workspace: str = "workspace",
    ) -> dict[str, Any]:
        """Import an existing novel draft and create a project.

        Args:
            file_path: Path to the text file to import.
            genre: Genre label (e.g. "玄幻", "都市").
            auto_split: Whether to auto-detect and split chapters.
            workspace: Workspace root directory.

        Returns:
            Dict with keys: novel_id, workspace, chapters, characters,
            world_setting, total_chapters, total_words.

        Raises:
            FileNotFoundError: If file_path does not exist.
            ValueError: If the file is empty.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        text = path.read_text(encoding="utf-8")
        if not text.strip():
            raise ValueError("文件内容为空")

        # 1. Split into chapters
        if auto_split:
            chapters = self.split_chapters(text)
        else:
            chapters = [{"chapter_number": 1, "title": "全文", "text": text}]

        # 2. Extract characters via LLM
        # Use a summary of the text (first ~2000 chars + last ~1000 chars)
        summary = self._make_summary_for_extraction(text)
        characters = self.extract_characters(summary, genre)

        # 3. Extract world setting via LLM
        world_setting = self.extract_world_setting(summary, genre)

        # 4. Create project structure
        novel_id = f"novel_{uuid.uuid4().hex[:8]}"
        project = self._create_project(
            novel_id=novel_id,
            genre=genre,
            chapters=chapters,
            characters=characters,
            world_setting=world_setting,
            workspace=workspace,
            source_file=str(path.name),
        )

        return project

    # ------------------------------------------------------------------
    # Chapter splitting
    # ------------------------------------------------------------------

    def split_chapters(self, text: str) -> list[dict[str, Any]]:
        """Split text into chapters by detecting title patterns.

        Returns:
            List of dicts with keys: chapter_number, title, text.
            If no chapter titles are detected, returns the entire text
            as a single chapter.
        """
        # Try each pattern in priority order
        for pattern in [_CHINESE_CHAPTER_RE, _ENGLISH_CHAPTER_RE, _NUMERIC_CHAPTER_RE]:
            matches = list(pattern.finditer(text))
            if len(matches) >= 2:
                return self._split_by_matches(text, matches)

        # No chapter pattern found: treat entire text as one chapter
        return [{"chapter_number": 1, "title": "第1章", "text": text.strip()}]

    def _split_by_matches(
        self, text: str, matches: list[re.Match]
    ) -> list[dict[str, Any]]:
        """Split text using regex match positions."""
        chapters: list[dict[str, Any]] = []

        for i, match in enumerate(matches):
            title = match.group(1).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            chapter_text = text[start:end].strip()

            chapters.append({
                "chapter_number": i + 1,
                "title": title,
                "text": chapter_text,
            })

        return chapters

    # ------------------------------------------------------------------
    # LLM extraction
    # ------------------------------------------------------------------

    def extract_characters(
        self, text_summary: str, genre: str
    ) -> list[dict[str, Any]]:
        """Use LLM to extract character information from text.

        Returns:
            List of character dicts with keys: name, role, description, personality.
        """
        prompt = f"""请从以下小说文本中提取所有主要角色信息。

题材：{genre}
文本摘要：
{text_summary}

请严格按以下 JSON 格式返回：
{{
  "characters": [
    {{
      "name": "角色姓名",
      "role": "主角/反派/配角",
      "description": "角色简要描述（外貌、身份、背景）",
      "personality": "性格特点（2-3个关键词）"
    }}
  ]
}}

要求：
1. 只提取有名字的角色
2. 每个角色的 name 必须是具体人名
3. description 和 personality 基于文本实际内容
4. 至少提取 1 个角色，最多 10 个
"""
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.llm.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": "你是小说角色分析专家。请严格按 JSON 格式返回。",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    json_mode=True,
                )
                result = _shared_extract_json_array(
                    response.content, unwrap_keys=("characters",)
                )
                if result is None:
                    obj = _shared_extract_json_obj(response.content)
                    if obj and "characters" in obj:
                        result = obj["characters"]
                if result and isinstance(result, list) and len(result) > 0:
                    return result
            except Exception as e:
                log.warning("角色提取失败 (attempt %d): %s", attempt + 1, e)

        log.warning("角色提取全部失败，返回空列表")
        return []

    def extract_world_setting(
        self, text_summary: str, genre: str
    ) -> dict[str, Any]:
        """Use LLM to extract world setting from text.

        Returns:
            Dict with keys: era, location, rules, terms.
        """
        prompt = f"""请从以下小说文本中提取世界观设定信息。

题材：{genre}
文本摘要：
{text_summary}

请严格按以下 JSON 格式返回：
{{
  "era": "时代背景（古代/现代/未来/架空）",
  "location": "地域背景描述",
  "rules": ["世界规则1", "世界规则2"],
  "terms": {{"专有名词": "解释"}}
}}

要求：
1. era 从以下选择：古代、现代、未来、架空
2. location 简洁描述（20字以内）
3. rules 列出最关键的 1-5 条世界规则
4. terms 提取文中出现的专有名词及解释
"""
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.llm.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": "你是小说世界观分析专家。请严格按 JSON 格式返回。",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    json_mode=True,
                )
                result = _shared_extract_json_obj(response.content)
                if result and "era" in result:
                    return result
            except Exception as e:
                log.warning("世界观提取失败 (attempt %d): %s", attempt + 1, e)

        log.warning("世界观提取全部失败，返回默认值")
        return {
            "era": "架空",
            "location": "未知",
            "rules": [],
            "terms": {},
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_summary_for_extraction(self, text: str) -> str:
        """Create a truncated summary for LLM extraction.

        Takes the first ~2000 chars and last ~1000 chars to capture
        beginning context and ending context.
        """
        if len(text) <= 3000:
            return text
        head = text[:2000]
        tail = text[-1000:]
        return f"{head}\n\n[...中间省略...]\n\n{tail}"

    def _create_project(
        self,
        novel_id: str,
        genre: str,
        chapters: list[dict[str, Any]],
        characters: list[dict[str, Any]],
        world_setting: dict[str, Any],
        workspace: str,
        source_file: str,
    ) -> dict[str, Any]:
        """Create project directory structure and save all data."""
        from src.novel.storage.file_manager import FileManager

        fm = FileManager(workspace)

        # Calculate total words
        total_words = sum(len(ch.get("text", "")) for ch in chapters)

        # Build outline from imported chapters
        chapter_outlines = []
        for ch in chapters:
            chapter_outlines.append({
                "chapter_number": ch["chapter_number"],
                "title": ch["title"],
                "goal": f"导入章节 - {ch['title']}",
                "key_events": ["导入内容"],
                "estimated_words": len(ch.get("text", "")),
                "mood": "过渡",
            })

        outline = {
            "template": "custom",
            "acts": [{
                "name": "导入内容",
                "description": "从已有稿件导入",
                "start_chapter": 1,
                "end_chapter": len(chapters),
            }],
            "volumes": [{
                "volume_number": 1,
                "title": "导入卷",
                "core_conflict": "待分析",
                "resolution": "待分析",
                "chapters": [ch["chapter_number"] for ch in chapters],
            }],
            "chapters": chapter_outlines,
        }

        # Build novel data
        novel_data = {
            "novel_id": novel_id,
            "title": f"{genre} - 导入自 {source_file}",
            "genre": genre,
            "theme": "导入稿件",
            "target_words": max(total_words, 10000),
            "status": "writing",
            "current_chapter": len(chapters),
            "outline": outline,
            "characters": characters,
            "world_setting": world_setting,
            "style_name": "webnovel.shuangwen",
            "imported_from": source_file,
        }

        # Save novel.json
        fm.save_novel(novel_id, novel_data)

        # Save each chapter
        for ch in chapters:
            chapter_data = {
                "chapter_number": ch["chapter_number"],
                "title": ch["title"],
                "full_text": ch["text"],
                "word_count": len(ch.get("text", "")),
                "status": "imported",
            }
            fm.save_chapter(novel_id, ch["chapter_number"], chapter_data)

        project_path = str(Path(workspace) / "novels" / novel_id)
        log.info("导入完成: %s (%d 章, %d 字)", project_path, len(chapters), total_words)

        return {
            "novel_id": novel_id,
            "workspace": project_path,
            "chapters": chapters,
            "characters": characters,
            "world_setting": world_setting,
            "total_chapters": len(chapters),
            "total_words": total_words,
        }

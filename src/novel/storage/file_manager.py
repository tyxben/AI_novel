"""文件系统管理 - 小说项目的 JSON 持久化和纯文本导出"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


class FileManager:
    """管理 workspace/novels/{novel_id}/ 目录

    职责：
    - 保存/加载 Novel 对象的 JSON 序列化
    - 保存/加载 Chapter 的 JSON 和纯文本
    - 导出完整小说为纯文本 TXT
    - 查询项目状态
    """

    def __init__(self, workspace_dir: str) -> None:
        self.workspace_root = Path(workspace_dir) / "novels"
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def _novel_dir(self, novel_id: str) -> Path:
        """获取小说项目目录"""
        d = self.workspace_root / novel_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _chapters_dir(self, novel_id: str) -> Path:
        """获取章节目录"""
        d = self._novel_dir(novel_id) / "chapters"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ========== Novel 操作 ==========

    def save_novel(self, novel_id: str, novel_data: dict[str, Any]) -> Path:
        """保存 Novel 对象为 JSON

        Args:
            novel_id: 小说 ID
            novel_data: Novel.model_dump() 的结果

        Returns:
            保存的文件路径
        """
        path = self._novel_dir(novel_id) / "novel.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(novel_data, f, ensure_ascii=False, indent=2)
        return path

    def load_novel(self, novel_id: str) -> dict[str, Any] | None:
        """加载 Novel JSON

        Returns:
            Novel dict 或 None（文件不存在时）
        """
        path = self._novel_dir(novel_id) / "novel.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    # ========== Chapter 操作 ==========

    def save_chapter(
        self, novel_id: str, chapter_number: int, chapter_data: dict[str, Any]
    ) -> Path:
        """保存单章 metadata JSON + 纯文本 .txt

        JSON 只存元数据（chapter_number, title, word_count, status 等），
        不存 full_text。章节正文保存到同名 .txt 文件。

        Args:
            novel_id: 小说 ID
            chapter_number: 章节号
            chapter_data: Chapter dict，可包含 full_text（会被提取出来）

        Returns:
            JSON 文件路径
        """
        # Extract full_text — don't store it in json
        full_text = chapter_data.get("full_text")
        # Build metadata-only dict (exclude full_text)
        data_to_save = {k: v for k, v in chapter_data.items() if k != "full_text"}

        if full_text is not None:
            # Update word_count from actual text
            data_to_save["word_count"] = len(full_text)
            # Save text to .txt file
            self.save_chapter_text(novel_id, chapter_number, full_text)

        path = self._chapters_dir(novel_id) / f"chapter_{chapter_number:03d}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)
        return path

    def load_chapter(
        self, novel_id: str, chapter_number: int
    ) -> dict[str, Any] | None:
        """加载单章 metadata + 正文

        JSON 提供元数据，.txt 提供正文（full_text）。
        .txt 是正文的 single source of truth；即使旧 JSON 中
        残留 full_text 字段，也会被 .txt 内容覆盖。
        """
        path = self._chapters_dir(novel_id) / f"chapter_{chapter_number:03d}.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # Always load text from .txt (single source of truth)
        txt_path = path.with_suffix(".txt")
        if txt_path.exists():
            data["full_text"] = txt_path.read_text(encoding="utf-8")
        return data

    def save_chapter_text(
        self, novel_id: str, chapter_number: int, text: str
    ) -> Path:
        """保存章节纯文本，并同步 JSON 的 word_count（不写入 full_text）"""
        path = self._chapters_dir(novel_id) / f"chapter_{chapter_number:03d}.txt"
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        # Sync word_count in JSON (but NOT full_text)
        json_path = path.with_suffix(".json")
        if json_path.exists():
            try:
                with open(json_path, encoding="utf-8") as jf:
                    data = json.load(jf)
                data["word_count"] = len(text)
                # Remove full_text if it exists in old json files
                data.pop("full_text", None)
                with open(json_path, "w", encoding="utf-8") as jf:
                    json.dump(data, jf, ensure_ascii=False, indent=2)
            except Exception as e:
                import logging
                logging.getLogger("novel").warning(
                    "Failed to sync JSON for chapter %d: %s", chapter_number, e
                )
        return path

    def load_chapter_text(
        self, novel_id: str, chapter_number: int
    ) -> str | None:
        """加载章节纯文本"""
        path = self._chapters_dir(novel_id) / f"chapter_{chapter_number:03d}.txt"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return f.read()

    def list_chapters(self, novel_id: str) -> list[int]:
        """列出已保存的章节号"""
        chapters_dir = self._chapters_dir(novel_id)
        chapter_numbers = []
        for p in sorted(chapters_dir.glob("chapter_*.json")):
            try:
                num = int(p.stem.split("_")[1])
                chapter_numbers.append(num)
            except (ValueError, IndexError):
                continue
        return chapter_numbers

    # ========== 章节版本管理 ==========

    def _revisions_dir(self, novel_id: str) -> Path:
        """获取章节修订版本目录"""
        d = self._novel_dir(novel_id) / "revisions"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_chapter_revision(
        self,
        novel_id: str,
        chapter_number: int,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """保存章节修订版本

        自动递增版本号，保存到 revisions/chapter_NNN_revN.txt。

        Args:
            novel_id: 小说 ID
            chapter_number: 章节号
            text: 章节文本
            metadata: 可选元数据（保存为同名 .json）

        Returns:
            保存的文件路径
        """
        revisions = self.list_chapter_revisions(novel_id, chapter_number)
        next_rev = max(revisions) + 1 if revisions else 1
        rev_dir = self._revisions_dir(novel_id)
        path = rev_dir / f"chapter_{chapter_number:03d}_rev{next_rev}.txt"
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        if metadata is not None:
            meta_path = rev_dir / f"chapter_{chapter_number:03d}_rev{next_rev}.json"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
        return path

    def list_chapter_revisions(
        self, novel_id: str, chapter_number: int
    ) -> list[int]:
        """列出章节的所有修订版本号

        Returns:
            排序后的版本号列表，如 [1, 2, 3]
        """
        rev_dir = self._revisions_dir(novel_id)
        prefix = f"chapter_{chapter_number:03d}_rev"
        revisions: list[int] = []
        for p in sorted(rev_dir.glob(f"{prefix}*.txt")):
            try:
                rev_str = p.stem.split("_rev")[1]
                revisions.append(int(rev_str))
            except (ValueError, IndexError):
                continue
        return sorted(revisions)

    def load_chapter_revision(
        self, novel_id: str, chapter_number: int, revision: int
    ) -> str | None:
        """加载指定版本的章节文本

        Returns:
            章节文本或 None（文件不存在时）
        """
        rev_dir = self._revisions_dir(novel_id)
        path = rev_dir / f"chapter_{chapter_number:03d}_rev{revision}.txt"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return f.read()

    # ========== 反馈管理 ==========

    def _feedback_dir(self, novel_id: str) -> Path:
        """获取反馈目录"""
        d = self._novel_dir(novel_id) / "feedback"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_feedback(
        self, novel_id: str, feedback_entry_dict: dict[str, Any]
    ) -> Path:
        """保存反馈条目

        Args:
            novel_id: 小说 ID
            feedback_entry_dict: FeedbackEntry.model_dump() 的结果

        Returns:
            保存的文件路径
        """
        fb_id = feedback_entry_dict.get("feedback_id", "unknown")
        fb_dir = self._feedback_dir(novel_id)
        path = fb_dir / f"feedback_{fb_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(feedback_entry_dict, f, ensure_ascii=False, indent=2)
        return path

    def list_feedback(self, novel_id: str) -> list[dict[str, Any]]:
        """列出所有反馈条目

        Returns:
            反馈 dict 列表
        """
        fb_dir = self._feedback_dir(novel_id)
        results: list[dict[str, Any]] = []
        for p in sorted(fb_dir.glob("feedback_*.json")):
            with open(p, encoding="utf-8") as f:
                results.append(json.load(f))
        return results

    # ========== 备份管理 ==========

    def save_backup(self, novel_id: str) -> Path:
        """备份当前 novel.json 到 revisions/ 目录

        复制 novel.json 到 revisions/novel_backup_{timestamp}.json，
        并自动清理旧备份（保留最近 20 个）。

        Args:
            novel_id: 小说 ID

        Returns:
            备份文件路径

        Raises:
            FileNotFoundError: novel.json 不存在时
        """
        novel_path = self._novel_dir(novel_id) / "novel.json"
        if not novel_path.exists():
            raise FileNotFoundError(f"novel.json 不存在: {novel_id}")

        rev_dir = self._novel_dir(novel_id) / "revisions"
        rev_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_path = rev_dir / f"novel_backup_{timestamp}.json"

        shutil.copy2(novel_path, backup_path)

        self._cleanup_old_backups(novel_id, keep=20)

        return backup_path

    def _cleanup_old_backups(self, novel_id: str, keep: int = 20) -> None:
        """删除旧备份，保留最近 N 个

        Args:
            novel_id: 小说 ID
            keep: 保留的备份数量
        """
        rev_dir = self._novel_dir(novel_id) / "revisions"
        if not rev_dir.exists():
            return

        backups = sorted(rev_dir.glob("novel_backup_*.json"))
        if len(backups) > keep:
            for old in backups[:-keep]:
                old.unlink()

    # ========== 变更日志管理 ==========

    def _changelogs_dir(self, novel_id: str) -> Path:
        """获取变更日志目录"""
        d = self._novel_dir(novel_id) / "changelogs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_change_log(self, novel_id: str, entry: dict[str, Any]) -> Path:
        """保存变更日志条目

        Args:
            novel_id: 小说 ID
            entry: 变更日志 dict，必须包含 change_id 字段

        Returns:
            保存的文件路径
        """
        change_id = entry.get("change_id", "unknown")
        if "/" in change_id or "\\" in change_id or change_id in (".", ".."):
            raise ValueError(f"非法 change_id: {change_id}")
        log_dir = self._changelogs_dir(novel_id)
        path = log_dir / f"{change_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=2)
        return path

    def list_change_logs(
        self, novel_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """列出变更日志（按修改时间倒序）

        Args:
            novel_id: 小说 ID
            limit: 返回的最大条数

        Returns:
            变更日志 dict 列表
        """
        log_dir = self._novel_dir(novel_id) / "changelogs"
        if not log_dir.exists():
            return []

        # 按文件修改时间倒序排列
        log_files = sorted(
            log_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        results: list[dict[str, Any]] = []
        for p in log_files[:limit]:
            with open(p, encoding="utf-8") as f:
                results.append(json.load(f))
        return results

    def load_change_log(
        self, novel_id: str, change_id: str
    ) -> dict[str, Any] | None:
        """加载指定变更日志

        Args:
            novel_id: 小说 ID
            change_id: 变更 ID

        Returns:
            变更日志 dict 或 None（不存在时）
        """
        if "/" in change_id or "\\" in change_id or change_id in (".", ".."):
            raise ValueError(f"非法 change_id: {change_id}")
        log_dir = self._novel_dir(novel_id) / "changelogs"
        path = log_dir / f"{change_id}.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    # ========== 叙事控制导出 ==========

    def export_debts_json(self, novel_id: str, debts: list[dict[str, Any]]) -> Path:
        """导出叙事债务为 JSON 文件

        Args:
            novel_id: 小说 ID
            debts: 债务 dict 列表

        Returns:
            导出的文件路径
        """
        path = self._novel_dir(novel_id) / "debts.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(debts, f, ensure_ascii=False, indent=2)
        return path

    def export_arcs_json(self, novel_id: str, arcs: list[dict[str, Any]]) -> Path:
        """导出故事弧线为 JSON 文件

        Args:
            novel_id: 小说 ID
            arcs: 弧线 dict 列表

        Returns:
            导出的文件路径
        """
        path = self._novel_dir(novel_id) / "arcs.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(arcs, f, ensure_ascii=False, indent=2)
        return path

    # ========== 导出 ==========

    def export_novel_txt(self, novel_id: str, output_path: str | None = None) -> Path:
        """导出完整小说为纯文本 TXT

        Args:
            novel_id: 小说 ID
            output_path: 输出路径，默认为项目目录下 {title}.txt

        Returns:
            导出的文件路径
        """
        novel_data = self.load_novel(novel_id)
        if novel_data is None:
            raise FileNotFoundError(f"小说项目不存在: {novel_id}")

        title = novel_data.get("title", novel_id)
        chapter_numbers = self.list_chapters(novel_id)

        lines: list[str] = [title, "=" * len(title) * 2, ""]

        for ch_num in chapter_numbers:
            ch_data = self.load_chapter(novel_id, ch_num)
            if ch_data is None:
                continue
            ch_title = ch_data.get("title", f"第{ch_num}章")
            # 避免标题已含"第X章"前缀时重复拼接
            import re as _re
            if _re.match(r"^第\d+章", ch_title):
                lines.append(ch_title)
            else:
                lines.append(f"第{ch_num}章 {ch_title}")
            lines.append("")
            text = ch_data.get("full_text", "")
            if not text:
                # 尝试从纯文本文件加载
                text = self.load_chapter_text(novel_id, ch_num) or ""
            lines.append(text)
            lines.append("")
            lines.append("")

        content = "\n".join(lines)

        if output_path is None:
            out = self._novel_dir(novel_id) / f"{title}.txt"
        else:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)

        with open(out, "w", encoding="utf-8") as f:
            f.write(content)

        return out

    # ========== 状态查询 ==========

    def load_status(self, novel_id: str) -> dict[str, Any]:
        """查询项目状态概要"""
        novel_data = self.load_novel(novel_id)
        if novel_data is None:
            return {
                "novel_id": novel_id,
                "title": "未找到",
                "status": "not_found",
                "current_chapter": 0,
                "total_chapters": 0,
                "total_words": 0,
                "target_words": 0,
            }

        chapter_numbers = self.list_chapters(novel_id)
        total_words = 0
        for ch_num in chapter_numbers:
            ch_data = self.load_chapter(novel_id, ch_num)
            if ch_data:
                total_words += ch_data.get("word_count", 0)

        # 从大纲获取总章节数
        outline = novel_data.get("outline") or {}
        total_chapters = len(outline.get("chapters", []))

        return {
            "novel_id": novel_id,
            "title": novel_data.get("title", ""),
            "status": novel_data.get("status", "unknown"),
            "current_chapter": novel_data.get("current_chapter", 0),
            "total_chapters": total_chapters,
            "total_words": total_words,
            "target_words": novel_data.get("target_words", 0),
            "author_name": novel_data.get("author_name", ""),
            "target_audience": novel_data.get("target_audience", ""),
            "protagonist_names": novel_data.get("protagonist_names", []),
            "synopsis": novel_data.get("synopsis", ""),
            "tags": novel_data.get("tags", []),
        }

    def novel_exists(self, novel_id: str) -> bool:
        """检查小说项目是否存在"""
        return (self._novel_dir(novel_id) / "novel.json").exists()

    def close(self) -> None:
        """释放资源（文件管理器无需特殊清理）"""
        pass

    def __enter__(self) -> "FileManager":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

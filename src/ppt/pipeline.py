"""PPT 生成流水线 - 编排 9 个阶段的执行

编排 DocumentAnalyzer / ContentExtractor / ContentEnricher /
PresentationPlanner / OutlineGenerator / ContentCreator /
DesignOrchestrator / ImageGenerator / PPTRenderer / QualityChecker，
管理 workspace、checkpoint、进度回调。
"""

from __future__ import annotations

import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.ppt.content_creator import ContentCreator
from src.ppt.design_orchestrator import DesignOrchestrator
from src.ppt.document_analyzer import DocumentAnalyzer
from src.ppt.file_manager import FileManager
from src.ppt.models import (
    ContentMap,
    DeckType,
    DocumentAnalysis,
    EditableOutline,
    ImageRequest,
    NarrativeStructure,
    PresentationPlan,
    SlideContent,
    SlideDesign,
    SlideOutline,
    SlideSpec,
)
from src.ppt.outline_generator import (
    OutlineGenerator,
    deserialize_edited_outline,
    serialize_outline_for_edit,
)
from src.ppt.ppt_renderer import PPTRenderer
from src.ppt.quality_checker import QualityChecker
from src.ppt.theme_manager import ThemeManager

try:
    from src.ppt.content_extractor import ContentExtractor

    _HAS_CONTENT_EXTRACTOR = True
except ImportError:
    _HAS_CONTENT_EXTRACTOR = False

try:
    from src.ppt.content_enricher import ContentEnricher

    _HAS_CONTENT_ENRICHER = True
except ImportError:
    _HAS_CONTENT_ENRICHER = False

try:
    from src.ppt.presentation_planner import PresentationPlanner

    _HAS_PLANNER = True
except ImportError:
    _HAS_PLANNER = False

try:
    from src.ppt.narrative_designer import NarrativeDesigner

    _HAS_NARRATIVE_DESIGNER = True
except ImportError:
    _HAS_NARRATIVE_DESIGNER = False

log = logging.getLogger("ppt")

# ---------------------------------------------------------------------------
# Checkpoint 阶段名称
# ---------------------------------------------------------------------------

_STAGE_ORDER = [
    "rewrite",
    "analysis",
    "extraction",
    "enrichment",
    "planning",
    "outline",
    "content",
    "design",
    "images",
    "render",
]


class PPTPipeline:
    """PPT 生成流水线，编排 9 个阶段。"""

    def __init__(
        self,
        workspace: str = "workspace",
        config: dict[str, Any] | None = None,
    ) -> None:
        self.workspace = workspace
        self.config = config or {}
        self.file_manager = FileManager(workspace)
        self.theme_manager = ThemeManager()

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def generate(
        self,
        text: str,
        theme: str = "modern",
        max_pages: int | None = None,
        generate_images: bool = True,
        output_path: str | None = None,
        progress_callback: Callable[[str, float, str], None] | None = None,
        deck_type: str | None = None,
    ) -> str:
        """生成 PPT 的主入口。

        Args:
            text: 输入文档文本。
            theme: 主题名称。
            max_pages: 最大页数限制。
            generate_images: 是否生成配图（False 则用占位色块）。
            output_path: 输出文件路径（None 则自动生成）。
            progress_callback: 进度回调 fn(stage, progress, message)。
            deck_type: PPT 类型字符串（如 "business_report"），None 为自动检测。

        Returns:
            生成的 .pptx 文件路径。
        """
        # 创建项目
        project_id = (
            f"ppt_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
        )
        self.last_project_id = project_id
        self.file_manager.create_project(project_id)

        # 保存输入文本
        project_dir = Path(self.workspace) / "ppt" / project_id
        input_path = project_dir / "input.txt"
        input_path.write_text(text, encoding="utf-8")

        # 初始化 checkpoint
        checkpoint: dict[str, Any] = {
            "project_id": project_id,
            "status": "started",
            "theme": theme,
            "max_pages": max_pages,
            "generate_images": generate_images,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "stages": {s: {"completed": False} for s in _STAGE_ORDER},
        }

        try:
            return self._run_pipeline(
                text=text,
                theme=theme,
                max_pages=max_pages,
                generate_images=generate_images,
                project_id=project_id,
                checkpoint=checkpoint,
                progress_callback=progress_callback,
                output_path=output_path,
                deck_type=deck_type,
            )
        except Exception:
            checkpoint["status"] = "failed"
            self._save_checkpoint(project_id, checkpoint)
            raise

    # ------------------------------------------------------------------
    # 断点续传
    # ------------------------------------------------------------------

    def resume(
        self,
        project_path: str,
        progress_callback: Callable[[str, float, str], None] | None = None,
    ) -> str:
        """从上次中断的阶段继续。

        Args:
            project_path: 项目目录路径。
            progress_callback: 进度回调。

        Returns:
            生成的 .pptx 文件路径。
        """
        project_id = Path(project_path).name
        ckpt = self.file_manager.load_checkpoint(project_id)
        if ckpt is None:
            raise FileNotFoundError(f"找不到项目检查点: {project_path}")

        checkpoint = ckpt.get("data", ckpt)

        # 加载输入文本
        project_dir = Path(self.workspace) / "ppt" / project_id
        input_path = project_dir / "input.txt"
        if not input_path.exists():
            raise FileNotFoundError(f"找不到输入文本: {input_path}")
        text = input_path.read_text(encoding="utf-8")

        theme = checkpoint.get("theme", "modern")
        max_pages = checkpoint.get("max_pages")
        generate_images = checkpoint.get("generate_images", True)

        return self._run_pipeline(
            text=text,
            theme=theme,
            max_pages=max_pages,
            generate_images=generate_images,
            project_id=project_id,
            checkpoint=checkpoint,
            progress_callback=progress_callback,
        )

    # ------------------------------------------------------------------
    # V2: 两阶段暂停模式
    # ------------------------------------------------------------------

    @staticmethod
    def _route_mode(
        topic: str | None, document_text: str | None
    ) -> str:
        """路由到 topic 或 document 模式。"""
        if topic and not document_text:
            return "topic"
        elif document_text:
            return "document"
        else:
            raise ValueError("必须提供 topic 或 document_text")

    def generate_outline_only(
        self,
        topic: str | None = None,
        document_text: str | None = None,
        audience: str = "business",
        scenario: str = "quarterly_review",
        materials: list[dict] | None = None,
        theme: str = "modern",
        target_pages: int | None = None,
        progress_callback: Callable[[str, float, str], None] | None = None,
    ) -> tuple[str, EditableOutline]:
        """V2 阶段 1：生成大纲后暂停，返回可编辑大纲。

        支持两种模式：
        - topic 模式：从主题生成（NarrativeDesigner -> OutlineGenerator.from_narrative）
        - document 模式：从文档生成（DocumentAnalyzer -> OutlineGenerator.generate）

        Args:
            topic: PPT 主题（topic 模式必填）。
            document_text: 文档文本（document 模式必填）。
            audience: 受众类型。
            scenario: 场景 ID。
            materials: 零散材料。
            theme: 主题名称。
            target_pages: 目标页数。
            progress_callback: 进度回调。

        Returns:
            (project_id, EditableOutline) 元组。
        """
        mode = self._route_mode(topic, document_text)

        # 创建项目
        project_id = f"ppt_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
        self.last_project_id = project_id
        self.file_manager.create_project(project_id)

        project_dir = Path(self.workspace) / "ppt" / project_id

        def _notify(stage: str, progress: float, message: str) -> None:
            if progress_callback:
                progress_callback(stage, progress, message)

        # 初始化 checkpoint
        checkpoint: dict[str, Any] = {
            "project_id": project_id,
            "status": "outline_review",
            "mode": mode,
            "theme": theme,
            "target_pages": target_pages,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "input": {
                "topic": topic,
                "document_text": document_text[:500] if document_text else None,
                "audience": audience,
                "scenario": scenario,
                "theme": theme,
            },
            "stages": {},
        }

        narrative_arc = ""

        if mode == "topic":
            # ---- Topic 模式：NarrativeDesigner -> OutlineGenerator.from_narrative ----
            _notify("narrative_design", 0.1, "正在设计叙事结构...")

            if not _HAS_NARRATIVE_DESIGNER:
                raise ImportError(
                    "NarrativeDesigner 不可用，请安装 pyyaml: pip install pyyaml"
                )

            try:
                designer = NarrativeDesigner(self.config)
                narrative = designer.design(
                    topic=topic,
                    audience=audience,
                    scenario=scenario,
                    materials=materials,
                    target_pages=target_pages,
                )
                narrative_arc = (
                    f"{scenario}: "
                    f"{' → '.join(s.role.value for s in narrative.sections)}"
                )
            except Exception as e:
                log.error("叙事结构设计失败: %s", e)
                raise

            _notify("outline_generation", 0.3, "正在生成大纲...")

            outline_gen = OutlineGenerator(self.config)
            outlines = outline_gen.from_narrative(
                narrative, theme=theme, target_pages=target_pages
            )
        else:
            # ---- Document 模式：复用现有分析流程 ----
            # 保存输入文本
            input_path = project_dir / "input.txt"
            input_path.write_text(document_text, encoding="utf-8")

            _notify("analyzing", 0.1, "正在分析文档...")

            analyzer = DocumentAnalyzer(self.config)
            analysis = analyzer.analyze(document_text)

            _notify("outline_generation", 0.3, "正在生成大纲...")

            outline_gen = OutlineGenerator(self.config)
            outlines = outline_gen.generate(
                document_text, analysis, max_pages=target_pages
            )
            narrative_arc = f"document: {analysis.theme}"

        _notify("outline_review", 0.5, "大纲生成完成，等待审核...")

        # 序列化为可编辑大纲
        editable = serialize_outline_for_edit(
            outlines, project_id=project_id, narrative_arc=narrative_arc
        )

        # 保存 checkpoint
        checkpoint["stages"]["outline"] = {
            "completed": True,
            "data": editable.model_dump(),
        }
        self._save_checkpoint(project_id, checkpoint)

        # 保存 YAML 版大纲供 CLI 编辑
        try:
            import yaml

            yaml_path = project_dir / "outline_editable.yaml"
            yaml_path.write_text(
                yaml.dump(
                    editable.model_dump(),
                    allow_unicode=True,
                    default_flow_style=False,
                ),
                encoding="utf-8",
            )
        except ImportError:
            pass  # yaml 不可用则跳过

        return project_id, editable

    def continue_from_outline(
        self,
        project_id: str,
        edited_outline: EditableOutline,
        generate_images: bool = True,
        progress_callback: Callable[[str, float, str], None] | None = None,
    ) -> str:
        """V2 阶段 2：从用户确认的大纲继续生成 PPT。

        Args:
            project_id: 项目 ID。
            edited_outline: 用户编辑后的大纲。
            generate_images: 是否生成配图。
            progress_callback: 进度回调。

        Returns:
            生成的 .pptx 文件路径。
        """

        def _notify(stage: str, progress: float, message: str) -> None:
            if progress_callback:
                progress_callback(stage, progress, message)

        # 反序列化大纲
        outlines = deserialize_edited_outline(edited_outline)

        _notify("creating_content", 0.55, "正在创作内容...")

        # 加载 checkpoint 获取 theme
        ckpt = self.file_manager.load_checkpoint(project_id)
        theme = "modern"
        if ckpt:
            ckpt_data = ckpt.get("data", ckpt)
            theme = ckpt_data.get(
                "theme", ckpt_data.get("input", {}).get("theme", "modern")
            )

        # 阶段 6: 内容创作
        creator = ContentCreator(self.config)
        contents = creator.create("", outlines)
        _notify("creating_content", 0.65, f"内容创作完成（{len(contents)}页）")

        # 阶段 7: 设计编排
        _notify("designing", 0.67, "正在设计编排...")
        theme_config = self.theme_manager.get_theme(theme)
        orchestrator = DesignOrchestrator(self.config, theme_config)
        designs = orchestrator.orchestrate(contents, outlines)
        image_requests = orchestrator.get_image_requests()
        _notify("designing", 0.72, "设计编排完成")

        # 组装 SlideSpec
        slides = self._assemble_slides(outlines, contents, designs)

        # 阶段 8: 配图生成（可选）
        if generate_images and image_requests:
            _notify(
                "generating_images",
                0.74,
                f"正在生成配图（共{len(image_requests)}张）...",
            )
            slides = self._generate_images(
                slides,
                image_requests,
                project_id,
                progress_callback=progress_callback,
            )
            _notify("generating_images", 0.90, "配图生成完成")

        # 阶段 9: 渲染 + 质量检查
        _notify("rendering", 0.91, "正在渲染PPT...")

        checker = QualityChecker()
        report = checker.check(slides)
        if report.issues:
            log.info(
                "质量检查: %s (分数: %.1f)", report.summary, report.score
            )
            slides = checker.fix(slides, report)

        renderer = PPTRenderer(theme_config)
        renderer.render(slides)
        final_output = str(self.file_manager.get_output_path(project_id))
        renderer.save(final_output)

        # 更新 checkpoint
        checkpoint = {
            "project_id": project_id,
            "status": "completed",
            "output_path": final_output,
            "quality_report": report.model_dump(),
        }
        self._save_checkpoint(project_id, checkpoint)

        _notify("completed", 1.0, "PPT已生成！")
        return final_output

    # ------------------------------------------------------------------
    # 项目状态
    # ------------------------------------------------------------------

    def get_status(self, project_path: str) -> dict[str, Any]:
        """获取项目状态。"""
        project_id = Path(project_path).name
        ckpt = self.file_manager.load_checkpoint(project_id)
        if ckpt is None:
            return {"project_id": project_id, "status": "not_found"}

        data = ckpt.get("data", ckpt)
        stages = data.get("stages", {})
        completed = [
            s
            for s in _STAGE_ORDER
            if stages.get(s, {}).get("completed")
        ]
        return {
            "project_id": project_id,
            "status": data.get("status", "unknown"),
            "theme": data.get("theme", "modern"),
            "created_at": data.get("created_at"),
            "completed_stages": completed,
            "total_stages": len(_STAGE_ORDER),
            "output_path": data.get("output_path"),
        }

    # ------------------------------------------------------------------
    # 内部：流水线执行
    # ------------------------------------------------------------------

    def _run_pipeline(
        self,
        text: str,
        theme: str,
        max_pages: int | None,
        generate_images: bool,
        project_id: str,
        checkpoint: dict,
        progress_callback: Callable[[str, float, str], None] | None,
        output_path: str | None = None,
        deck_type: str | None = None,
    ) -> str:
        """执行流水线各阶段（跳过已完成的阶段）。"""

        project_dir = Path(self.workspace) / "ppt" / project_id
        stages = checkpoint.get("stages", {})

        def _notify(stage: str, progress: float, message: str) -> None:
            if progress_callback:
                progress_callback(stage, progress, message)

        # --- 阶段 0: 文档改写（不适合 PPT 的文档自动改写） ---
        if not stages.get("rewrite", {}).get("completed"):
            try:
                from src.ppt.document_analyzer import check_ppt_suitability
                from src.ppt.document_rewriter import DocumentRewriter

                suit = check_ppt_suitability(text)
                if not suit.suitable:
                    _notify("rewriting", 0.01, "文档不适合直接生成PPT，正在改写...")
                    rewriter = DocumentRewriter(self.config)
                    rewritten = rewriter.rewrite(text)
                    did_rewrite = rewritten != text
                    if did_rewrite:
                        # 保存改写后文本，替换流水线输入
                        text = rewritten
                        (project_dir / "input_rewritten.txt").write_text(
                            text, encoding="utf-8",
                        )
                        log.info("文档已改写为 PPT 友好版本")
                    stages["rewrite"] = {
                        "completed": True,
                        "rewritten": did_rewrite,
                        "original_score": suit.score,
                    }
                else:
                    stages["rewrite"] = {"completed": True, "rewritten": False}
            except ImportError:
                stages["rewrite"] = {"completed": True, "rewritten": False}
            except Exception as e:
                log.warning("文档改写阶段失败，使用原文: %s", e)
                stages["rewrite"] = {"completed": True, "rewritten": False}
            checkpoint["stages"] = stages
            self._save_checkpoint(project_id, checkpoint)
        else:
            # 断点续传：如果之前改写过，加载改写后的文本
            if stages.get("rewrite", {}).get("rewritten"):
                rewritten_path = project_dir / "input_rewritten.txt"
                if rewritten_path.exists():
                    text = rewritten_path.read_text(encoding="utf-8")
                    log.info("加载改写后的文档")
            log.info("跳过已完成的阶段: rewrite")

        # --- 阶段 1: 文档分析 ---
        if not stages.get("analysis", {}).get("completed"):
            _notify("analyzing", 0.02, "正在分析文档...")
            analyzer = DocumentAnalyzer(self.config)
            analysis = analyzer.analyze(text)
            analysis_data = analysis.model_dump()
            # 将枚举值转为字符串以便 JSON 序列化
            analysis_data["doc_type"] = analysis.doc_type.value
            analysis_data["audience"] = analysis.audience.value
            analysis_data["tone"] = analysis.tone.value
            stages["analysis"] = {"completed": True, "data": analysis_data}
            checkpoint["status"] = "analyzed"
            checkpoint["stages"] = stages
            self._save_checkpoint(project_id, checkpoint)
            _notify("analyzing", 0.15, "文档分析完成")
        else:
            analysis = DocumentAnalysis(**stages["analysis"]["data"])
            log.info("跳过已完成的阶段: analysis")

        # --- 阶段 2: 内容提取 ---
        content_map = None
        if stages.get("extraction", {}).get("completed"):
            content_map = self._load_content_map(
                stages["extraction"].get("data")
            )
            log.info("跳过已完成的阶段: extraction")
        elif _HAS_CONTENT_EXTRACTOR:
            _notify("extracting", 0.17, "正在提取文档结构...")
            try:
                extractor = ContentExtractor(self.config)
                content_map = extractor.extract(text)
                stages["extraction"] = {
                    "completed": True,
                    "data": content_map.model_dump(),
                }
                checkpoint["status"] = "extracted"
                checkpoint["stages"] = stages
                self._save_checkpoint(project_id, checkpoint)
                _notify("extracting", 0.30, "文档结构提取完成")
            except Exception as e:
                log.warning("内容提取失败，跳过: %s", e)
                stages["extraction"] = {"completed": True, "data": None}
                checkpoint["stages"] = stages
                self._save_checkpoint(project_id, checkpoint)
        else:
            log.info("ContentExtractor 不可用，跳过内容提取阶段")
            stages["extraction"] = {"completed": True, "data": None}
            checkpoint["stages"] = stages
            self._save_checkpoint(project_id, checkpoint)

        # --- 阶段 3: 内容增强（联网搜索/LLM知识补充） ---
        if content_map is not None and not stages.get("enrichment", {}).get("completed"):
            if _HAS_CONTENT_ENRICHER:
                _notify("enriching", 0.30, "正在补充外部信息...")
                try:
                    enricher = ContentEnricher(self.config)
                    content_map = enricher.enrich(
                        content_map, text, deck_type=deck_type,
                    )
                    stages["enrichment"] = {
                        "completed": True,
                        "data": content_map.model_dump(),
                    }
                    checkpoint["stages"] = stages
                    self._save_checkpoint(project_id, checkpoint)
                    _notify("enriching", 0.35, "内容增强完成")
                except Exception as e:
                    log.warning("内容增强失败，跳过: %s", e)
                    stages["enrichment"] = {"completed": True, "data": None}
                    checkpoint["stages"] = stages
                    self._save_checkpoint(project_id, checkpoint)
            else:
                stages["enrichment"] = {"completed": True, "data": None}
                checkpoint["stages"] = stages
                self._save_checkpoint(project_id, checkpoint)
        elif stages.get("enrichment", {}).get("completed"):
            enriched = self._load_content_map(stages["enrichment"].get("data"))
            if enriched is not None:
                content_map = enriched
            log.info("跳过已完成的阶段: enrichment")
        else:
            stages["enrichment"] = {"completed": True, "data": None}
            checkpoint["stages"] = stages
            self._save_checkpoint(project_id, checkpoint)

        # --- 阶段 4: 演示计划 ---
        presentation_plan: PresentationPlan | None = None
        deck_type_enum: DeckType | None = None
        if stages.get("planning", {}).get("completed"):
            plan_data = stages["planning"].get("data")
            if plan_data:
                presentation_plan = PresentationPlan(**plan_data)
                deck_type_enum = presentation_plan.deck_type
            log.info("跳过已完成的阶段: planning")
        elif _HAS_PLANNER:
            _notify("planning", 0.35, "正在规划演示策略...")
            try:
                planner = PresentationPlanner(self.config)
                presentation_plan = planner.plan(
                    text, analysis, content_map,
                    deck_type=deck_type, max_pages=max_pages,
                )
                deck_type_enum = presentation_plan.deck_type
                stages["planning"] = {
                    "completed": True,
                    "data": presentation_plan.model_dump(),
                }
                checkpoint["stages"] = stages
                self._save_checkpoint(project_id, checkpoint)
                _notify(
                    "planning", 0.40,
                    f"演示计划完成（{presentation_plan.deck_type.value}）",
                )
            except Exception as e:
                log.warning("演示计划失败，跳过: %s", e)
                stages["planning"] = {"completed": True, "data": None}
                checkpoint["stages"] = stages
                self._save_checkpoint(project_id, checkpoint)
        else:
            stages["planning"] = {"completed": True, "data": None}
            checkpoint["stages"] = stages
            self._save_checkpoint(project_id, checkpoint)

        # --- 阶段 5: 大纲生成 ---
        if not stages.get("outline", {}).get("completed"):
            _notify("outlining", 0.42, "正在生成大纲...")
            outline_gen = OutlineGenerator(self.config)
            outlines = outline_gen.generate(
                text, analysis, max_pages=max_pages,
                content_map=content_map,
                presentation_plan=presentation_plan,
            )
            outlines_data = [o.model_dump() for o in outlines]
            # 枚举转字符串（Pydantic v2 str Enum 通常已是字符串，兜底处理）
            for od in outlines_data:
                if not isinstance(od.get("layout"), str):
                    od["layout"] = od["layout"].value if hasattr(od["layout"], "value") else str(od["layout"])
            stages["outline"] = {"completed": True, "data": outlines_data}
            checkpoint["status"] = "outlined"
            checkpoint["stages"] = stages
            self._save_checkpoint(project_id, checkpoint)
            _notify("outlining", 0.50, f"大纲生成完成（{len(outlines)}页）")
        else:
            outlines = [
                SlideOutline(**d) for d in stages["outline"]["data"]
            ]
            log.info("跳过已完成的阶段: outline")

        # --- 阶段 6: 内容创作 ---
        if not stages.get("content", {}).get("completed"):
            _notify("creating_content", 0.52, "正在创作内容...")
            creator = ContentCreator(self.config)
            contents = creator.create(
                text, outlines, content_map=content_map,
                deck_type=deck_type_enum,
            )
            contents_data = [c.model_dump() for c in contents]
            stages["content"] = {"completed": True, "data": contents_data}
            checkpoint["status"] = "content_created"
            checkpoint["stages"] = stages
            self._save_checkpoint(project_id, checkpoint)
            _notify(
                "creating_content",
                0.62,
                f"内容创作完成（{len(contents)}页）",
            )
        else:
            contents = [
                SlideContent(**d) for d in stages["content"]["data"]
            ]
            log.info("跳过已完成的阶段: content")

        # --- 阶段 7: 设计编排 ---
        if not stages.get("design", {}).get("completed"):
            _notify("designing", 0.64, "正在设计编排...")
            theme_config = self.theme_manager.get_theme(theme)
            orchestrator = DesignOrchestrator(self.config, theme_config)
            designs = orchestrator.orchestrate(contents, outlines)
            image_requests = orchestrator.get_image_requests()

            designs_data = [d.model_dump() for d in designs]
            image_requests_data = [r.model_dump() for r in image_requests]
            stages["design"] = {
                "completed": True,
                "data": designs_data,
                "image_requests": image_requests_data,
            }
            checkpoint["status"] = "designed"
            checkpoint["stages"] = stages
            self._save_checkpoint(project_id, checkpoint)
            _notify("designing", 0.72, "设计编排完成")
        else:
            designs = [
                SlideDesign(**d) for d in stages["design"]["data"]
            ]
            image_requests = [
                ImageRequest(**r)
                for r in stages["design"].get("image_requests", [])
            ]
            log.info("跳过已完成的阶段: design")

        # 组装 SlideSpec
        slides = self._assemble_slides(outlines, contents, designs)

        # --- 阶段 8: 配图生成（可选） ---
        if generate_images and not stages.get("images", {}).get("completed"):
            if image_requests:
                _notify(
                    "generating_images",
                    0.74,
                    f"正在生成配图（共{len(image_requests)}张）...",
                )
                slides = self._generate_images(
                    slides,
                    image_requests,
                    project_id,
                    progress_callback=progress_callback,
                )
            stages["images"] = {"completed": True}
            checkpoint["status"] = "images_generated"
            checkpoint["stages"] = stages
            self._save_checkpoint(project_id, checkpoint)
            _notify("generating_images", 0.90, "配图生成完成")
        elif not generate_images:
            stages["images"] = {"completed": True}
            checkpoint["stages"] = stages
            log.info("跳过配图生成（generate_images=False）")
        else:
            # 恢复图片路径
            slides = self._restore_image_paths(slides, project_id)
            log.info("跳过已完成的阶段: images")

        # --- 阶段 9: PPT 渲染 + 质量检查 ---
        if not stages.get("render", {}).get("completed"):
            _notify("rendering", 0.91, "正在渲染PPT...")
            theme_config = self.theme_manager.get_theme(theme)

            # 质量检查 + 自动修复
            _notify("checking", 0.95, "正在质量检查...")
            checker = QualityChecker()
            report = checker.check(slides)
            if report.issues:
                log.info(
                    "质量检查: %s (分数: %.1f)",
                    report.summary,
                    report.score,
                )
                slides = checker.fix(slides, report)

            # 渲染
            renderer = PPTRenderer(theme_config)
            renderer.render(slides)
            final_output = output_path or str(
                self.file_manager.get_output_path(project_id)
            )
            renderer.save(final_output)

            stages["render"] = {"completed": True}
            checkpoint["status"] = "completed"
            checkpoint["output_path"] = final_output
            checkpoint["quality_report"] = report.model_dump()
            checkpoint["stages"] = stages
            self._save_checkpoint(project_id, checkpoint)
            _notify("completed", 1.0, "PPT已生成！")

            return final_output
        else:
            final_output = checkpoint.get("output_path", "")
            if final_output and os.path.exists(final_output):
                return final_output
            raise FileNotFoundError(
                f"PPT 输出文件不存在: {final_output}"
            )

    # ------------------------------------------------------------------
    # 图片生成
    # ------------------------------------------------------------------

    def _generate_images(
        self,
        slides: list[SlideSpec],
        image_requests: list[ImageRequest],
        project_id: str,
        progress_callback: Callable[[str, float, str], None] | None = None,
    ) -> list[SlideSpec]:
        """为需要图片的页面生成配图。

        使用 ThreadPoolExecutor 并行生成，最多 3 张同时。
        图片保存到 workspace/ppt/{project_id}/images/。
        生成失败的页面保持 image_path=None（渲染器会用占位色块）。
        """
        page_to_idx: dict[int, int] = {}
        for i, slide in enumerate(slides):
            page_to_idx[slide.page_number] = i

        total = len(image_requests)
        completed = 0

        def _gen_one(req: ImageRequest) -> tuple[int, str | None]:
            save_path = str(
                self.file_manager.get_image_path(
                    project_id, req.page_number
                )
            )
            result = self._generate_single_image(req, save_path)
            return req.page_number, result

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                pool.submit(_gen_one, req): req for req in image_requests
            }
            for future in as_completed(futures):
                page_num, img_path = future.result()
                completed += 1
                if img_path and page_num in page_to_idx:
                    slides[page_to_idx[page_num]].image_path = img_path
                if progress_callback:
                    pct = 0.74 + 0.16 * (completed / total)
                    progress_callback(
                        "generating_images",
                        pct,
                        f"正在生成配图（{completed}/{total}张）...",
                    )

        return slides

    def _generate_single_image(
        self, image_request: ImageRequest, save_path: str
    ) -> str | None:
        """生成单张图片，返回保存路径或 None。"""
        try:
            from src.imagegen.image_generator import create_image_generator

            # 根据 orientation 设置尺寸
            if image_request.size.value == "landscape":
                width, height = 1024, 576
            elif image_request.size.value == "portrait":
                width, height = 576, 1024
            else:
                width, height = 768, 768

            # 将尺寸注入 imagegen 配置
            img_config = dict(self.config.get("imagegen", {}))
            img_config["width"] = width
            img_config["height"] = height

            generator = create_image_generator(img_config)
            image = generator.generate(prompt=image_request.prompt)

            # 保存图片
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            image.save(save_path)
            log.info(
                "图片生成成功: 第%d页 -> %s",
                image_request.page_number,
                save_path,
            )
            return save_path

        except Exception as e:
            log.warning(
                "图片生成失败（第%d页）: %s", image_request.page_number, e
            )
            return None

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _assemble_slides(
        self,
        outlines: list[SlideOutline],
        contents: list[SlideContent],
        designs: list[SlideDesign],
    ) -> list[SlideSpec]:
        """将大纲、内容、设计合并为完整的 SlideSpec 列表。"""
        slides: list[SlideSpec] = []
        for outline, content, design in zip(outlines, contents, designs):
            slide = SlideSpec(
                page_number=outline.page_number,
                content=content,
                design=design,
                needs_image=outline.needs_image,
                image_request=(
                    ImageRequest(
                        page_number=outline.page_number,
                        prompt=outline.image_prompt or "",
                        style="modern",
                    )
                    if outline.needs_image and outline.image_prompt
                    else None
                ),
            )
            slides.append(slide)
        return slides

    def _restore_image_paths(
        self, slides: list[SlideSpec], project_id: str
    ) -> list[SlideSpec]:
        """断点续传时恢复已生成的图片路径。"""
        for slide in slides:
            img_path = self.file_manager.get_image_path(
                project_id, slide.page_number
            )
            if img_path.exists():
                slide.image_path = str(img_path)
        return slides

    @staticmethod
    def _load_content_map(data: dict | None) -> ContentMap | None:
        """从 checkpoint 数据重建 ContentMap。"""
        if data is None:
            return None
        try:
            return ContentMap(**data)
        except Exception as e:
            log.warning("无法加载 ContentMap checkpoint: %s", e)
            return None

    def _save_checkpoint(self, project_id: str, data: dict) -> None:
        """保存 checkpoint。"""
        self.file_manager.save_checkpoint(
            project_id, data.get("status", "unknown"), data
        )

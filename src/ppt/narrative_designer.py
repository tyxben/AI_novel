"""叙事结构设计器 — 根据场景模板 + LLM 生成叙事结构。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from src.agents.utils import extract_json_obj
from src.llm.llm_client import LLMClient, create_llm_client
from src.ppt.models import (
    ImageStrategy,
    LayoutType,
    NarrativeSection,
    NarrativeStructure,
    PageRole,
)

log = logging.getLogger("ppt")

# 叙事模板目录
_NARRATIVES_DIR = Path(__file__).parent / "narratives"


class NarrativeDesigner:
    """根据场景模板和 LLM 设计叙事结构。"""

    def __init__(self, config: dict) -> None:
        self._llm: LLMClient = create_llm_client(config.get("llm", {}))
        self._templates_cache: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # 模板管理
    # ------------------------------------------------------------------

    def load_scenario_template(self, scenario_id: str) -> dict:
        """加载场景 YAML 模板。

        Args:
            scenario_id: 场景 ID，如 ``"quarterly_review"``。

        Returns:
            解析后的模板字典。如果指定场景不存在则 fallback 到
            ``quarterly_review``。
        """
        if scenario_id in self._templates_cache:
            return self._templates_cache[scenario_id]

        path = _NARRATIVES_DIR / f"{scenario_id}.yaml"
        if not path.exists():
            log.warning("场景模板不存在: %s，使用 quarterly_review", scenario_id)
            path = _NARRATIVES_DIR / "quarterly_review.yaml"

        with open(path, encoding="utf-8") as f:
            template = yaml.safe_load(f)

        self._templates_cache[scenario_id] = template
        return template

    def list_scenarios(self) -> list[dict[str, str]]:
        """列出所有可用场景。

        Returns:
            场景列表，每项包含 ``id`` / ``name`` / ``description``。
        """
        scenarios: list[dict[str, str]] = []
        if not _NARRATIVES_DIR.is_dir():
            return scenarios
        for path in sorted(_NARRATIVES_DIR.glob("*.yaml")):
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            scenarios.append(
                {
                    "id": data.get("narrative_id", path.stem),
                    "name": data.get("name", path.stem),
                    "description": data.get("description", ""),
                }
            )
        return scenarios

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def design(
        self,
        topic: str,
        audience: str = "business",
        scenario: str = "quarterly_review",
        materials: list[dict[str, Any]] | None = None,
        target_pages: int | None = None,
    ) -> NarrativeStructure:
        """根据主题、受众、场景生成叙事结构。

        Args:
            topic: PPT 主题。
            audience: 受众类型。
            scenario: 场景 ID。
            materials: 用户提供的零散材料
                ``[{"type": "text", "content": "..."}]``。
            target_pages: 目标页数（``None`` 则使用模板默认值）。

        Returns:
            ``NarrativeStructure`` 实例。
        """
        # 1. 加载场景模板
        template = self.load_scenario_template(scenario)

        # 2. 确定目标页数
        if target_pages is None:
            min_p = template.get("target_pages_min", 10)
            max_p = template.get("target_pages_max", 20)
            target_pages = (min_p + max_p) // 2

        # 3. 调用 LLM 生成叙事结构
        sections = self._generate_with_llm(
            topic, audience, scenario, template, materials, target_pages
        )

        # 4. 如果 LLM 失败，用模板做 fallback
        if sections is None:
            log.warning("LLM 叙事设计失败，使用模板 fallback")
            sections = self._fallback_from_template(template, topic)

        return NarrativeStructure(
            scenario=scenario,
            topic=topic,
            audience=audience,
            total_pages=len(sections),
            sections=sections,
        )

    # ------------------------------------------------------------------
    # LLM 叙事生成
    # ------------------------------------------------------------------

    def _generate_with_llm(
        self,
        topic: str,
        audience: str,
        scenario: str,
        template: dict,
        materials: list[dict[str, Any]] | None,
        target_pages: int,
    ) -> list[NarrativeSection] | None:
        """调用 LLM 生成叙事结构。"""
        system_prompt = self._build_system_prompt(template)
        user_prompt = self._build_user_prompt(
            topic, audience, template, materials, target_pages
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = self._llm.chat(
                messages, temperature=0.5, json_mode=True, max_tokens=4096
            )
            data = extract_json_obj(response.content)
        except Exception as e:
            log.warning("NarrativeDesigner LLM 调用失败: %s", e)
            return None

        if data is None or "sections" not in data:
            return None

        return self._parse_sections(data["sections"])

    # ------------------------------------------------------------------
    # Prompt 构建
    # ------------------------------------------------------------------

    def _build_system_prompt(self, template: dict) -> str:
        """构建 LLM system prompt。"""
        tips = template.get("narrative_tips", [])
        tips_text = "\n".join(f"- {t}" for t in tips) if tips else "- 无特殊提示"

        structure_desc: list[str] = []
        for item in template.get("structure", []):
            role = item.get("role", "unknown")
            title_tpl = item.get("title_template", "")
            required = "必须" if item.get("required", True) else "可选"
            kpc = item.get("key_points_count", "3-5")
            structure_desc.append(
                f'- {role}（{required}）: 标题参考 "{title_tpl}"，建议 {kpc} 个要点'
            )
        structure_text = "\n".join(structure_desc) if structure_desc else "- 无预设结构"

        return (
            "你是一位资深演示策划师。根据用户的主题和受众，设计一份 PPT 叙事结构。\n"
            "\n"
            f"## 场景: {template.get('name', '')}\n"
            f"{template.get('description', '')}\n"
            "\n"
            "## 参考结构\n"
            f"{structure_text}\n"
            "\n"
            "## 场景提示\n"
            f"{tips_text}\n"
            "\n"
            "## 核心要求\n"
            "1. 根据主题识别需要覆盖的关键信息点\n"
            "2. 如果用户提供了材料，将材料归类到对应页面\n"
            "3. 为每个页面生成具体的标题提示和要点提示\n"
            "4. 可以增删页面，但必须保留 required=true 的页面\n"
            "5. title_hint 必须是中文，具体且有力\n"
            "6. key_points_hint 每条 20-50 字，是完整信息点\n"
            "7. 页面总数要符合目标页数\n"
            "\n"
            "## 输出格式（JSON）\n"
            "{\n"
            '  "sections": [\n'
            "    {\n"
            '      "role": "cover",\n'
            '      "title_hint": "具体标题",\n'
            '      "key_points_hint": [],\n'
            '      "speaker_notes_hint": "这页要讲什么"\n'
            "    },\n"
            "    ...\n"
            "  ]\n"
            "}"
        )

    def _build_user_prompt(
        self,
        topic: str,
        audience: str,
        template: dict,
        materials: list[dict[str, Any]] | None,
        target_pages: int,
    ) -> str:
        """构建 LLM user prompt。"""
        parts = [
            f"## 主题\n{topic}",
            f"## 受众\n{audience}",
            f"## 目标页数\n{target_pages} 页",
        ]

        if materials:
            mat_texts: list[str] = []
            for i, mat in enumerate(materials[:10]):  # 最多 10 个材料
                content = str(mat.get("content", ""))[:5000]  # 每个最多 5000 字
                mat_texts.append(f"### 材料 {i + 1}\n{content}")
            parts.append("## 用户提供的材料\n" + "\n\n".join(mat_texts))

        parts.append(
            f"请为主题「{topic}」设计一份 {target_pages} 页的叙事结构。"
            f"返回 JSON 格式。"
        )

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # LLM 返回值解析
    # ------------------------------------------------------------------

    def _parse_sections(
        self, raw_sections: list[Any]
    ) -> list[NarrativeSection] | None:
        """解析 LLM 返回的 sections 列表。

        Returns:
            解析后的 ``NarrativeSection`` 列表，或 ``None``（解析失败时）。
        """
        if not isinstance(raw_sections, list) or len(raw_sections) < 3:
            return None

        sections: list[NarrativeSection] = []
        for item in raw_sections:
            if not isinstance(item, dict):
                continue

            # 解析 role
            role_str = str(item.get("role", "")).strip()
            try:
                role = PageRole(role_str)
            except (ValueError, KeyError):
                role = PageRole.KNOWLEDGE_POINT  # fallback

            # 解析 key_points_hint
            kph = item.get("key_points_hint", [])
            if not isinstance(kph, list):
                kph = []
            kph = [str(p) for p in kph if p]

            # 解析 layout_preference（可选）
            layout_pref: LayoutType | None = None
            layout_str = item.get("layout_preference")
            if layout_str:
                try:
                    layout_pref = LayoutType(str(layout_str))
                except (ValueError, KeyError):
                    layout_pref = None

            # 解析 image_strategy（可选）
            img_strategy = ImageStrategy.NONE
            img_str = item.get("image_strategy")
            if img_str:
                try:
                    img_strategy = ImageStrategy(str(img_str))
                except (ValueError, KeyError):
                    img_strategy = ImageStrategy.NONE

            sections.append(
                NarrativeSection(
                    role=role,
                    title_hint=str(item.get("title_hint", "")),
                    key_points_hint=kph,
                    speaker_notes_hint=str(item.get("speaker_notes_hint", "")),
                    layout_preference=layout_pref,
                    image_strategy=img_strategy,
                    required=bool(item.get("required", True)),
                )
            )

        if len(sections) < 3:
            return None

        return sections

    # ------------------------------------------------------------------
    # 模板 Fallback
    # ------------------------------------------------------------------

    def _fallback_from_template(
        self, template: dict, topic: str
    ) -> list[NarrativeSection]:
        """LLM 失败时，直接从模板生成基础结构。"""
        sections: list[NarrativeSection] = []
        for item in template.get("structure", []):
            role_str = str(item.get("role", "cover"))
            try:
                role = PageRole(role_str)
            except (ValueError, KeyError):
                role = PageRole.KNOWLEDGE_POINT

            title = (
                str(item.get("title_template", ""))
                .replace("{{period}}", "")
                .replace("{{quarter}}", "")
                .replace("{{product_name}}", "")
                .replace("{{topic}}", topic)
                .strip()
            )
            if not title:
                title = role_str.replace("_", " ").title()

            sections.append(
                NarrativeSection(
                    role=role,
                    title_hint=title,
                    required=bool(item.get("required", True)),
                )
            )

        # 确保至少有 cover 和 closing
        if not sections:
            sections = [
                NarrativeSection(role=PageRole.COVER, title_hint=topic),
                NarrativeSection(
                    role=PageRole.EXECUTIVE_SUMMARY, title_hint="核心要点"
                ),
                NarrativeSection(role=PageRole.CLOSING, title_hint="谢谢"),
            ]

        return sections

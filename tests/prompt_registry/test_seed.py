"""Tests for seed_default_prompts function."""

import pytest

from src.prompt_registry.registry import PromptRegistry
from src.prompt_registry.seed_data import seed_default_prompts


@pytest.fixture
def seeded_registry(tmp_path):
    db_path = str(tmp_path / "seed_test.db")
    reg = PromptRegistry(db_path=db_path)
    seed_default_prompts(reg)
    yield reg
    reg.close()


class TestSeedBlockCounts:
    def test_anti_pattern_blocks_created(self, seeded_registry):
        blocks = seeded_registry.list_blocks(block_type="anti_pattern")
        assert len(blocks) == 4
        base_ids = {b.base_id for b in blocks}
        assert "writer_anti_ai_flavor" in base_ids
        assert "writer_anti_repetition" in base_ids
        assert "writer_narrative_logic" in base_ids
        assert "writer_character_name_lock" in base_ids

    def test_style_system_instruction_blocks_created(self, seeded_registry):
        blocks = seeded_registry.list_blocks(block_type="system_instruction")
        # 10 styles: wuxia.classical, wuxia.modern, webnovel.shuangwen, webnovel.xuanhuan,
        # webnovel.romance, literary.realism, literary.lyrical, scifi.hardscifi,
        # light_novel.campus, light_novel.fantasy
        assert len(blocks) == 10

    def test_few_shot_example_blocks_created(self, seeded_registry):
        blocks = seeded_registry.list_blocks(block_type="few_shot_example")
        # Each style has a few-shot block
        assert len(blocks) == 10

    def test_craft_technique_blocks_created(self, seeded_registry):
        blocks = seeded_registry.list_blocks(block_type="craft_technique")
        assert len(blocks) == 5
        base_ids = {b.base_id for b in blocks}
        assert "craft_battle" in base_ids
        assert "craft_dialogue" in base_ids
        assert "craft_emotional" in base_ids
        assert "craft_strategy" in base_ids
        assert "craft_general" in base_ids

    def test_feedback_injection_block_created(self, seeded_registry):
        blocks = seeded_registry.list_blocks(block_type="feedback_injection")
        assert len(blocks) == 1
        assert blocks[0].base_id == "feedback_injection"

    def test_total_block_count(self, seeded_registry):
        all_blocks = seeded_registry.list_blocks()
        # 4 anti_pattern + 10 system_instruction + 10 few_shot + 5 craft + 1 feedback = 30
        assert len(all_blocks) == 30


class TestSeedBlockContent:
    def test_all_blocks_have_nonempty_content(self, seeded_registry):
        blocks = seeded_registry.list_blocks()
        for block in blocks:
            assert block.content, f"Block {block.base_id} has empty content"

    def test_anti_ai_flavor_content(self, seeded_registry):
        block = seeded_registry.get_active_block("writer_anti_ai_flavor")
        assert block is not None
        assert "内心翻涌" in block.content
        assert "AI" in block.content

    def test_style_wuxia_classical_content(self, seeded_registry):
        block = seeded_registry.get_active_block("style_wuxia_classical")
        assert block is not None
        assert "古典武侠" in block.content
        assert block.genre == "wuxia"

    def test_craft_battle_content(self, seeded_registry):
        block = seeded_registry.get_active_block("craft_battle")
        assert block is not None
        assert "战斗" in block.content
        assert block.scene_type == "battle"

    def test_feedback_injection_has_placeholders(self, seeded_registry):
        block = seeded_registry.get_active_block("feedback_injection")
        assert block is not None
        assert "{strengths}" in block.content
        assert "{weaknesses}" in block.content


class TestSeedBlockAttributes:
    def test_anti_pattern_blocks_have_correct_agent(self, seeded_registry):
        blocks = seeded_registry.list_blocks(block_type="anti_pattern")
        for block in blocks:
            assert block.agent == "writer"

    def test_style_blocks_have_genre(self, seeded_registry):
        blocks = seeded_registry.list_blocks(block_type="system_instruction")
        for block in blocks:
            assert block.genre is not None, f"Style block {block.base_id} has no genre"

    def test_craft_blocks_scene_types(self, seeded_registry):
        battle = seeded_registry.get_active_block("craft_battle")
        assert battle.scene_type == "battle"
        dialogue = seeded_registry.get_active_block("craft_dialogue")
        assert dialogue.scene_type == "dialogue"
        emotional = seeded_registry.get_active_block("craft_emotional")
        assert emotional.scene_type == "emotional"
        strategy = seeded_registry.get_active_block("craft_strategy")
        assert strategy.scene_type == "strategy"
        general = seeded_registry.get_active_block("craft_general")
        assert general.scene_type is None


class TestSeedTemplates:
    def test_templates_created(self, seeded_registry):
        templates = seeded_registry.list_templates("writer")
        assert len(templates) == 5  # default + battle + dialogue + emotional + strategy

    def test_default_template_block_refs(self, seeded_registry):
        tpl = seeded_registry.get_template("writer_default")
        assert tpl is not None
        assert "style_{genre}" in tpl.block_refs
        assert "craft_general" in tpl.block_refs
        assert "writer_anti_ai_flavor" in tpl.block_refs
        assert "feedback_injection" in tpl.block_refs

    def test_battle_template_block_refs(self, seeded_registry):
        tpl = seeded_registry.get_template("writer_battle")
        assert tpl is not None
        assert "craft_battle" in tpl.block_refs
        assert "craft_general" in tpl.block_refs

    def test_template_refs_resolve_to_existing_blocks(self, seeded_registry):
        """All non-dynamic block_refs in templates should have corresponding blocks."""
        templates = seeded_registry.list_templates()
        for tpl in templates:
            for ref in tpl.block_refs:
                if "{genre}" in ref:
                    continue  # Dynamic ref, resolved at build time
                block = seeded_registry.get_active_block(ref)
                assert block is not None, (
                    f"Template {tpl.template_id} references block '{ref}' which does not exist"
                )


class TestSeedBuildPrompt:
    def test_build_with_seeded_wuxia(self, seeded_registry):
        prompt = seeded_registry.build_prompt("writer", "default", "wuxia_classical")
        assert "古典武侠" in prompt
        assert "通用写作技法" in prompt

    def test_build_with_seeded_battle_scifi(self, seeded_registry):
        prompt = seeded_registry.build_prompt("writer", "battle", "scifi_hardscifi")
        assert "战斗场景" in prompt
        assert "刘慈欣" in prompt

    def test_build_with_feedback_injection(self, seeded_registry):
        context = {
            "last_strengths": ["节奏紧凑"],
            "last_weaknesses": ["对话太生硬"],
        }
        prompt = seeded_registry.build_prompt("writer", "default", "wuxia_classical", context=context)
        assert "节奏紧凑" in prompt
        assert "对话太生硬" in prompt

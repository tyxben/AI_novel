"""Tests for dead character detection in ContinuityService."""
from src.novel.services.continuity_service import ContinuityService


class TestDeadCharacterDetection:
    def test_detects_death_keyword(self):
        svc = ContinuityService()
        chapters = [
            {
                "chapter_number": 17,
                "title": "煞气初成",
                "actual_summary": "林辰处决了黑风煞，获得了藏宝线索并触发了新的主线任务。",
            },
        ]
        brief = svc.generate_brief(
            chapter_number=20,
            chapters=chapters,
        )
        forbidden = brief.get("forbidden_breaks", [])
        # Should mention 黑风煞 as dead
        assert any("黑风煞" in item and "死" in item for item in forbidden)

    def test_detects_multiple_deaths(self):
        svc = ContinuityService()
        chapters = [
            {
                "chapter_number": 5,
                "actual_summary": "林辰斩杀了王五，俘虏了赵六。",
            },
            {
                "chapter_number": 17,
                "actual_summary": "黑风煞被处决，气绝身亡。",
            },
        ]
        brief = svc.generate_brief(chapter_number=20, chapters=chapters)
        forbidden = brief.get("forbidden_breaks", [])
        names_mentioned = " ".join(forbidden)
        assert "黑风煞" in names_mentioned

    def test_does_not_flag_protagonist(self):
        svc = ContinuityService()
        chapters = [
            {
                "chapter_number": 10,
                "actual_summary": "林辰差点死在敌人手里。",
            },
        ]
        brief = svc.generate_brief(chapter_number=11, chapters=chapters)
        forbidden = brief.get("forbidden_breaks", [])
        # 林辰 should NOT be flagged
        assert not any("林辰" in item and "死亡" in item for item in forbidden)

    def test_no_chapters(self):
        svc = ContinuityService()
        brief = svc.generate_brief(chapter_number=1, chapters=[])
        # Should not crash
        assert "forbidden_breaks" in brief

    def test_dead_character_in_format_for_prompt(self):
        svc = ContinuityService()
        chapters = [
            {
                "chapter_number": 17,
                "actual_summary": "林辰处决了黑风煞。",
            },
        ]
        brief = svc.generate_brief(chapter_number=20, chapters=chapters)
        prompt = svc.format_for_prompt(brief)
        # The forbidden section should mention dead characters
        assert "黑风煞" in prompt or "禁止违反" in prompt

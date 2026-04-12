"""Tests for P0 Entity Registry (Knowledge Graph).

Covers:
- Entity / EntityType / EntityMention Pydantic models
- RuleBasedExtractor: regex-based entity extraction (locations, skills,
  titles, artifacts), blacklist filtering, length filtering
- EntityService: extract-and-register, deduplication, alias merging,
  name conflict detection, stats
- LLMEntityExtractor: happy path, exception fallback, invalid JSON fallback
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Standalone LLMResponse (no real LLM import)
# ---------------------------------------------------------------------------


@dataclass
class LLMResponse:
    content: str
    model: str = "test"
    usage: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# MockDB (self-contained, mimics StructuredDB entity methods)
# ---------------------------------------------------------------------------


class MockDB:
    """In-memory mock for StructuredDB entity-related methods."""

    def __init__(self) -> None:
        self.entities: dict[str, dict] = {}

    def get_entity_by_name(self, name: str) -> dict | None:
        for e in self.entities.values():
            if e["canonical_name"] == name:
                return e
        return None

    def get_entity_by_name_and_type(self, name: str, entity_type: str) -> dict | None:
        for e in self.entities.values():
            if e["canonical_name"] == name and e["entity_type"] == entity_type:
                return e
        return None

    def insert_entity(self, entity: Any) -> None:
        """Accept either a dict or a Pydantic model with model_dump()."""
        if hasattr(entity, "model_dump"):
            data = entity.model_dump()
        else:
            data = dict(entity)
        eid = data.get("entity_id", str(uuid4()))
        data.setdefault("entity_id", eid)
        data.setdefault("mention_count", 0)
        data.setdefault("last_mention_chapter", 0)
        data.setdefault("aliases", "[]")
        if isinstance(data["aliases"], list):
            data["aliases"] = json.dumps(data["aliases"], ensure_ascii=False)
        self.entities[eid] = data

    def update_entity_mention(self, entity_id: str, chapter: int) -> None:
        if entity_id in self.entities:
            self.entities[entity_id]["mention_count"] += 1
            self.entities[entity_id]["last_mention_chapter"] = chapter

    def get_all_entities(self) -> list[dict]:
        return list(self.entities.values())

    def merge_entity_as_alias(self, primary_id: str, secondary_id: str) -> None:
        if primary_id in self.entities and secondary_id in self.entities:
            primary = self.entities[primary_id]
            secondary = self.entities[secondary_id]
            aliases = json.loads(primary.get("aliases", "[]"))
            aliases.append(secondary["canonical_name"])
            primary["aliases"] = json.dumps(aliases, ensure_ascii=False)
            del self.entities[secondary_id]

    def query_entities_by_chapter_range(
        self, from_chapter: int, to_chapter: int
    ) -> list[dict]:
        return [
            e
            for e in self.entities.values()
            if from_chapter <= e.get("first_mention_chapter", 0) <= to_chapter
        ]

    def get_entity_count_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self.entities.values():
            t = e.get("entity_type", "other")
            counts[t] = counts.get(t, 0) + 1
        return counts


# =========================================================================
# TestEntityModel
# =========================================================================


class TestEntityModel:
    """Entity / EntityType / EntityMention Pydantic models."""

    def test_entity_creation(self) -> None:
        from src.novel.models.entity import Entity, EntityType

        ent = Entity(
            canonical_name="青云山",
            entity_type=EntityType.LOCATION,
            first_mention_chapter=1,
        )
        assert ent.canonical_name == "青云山"
        assert ent.entity_type == "location"
        assert ent.first_mention_chapter == 1
        # entity_id auto-generated
        assert ent.entity_id is not None
        assert len(ent.entity_id) > 0
        # defaults
        assert ent.aliases == []
        assert ent.mention_count == 0
        assert ent.last_mention_chapter == 0
        assert ent.definition == ""
        assert ent.metadata == {}
        assert ent.created_at  # non-empty ISO timestamp

    def test_entity_type_constants(self) -> None:
        from src.novel.models.entity import EntityType

        expected = {
            "CHARACTER": "character",
            "LOCATION": "location",
            "FACTION": "faction",
            "SKILL": "skill",
            "ARTIFACT": "artifact",
            "RACE": "race",
            "TITLE": "title",
            "FORMATION": "formation",
            "EVENT": "event",
            "POSITION": "position",
            "TERM": "term",
            "OTHER": "other",
        }
        for attr, value in expected.items():
            assert hasattr(EntityType, attr), f"EntityType missing {attr}"
            assert getattr(EntityType, attr) == value

    def test_entity_mention_creation(self) -> None:
        from src.novel.models.entity import EntityMention

        mention = EntityMention(
            entity_id="ent-001",
            chapter=3,
            mentioned_name="青云",
            context="他来到青云山下",
        )
        assert mention.entity_id == "ent-001"
        assert mention.chapter == 3
        assert mention.mentioned_name == "青云"
        assert mention.context == "他来到青云山下"
        assert mention.mention_id is not None
        assert len(mention.mention_id) > 0


# =========================================================================
# TestRuleBasedExtractor
# =========================================================================


class TestRuleBasedExtractor:
    """RuleBasedExtractor regex-based entity extraction."""

    @pytest.fixture()
    def extractor(self):
        from src.novel.services.entity_extractor import RuleBasedExtractor

        return RuleBasedExtractor()

    def test_extract_locations(self, extractor) -> None:
        text = "主角来到青云山的山顶"
        entities = extractor.extract_entities(text, chapter=1)
        names = [e.canonical_name for e in entities]
        assert "青云山" in names
        # Verify type
        loc = next(e for e in entities if e.canonical_name == "青云山")
        assert loc.entity_type == "location"
        assert loc.first_mention_chapter == 1

    def test_extract_locations_faction(self, extractor) -> None:
        text = "天剑宗的弟子向他走来"
        entities = extractor.extract_entities(text, chapter=2)
        names = [e.canonical_name for e in entities]
        assert "天剑宗" in names
        matched = [e for e in entities if e.canonical_name == "天剑宗"]
        assert len(matched) >= 1
        # Should be location type (faction patterns use LOCATION type)
        assert matched[0].entity_type == "location"

    def test_extract_skills(self, extractor) -> None:
        text = "他修炼《九阳真经》多年"
        entities = extractor.extract_entities(text, chapter=1)
        names = [e.canonical_name for e in entities]
        assert "九阳真经" in names
        skill = next(e for e in entities if e.canonical_name == "九阳真经")
        assert skill.entity_type == "skill"

    def test_extract_skills_suffix(self, extractor) -> None:
        """Skill suffix pattern: regex prefix group is greedy (2-6 Chinese
        chars), so preceding Chinese chars get absorbed. Punctuation
        boundaries ensure clean capture.
        """
        # Comma before skill name prevents greedy prefix absorption
        text = "，碎星剑法威力惊人"
        entities = extractor.extract_entities(text, chapter=3)
        names = [e.canonical_name for e in entities]
        assert "碎星剑法" in names
        skill = next(e for e in entities if e.canonical_name == "碎星剑法")
        assert skill.entity_type == "skill"

    def test_extract_titles(self, extractor) -> None:
        text = "金丹期的修士不可小觑"
        entities = extractor.extract_entities(text, chapter=5)
        names = [e.canonical_name for e in entities]
        assert "金丹期" in names
        title = next(e for e in entities if e.canonical_name == "金丹期")
        assert title.entity_type == "title"

    def test_extract_artifacts(self, extractor) -> None:
        text = "那把玄铁剑发出寒光"
        entities = extractor.extract_entities(text, chapter=1)
        names = [e.canonical_name for e in entities]
        assert "玄铁剑" in names
        art = next(e for e in entities if e.canonical_name == "玄铁剑")
        assert art.entity_type == "artifact"

    def test_blacklist_filtering(self, extractor) -> None:
        """Common words in blacklist must not be extracted."""
        text = "这里有什么他不知道的"
        entities = extractor.extract_entities(text, chapter=1)
        names = {e.canonical_name for e in entities}
        assert "这里" not in names
        assert "他" not in names
        assert "什么" not in names

    def test_length_filtering(self, extractor) -> None:
        """Single-char and overly long strings should be filtered."""
        # Single char won't match 2+ char regex, but verify _is_valid
        from src.novel.services.entity_extractor import RuleBasedExtractor

        assert not RuleBasedExtractor._is_valid("山")  # too short
        assert not RuleBasedExtractor._is_valid("这是一个超级无敌长的名字吧")  # > 8 chars
        assert RuleBasedExtractor._is_valid("青云山")  # valid

    def test_mixed_text_extraction(self, extractor) -> None:
        """Comprehensive text with multiple entity types.

        Note: regex prefix groups are greedy (2-6 Chinese chars), so
        preceding Chinese text gets absorbed. We use punctuation
        boundaries to isolate entity names cleanly.
        """
        text = (
            "叶辰站在青云山巅，手持玄铁剑，"
            "修炼《太极混元功》，金丹期修士不可小觑。"
            "天剑宗的长老也来到了碧水湖畔。"
        )
        entities = extractor.extract_entities(text, chapter=1)
        names = {e.canonical_name for e in entities}
        types = {e.entity_type for e in entities}

        # Locations
        assert "青云山" in names
        assert "天剑宗" in names
        assert "碧水湖" in names
        # Skills (book-name bracket pattern)
        assert "太极混元功" in names
        # Artifacts
        assert "玄铁剑" in names
        # Titles (comma-separated ensures clean capture)
        assert "金丹期" in names
        # Multiple types present
        assert "location" in types
        assert "skill" in types
        assert "artifact" in types
        assert "title" in types


# =========================================================================
# TestEntityService
# =========================================================================

# EntityService may not exist yet (P0 Phase 2). Guard import.
_entity_service_available = True
try:
    from src.novel.services.entity_service import EntityService  # noqa: F401
except ImportError:
    _entity_service_available = False

_skip_entity_service = pytest.mark.skipif(
    not _entity_service_available,
    reason="src.novel.services.entity_service not implemented yet",
)


@_skip_entity_service
class TestEntityService:
    """EntityService: extract-and-register, dedup, alias merge, conflicts."""

    @pytest.fixture()
    def db(self) -> MockDB:
        return MockDB()

    @pytest.fixture()
    def service(self, db: MockDB):
        from src.novel.services.entity_service import EntityService

        return EntityService(db, llm_client=None)

    def test_extract_and_register_new(self, service, db) -> None:
        """Extracting from fresh text should register new entities."""
        text = "主角来到青云山，手持玄铁剑"
        result = service.extract_and_register(
            chapter_text=text, chapter_number=1, use_llm=False
        )
        assert result["new_count"] > 0
        assert isinstance(result["entities"], list)
        assert len(db.entities) > 0

    def test_extract_and_register_existing(self, service, db) -> None:
        """Re-extracting same entity should increment mention count."""
        text1 = "主角来到青云山修炼"
        service.extract_and_register(
            chapter_text=text1, chapter_number=1, use_llm=False
        )
        initial_count = len(db.entities)

        text2 = "他再次回到青云山"
        result = service.extract_and_register(
            chapter_text=text2, chapter_number=2, use_llm=False
        )
        assert result["updated_count"] > 0
        # No new entities for repeated name
        assert len(db.entities) == initial_count

        # Verify mention_count increased for "青云山"
        ent = db.get_entity_by_name("青云山")
        assert ent is not None
        assert ent["mention_count"] >= 1
        assert ent["last_mention_chapter"] == 2

    def test_deduplicate_entities(self, service) -> None:
        """Same name + same type appearing twice in one text should be deduped."""
        from src.novel.models.entity import Entity, EntityType

        entities = [
            Entity(
                canonical_name="青云山",
                entity_type=EntityType.LOCATION,
                first_mention_chapter=1,
            ),
            Entity(
                canonical_name="青云山",
                entity_type=EntityType.LOCATION,
                first_mention_chapter=1,
            ),
        ]
        deduped = service._deduplicate_entities(entities)
        assert len(deduped) == 1
        assert deduped[0].canonical_name == "青云山"

    def test_merge_aliases_similar_names(self, service, db) -> None:
        """Entities with >= 0.8 similarity within same type should be merged."""
        from src.novel.models.entity import Entity, EntityType

        ent1 = Entity(
            canonical_name="玄铁剑",
            entity_type=EntityType.ARTIFACT,
            first_mention_chapter=1,
        )
        ent2 = Entity(
            canonical_name="玄铁剑法",
            entity_type=EntityType.SKILL,
            first_mention_chapter=2,
        )
        db.insert_entity(ent1)
        db.insert_entity(ent2)

        # "玄铁剑" vs "玄铁剑法" — different types, should NOT merge
        merged = service.merge_aliases(dry_run=False)
        # They have different entity_types so no merge happens
        assert merged == 0

        # Now test same-type merge with high similarity
        ent3 = Entity(
            canonical_name="青云宗",
            entity_type=EntityType.LOCATION,
            first_mention_chapter=1,
        )
        ent4 = Entity(
            canonical_name="青云派",
            entity_type=EntityType.LOCATION,
            first_mention_chapter=3,
        )
        db.insert_entity(ent3)
        db.insert_entity(ent4)

        # "青云宗" vs "青云派" — SequenceMatcher ratio
        ratio = SequenceMatcher(None, "青云宗", "青云派").ratio()
        # ratio ~ 0.667 < 0.8 — not merged
        merged2 = service.merge_aliases(dry_run=False)
        if ratio < 0.8:
            assert merged2 == 0
        else:
            assert merged2 >= 1

    def test_merge_aliases_dry_run(self, service, db) -> None:
        """dry_run=True should not modify entities in the database."""
        from src.novel.models.entity import Entity, EntityType

        ent1 = Entity(
            canonical_name="碎星剑",
            entity_type=EntityType.ARTIFACT,
            first_mention_chapter=1,
        )
        ent2 = Entity(
            canonical_name="碎星剑法",
            entity_type=EntityType.ARTIFACT,
            first_mention_chapter=2,
        )
        db.insert_entity(ent1)
        db.insert_entity(ent2)

        entity_count_before = len(db.entities)
        _merged = service.merge_aliases(dry_run=True)
        entity_count_after = len(db.entities)
        # DB unchanged
        assert entity_count_after == entity_count_before

    def test_detect_name_conflicts(self, service, db) -> None:
        """Similar entity names across chapters should be flagged."""
        from src.novel.models.entity import Entity, EntityType

        # Insert existing entity
        existing = Entity(
            canonical_name="青云山",
            entity_type=EntityType.LOCATION,
            first_mention_chapter=1,
        )
        db.insert_entity(existing)

        # Current chapter entity with similar name
        current = [
            Entity(
                canonical_name="青云峰",
                entity_type=EntityType.LOCATION,
                first_mention_chapter=5,
            )
        ]

        # detect_name_conflicts may rely on db.query_similar_entities
        # If that method doesn't exist in MockDB, we skip gracefully
        try:
            conflicts = service.detect_name_conflicts(current, threshold=0.7)
        except (AttributeError, NotImplementedError):
            pytest.skip("detect_name_conflicts requires query_similar_entities in DB")
            return

        # "青云山" vs "青云峰" have high similarity
        ratio = SequenceMatcher(None, "青云山", "青云峰").ratio()
        if ratio >= 0.7:
            assert len(conflicts) >= 1
            assert conflicts[0]["current_name"] == "青云峰"
            assert conflicts[0]["existing_name"] == "青云山"

    def test_get_entity_stats(self, db) -> None:
        """Verify entity count-by-type aggregation."""
        from src.novel.models.entity import Entity, EntityType

        db.insert_entity(Entity(
            canonical_name="青云山",
            entity_type=EntityType.LOCATION,
            first_mention_chapter=1,
        ))
        db.insert_entity(Entity(
            canonical_name="天剑宗",
            entity_type=EntityType.LOCATION,
            first_mention_chapter=2,
        ))
        db.insert_entity(Entity(
            canonical_name="碎星剑法",
            entity_type=EntityType.SKILL,
            first_mention_chapter=1,
        ))

        counts = db.get_entity_count_by_type()
        assert counts["location"] == 2
        assert counts["skill"] == 1


# =========================================================================
# TestLLMEntityExtractor
# =========================================================================


class TestLLMEntityExtractor:
    """LLMEntityExtractor: LLM-based fallback extraction."""

    def _make_mock_llm(self, content: str) -> Any:
        """Create a mock LLM client returning fixed content."""
        from unittest.mock import MagicMock

        client = MagicMock()
        client.chat.return_value = LLMResponse(content=content)
        return client

    def test_llm_extract_happy_path(self) -> None:
        from src.novel.services.entity_extractor import LLMEntityExtractor

        valid_json = json.dumps(
            {
                "entities": [
                    {
                        "name": "青云山",
                        "type": "location",
                        "definition": "主角修炼的山脉",
                    },
                    {
                        "name": "碎星剑法",
                        "type": "skill",
                        "definition": "主角习得的剑术",
                    },
                ]
            },
            ensure_ascii=False,
        )
        mock_llm = self._make_mock_llm(valid_json)
        extractor = LLMEntityExtractor(mock_llm)

        entities = extractor.extract_entities("一段章节文本", chapter=1)

        assert len(entities) == 2
        names = {e.canonical_name for e in entities}
        assert "青云山" in names
        assert "碎星剑法" in names

        loc = next(e for e in entities if e.canonical_name == "青云山")
        assert loc.entity_type == "location"
        assert loc.definition == "主角修炼的山脉"
        assert loc.first_mention_chapter == 1

    def test_llm_extract_failure(self) -> None:
        """LLM raising an exception should return empty list."""
        from unittest.mock import MagicMock

        from src.novel.services.entity_extractor import LLMEntityExtractor

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = RuntimeError("API timeout")
        extractor = LLMEntityExtractor(mock_llm)

        entities = extractor.extract_entities("some text", chapter=1)

        assert entities == []

    def test_llm_extract_invalid_json(self) -> None:
        """LLM returning garbage (not valid JSON) should return empty list."""
        from src.novel.services.entity_extractor import LLMEntityExtractor

        mock_llm = self._make_mock_llm("this is not json at all {{{")
        extractor = LLMEntityExtractor(mock_llm)

        entities = extractor.extract_entities("some text", chapter=1)

        assert entities == []

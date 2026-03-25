# Narrative Control Layer - Task List

## Overview

This task list covers **Phase 1** implementation: StoryUnit, ChapterDebt, and BriefValidator. Tasks are organized by dependency order and grouped by component. Each task includes file paths, estimated complexity, and acceptance criteria.

**Complexity Scale**:
- **S** (Small): 1-2 hours, < 100 lines
- **M** (Medium): 2-4 hours, 100-300 lines
- **L** (Large): 4-8 hours, 300-500 lines
- **XL** (Extra Large): 8+ hours, > 500 lines

---

## Phase 1: Foundation (Target: 1-2 Weeks)

### 1. Data Models

- [x] **1.1** Create StoryUnit and ArcBrief models
  **File**: `/Users/ty/self/AI_novel/src/novel/models/story_unit.py`
  **Complexity**: M
  **Details**:
  - Define `StoryUnit` Pydantic model with fields: arc_id, volume_id, name, chapters, phase, hook, escalation_point, turning_point, closure_method, residual_question, status, completion_rate
  - Define `ArcBrief` model with central_conflict, protagonist_goal, antagonist_goal, success_consequence, failure_consequence, setup_beats, escalation_beats, climax_description, resolution_outcome
  - Add field validation (chapters length 3-7, phase enum, completion_rate 0.0-1.0)
  - Add `__repr__` and `__str__` methods for debugging

  **Acceptance**:
  - [ ] Models pass Pydantic validation for valid data
  - [ ] Invalid data raises ValidationError with clear message
  - [ ] Models serialize/deserialize to/from JSON

- [x] **1.2** Create ChapterDebt and related models
  **File**: `/Users/ty/self/AI_novel/src/novel/models/debt.py`
  **Complexity**: M
  **Details**:
  - Define `ChapterDebt` with debt_id, source_chapter, created_at, type, description, character_pending_actions, emotional_debt, target_chapter, status, fulfilled_at, fulfillment_note, urgency_level, escalation_history
  - Define `DebtExtractionResult` with chapter_number, debts, extraction_method, confidence
  - Define `DebtContext` with chapter_number, pending_debts, overdue_debts, critical_debts, formatted_summary, token_count
  - Add type enums and validators

  **Acceptance**:
  - [ ] All models pass validation tests
  - [ ] Enum fields enforce valid values
  - [ ] Timestamps use ISO format

- [x] **1.3** Create validation models
  **File**: `/Users/ty/self/AI_novel/src/novel/models/validation.py`
  **Complexity**: S
  **Details**:
  - Define `BriefItemResult` with item_name, expected, fulfilled, evidence, reason
  - Define `BriefFulfillmentReport` with chapter_number, main_conflict_fulfilled, payoff_delivered, character_arc_step_taken, foreshadowing_planted, foreshadowing_collected, end_hook_present, item_results, unfulfilled_items, overall_pass, pass_rate, suggested_debts
  - Add computed property for pass_rate if not provided

  **Acceptance**:
  - [ ] Models serialize correctly
  - [ ] pass_rate calculates correctly (passed/total)
  - [ ] suggested_debts defaults to empty list

- [x] **1.4** Update ChapterOutline model
  **File**: `/Users/ty/self/AI_novel/src/novel/models/novel.py`
  **Complexity**: S
  **Details**:
  - Add `arc_id: str | None = Field(None, description="Parent story arc ID")` to ChapterOutline
  - Ensure backwards compatibility (None is valid)

  **Acceptance**:
  - [ ] Existing tests pass without modification
  - [ ] New field accessible in ChapterOutline instances
  - [ ] Field serializes to JSON

- [x] **1.5** Update Volume model
  **File**: `/Users/ty/self/AI_novel/src/novel/models/novel.py`
  **Complexity**: S
  **Details**:
  - Add `story_units: list[StoryUnit] = Field(default_factory=list)` to Volume
  - Import StoryUnit from story_unit module

  **Acceptance**:
  - [ ] Volume can hold list of StoryUnit objects
  - [ ] Empty list is valid default
  - [ ] Serialization includes story_units

### 2. Storage Layer

- [x] **2.1** Add chapter_debts table to StructuredDB
  **File**: `/Users/ty/self/AI_novel/src/novel/storage/structured_db.py`
  **Complexity**: M
  **Details**:
  - Add `_ensure_chapter_debts_table()` method with SQL CREATE TABLE
  - Add indexes on status, source_chapter, urgency_level
  - Call from `__init__` to ensure table exists
  - Add `insert_debt(debt: ChapterDebt)` method
  - Add `update_debt_status(debt_id, status, fulfilled_at, note)` method
  - Add `query_debts(status=None, source_chapter=None)` method

  **Acceptance**:
  - [ ] Table created on first run
  - [ ] Indexes created correctly
  - [ ] insert_debt stores all fields correctly
  - [ ] query_debts filters by status and source_chapter

- [x] **2.2** Add story_units table to StructuredDB
  **File**: `/Users/ty/self/AI_novel/src/novel/storage/structured_db.py`
  **Complexity**: M
  **Details**:
  - Add `_ensure_story_units_table()` method
  - Add indexes on volume_id, status
  - Add `insert_story_unit(unit: StoryUnit)` method
  - Add `update_story_unit_progress(arc_id, completion_rate, phase)` method
  - Add `query_story_units(volume_id=None)` method

  **Acceptance**:
  - [ ] Table created with correct schema
  - [ ] JSON serialization of chapters array works
  - [ ] insert_story_unit stores all fields
  - [ ] query_story_units retrieves full StoryUnit objects

- [x] **2.3** Extend FileManager for narrative control exports
  **File**: `/Users/ty/self/AI_novel/src/novel/storage/file_manager.py`
  **Complexity**: S
  **Details**:
  - Add `export_debts_json(project_path)` method
  - Add `export_arcs_json(project_path)` method
  - Add `export_validation_reports_json(project_path)` method
  - Each exports to `project_path/debts.json`, `arcs.json`, `validation_reports.json`

  **Acceptance**:
  - [ ] JSON files created with correct structure
  - [ ] Files are human-readable and valid JSON
  - [ ] Exports include all relevant data

### 3. Service Layer

- [x] **3.1** Implement ObligationTracker service
  **File**: `/Users/ty/self/AI_novel/src/novel/services/obligation_tracker.py`
  **Complexity**: L
  **Details**:
  - Create `ObligationTracker` class with `__init__(db: StructuredDB)`
  - Implement `add_debt(debt: ChapterDebt)` - Insert into DB
  - Implement `get_debts_for_chapter(chapter_num: int) -> list[ChapterDebt]` - Query pending/overdue debts before chapter_num
  - Implement `mark_debt_fulfilled(debt_id: str, chapter_num: int, note: str | None)` - Update status to fulfilled
  - Implement `escalate_debts(current_chapter: int) -> int` - Find overdue debts, escalate urgency, update status, return count
  - Implement `get_summary_for_writer(chapter_num: int, max_tokens: int = 1000) -> str` - Format debts into prompt-ready text
  - Implement `get_debt_statistics() -> dict` - Return counts by status, avg fulfillment time
  - Add logging for all operations

  **Acceptance**:
  - [ ] add_debt stores debt in DB
  - [ ] get_debts_for_chapter returns only pending/overdue before chapter
  - [ ] mark_debt_fulfilled updates status and fulfilled_at
  - [ ] escalate_debts correctly identifies overdue debts (must_pay_next after 1ch, pay_within_3 after 3ch)
  - [ ] escalate_debts updates urgency_level and status
  - [ ] get_summary_for_writer produces formatted text under max_tokens
  - [ ] get_debt_statistics returns correct counts

- [x] **3.2** Implement DebtExtractor service
  **File**: `/Users/ty/self/AI_novel/src/novel/services/debt_extractor.py`
  **Complexity**: L
  **Details**:
  - Create `DebtExtractor` class with `__init__(llm_client: LLMClient | None)`
  - Implement `extract_from_chapter(chapter_text, chapter_number, method) -> DebtExtractionResult`
  - Implement `_extract_rule_based(chapter_text, chapter_number)` - Use regex patterns for promises, tension, actions
  - Implement `_extract_llm(chapter_text, chapter_number)` - Use LLM with extraction prompt
  - Implement `_is_similar_debt(debt1, debt2) -> bool` - Check description overlap
  - Implement `_deduplicate_debts(debts) -> list[ChapterDebt]` - Remove duplicates
  - Define regex patterns for promises, tension, actions
  - Define LLM prompts (_EXTRACTION_SYSTEM, _EXTRACTION_USER)
  - Add error handling for LLM failures

  **Acceptance**:
  - [ ] rule_based extraction finds explicit promises with regex
  - [ ] llm extraction calls LLM and parses JSON response
  - [ ] hybrid method combines both without duplicates
  - [ ] _is_similar_debt detects overlapping descriptions
  - [ ] _deduplicate_debts removes similar debts
  - [ ] Graceful fallback when LLM unavailable

### 4. Tools Layer

- [x] **4.1** Implement BriefValidator tool
  **File**: `/Users/ty/self/AI_novel/src/novel/tools/brief_validator.py`
  **Complexity**: L
  **Details**:
  - Create `BriefValidator` class with `__init__(llm_client: LLMClient)`
  - Implement `validate_chapter(chapter_text, chapter_brief) -> BriefFulfillmentReport`
  - Format chapter_brief dict into readable bullet points
  - Truncate chapter_text to first 3000 chars if too long
  - Call LLM with validation prompt (_VALIDATION_SYSTEM, _VALIDATION_USER)
  - Parse JSON response into BriefFulfillmentReport
  - Calculate pass_rate from item_results
  - Generate suggested_debts for unfulfilled mandatory items
  - Handle empty chapter_brief gracefully (return overall_pass=True)
  - Add error handling and logging

  **Acceptance**:
  - [x] validate_chapter returns BriefFulfillmentReport
  - [x] Empty brief returns pass=True without LLM call
  - [x] LLM response parsed correctly
  - [x] pass_rate calculated correctly
  - [x] suggested_debts populated for unfulfilled items
  - [x] Error handling returns permissive default

### 5. Agent Integration

- [x] **5.1** Add arc generation to NovelDirector
  **File**: `/Users/ty/self/AI_novel/src/novel/agents/novel_director.py`
  **Complexity**: XL
  **Details**:
  - Add `generate_story_arcs(volume_outline: VolumeOutline, genre: str) -> list[StoryUnit]` method
  - Determine arc count based on chapter count (2 arcs for <=10ch, 3 for <=20ch, 5 for <=35ch, 6 for >35ch)
  - Distribute chapters across arcs (3-7 per arc, distribute remainder)
  - Implement `_generate_single_arc(volume_outline, arc_chapters, arc_number, genre) -> StoryUnit` - LLM call
  - Define prompt for arc generation (_ARC_GENERATION_SYSTEM, _ARC_GENERATION_USER)
  - Extract JSON response into StoryUnit object
  - Set escalation_point (typically 60-70% through arc)
  - Set turning_point (typically 70-80% through arc)
  - Add arc_id to each ChapterOutline in the arc
  - Update `create_volume_outline()` to call `generate_story_arcs()` if enabled

  **Acceptance**:
  - [x] generate_story_arcs creates correct number of arcs
  - [x] Each arc has 3-7 chapters
  - [x] All volume chapters assigned to exactly one arc
  - [x] escalation_point and turning_point set correctly
  - [x] ChapterOutline.arc_id linked to parent arc
  - [x] LLM prompt generates valid StoryUnit data

- [x] **5.2** Add debt context injection to Writer
  **File**: `/Users/ty/self/AI_novel/src/novel/agents/writer.py`
  **Complexity**: M
  **Details**:
  - Add `obligation_tracker: ObligationTracker | None = None` parameter to `generate_chapter()` and `write_scene()`
  - Before generating chapter, call `obligation_tracker.get_summary_for_writer(chapter_num)`
  - Inject debt summary into system prompt or user message (in dedicated section)
  - Ensure injection happens before all scene generation
  - Add logging when debts injected
  - Handle None tracker gracefully (no injection)

  **Acceptance**:
  - [x] Debt summary appears in LLM context
  - [x] Critical debts appear in system prompt
  - [x] No debt tracker → no injection, no errors
  - [x] Logging confirms debt injection

- [x] **5.3** Add brief validation to QualityReviewer
  **File**: `/Users/ty/self/AI_novel/src/novel/agents/quality_reviewer.py`
  **Complexity**: L
  **Details**:
  - Add `chapter_brief: dict | None`, `brief_validator: BriefValidator | None`, `debt_extractor: DebtExtractor | None`, `obligation_tracker: ObligationTracker | None`, `chapter_number: int = 0` parameters to `review_chapter()`
  - After existing quality checks, call `brief_validator.validate_chapter(chapter_text, chapter_brief)` if validator present
  - Store result in `report["brief_fulfillment"]`
  - If `overall_pass=False`, create ChapterDebt for each unfulfilled item via `obligation_tracker.add_debt()`
  - Call `debt_extractor.extract_from_chapter(chapter_text, chapter_number, method="hybrid")` if extractor present
  - Add all extracted debts via `obligation_tracker.add_debt()`
  - Store `report["debts_extracted"] = len(extraction_result.debts)`
  - Add logging for brief validation and debt extraction

  **Acceptance**:
  - [x] Brief validation runs after quality checks
  - [x] Validation result stored in report
  - [x] Unfulfilled brief items create debts
  - [x] Debt extraction runs automatically
  - [x] All debts stored in tracker
  - [x] Graceful handling when services None

- [x] **5.4** Update QualityReviewer LangGraph node
  **File**: `/Users/ty/self/AI_novel/src/novel/agents/quality_reviewer.py`
  **Complexity**: M
  **Details**:
  - Modify `quality_reviewer_node(state)` to extract services from state
  - Extract `state.get("obligation_tracker")`, `state.get("brief_validator")`, `state.get("debt_extractor")`
  - Extract `state.get("current_chapter_brief")` and `state.get("current_chapter", 1)`
  - Pass all to `reviewer.review_chapter()`
  - Handle None services gracefully

  **Acceptance**:
  - [x] Node extracts services from state
  - [x] Services passed to review_chapter
  - [x] Node works without services (backwards compatible)

### 6. Pipeline Integration

- [x] **6.1** Update NovelPipeline to initialize narrative control
  **File**: `/Users/ty/self/AI_novel/src/novel/pipeline.py`
  **Complexity**: M
  **Details**:
  - In `generate_chapters()`, after loading memory and LLM:
    - Import ObligationTracker, DebtExtractor, BriefValidator
    - Initialize `obligation_tracker = ObligationTracker(self.memory.structured_db)`
    - Initialize `debt_extractor = DebtExtractor(llm_client)`
    - Initialize `brief_validator = BriefValidator(llm_client)`
  - Before each chapter generation, call `obligation_tracker.escalate_debts(chapter_num)`
  - Add services to chapter generation state:
    - `state["obligation_tracker"] = obligation_tracker`
    - `state["brief_validator"] = brief_validator`
    - `state["debt_extractor"] = debt_extractor`
  - After all chapters in volume, call `_generate_volume_settlement()` (stub for Phase 2)
  - Return debt statistics in result dict

  **Acceptance**:
  - [ ] Services initialized correctly
  - [ ] escalate_debts called before each chapter
  - [ ] Services available in state
  - [ ] Debt statistics returned in result
  - [ ] Pipeline works without breaking existing behavior

- [x] **6.2** Update create_novel to generate story arcs
  **File**: `/Users/ty/self/AI_novel/src/novel/pipeline.py`
  **Complexity**: M
  **Details**:
  - In `create_novel()`, after NovelDirector generates volume outlines:
    - For each volume, call `director.generate_story_arcs(volume_outline, genre)`
    - Store arcs in `volume.story_units`
    - Update ChapterOutline.arc_id for each chapter
    - Save arcs to StructuredDB via `self.memory.structured_db.insert_story_unit(arc)`
  - Add logging for arc generation
  - Make arc generation optional via config flag (default True)

  **Acceptance**:
  - [ ] Arcs generated for each volume
  - [ ] Arcs stored in Volume.story_units
  - [ ] ChapterOutline.arc_id set correctly
  - [ ] Arcs persisted to DB
  - [ ] Optional via config

- [x] **6.3** Add chapter_brief to state
  **File**: `/Users/ty/self/AI_novel/src/novel/pipeline.py`
  **Complexity**: S
  **Details**:
  - In `generate_chapters()`, when preparing state for chapter graph:
    - Extract `chapter_brief = chapter_outline.chapter_brief`
    - Add to state: `state["current_chapter_brief"] = chapter_brief`
  - Ensure chapter_brief dict available to QualityReviewer node

  **Acceptance**:
  - [ ] chapter_brief extracted from outline
  - [ ] Added to state
  - [ ] Available in QualityReviewer node

### 7. Testing

- [x] **7.1** Unit tests for ObligationTracker
  **File**: `/Users/ty/self/AI_novel/tests/novel/test_obligation_tracker.py`
  **Complexity**: L
  **Details**:
  - `test_add_debt()` - Verify debt stored in DB
  - `test_get_debts_for_chapter()` - Verify only pending/overdue before chapter returned
  - `test_mark_debt_fulfilled()` - Verify status updated
  - `test_escalate_debts_must_pay_next()` - Verify must_pay_next escalates after 1ch
  - `test_escalate_debts_pay_within_3()` - Verify pay_within_3 escalates after 3ch
  - `test_escalate_debts_no_escalation()` - Verify no escalation if within window
  - `test_get_summary_for_writer()` - Verify formatted summary generated
  - `test_get_summary_for_writer_truncate()` - Verify truncation at max_tokens
  - `test_get_debt_statistics()` - Verify counts correct
  - Use in-memory SQLite DB for tests
  - Mock LLM client not needed (no LLM calls)

  **Acceptance**:
  - [ ] All tests pass
  - [ ] Edge cases covered (empty debts, all overdue, etc.)
  - [ ] Tests use isolated DB

- [x] **7.2** Unit tests for DebtExtractor
  **File**: `/Users/ty/self/AI_novel/tests/novel/services/test_debt_extractor.py`
  **Complexity**: L
  **Details**:
  - `test_extract_rule_based_promises()` - Verify regex finds promises
  - `test_extract_rule_based_tension()` - Verify regex finds tension patterns
  - `test_extract_rule_based_actions()` - Verify regex finds interrupted actions
  - `test_extract_llm()` - Mock LLM, verify JSON parsing
  - `test_extract_hybrid()` - Verify combination without duplicates
  - `test_is_similar_debt()` - Verify similarity detection
  - `test_deduplicate_debts()` - Verify deduplication
  - Mock LLM with MagicMock returning LLMResponse
  - Test various chapter texts (promises, no promises, edge cases)

  **Acceptance**:
  - [ ] All tests pass
  - [ ] Rule-based extraction works without LLM
  - [ ] LLM extraction mocked correctly
  - [ ] Hybrid mode combines results

- [x] **7.3** Unit tests for BriefValidator
  **File**: `/Users/ty/self/AI_novel/tests/novel/test_tools/test_brief_validator.py`
  **Complexity**: L
  **Details**:
  - `test_validate_chapter_all_fulfilled()` - Mock LLM to return all true
  - `test_validate_chapter_partial_fulfilled()` - Mock LLM to return some false
  - `test_validate_chapter_none_fulfilled()` - Mock LLM to return all false
  - `test_validate_empty_brief()` - Verify returns pass=True without LLM call
  - `test_validate_missing_fields()` - Verify handles incomplete brief
  - `test_suggested_debts_generation()` - Verify unfulfilled items become suggestions
  - `test_pass_rate_calculation()` - Verify pass_rate computed correctly
  - `test_truncate_long_chapter()` - Verify chapter truncated to 3000 chars
  - Mock LLM with different JSON responses

  **Acceptance**:
  - [x] All tests pass
  - [x] LLM mocked correctly
  - [x] Empty brief handled gracefully
  - [x] Pass rate calculated correctly

- [x] **7.4** Unit tests for StoryUnit models
  **File**: `/Users/ty/self/AI_novel/tests/novel/models/test_story_unit.py`
  **Complexity**: M
  **Details**:
  - `test_story_unit_valid()` - Create valid StoryUnit, verify fields
  - `test_story_unit_invalid_chapters_too_few()` - Verify ValidationError for <3 chapters
  - `test_story_unit_invalid_chapters_too_many()` - Verify ValidationError for >7 chapters
  - `test_story_unit_serialization()` - Verify JSON round-trip
  - `test_arc_brief_valid()` - Create valid ArcBrief
  - `test_arc_brief_serialization()` - Verify JSON round-trip

  **Acceptance**:
  - [ ] All tests pass
  - [ ] Validation errors raised for invalid data
  - [ ] Serialization works correctly

- [x] **7.5** Unit tests for Debt models
  **File**: `/Users/ty/self/AI_novel/tests/novel/models/test_debt.py`
  **Complexity**: M
  **Details**:
  - `test_chapter_debt_valid()` - Create valid ChapterDebt
  - `test_chapter_debt_invalid_type()` - Verify ValidationError for invalid type
  - `test_chapter_debt_invalid_status()` - Verify ValidationError for invalid status
  - `test_chapter_debt_serialization()` - Verify JSON round-trip
  - `test_debt_extraction_result()` - Create valid DebtExtractionResult
  - `test_debt_context()` - Create valid DebtContext

  **Acceptance**:
  - [ ] All tests pass
  - [ ] Enum validation works
  - [ ] Serialization preserves data

- [x] **7.6** Unit tests for Validation models
  **File**: `/Users/ty/self/AI_novel/tests/novel/models/test_validation.py`
  **Complexity**: M
  **Details**:
  - `test_brief_item_result()` - Create valid BriefItemResult
  - `test_brief_fulfillment_report()` - Create valid BriefFulfillmentReport
  - `test_brief_fulfillment_report_pass_rate()` - Verify pass_rate calculation
  - `test_brief_fulfillment_report_serialization()` - Verify JSON round-trip

  **Acceptance**:
  - [ ] All tests pass
  - [ ] Pass rate calculated correctly
  - [ ] Serialization works

- [ ] **7.7** Integration test: End-to-end chapter with debts
  **File**: `/Users/ty/self/AI_novel/tests/novel/test_narrative_control_integration.py`
  **Complexity**: XL
  **Details**:
  - `test_chapter_generation_with_debts()` - Full pipeline:
    - Create mock novel with chapter_brief
    - Generate chapter via pipeline
    - Verify brief validation ran
    - Verify debts extracted
    - Verify debts stored in tracker
  - `test_debt_propagation_across_chapters()` - Multi-chapter:
    - Generate Chapter 1 with pending action
    - Verify debt created
    - Generate Chapter 2 with debt context
    - Verify debt in Writer context
    - Verify debt fulfilled or escalated
  - `test_brief_validation_creates_debts()` - Unfulfilled brief:
    - Generate chapter missing main_conflict
    - Verify BriefValidator fails
    - Verify ChapterDebt created
  - Mock LLM for all generations
  - Use temporary workspace

  **Acceptance**:
  - [ ] All integration tests pass
  - [ ] Full pipeline works end-to-end
  - [ ] Debts propagate across chapters
  - [ ] Brief validation triggers debt creation

- [ ] **7.8** Edge case tests
  **File**: `/Users/ty/self/AI_novel/tests/novel/test_narrative_control_edge_cases.py`
  **Complexity**: M
  **Details**:
  - `test_empty_chapter_brief()` - Verify no errors with empty brief
  - `test_no_debts_extracted()` - Verify handles chapter with no debts
  - `test_all_debts_overdue()` - Verify escalation for all debts
  - `test_debt_fulfilled_multiple_times()` - Verify no duplicate debts
  - `test_conflicting_debts()` - Verify tracker handles conflicting must_pay_next
  - `test_abandoned_debt()` - Verify manual abandonment (future)
  - `test_missing_services()` - Verify pipeline works with services=None

  **Acceptance**:
  - [ ] All edge case tests pass
  - [ ] Graceful degradation verified
  - [ ] No crashes on edge cases

### 8. Documentation

- [ ] **8.1** Add docstrings to all new classes and methods
  **Files**: All new files
  **Complexity**: M
  **Details**:
  - Add module-level docstrings to all new files
  - Add class docstrings with description and example usage
  - Add method docstrings with Args, Returns, Raises
  - Follow Google style guide
  - Include code examples for complex methods

  **Acceptance**:
  - [ ] All public classes documented
  - [ ] All public methods documented
  - [ ] Examples provided for ObligationTracker, BriefValidator, DebtExtractor

- [ ] **8.2** Update CLAUDE.md with narrative control features
  **File**: `/Users/ty/self/AI_novel/CLAUDE.md`
  **Complexity**: S
  **Details**:
  - Add section "Narrative Control Layer (Phase 1)"
  - Document StoryUnit, ChapterDebt, BriefValidator
  - Document ObligationTracker, DebtExtractor services
  - Add usage examples
  - Document configuration flags

  **Acceptance**:
  - [ ] CLAUDE.md updated
  - [ ] Usage examples clear
  - [ ] Configuration documented

- [ ] **8.3** Create narrative control usage guide
  **File**: `/Users/ty/self/AI_novel/docs/narrative-control-guide.md`
  **Complexity**: M
  **Details**:
  - Create comprehensive usage guide with:
    - Overview of narrative control concepts
    - How to enable/disable features
    - How to interpret debt reports
    - How to manually mark debts as fulfilled/abandoned
    - Troubleshooting common issues
  - Include code examples for all public APIs
  - Add diagrams if helpful

  **Acceptance**:
  - [ ] Guide covers all features
  - [ ] Examples runnable
  - [ ] Troubleshooting section helpful

### 9. Performance Optimization

- [ ] **9.1** Add database indexes
  **File**: `/Users/ty/self/AI_novel/src/novel/storage/structured_db.py`
  **Complexity**: S
  **Details**:
  - Verify indexes created on chapter_debts (status, source_chapter, urgency_level)
  - Verify indexes created on story_units (volume_id, status)
  - Measure query performance before/after indexes

  **Acceptance**:
  - [ ] Indexes exist
  - [ ] Query performance improved (measure with EXPLAIN QUERY PLAN)

- [ ] **9.2** Optimize debt context token usage
  **File**: `/Users/ty/self/AI_novel/src/novel/services/obligation_tracker.py`
  **Complexity**: M
  **Details**:
  - Implement truncation logic in `get_summary_for_writer()`
  - Prioritize critical debts (top 3)
  - Limit high debts (top 2)
  - Limit normal debts (top 2)
  - Add token estimation (Chinese char * 2)
  - Truncate if exceeds max_tokens
  - Add "(已截断)" notice if truncated

  **Acceptance**:
  - [ ] Summary stays under max_tokens
  - [ ] Critical debts always included
  - [ ] Truncation notice added when needed

- [ ] **9.3** Optimize BriefValidator chapter truncation
  **File**: `/Users/ty/self/AI_novel/src/novel/tools/brief_validator.py`
  **Complexity**: S
  **Details**:
  - Truncate chapter_text to 3000 chars before LLM call
  - Add notice "(章节过长，已截取前 3000 字符)" if truncated
  - Measure token savings (estimate before/after)

  **Acceptance**:
  - [ ] Chapter truncated to 3000 chars
  - [ ] Notice added if truncated
  - [ ] Token usage reduced (verify with test)

### 10. Quality Assurance

- [ ] **10.1** Run full test suite
  **Command**: `python -m pytest tests/novel/ -v`
  **Complexity**: S
  **Details**:
  - Ensure all new tests pass
  - Ensure existing tests still pass (backwards compatibility)
  - Verify test coverage >= 85% for new modules

  **Acceptance**:
  - [ ] All tests pass
  - [ ] No regressions in existing tests
  - [ ] Coverage >= 85%

- [ ] **10.2** Manual testing with sample novel
  **Complexity**: M
  **Details**:
  - Create a test novel project with 10 chapters
  - Enable narrative control features
  - Generate chapters and verify:
    - Arcs created correctly (2 arcs for 10 chapters)
    - Debts extracted and tracked
    - Brief validation works
    - Debt context injected into Writer
    - Debt escalation happens correctly
  - Review generated debts.json, arcs.json
  - Verify debt statistics accurate

  **Acceptance**:
  - [ ] Sample novel generates successfully
  - [ ] Arcs align with chapter structure
  - [ ] Debts extracted make narrative sense
  - [ ] Brief validation catches unfulfilled items
  - [ ] Debt statistics accurate

- [ ] **10.3** Performance benchmarking
  **Complexity**: M
  **Details**:
  - Benchmark token usage before/after narrative control
  - Measure time overhead per chapter (debt extraction, brief validation, escalation)
  - Verify token usage increase <= 10%
  - Verify time overhead <= 15% per chapter

  **Acceptance**:
  - [ ] Token usage increase <= 10%
  - [ ] Time overhead <= 15%
  - [ ] Benchmarks documented

---

## Phase 2: Enrichment (High-Level Preview)

**Not detailed for Phase 1 implementation.**

- [ ] **2.1** Extend Foreshadowing model with function_type, payoff_level, payoff_window, payoff_form, purpose_statement, non_payoff_risk
- [ ] **2.2** Implement ForeshadowingTracker service
- [ ] **2.3** Upgrade Volume Settlement to VolumeBrief with promise/fulfillment/carryover tables
- [ ] **2.4** Implement cross-volume debt inheritance
- [ ] **2.5** Add LLM-based debt resolution suggestions

---

## Phase 3: Advanced (High-Level Preview)

**Not detailed for Phase 1 implementation.**

- [ ] **3.1** Define Plotline entity model
- [ ] **3.2** Implement PlotlineTracker service
- [ ] **3.3** Implement Narrative Quality Validators (arc progress, promise keeping)
- [ ] **3.4** Implement Rhythm Recipe System (5-chapter and 7-chapter templates)

---

## Summary

**Phase 1 Total Tasks**: 54 tasks
- Data Models: 5 tasks
- Storage Layer: 3 tasks
- Service Layer: 2 tasks
- Tools Layer: 1 task
- Agent Integration: 4 tasks
- Pipeline Integration: 3 tasks
- Testing: 8 tasks
- Documentation: 3 tasks
- Performance: 3 tasks
- QA: 3 tasks

**Estimated Timeline**:
- Week 1 (Days 1-5): Tasks 1.1 - 4.1 (Models, Storage, Services, Tools)
- Week 2 (Days 6-10): Tasks 5.1 - 7.8 (Agent Integration, Pipeline, Testing)
- Week 3 (Days 11-12): Tasks 8.1 - 10.3 (Documentation, Performance, QA)

**Critical Path**:
1. Models (1.1 - 1.5) → Storage (2.1 - 2.3) → Services (3.1 - 3.2) → Tools (4.1)
2. Agent Integration (5.1 - 5.4) depends on Services + Tools
3. Pipeline Integration (6.1 - 6.3) depends on Agent Integration
4. Testing (7.1 - 7.8) depends on all implementation
5. Documentation (8.1 - 8.3) can be parallel with Testing
6. Performance (9.1 - 9.3) and QA (10.1 - 10.3) are final steps

**Dependencies**:
- All testing depends on implementation complete
- Integration tests depend on unit tests passing
- QA depends on all tests passing
- Documentation can be written in parallel with implementation

**Risk Mitigation**:
- Start with models and storage (foundational, low risk)
- Test each component in isolation before integration
- Use mocked LLM for all tests (avoid external dependencies)
- Maintain backwards compatibility (graceful degradation)
- Feature flags for opt-in narrative control

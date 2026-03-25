# Narrative Control Layer - Requirements Specification

## Executive Summary

Upgrade the AI novel writing system with advanced narrative control mechanisms to ensure story coherence, promise fulfillment, and reader retention. The system will track narrative obligations across chapters, enforce mini-arc structures, and validate that each chapter delivers on its planned objectives.

## User Stories

### US-1: Mini-Arc Structure (StoryUnit)
**As a** novel pipeline developer
**I want** chapters to be organized into 3-7 chapter mini-arcs (StoryUnits) within each volume
**So that** the narrative has clear escalation patterns and readers experience satisfying short-term payoffs

**Acceptance Criteria:**
- GIVEN a VolumeOutline with 30 chapters
- WHEN NovelDirector generates the volume plan
- THEN the system SHALL create 4-6 StoryUnit arcs, each spanning 3-7 chapters
- AND each StoryUnit SHALL have defined phases: setup → escalation → climax → resolution
- AND each StoryUnit SHALL specify an escalation_point (tension peak) and turning_point (direction change)
- AND each StoryUnit SHALL have a closure_method (how it resolves) and residual_question (hook to next arc)
- AND each ChapterOutline SHALL reference its parent arc_id

### US-2: Narrative Debt Tracking (ChapterDebt)
**As a** Writer agent
**I want** to know what narrative promises were made in previous chapters
**So that** I can ensure critical setups are paid off and no threads are forgotten

**Acceptance Criteria:**
- GIVEN a generated chapter that introduces "character X promises to investigate Y tomorrow"
- WHEN the chapter is reviewed
- THEN the system SHALL extract a ChapterDebt with status=pending and type=must_pay_next
- AND when planning the next chapter, the debt SHALL be injected into Writer context
- AND when Writer generates the next chapter mentioning the investigation result
- THEN the debt status SHALL update to fulfilled
- AND if 3 chapters pass without fulfillment, status SHALL update to overdue

### US-3: Chapter Brief Validation (BriefValidator)
**As a** QualityReviewer agent
**I want** to verify that each chapter fulfilled its planned chapter_brief
**So that** the narrative stays on track and key beats are not skipped

**Acceptance Criteria:**
- GIVEN a ChapterOutline with chapter_brief containing main_conflict="主角vs配角比武"
- WHEN Writer generates the chapter text
- AND BriefValidator checks the chapter
- THEN it SHALL return BriefFulfillmentReport with main_conflict_fulfilled=True/False
- AND if main_conflict_fulfilled=False, a ChapterDebt SHALL be created with must_pay_next=True
- AND the debt description SHALL reference the unfulfilled brief item

### US-4: Debt Inheritance and Escalation
**As a** novel pipeline
**I want** unfulfilled debts to propagate to subsequent chapters with increasing urgency
**So that** critical narrative threads are not dropped

**Acceptance Criteria:**
- GIVEN ChapterDebt with type=pay_within_3 created in Chapter 5
- WHEN Chapter 6, 7 are generated without fulfilling the debt
- THEN in Chapter 8 context, the debt SHALL be escalated to must_pay_next
- AND the debt SHALL include a urgency_level field (normal/high/critical)
- AND critical debts SHALL appear in Writer system prompt

### US-5: Foreshadowing Function Types
**As a** PlotPlanner agent
**I want** foreshadowing items to specify their narrative function (misdirection/twist/emotional)
**So that** the payoff can be designed appropriately

**Acceptance Criteria:**
- GIVEN a Foreshadowing item with function_type=twist, payoff_window=2ch
- WHEN the system reaches 2 chapters past planted_chapter
- AND no collection has occurred
- THEN ForeshadowingTracker SHALL flag it as overdue
- AND suggest a payoff_form (e.g., truth_reveal, identity_reveal)

### US-6: Volume Settlement Report
**As a** novel pipeline
**I want** a comprehensive settlement at volume end
**So that** I can verify all promises were resolved or intentionally carried forward

**Acceptance Criteria:**
- GIVEN Volume 1 with 30 chapters completed
- WHEN the pipeline generates VolumeSnapshot
- THEN it SHALL include a VolumeBrief with promise_table, fulfillment_table, carryover_table
- AND promise_table SHALL list all narrative promises made in the volume
- AND fulfillment_table SHALL track which were resolved
- AND carryover_table SHALL list intentionally deferred promises with justification

## Functional Requirements

### FR-1: StoryUnit Model
The system SHALL define a StoryUnit data model with the following fields:
- `arc_id: str` - UUID
- `volume_id: int` - Parent volume number
- `name: str` - Arc name (e.g., "新生试炼篇")
- `chapters: list[int]` - Chapters in this arc (3-7 items)
- `phase: Literal["setup", "escalation", "climax", "resolution"]` - Current phase
- `hook: str` - Opening hook that launches the arc
- `escalation_point: int` - Chapter where tension peaks
- `turning_point: int` - Chapter where direction changes
- `closure_method: str` - How the arc resolves
- `residual_question: str` - Unresolved element that hooks into next arc

### FR-2: ChapterDebt Model
The system SHALL define a ChapterDebt data model with:
- `debt_id: str` - UUID
- `source_chapter: int` - Where the promise was made
- `created_at: str` - ISO timestamp
- `type: Literal["must_pay_next", "pay_within_3", "long_tail_payoff"]`
- `description: str` - What needs to be resolved
- `character_pending_actions: list[str]` - Character-specific obligations
- `emotional_debt: str | None` - Unresolved emotional tension
- `target_chapter: int | None` - When it should be paid (if specified)
- `status: Literal["pending", "fulfilled", "overdue", "abandoned"]`
- `fulfilled_at: int | None` - Chapter where debt was paid
- `urgency_level: Literal["normal", "high", "critical"]`

### FR-3: BriefValidator Tool
The system SHALL implement a BriefValidator tool that:
- Takes `chapter_text: str` and `chapter_brief: dict` as input
- Uses LLM to evaluate if each brief item was fulfilled
- Returns BriefFulfillmentReport with:
  - `main_conflict_fulfilled: bool`
  - `payoff_delivered: bool`
  - `character_arc_step_taken: bool`
  - `foreshadowing_planted: list[bool]` - Per item
  - `foreshadowing_collected: list[bool]` - Per item
  - `end_hook_present: bool`
  - `unfulfilled_items: list[str]` - Descriptions of failures
  - `overall_pass: bool`

### FR-4: Debt Extraction from Generated Chapters
The system SHALL automatically extract debts after chapter generation by:
- Analyzing chapter_text for:
  - Character commitments ("我会..." / "明天我..." / "I will...")
  - Unresolved conflicts (fight interrupted, mystery introduced)
  - Explicit promises to reader (setup without payoff)
- Creating ChapterDebt entries with appropriate type and urgency
- Storing debts in NovelMemory or StructuredDB

### FR-5: Debt Context Injection
Before Writer generates a chapter, the system SHALL:
- Query all pending/overdue debts from previous chapters
- Format debts into a context section for Writer prompt
- Include urgency signals for critical debts
- Provide suggested resolution approaches if urgency_level=critical

### FR-6: Enhanced Foreshadowing Model
The system SHALL extend the Foreshadowing model with:
- `function_type: Literal["misdirection", "twist", "emotional", "worldbuilding", "power", "relationship"]`
- `payoff_level: Literal["small", "medium", "large"]`
- `payoff_window: Literal["2ch", "volume", "late_book"]`
- `payoff_form: Literal["truth_reveal", "promise_fulfilled", "identity_reveal", "item_activation", "karmic_return"] | None`
- `purpose_statement: str` - Why this foreshadowing exists
- `non_payoff_risk: str` - What goes wrong if not collected

### FR-7: ObligationTracker Service
The system SHALL implement an ObligationTracker runtime service that:
- Loads all pending debts for current and previous chapters
- Escalates overdue debts (must_pay_next not paid → critical)
- Provides `get_debts_for_chapter(chapter_num: int) -> list[ChapterDebt]`
- Provides `mark_debt_fulfilled(debt_id: str, chapter_num: int)`
- Provides `get_summary_for_writer(chapter_num: int) -> str`
- Persists debt state to JSON or StructuredDB

### FR-8: Volume Settlement Engine
At volume end, the system SHALL:
- Generate VolumeBrief with three tables:
  - `promise_table: list[dict]` - All narrative setups in the volume
  - `fulfillment_table: list[dict]` - Resolved promises with chapter references
  - `carryover_table: list[dict]` - Intentional deferrals with justification
- Validate that all major promises are either fulfilled or justified
- Flag orphaned setups (promises with no payoff plan)

## Non-Functional Requirements

### NFR-1: Performance
- Debt extraction SHALL complete within 5 seconds per chapter
- BriefValidator SHALL complete within 10 seconds (single LLM call)
- ObligationTracker queries SHALL complete within 100ms

### NFR-2: Token Efficiency
- BriefValidator SHALL use chapter_brief only (no full context), max 500 tokens
- Debt context injection SHALL be capped at 1000 tokens
- Foreshadowing tracking SHALL use BM25 retrieval before LLM analysis

### NFR-3: Integration
- All new models SHALL be Pydantic BaseModel subclasses
- All agents SHALL remain SYNC (no async)
- LangGraph integration SHALL be optional with sequential fallback
- Storage SHALL extend StructuredDB and NovelMemory interfaces

### NFR-4: Testability
- All components SHALL have unit tests with mocked LLM
- Edge cases: empty chapter_brief, no debts, all debts overdue
- Integration tests with full chapter generation pipeline

### NFR-5: Backwards Compatibility
- Existing novels without StoryUnit data SHALL continue to work
- ChapterOutline.chapter_brief remains optional (default empty dict)
- BriefValidator gracefully handles missing brief fields

## Edge Cases

### EC-1: Empty Chapter Brief
**Given** a ChapterOutline with empty chapter_brief
**When** BriefValidator runs
**Then** it SHALL return overall_pass=True with a warning log

### EC-2: Debt Fulfilled Multiple Times
**Given** a debt marked fulfilled in Chapter 5
**When** Chapter 6 also addresses the same obligation
**Then** the system SHALL NOT create duplicate debts
**And** the original debt SHALL remain status=fulfilled

### EC-3: Conflicting Debts
**Given** two must_pay_next debts that contradict each other
**When** Writer context is assembled
**Then** ObligationTracker SHALL flag the conflict
**And** provide a resolution suggestion (prioritize by urgency)

### EC-4: Volume-Spanning Arc
**Given** a StoryUnit that starts in Chapter 28 of Volume 1
**When** Volume 1 ends at Chapter 30
**Then** the arc SHALL be marked incomplete
**And** carried forward to Volume 2 settlement

### EC-5: Abandoned Debt
**Given** a long_tail_payoff debt that becomes irrelevant
**When** 10 chapters pass and plot has pivoted
**Then** the system SHALL allow manual marking as abandoned
**And** include justification in volume settlement

## Success Metrics

### Narrative Quality Metrics
- **Debt Fulfillment Rate**: >= 90% of must_pay_next debts resolved within 1 chapter
- **Brief Compliance Rate**: >= 85% of chapters pass BriefValidator on first attempt
- **Arc Completion Rate**: 100% of StoryUnit arcs reach resolution phase

### System Performance Metrics
- **Debt Extraction Accuracy**: >= 80% precision on manual review sample
- **False Positive Rate**: <= 15% (debts flagged but already resolved)
- **Token Usage**: <= 10% increase in total token consumption

### Developer Experience Metrics
- **Integration Time**: Phase 1 implementation <= 2 weeks
- **Test Coverage**: >= 85% line coverage for new modules
- **Documentation Completeness**: All public APIs documented with examples

## Out of Scope (Phase 1)

The following features are deferred to Phase 2 or 3:
- Plotline entity and PlotlineTracker (Phase 3)
- Narrative Quality Validators for cross-chapter arc progress (Phase 3)
- Rhythm Recipe System with 5/7-chapter templates (Phase 3)
- Automatic debt resolution suggestions via LLM (Phase 2 - manual suggestions only)
- Multi-volume debt tracking (Phase 2)
- Interactive debt management UI (Phase 2)

## Dependencies

### Internal Dependencies
- `src/novel/models/` - Pydantic data models
- `src/novel/agents/novel_director.py` - Arc generation
- `src/novel/agents/plot_planner.py` - Brief integration
- `src/novel/agents/writer.py` - Debt context injection
- `src/novel/agents/quality_reviewer.py` - BriefValidator integration
- `src/novel/storage/structured_db.py` - Debt persistence
- `src/novel/storage/novel_memory.py` - Unified access layer
- `src/llm/llm_client.py` - LLM communication

### External Dependencies
- Python 3.10+
- Pydantic 2.x
- LLM backend (OpenAI/DeepSeek/Gemini/Ollama)
- SQLite3 (for StructuredDB)

## Glossary

- **StoryUnit**: A 3-7 chapter mini-arc within a volume, with defined escalation and resolution
- **ChapterDebt**: A narrative obligation created when a chapter introduces a setup that requires payoff
- **Chapter Brief**: A task specification (in ChapterOutline.chapter_brief dict) defining what the chapter must accomplish
- **BriefValidator**: A tool that verifies a generated chapter fulfilled its brief requirements
- **ObligationTracker**: A runtime service managing debt lifecycle (creation, escalation, fulfillment)
- **Volume Settlement**: End-of-volume validation ensuring all promises resolved or justified
- **Debt Escalation**: Process of increasing urgency when a debt remains unfulfilled past its deadline
- **Payoff Window**: The planned timeframe for resolving a foreshadowing item (2ch/volume/late_book)

## References

- Existing codebase: `/Users/ty/self/AI_novel/`
- Foreshadowing model: `src/novel/models/foreshadowing.py`
- Novel model: `src/novel/models/novel.py` (Act, VolumeOutline, ChapterOutline)
- Memory model: `src/novel/models/memory.py` (VolumeSnapshot)
- Chapter model: `src/novel/models/chapter.py` (MoodTag, Scene, Chapter)
- Quality tools: `src/novel/tools/quality_check_tool.py`
- LangGraph integration: `src/novel/agents/graph.py`

# 小说知识图谱增强功能 - 技术设计规格

## 概述

为现有小说写作系统增加三个核心知识管理功能：

- **P0: 实体分类索引 (Entity Registry)** — 全书实体库，支持别名管理和一致性检测
- **P1: 伏笔图谱 (Foreshadowing Graph)** — NetworkX 伏笔追踪图，自动检测遗忘伏笔
- **P2: 覆盖率指标 + 别名合并** — 健康度仪表盘，量化项目质量

所有功能与现有 pipeline 深度集成，遵循"写后提取→写前注入"模式，最大化省 Token。

---

## P0: 实体分类索引 (Entity Registry)

### 1. 数据模型

#### 1.1 Pydantic 模型

```python
# src/novel/models/entity.py

from __future__ import annotations
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, Field

class EntityType:
    """实体类型枚举（参考《史记》18类，适配网文）"""
    CHARACTER = "character"          # 人名
    LOCATION = "location"            # 地名
    FACTION = "faction"              # 势力/宗门/组织
    SKILL = "skill"                  # 功法/技能/绝招
    ARTIFACT = "artifact"            # 器物/宝物/法宝
    RACE = "race"                    # 种族
    TITLE = "title"                  # 称号/外号
    FORMATION = "formation"          # 阵法/禁制
    EVENT = "event"                  # 历史事件
    POSITION = "position"            # 职位/官衔
    TERM = "term"                    # 专有名词
    OTHER = "other"                  # 其他

class Entity(BaseModel):
    """实体条目"""
    entity_id: str = Field(default_factory=lambda: str(uuid4()))
    canonical_name: str = Field(..., min_length=1, description="规范名称（主名）")
    aliases: list[str] = Field(default_factory=list, description="别名列表")
    entity_type: str = Field(..., description="实体类型，见 EntityType")
    first_mention_chapter: int = Field(..., ge=1, description="首次出现章节")
    definition: str = Field("", description="实体定义/描述")
    metadata: dict = Field(default_factory=dict, description="扩展元数据，如{力量等级:金丹期}")
    
    # 内部字段
    mention_count: int = Field(0, ge=0, description="总提及次数")
    last_mention_chapter: int = Field(0, ge=0, description="最后提及章节")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class EntityMention(BaseModel):
    """实体提及记录（用于追踪上下文）"""
    mention_id: str = Field(default_factory=lambda: str(uuid4()))
    entity_id: str = Field(..., description="关联的实体ID")
    chapter: int = Field(..., ge=1)
    mentioned_name: str = Field(..., description="实际提及的名称（可能是别名）")
    context: str = Field("", max_length=200, description="前后文摘录")
```

#### 1.2 存储 Schema (SQLite)

在 `StructuredDB._SCHEMA` 中新增：

```sql
-- 实体注册表
CREATE TABLE IF NOT EXISTS entities (
    entity_id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    aliases TEXT NOT NULL DEFAULT '[]',  -- JSON array
    entity_type TEXT NOT NULL,
    first_mention_chapter INTEGER NOT NULL,
    definition TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}',  -- JSON object
    mention_count INTEGER DEFAULT 0,
    last_mention_chapter INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 实体提及记录（可选，用于高级分析）
CREATE TABLE IF NOT EXISTS entity_mentions (
    mention_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    chapter INTEGER NOT NULL,
    mentioned_name TEXT NOT NULL,
    context TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (entity_id) REFERENCES entities(entity_id) ON DELETE CASCADE
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_canonical ON entities(canonical_name);
CREATE INDEX IF NOT EXISTS idx_entity_mentions_chapter ON entity_mentions(chapter);
CREATE INDEX IF NOT EXISTS idx_entity_mentions_entity ON entity_mentions(entity_id);
```

### 2. 提取逻辑

#### 2.1 提取策略

**优先级**:
1. **规则提取**（免费）— 针对特定类型（地名、功法、称号）使用正则
2. **NER模型**（可选）— 使用 spaCy/jieba 提取人名/地名（本地离线）
3. **LLM提取**（fallback）— 仅在规则+NER无法覆盖时调用

#### 2.2 规则模板

```python
# src/novel/services/entity_extractor.py

import re
from typing import Any

# 规则模式 (示例)
_LOCATION_PATTERNS = [
    re.compile(r"([^\s]{2,6})(山|峰|谷|洞|林|城|镇|村|岛|海|河|湖|宫|殿|阁|院|楼|台)"),
    re.compile(r"([\u4e00-\u9fa5]{2,4})(宗|门|派|教|帮|会)"),
]

_SKILL_PATTERNS = [
    re.compile(r"《([^\s》]{2,8})》"),  # 书名号包裹的功法
    re.compile(r"([^\s]{2,6})(功|诀|法|术|式|掌|拳|剑|刀|阵)"),
]

_TITLE_PATTERNS = [
    re.compile(r"([^\s]{2,4})(仙|魔|神|王|帝|尊|圣|祖|宗|长老|掌门|弟子)"),
]

_ARTIFACT_PATTERNS = [
    re.compile(r"([^\s]{2,6})(剑|刀|枪|戟|鼎|炉|印|塔|珠|镜|环|钟|符|丹|药)"),
]

class RuleBasedExtractor:
    """规则优先的实体提取器"""
    
    def extract_entities(self, text: str, chapter: int) -> list[Entity]:
        """从文本提取实体（规则优先）"""
        entities = []
        
        # 地名提取
        for pattern in _LOCATION_PATTERNS:
            for match in pattern.finditer(text):
                name = match.group(0)
                if len(name) >= 2 and self._is_valid_entity(name):
                    entities.append(Entity(
                        canonical_name=name,
                        entity_type=EntityType.LOCATION,
                        first_mention_chapter=chapter,
                    ))
        
        # 功法提取
        for pattern in _SKILL_PATTERNS:
            for match in pattern.finditer(text):
                name = match.group(1) if match.lastindex else match.group(0)
                if self._is_valid_entity(name):
                    entities.append(Entity(
                        canonical_name=name,
                        entity_type=EntityType.SKILL,
                        first_mention_chapter=chapter,
                    ))
        
        # 称号/别名提取
        for pattern in _TITLE_PATTERNS:
            for match in pattern.finditer(text):
                name = match.group(0)
                if self._is_valid_entity(name):
                    entities.append(Entity(
                        canonical_name=name,
                        entity_type=EntityType.TITLE,
                        first_mention_chapter=chapter,
                    ))
        
        # 器物提取
        for pattern in _ARTIFACT_PATTERNS:
            for match in pattern.finditer(text):
                name = match.group(0)
                if self._is_valid_entity(name):
                    entities.append(Entity(
                        canonical_name=name,
                        entity_type=EntityType.ARTIFACT,
                        first_mention_chapter=chapter,
                    ))
        
        return entities
    
    def _is_valid_entity(self, name: str) -> bool:
        """过滤无效实体（常用词、代词等）"""
        # 黑名单
        blacklist = {
            "他", "她", "它", "我", "你", "这", "那", "什么", "哪里",
            "如何", "为何", "不是", "可以", "不能", "已经", "就是",
            "一个", "一种", "许多", "所有", "大家", "众人",
            # 网文高频词
            "这里", "那里", "此刻", "现在", "当时", "如今", "此时",
        }
        if name in blacklist:
            return False
        
        # 长度过滤
        if len(name) < 2 or len(name) > 8:
            return False
        
        # 纯数字/标点
        if re.fullmatch(r"[\d\W]+", name):
            return False
        
        return True
```

#### 2.3 LLM Fallback（仅用于高价值章节或首次索引）

```python
class LLMEntityExtractor:
    """LLM 实体提取（fallback）"""
    
    _SYSTEM_PROMPT = """你是一个网络小说实体提取专家。从给定章节文本中提取所有重要实体。

返回严格 JSON 格式：
{
  "entities": [
    {
      "name": "青云山",
      "type": "location",
      "definition": "主角修炼的山脉"
    },
    {
      "name": "碎星剑法",
      "type": "skill",
      "definition": "主角习得的剑术"
    }
  ]
}

实体类型：character, location, faction, skill, artifact, race, title, formation, term, other
"""
    
    def __init__(self, llm_client):
        self.llm = llm_client
    
    def extract_entities(self, text: str, chapter: int, max_tokens: int = 1024) -> list[Entity]:
        """LLM 提取实体（仅关键章节使用）"""
        user_prompt = f"## 第{chapter}章文本\n\n{text[:3000]}"  # 限制输入长度
        
        response = self.llm.chat(
            messages=[
                {"role": "system", "content": self._SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            json_mode=True,
            max_tokens=max_tokens,
        )
        
        data = json.loads(response.content)
        entities = []
        for item in data.get("entities", []):
            entities.append(Entity(
                canonical_name=item["name"],
                entity_type=item.get("type", "other"),
                first_mention_chapter=chapter,
                definition=item.get("definition", ""),
            ))
        
        return entities
```

### 3. 集成点

#### 3.1 写后提取（pipeline.py 章节生成后）

在 `generate_chapters()` 主循环中，每章生成完成后：

```python
# 位置：pipeline.py 第 ~1450 行左右（章节生成完成、质量检查后）

# ========== 实体提取与索引 ==========
if self.memory:
    try:
        from src.novel.services.entity_service import EntityService
        entity_svc = EntityService(self.memory.structured_db, llm_client=None)  # 规则优先
        
        # 提取实体
        extracted = entity_svc.extract_and_register(
            chapter_text=state["current_chapter_text"],
            chapter_number=ch_num,
            use_llm=False,  # 默认仅规则提取
        )
        log.info("第%d章实体提取完成: %d 个新实体", ch_num, extracted["new_count"])
        
        # 别名合并（如果启用）
        if ch_num % 5 == 0:  # 每5章做一次别名清理
            merged = entity_svc.merge_aliases(dry_run=False)
            if merged > 0:
                log.info("实体别名合并完成: %d 组", merged)
    except Exception as exc:
        log.warning("实体提取失败（非阻塞）: %s", exc)
```

#### 3.2 写前注入（ContinuityService）

在 `continuity_service.py` 中新增方法：

```python
def _extract_active_entities(
    self,
    brief: dict[str, Any],
    chapter_number: int,
) -> None:
    """注入活跃实体列表（近期出现的实体）"""
    if not self.db:
        return
    
    try:
        # 查询近3章内出现的实体
        entities = self.db.query_entities_by_chapter_range(
            from_chapter=max(1, chapter_number - 3),
            to_chapter=chapter_number - 1,
        )
        
        # 按类型分组
        by_type = {}
        for ent in entities:
            t = ent.get("entity_type", "other")
            by_type.setdefault(t, []).append(ent.get("canonical_name", ""))
        
        # 注入 brief
        brief["active_entities"] = by_type
    except Exception:
        log.warning("活跃实体提取失败", exc_info=True)
```

并在 `format_for_prompt()` 中添加输出：

```python
# 在 format_for_prompt() 中
active_entities = brief.get("active_entities", {})
if active_entities:
    sections.append("### 活跃实体（近期出现）")
    for etype, names in active_entities.items():
        sections.append(f"- {etype}: {', '.join(names[:10])}")  # 限制数量
    sections.append("")
```

#### 3.3 一致性检查增强

在 `ConsistencyChecker.check_chapter()` 中增加实体名称检查：

```python
# src/novel/agents/consistency_checker.py

def check_entity_consistency(
    self,
    chapter_text: str,
    chapter_number: int,
    memory: Any,
) -> list[dict]:
    """检查实体名称一致性（青云山 vs 青云峰 类矛盾）"""
    if not hasattr(memory, "structured_db"):
        return []
    
    try:
        from src.novel.services.entity_service import EntityService
        entity_svc = EntityService(memory.structured_db, llm_client=None)
        
        # 提取当前章节实体
        current_entities = entity_svc.extract_entities_from_text(chapter_text, chapter_number)
        
        # 检测与已有实体的相似度（编辑距离）
        conflicts = entity_svc.detect_name_conflicts(
            current_entities,
            threshold=0.7,  # 70% 相似度即报警
        )
        
        return conflicts
    except Exception:
        log.warning("实体一致性检查失败", exc_info=True)
        return []
```

### 4. API 接口

#### 4.1 EntityService

```python
# src/novel/services/entity_service.py

class EntityService:
    """实体注册与管理服务"""
    
    def __init__(self, db: StructuredDB, llm_client=None):
        self.db = db
        self.llm = llm_client
        self.rule_extractor = RuleBasedExtractor()
        self.llm_extractor = LLMEntityExtractor(llm_client) if llm_client else None
    
    def extract_and_register(
        self,
        chapter_text: str,
        chapter_number: int,
        use_llm: bool = False,
    ) -> dict[str, Any]:
        """提取并注册实体
        
        Returns:
            {
                "new_count": int,
                "updated_count": int,
                "entities": list[Entity],
            }
        """
        # 规则提取
        entities = self.rule_extractor.extract_entities(chapter_text, chapter_number)
        
        # LLM 补充（可选）
        if use_llm and self.llm_extractor:
            llm_entities = self.llm_extractor.extract_entities(chapter_text, chapter_number)
            entities.extend(llm_entities)
        
        # 去重
        entities = self._deduplicate_entities(entities)
        
        # 注册到数据库
        new_count = 0
        updated_count = 0
        for ent in entities:
            existing = self.db.get_entity_by_name(ent.canonical_name)
            if existing:
                # 更新提及次数
                self.db.update_entity_mention(
                    entity_id=existing["entity_id"],
                    chapter=chapter_number,
                )
                updated_count += 1
            else:
                # 新增实体
                self.db.insert_entity(ent)
                new_count += 1
        
        return {
            "new_count": new_count,
            "updated_count": updated_count,
            "entities": [e.model_dump() for e in entities],
        }
    
    def merge_aliases(self, dry_run: bool = True) -> int:
        """别名合并（基于编辑距离）
        
        Returns:
            合并的实体组数
        """
        from difflib import SequenceMatcher
        
        entities = self.db.get_all_entities()
        merged_count = 0
        
        # 按类型分组（只在同类型内合并）
        by_type = {}
        for ent in entities:
            t = ent.get("entity_type", "other")
            by_type.setdefault(t, []).append(ent)
        
        for etype, group in by_type.items():
            # N^2 相似度比较（可优化为 BK-tree）
            for i, ent1 in enumerate(group):
                for ent2 in group[i+1:]:
                    name1 = ent1.get("canonical_name", "")
                    name2 = ent2.get("canonical_name", "")
                    
                    # 计算相似度
                    ratio = SequenceMatcher(None, name1, name2).ratio()
                    if ratio >= 0.8:  # 80% 相似
                        # 合并：保留首次出现的为主名，另一个作为别名
                        primary = ent1 if ent1["first_mention_chapter"] <= ent2["first_mention_chapter"] else ent2
                        secondary = ent2 if primary == ent1 else ent1
                        
                        if not dry_run:
                            self.db.merge_entity_as_alias(
                                primary_id=primary["entity_id"],
                                secondary_id=secondary["entity_id"],
                            )
                        
                        merged_count += 1
                        log.info("实体合并: %s <- %s (相似度: %.2f)", name1, name2, ratio)
        
        return merged_count
    
    def detect_name_conflicts(
        self,
        current_entities: list[Entity],
        threshold: float = 0.7,
    ) -> list[dict]:
        """检测实体名称冲突（相似但不完全一致）"""
        conflicts = []
        
        for ent in current_entities:
            # 查询数据库中同类型的相似实体
            candidates = self.db.query_similar_entities(
                name=ent.canonical_name,
                entity_type=ent.entity_type,
                similarity_threshold=threshold,
            )
            
            for candidate in candidates:
                if candidate["canonical_name"] != ent.canonical_name:
                    conflicts.append({
                        "current_name": ent.canonical_name,
                        "existing_name": candidate["canonical_name"],
                        "type": ent.entity_type,
                        "similarity": candidate["similarity"],
                        "conflict_type": "name_variant",
                    })
        
        return conflicts
    
    def _deduplicate_entities(self, entities: list[Entity]) -> list[Entity]:
        """去重（同名同类型只保留一个）"""
        seen = set()
        result = []
        for ent in entities:
            key = (ent.canonical_name, ent.entity_type)
            if key not in seen:
                seen.add(key)
                result.append(ent)
        return result
```

#### 4.2 StructuredDB 扩展方法

在 `structured_db.py` 中新增：

```python
# src/novel/storage/structured_db.py

def insert_entity(self, entity: Entity) -> None:
    """插入实体"""
    with self.transaction() as cur:
        cur.execute(
            """
            INSERT INTO entities (
                entity_id, canonical_name, aliases, entity_type,
                first_mention_chapter, definition, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity.entity_id,
                entity.canonical_name,
                json.dumps(entity.aliases, ensure_ascii=False),
                entity.entity_type,
                entity.first_mention_chapter,
                entity.definition,
                json.dumps(entity.metadata, ensure_ascii=False),
            ),
        )

def get_entity_by_name(self, name: str) -> dict | None:
    """根据规范名称查询实体"""
    with self.transaction() as cur:
        cur.execute(
            "SELECT * FROM entities WHERE canonical_name = ?",
            (name,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

def get_all_entities(self) -> list[dict]:
    """获取所有实体"""
    with self.transaction() as cur:
        cur.execute("SELECT * FROM entities")
        return [dict(row) for row in cur.fetchall()]

def query_entities_by_chapter_range(
    self,
    from_chapter: int,
    to_chapter: int,
) -> list[dict]:
    """查询章节范围内出现的实体"""
    with self.transaction() as cur:
        cur.execute(
            """
            SELECT DISTINCT e.*
            FROM entities e
            WHERE e.first_mention_chapter >= ?
              AND e.first_mention_chapter <= ?
            ORDER BY e.first_mention_chapter
            """,
            (from_chapter, to_chapter),
        )
        return [dict(row) for row in cur.fetchall()]

def update_entity_mention(self, entity_id: str, chapter: int) -> None:
    """更新实体提及次数和最后提及章节"""
    with self.transaction() as cur:
        cur.execute(
            """
            UPDATE entities
            SET mention_count = mention_count + 1,
                last_mention_chapter = ?
            WHERE entity_id = ?
            """,
            (chapter, entity_id),
        )

def merge_entity_as_alias(self, primary_id: str, secondary_id: str) -> None:
    """将 secondary 合并为 primary 的别名"""
    with self.transaction() as cur:
        # 读取 secondary 的名称
        cur.execute("SELECT canonical_name FROM entities WHERE entity_id = ?", (secondary_id,))
        row = cur.fetchone()
        if not row:
            return
        secondary_name = row["canonical_name"]
        
        # 追加到 primary 的 aliases
        cur.execute("SELECT aliases FROM entities WHERE entity_id = ?", (primary_id,))
        row = cur.fetchone()
        if not row:
            return
        aliases = json.loads(row["aliases"])
        if secondary_name not in aliases:
            aliases.append(secondary_name)
        
        # 更新 primary
        cur.execute(
            "UPDATE entities SET aliases = ? WHERE entity_id = ?",
            (json.dumps(aliases, ensure_ascii=False), primary_id),
        )
        
        # 删除 secondary
        cur.execute("DELETE FROM entities WHERE entity_id = ?", (secondary_id,))
```

### 5. 省 Token 策略

1. **规则优先**: 90%+ 实体通过正则提取，零 LLM 成本
2. **懒加载 LLM**: 默认 `use_llm=False`，仅在手动触发或首次全书索引时启用
3. **批处理**: 首次索引时分批调用 LLM（每次最多5章），避免超时
4. **去重前置**: 先规则去重，再送 LLM，减少重复输出
5. **增量索引**: 每章写后仅索引新内容，不重新扫描全书

### 6. 任务拆分

#### Phase 1: 核心实体提取 (2-3h)
1. 创建 `src/novel/models/entity.py` — Entity/EntityMention 模型
2. 扩展 `StructuredDB._SCHEMA` — 实体表 + 索引
3. 实现 `StructuredDB` 实体 CRUD 方法
4. 实现 `RuleBasedExtractor` — 规则提取（4类：地名/功法/称号/器物）
5. 测试：规则提取器单元测试

#### Phase 2: 服务层与集成 (2-3h)
1. 实现 `EntityService` — 提取/注册/去重/别名合并
2. 集成到 `pipeline.py` — 写后提取
3. 集成到 `ContinuityService` — 写前注入活跃实体
4. 测试：端到端测试（生成章节→提取实体→下章注入）

#### Phase 3: LLM Fallback + 一致性检查 (1-2h)
1. 实现 `LLMEntityExtractor` — LLM 补充提取
2. 扩展 `ConsistencyChecker` — 实体名称一致性检查
3. 测试：模拟名称冲突（青云山 vs 青云峰）

---

## P1: 伏笔图谱 (Foreshadowing Graph)

### 1. 数据模型

#### 1.1 Pydantic 模型（扩展现有 `Foreshadowing`）

现有 `src/novel/models/foreshadowing.py` 已有 `Foreshadowing` 模型，仅需追加图相关字段：

```python
# src/novel/models/foreshadowing.py (扩展)

class ForeshadowingEdge(BaseModel):
    """伏笔关系边"""
    edge_id: str = Field(default_factory=lambda: str(uuid4()))
    from_foreshadowing_id: str = Field(..., description="源伏笔ID")
    to_foreshadowing_id: str = Field(..., description="目标伏笔ID")
    relation_type: Literal["trigger", "collect", "parallel", "conflict"] = Field(
        ..., description="触发/回收/并行/冲突"
    )
    description: str = Field("", description="关系描述")

class ForeshadowingStatus(BaseModel):
    """伏笔状态摘要（用于检查遗忘）"""
    foreshadowing_id: str
    planted_chapter: int
    target_chapter: int
    status: Literal["pending", "collected", "abandoned"]
    chapters_since_plant: int = Field(..., description="距埋设已过多少章")
    last_mentioned_chapter: int | None = Field(None, description="最后被提及的章节")
    is_forgotten: bool = Field(False, description="是否即将遗忘（超过阈值未提及）")
```

#### 1.2 NetworkX 图存储

在 `KnowledgeGraph` 中扩展：

```python
# src/novel/storage/knowledge_graph.py (扩展)

def add_foreshadowing_node(
    self,
    foreshadowing_id: str,
    planted_chapter: int,
    content: str,
    target_chapter: int = -1,
    status: str = "pending",
    **attrs: Any,
) -> None:
    """添加伏笔节点"""
    self.graph.add_node(
        foreshadowing_id,
        type="foreshadowing",
        planted_chapter=planted_chapter,
        content=content,
        target_chapter=target_chapter,
        status=status,
        last_mentioned_chapter=planted_chapter,
        **attrs,
    )

def add_foreshadowing_edge(
    self,
    from_id: str,
    to_id: str,
    relation_type: str,
    chapter: int,
    **attrs: Any,
) -> None:
    """添加伏笔关系边"""
    key = f"{relation_type}_{chapter}"
    self.graph.add_edge(
        from_id,
        to_id,
        key=key,
        edge_type="foreshadowing_relation",
        relation_type=relation_type,
        chapter=chapter,
        **attrs,
    )

def get_pending_foreshadowings(self, current_chapter: int) -> list[dict]:
    """获取未回收的伏笔列表"""
    results = []
    for node_id, attrs in self.graph.nodes(data=True):
        if attrs.get("type") != "foreshadowing":
            continue
        if attrs.get("status") != "pending":
            continue
        
        planted = attrs.get("planted_chapter", 0)
        last_mention = attrs.get("last_mentioned_chapter", planted)
        chapters_since = current_chapter - last_mention
        
        results.append({
            "foreshadowing_id": node_id,
            "content": attrs.get("content", ""),
            "planted_chapter": planted,
            "target_chapter": attrs.get("target_chapter", -1),
            "chapters_since_plant": current_chapter - planted,
            "last_mentioned_chapter": last_mention,
            "is_forgotten": chapters_since >= 10,  # 10章未提及=即将遗忘
        })
    
    # 按即将遗忘 + 距埋设章数排序
    results.sort(key=lambda x: (-int(x["is_forgotten"]), -x["chapters_since_plant"]))
    return results

def mark_foreshadowing_collected(
    self,
    foreshadowing_id: str,
    collected_chapter: int,
) -> None:
    """标记伏笔已回收"""
    if foreshadowing_id in self.graph:
        self.graph.nodes[foreshadowing_id]["status"] = "collected"
        self.graph.nodes[foreshadowing_id]["collected_chapter"] = collected_chapter

def update_foreshadowing_mention(
    self,
    foreshadowing_id: str,
    chapter: int,
) -> None:
    """更新伏笔最后提及章节"""
    if foreshadowing_id in self.graph:
        self.graph.nodes[foreshadowing_id]["last_mentioned_chapter"] = chapter
```

### 2. 提取逻辑

#### 2.1 从 chapter_brief 自动创建（写前）

在 `PlotPlanner` 阶段，如果 chapter_brief 有 `foreshadowing_plant` 或 `foreshadowing_collect`，自动创建图节点：

```python
# src/novel/services/foreshadowing_service.py

class ForeshadowingService:
    """伏笔图谱管理服务"""
    
    def __init__(self, knowledge_graph: KnowledgeGraph, llm_client=None):
        self.graph = knowledge_graph
        self.llm = llm_client
    
    def register_planned_foreshadowings(
        self,
        chapter_brief: dict,
        chapter_number: int,
    ) -> int:
        """从 chapter_brief 注册计划的伏笔
        
        Returns:
            注册的伏笔数量
        """
        count = 0
        
        # 埋设伏笔
        plants = chapter_brief.get("foreshadowing_plant", [])
        if isinstance(plants, str):
            plants = [plants]
        
        for plant in plants:
            fid = f"foreshadow_{chapter_number}_{uuid4().hex[:8]}"
            self.graph.add_foreshadowing_node(
                foreshadowing_id=fid,
                planted_chapter=chapter_number,
                content=plant,
                target_chapter=-1,  # 未指定目标
                status="pending",
            )
            count += 1
            log.info("伏笔节点已注册: %s (第%d章)", plant, chapter_number)
        
        # 回收伏笔（建立回收边）
        collects = chapter_brief.get("foreshadowing_collect", [])
        if isinstance(collects, str):
            collects = [collects]
        
        for collect in collects:
            # 查找匹配的待回收伏笔（模糊匹配）
            matched = self._find_matching_foreshadowing(collect)
            if matched:
                self.graph.add_foreshadowing_edge(
                    from_id=matched["foreshadowing_id"],
                    to_id=f"collect_{chapter_number}_{uuid4().hex[:8]}",
                    relation_type="collect",
                    chapter=chapter_number,
                )
                self.graph.mark_foreshadowing_collected(
                    foreshadowing_id=matched["foreshadowing_id"],
                    collected_chapter=chapter_number,
                )
                log.info("伏笔回收: %s (第%d章)", collect, chapter_number)
        
        return count
    
    def _find_matching_foreshadowing(self, collect_desc: str) -> dict | None:
        """模糊匹配待回收伏笔（基于内容相似度）"""
        from difflib import SequenceMatcher
        
        pending = self.graph.get_pending_foreshadowings(current_chapter=999999)
        best_match = None
        best_score = 0.0
        
        for foreshadow in pending:
            content = foreshadow.get("content", "")
            score = SequenceMatcher(None, collect_desc, content).ratio()
            if score > best_score:
                best_score = score
                best_match = foreshadow
        
        if best_score >= 0.5:  # 50% 相似度
            return best_match
        return None
```

#### 2.2 从章节文本确认（写后）

章节生成后，检查文本中是否真的埋设/回收了伏笔（防止 LLM 遗忘执行 chapter_brief）：

```python
class ForeshadowingService:
    # ... (续上)
    
    def verify_foreshadowings_in_text(
        self,
        chapter_text: str,
        chapter_number: int,
        planned_plants: list[str],
        planned_collects: list[str],
    ) -> dict[str, Any]:
        """验证伏笔是否真的在文本中执行
        
        Returns:
            {
                "plants_confirmed": list[str],
                "plants_missing": list[str],
                "collects_confirmed": list[str],
                "collects_missing": list[str],
            }
        """
        result = {
            "plants_confirmed": [],
            "plants_missing": [],
            "collects_confirmed": [],
            "collects_missing": [],
        }
        
        # 简单关键词匹配（可选 LLM 深度分析）
        for plant in planned_plants:
            keywords = self._extract_keywords(plant)
            if any(kw in chapter_text for kw in keywords):
                result["plants_confirmed"].append(plant)
            else:
                result["plants_missing"].append(plant)
                log.warning("伏笔埋设缺失: %s (第%d章)", plant, chapter_number)
        
        for collect in planned_collects:
            keywords = self._extract_keywords(collect)
            if any(kw in chapter_text for kw in keywords):
                result["collects_confirmed"].append(collect)
            else:
                result["collects_missing"].append(collect)
                log.warning("伏笔回收缺失: %s (第%d章)", collect, chapter_number)
        
        return result
    
    def _extract_keywords(self, desc: str, top_n: int = 3) -> list[str]:
        """从描述中提取关键词（简单实现：取前3个名词）"""
        import jieba.posseg as pseg
        words = pseg.cut(desc)
        nouns = [w for w, flag in words if flag.startswith('n')]
        return nouns[:top_n]
```

### 3. 集成点

#### 3.1 写前注入（ContinuityService）

在 `generate_brief()` 中增加待回收伏笔列表：

```python
# src/novel/services/continuity_service.py (扩展)

def _extract_pending_foreshadowings(
    self,
    brief: dict[str, Any],
    chapter_number: int,
    novel_memory: Any,
) -> None:
    """注入待回收伏笔列表"""
    if not hasattr(novel_memory, "knowledge_graph"):
        return
    
    try:
        pending = novel_memory.knowledge_graph.get_pending_foreshadowings(chapter_number)
        
        # 分类：即将遗忘 vs 正常待回收
        forgotten = [f for f in pending if f["is_forgotten"]]
        normal = [f for f in pending if not f["is_forgotten"]]
        
        brief["pending_foreshadowings"] = normal[:5]  # 限制数量
        brief["forgotten_foreshadowings"] = forgotten[:3]  # 优先级最高
    except Exception:
        log.warning("伏笔图谱查询失败", exc_info=True)
```

在 `format_for_prompt()` 中输出：

```python
# 在 format_for_prompt() 末尾
forgotten = brief.get("forgotten_foreshadowings", [])
if forgotten:
    sections.append("### ⚠️ 即将遗忘的伏笔（必须本章提及或回收）")
    for f in forgotten:
        sections.append(
            f"- 第{f['planted_chapter']}章埋设: {f['content']} "
            f"(已 {f['chapters_since_plant']} 章未提及)"
        )
    sections.append("")

pending = brief.get("pending_foreshadowings", [])
if pending:
    sections.append("### 待回收伏笔")
    for f in pending:
        target = f"→ 第{f['target_chapter']}章" if f['target_chapter'] > 0 else ""
        sections.append(
            f"- 第{f['planted_chapter']}章: {f['content']} {target}"
        )
    sections.append("")
```

#### 3.2 写后验证（pipeline.py）

在章节生成后：

```python
# 位置：pipeline.py 第 ~1450 行（实体提取后）

# ========== 伏笔验证与图更新 ==========
if self.memory and hasattr(self.memory, "knowledge_graph"):
    try:
        from src.novel.services.foreshadowing_service import ForeshadowingService
        foreshadow_svc = ForeshadowingService(self.memory.knowledge_graph, llm_client=None)
        
        # 注册计划的伏笔（从 chapter_brief）
        ch_brief = ch_outline.get("chapter_brief", {})
        foreshadow_svc.register_planned_foreshadowings(ch_brief, ch_num)
        
        # 验证文本中是否真的执行了
        plants = ch_brief.get("foreshadowing_plant", [])
        collects = ch_brief.get("foreshadowing_collect", [])
        verification = foreshadow_svc.verify_foreshadowings_in_text(
            chapter_text=state["current_chapter_text"],
            chapter_number=ch_num,
            planned_plants=plants if isinstance(plants, list) else [plants],
            planned_collects=collects if isinstance(collects, list) else [collects],
        )
        
        if verification["plants_missing"]:
            log.warning("第%d章伏笔埋设缺失: %s", ch_num, verification["plants_missing"])
        if verification["collects_missing"]:
            log.warning("第%d章伏笔回收缺失: %s", ch_num, verification["collects_missing"])
    except Exception as exc:
        log.warning("伏笔图谱更新失败（非阻塞）: %s", exc)
```

### 4. API 接口

见上文 `ForeshadowingService` 类。

### 5. 省 Token 策略

1. **图优先**: 伏笔追踪完全基于 NetworkX 图，无 LLM 成本
2. **规则验证**: 写后验证用关键词匹配，不调用 LLM
3. **模糊匹配**: 回收伏笔用 SequenceMatcher（本地），不调用 LLM
4. **懒加载 LLM**: 仅在需要深度分析伏笔内涵时才用 LLM（可选功能）

### 6. 任务拆分

#### Phase 1: 图存储扩展 (1-2h)
1. 扩展 `KnowledgeGraph` — 伏笔节点/边操作
2. 实现 `get_pending_foreshadowings()` — 查询待回收伏笔
3. 测试：图操作单元测试

#### Phase 2: 服务层与注册 (2h)
1. 实现 `ForeshadowingService` — 注册/验证/查询
2. 集成到 `pipeline.py` — 写后注册与验证
3. 测试：模拟伏笔埋设→回收流程

#### Phase 3: ContinuityService 注入 (1h)
1. 扩展 `ContinuityService` — 注入待回收/遗忘伏笔
2. 测试：生成章节时检查 prompt 是否包含伏笔提示

---

## P2: 覆盖率指标 + 别名合并

### 1. 数据模型

#### 1.1 健康度指标模型

```python
# src/novel/models/health.py

from pydantic import BaseModel, Field

class HealthMetrics(BaseModel):
    """小说项目健康度指标"""
    
    # 伏笔覆盖
    foreshadowing_total: int = Field(0, ge=0, description="总伏笔数")
    foreshadowing_collected: int = Field(0, ge=0, description="已回收伏笔数")
    foreshadowing_abandoned: int = Field(0, ge=0, description="已废弃伏笔数")
    foreshadowing_forgotten: int = Field(0, ge=0, description="即将遗忘伏笔数")
    foreshadowing_collection_rate: float = Field(0.0, ge=0.0, le=1.0, description="回收率")
    
    # 里程碑进度
    milestone_total: int = Field(0, ge=0)
    milestone_completed: int = Field(0, ge=0)
    milestone_overdue: int = Field(0, ge=0)
    milestone_completion_rate: float = Field(0.0, ge=0.0, le=1.0)
    
    # 角色覆盖
    character_total: int = Field(0, ge=0)
    character_active: int = Field(0, ge=0, description="有出场记录的角色数")
    character_coverage: float = Field(0.0, ge=0.0, le=1.0, description="角色出场覆盖率")
    character_top_10_appearance_ratio: float = Field(
        0.0, ge=0.0, le=1.0, description="前10角色占总出场的比例"
    )
    
    # 实体一致性
    entity_total: int = Field(0, ge=0)
    entity_conflict_count: int = Field(0, ge=0, description="名称冲突数")
    entity_consistency_score: float = Field(
        1.0, ge=0.0, le=1.0, description="实体一致性得分 (1-冲突率)"
    )
    
    # 叙事债务
    debt_total: int = Field(0, ge=0)
    debt_overdue: int = Field(0, ge=0)
    debt_health: str = Field("healthy", description="healthy/warning/critical")
    
    # 综合得分
    overall_health_score: float = Field(
        0.0, ge=0.0, le=100.0, description="综合健康度得分 (0-100)"
    )
```

### 2. 指标计算逻辑

#### 2.1 HealthService

```python
# src/novel/services/health_service.py

from src.novel.models.health import HealthMetrics

class HealthService:
    """小说项目健康度计算服务"""
    
    def __init__(
        self,
        structured_db,
        knowledge_graph,
        obligation_tracker=None,
        milestone_tracker=None,
    ):
        self.db = structured_db
        self.graph = knowledge_graph
        self.obligation_tracker = obligation_tracker
        self.milestone_tracker = milestone_tracker
    
    def compute_health_metrics(self, current_chapter: int, novel_data: dict) -> HealthMetrics:
        """计算完整健康度指标"""
        metrics = HealthMetrics()
        
        # 伏笔覆盖
        self._compute_foreshadowing_metrics(metrics, current_chapter)
        
        # 里程碑进度
        self._compute_milestone_metrics(metrics, current_chapter, novel_data)
        
        # 角色覆盖
        self._compute_character_metrics(metrics, current_chapter, novel_data)
        
        # 实体一致性
        self._compute_entity_metrics(metrics)
        
        # 叙事债务
        self._compute_debt_metrics(metrics, current_chapter)
        
        # 综合得分
        metrics.overall_health_score = self._compute_overall_score(metrics)
        
        return metrics
    
    def _compute_foreshadowing_metrics(self, metrics: HealthMetrics, current_chapter: int) -> None:
        """伏笔覆盖率"""
        try:
            all_nodes = self.graph.graph.nodes(data=True)
            foreshadowings = [
                (nid, attrs) for nid, attrs in all_nodes
                if attrs.get("type") == "foreshadowing"
            ]
            
            metrics.foreshadowing_total = len(foreshadowings)
            metrics.foreshadowing_collected = sum(
                1 for _, attrs in foreshadowings
                if attrs.get("status") == "collected"
            )
            metrics.foreshadowing_abandoned = sum(
                1 for _, attrs in foreshadowings
                if attrs.get("status") == "abandoned"
            )
            
            # 即将遗忘（10章未提及）
            forgotten = 0
            for nid, attrs in foreshadowings:
                if attrs.get("status") != "pending":
                    continue
                last_mention = attrs.get("last_mentioned_chapter", attrs.get("planted_chapter", 0))
                if current_chapter - last_mention >= 10:
                    forgotten += 1
            metrics.foreshadowing_forgotten = forgotten
            
            # 回收率
            if metrics.foreshadowing_total > 0:
                metrics.foreshadowing_collection_rate = (
                    metrics.foreshadowing_collected / metrics.foreshadowing_total
                )
        except Exception:
            log.warning("伏笔指标计算失败", exc_info=True)
    
    def _compute_milestone_metrics(
        self,
        metrics: HealthMetrics,
        current_chapter: int,
        novel_data: dict,
    ) -> None:
        """里程碑进度"""
        if not self.milestone_tracker:
            return
        
        try:
            progress = self.milestone_tracker.compute_volume_progress(current_chapter)
            metrics.milestone_total = (
                len(progress.get("milestones_completed", []))
                + len(progress.get("milestones_pending", []))
                + len(progress.get("milestones_overdue", []))
            )
            metrics.milestone_completed = len(progress.get("milestones_completed", []))
            metrics.milestone_overdue = len(progress.get("milestones_overdue", []))
            
            if metrics.milestone_total > 0:
                metrics.milestone_completion_rate = (
                    metrics.milestone_completed / metrics.milestone_total
                )
        except Exception:
            log.warning("里程碑指标计算失败", exc_info=True)
    
    def _compute_character_metrics(
        self,
        metrics: HealthMetrics,
        current_chapter: int,
        novel_data: dict,
    ) -> None:
        """角色出场覆盖率"""
        try:
            characters = novel_data.get("characters", [])
            metrics.character_total = len(characters)
            
            # 查询每个角色的出场次数（从 character_states 表）
            appearance_counts = {}
            for char in characters:
                char_id = char.get("character_id", "")
                if not char_id:
                    continue
                
                # 查询该角色在所有章节的状态记录数
                with self.db.transaction() as cur:
                    cur.execute(
                        "SELECT COUNT(*) as cnt FROM character_states WHERE character_id = ?",
                        (char_id,),
                    )
                    row = cur.fetchone()
                    count = row["cnt"] if row else 0
                appearance_counts[char_id] = count
            
            # 活跃角色数（至少出场1次）
            metrics.character_active = sum(1 for cnt in appearance_counts.values() if cnt > 0)
            
            # 覆盖率
            if metrics.character_total > 0:
                metrics.character_coverage = metrics.character_active / metrics.character_total
            
            # 前10角色占比
            sorted_counts = sorted(appearance_counts.values(), reverse=True)
            top_10_sum = sum(sorted_counts[:10])
            total_sum = sum(sorted_counts)
            if total_sum > 0:
                metrics.character_top_10_appearance_ratio = top_10_sum / total_sum
        except Exception:
            log.warning("角色指标计算失败", exc_info=True)
    
    def _compute_entity_metrics(self, metrics: HealthMetrics) -> None:
        """实体一致性得分"""
        try:
            entities = self.db.get_all_entities()
            metrics.entity_total = len(entities)
            
            # 计算名称冲突数（相似度 >= 0.7 的同类型实体对）
            from difflib import SequenceMatcher
            conflict_count = 0
            
            by_type = {}
            for ent in entities:
                t = ent.get("entity_type", "other")
                by_type.setdefault(t, []).append(ent)
            
            for etype, group in by_type.items():
                for i, ent1 in enumerate(group):
                    for ent2 in group[i+1:]:
                        name1 = ent1.get("canonical_name", "")
                        name2 = ent2.get("canonical_name", "")
                        ratio = SequenceMatcher(None, name1, name2).ratio()
                        if 0.7 <= ratio < 1.0:  # 相似但不完全一致
                            conflict_count += 1
            
            metrics.entity_conflict_count = conflict_count
            
            # 一致性得分 = 1 - 冲突率
            if metrics.entity_total > 0:
                conflict_rate = conflict_count / metrics.entity_total
                metrics.entity_consistency_score = max(0.0, 1.0 - conflict_rate)
        except Exception:
            log.warning("实体指标计算失败", exc_info=True)
    
    def _compute_debt_metrics(self, metrics: HealthMetrics, current_chapter: int) -> None:
        """叙事债务健康度"""
        if not self.obligation_tracker:
            return
        
        try:
            stats = self.obligation_tracker.get_debt_statistics()
            metrics.debt_total = stats.get("total_count", 0)
            metrics.debt_overdue = stats.get("overdue_count", 0)
            
            # 健康状态
            if metrics.debt_overdue == 0:
                metrics.debt_health = "healthy"
            elif metrics.debt_overdue <= 2:
                metrics.debt_health = "warning"
            else:
                metrics.debt_health = "critical"
        except Exception:
            log.warning("债务指标计算失败", exc_info=True)
    
    def _compute_overall_score(self, metrics: HealthMetrics) -> float:
        """综合健康度得分 (0-100)
        
        权重分配：
        - 伏笔回收率: 20%
        - 里程碑完成率: 25%
        - 角色覆盖率: 15%
        - 实体一致性: 20%
        - 债务健康度: 20%
        """
        score = 0.0
        
        # 伏笔回收率 (20分)
        score += metrics.foreshadowing_collection_rate * 20
        
        # 里程碑完成率 (25分)
        score += metrics.milestone_completion_rate * 25
        
        # 角色覆盖率 (15分)
        score += metrics.character_coverage * 15
        
        # 实体一致性 (20分)
        score += metrics.entity_consistency_score * 20
        
        # 债务健康度 (20分)
        debt_score_map = {"healthy": 20, "warning": 10, "critical": 0}
        score += debt_score_map.get(metrics.debt_health, 0)
        
        # 惩罚项：即将遗忘的伏笔每个 -2 分
        penalty = min(20, metrics.foreshadowing_forgotten * 2)
        score = max(0, score - penalty)
        
        return score
```

### 3. 别名合并

在 P0 的 `EntityService.merge_aliases()` 已实现，此处扩展为应用到 `CharacterProfile`：

```python
# src/novel/models/character.py (扩展)

class CharacterProfile(BaseModel):
    # ... (现有字段)
    alias: list[str] = Field(default_factory=list)  # 已存在
    
    # 新增：别名归一化配置
    canonical_name_override: str | None = Field(
        None, description="手动指定的规范名（覆盖 name）"
    )
```

在 `NovelPipeline` 中增加别名归一化方法：

```python
# src/novel/pipeline.py (扩展)

def normalize_character_aliases(self, project_path: str) -> dict:
    """归一化角色别名（合并相似角色）
    
    Returns:
        {
            "merged_count": int,
            "conflicts": list[dict],  # 需要人工确认的冲突
        }
    """
    novel_id = Path(project_path).name
    fm = self._get_file_manager()
    novel_data = fm.load_novel(novel_id)
    
    characters = novel_data.get("characters", [])
    merged_count = 0
    conflicts = []
    
    from difflib import SequenceMatcher
    
    # N^2 比较（小规模项目可接受）
    for i, char1 in enumerate(characters):
        for char2 in characters[i+1:]:
            name1 = char1.get("name", "")
            name2 = char2.get("name", "")
            
            ratio = SequenceMatcher(None, name1, name2).ratio()
            if ratio >= 0.8:
                # 高相似度：建议合并
                conflicts.append({
                    "char1_id": char1.get("character_id"),
                    "char1_name": name1,
                    "char2_id": char2.get("character_id"),
                    "char2_name": name2,
                    "similarity": ratio,
                    "auto_mergeable": ratio >= 0.95,
                })
                
                # 自动合并（相似度 >= 95%）
                if ratio >= 0.95:
                    # 将 char2 的别名追加到 char1
                    aliases1 = char1.get("alias", [])
                    if name2 not in aliases1:
                        aliases1.append(name2)
                    char1["alias"] = aliases1
                    
                    # 标记 char2 为已废弃
                    char2["status"] = "merged"
                    char2["merged_into"] = char1.get("character_id")
                    
                    merged_count += 1
    
    # 保存
    fm.save_novel(novel_id, novel_data)
    
    return {
        "merged_count": merged_count,
        "conflicts": [c for c in conflicts if not c["auto_mergeable"]],
    }
```

### 4. 集成点

#### 4.1 Pipeline 新增 `get_status()` 方法

```python
# src/novel/pipeline.py (扩展)

def get_status(self, project_path: str) -> dict:
    """获取项目状态和健康度指标"""
    novel_id = Path(project_path).name
    fm = self._get_file_manager()
    novel_data = fm.load_novel(novel_id)
    
    # 基础信息
    status = {
        "novel_id": novel_id,
        "title": novel_data.get("title", ""),
        "genre": novel_data.get("genre", ""),
        "total_chapters": len(novel_data.get("outline", {}).get("chapters", [])),
        "completed_chapters": len(fm.list_chapters(novel_id)),
    }
    
    # 健康度指标
    try:
        from src.novel.services.health_service import HealthService
        from src.novel.storage.novel_memory import NovelMemory
        from src.novel.services.obligation_tracker import ObligationTracker
        from src.novel.services.milestone_tracker import MilestoneTracker
        
        memory = NovelMemory(novel_id, self.workspace)
        obligation_tracker = ObligationTracker(memory.structured_db)
        milestone_tracker = MilestoneTracker(novel_data)
        
        health_svc = HealthService(
            structured_db=memory.structured_db,
            knowledge_graph=memory.knowledge_graph,
            obligation_tracker=obligation_tracker,
            milestone_tracker=milestone_tracker,
        )
        
        current_chapter = status["completed_chapters"]
        metrics = health_svc.compute_health_metrics(current_chapter, novel_data)
        status["health_metrics"] = metrics.model_dump()
    except Exception as exc:
        log.warning("健康度指标计算失败: %s", exc)
        status["health_metrics"] = None
    
    return status
```

#### 4.2 CLI 输出美化

在 `main.py` 中扩展 `novel status` 命令：

```python
# main.py (扩展)

@novel.command()
@click.argument("project_path", type=click.Path(exists=True))
def status(project_path: str):
    """显示项目状态和健康度"""
    from src.novel.pipeline import NovelPipeline
    from rich.console import Console
    from rich.table import Table
    
    console = Console()
    pipe = NovelPipeline(workspace="workspace")
    
    status_data = pipe.get_status(project_path)
    
    # 基础信息
    console.print(f"\n[bold cyan]项目: {status_data['title']}[/bold cyan]")
    console.print(f"题材: {status_data['genre']}")
    console.print(f"进度: {status_data['completed_chapters']}/{status_data['total_chapters']} 章\n")
    
    # 健康度指标
    metrics = status_data.get("health_metrics")
    if not metrics:
        console.print("[yellow]健康度指标不可用[/yellow]")
        return
    
    # 综合得分
    score = metrics["overall_health_score"]
    score_color = "green" if score >= 80 else "yellow" if score >= 60 else "red"
    console.print(f"[bold {score_color}]综合健康度: {score:.1f}/100[/bold {score_color}]\n")
    
    # 详细指标表格
    table = Table(title="健康度详细指标")
    table.add_column("指标", style="cyan")
    table.add_column("数值", justify="right")
    table.add_column("状态", justify="center")
    
    # 伏笔
    table.add_row(
        "伏笔回收率",
        f"{metrics['foreshadowing_collected']}/{metrics['foreshadowing_total']} ({metrics['foreshadowing_collection_rate']*100:.1f}%)",
        "✅" if metrics['foreshadowing_collection_rate'] >= 0.7 else "⚠️",
    )
    if metrics['foreshadowing_forgotten'] > 0:
        table.add_row(
            "即将遗忘伏笔",
            str(metrics['foreshadowing_forgotten']),
            "❌",
        )
    
    # 里程碑
    table.add_row(
        "里程碑完成率",
        f"{metrics['milestone_completed']}/{metrics['milestone_total']} ({metrics['milestone_completion_rate']*100:.1f}%)",
        "✅" if metrics['milestone_completion_rate'] >= 0.8 else "⚠️",
    )
    if metrics['milestone_overdue'] > 0:
        table.add_row(
            "逾期里程碑",
            str(metrics['milestone_overdue']),
            "❌",
        )
    
    # 角色
    table.add_row(
        "角色出场覆盖",
        f"{metrics['character_active']}/{metrics['character_total']} ({metrics['character_coverage']*100:.1f}%)",
        "✅" if metrics['character_coverage'] >= 0.6 else "⚠️",
    )
    
    # 实体
    table.add_row(
        "实体一致性",
        f"{metrics['entity_consistency_score']*100:.1f}% ({metrics['entity_conflict_count']} 冲突)",
        "✅" if metrics['entity_consistency_score'] >= 0.95 else "⚠️",
    )
    
    # 债务
    debt_emoji = {"healthy": "✅", "warning": "⚠️", "critical": "❌"}
    table.add_row(
        "叙事债务",
        f"{metrics['debt_total']} 总计, {metrics['debt_overdue']} 逾期",
        debt_emoji.get(metrics['debt_health'], "⚠️"),
    )
    
    console.print(table)
```

### 5. 省 Token 策略

1. **纯本地计算**: 所有指标计算基于数据库查询和规则，零 LLM 成本
2. **惰性触发**: 仅在 `novel status` 命令时计算，不在每章生成时自动执行
3. **缓存**: 可选地将健康度指标缓存到 novel.json，避免重复计算

### 6. 任务拆分

#### Phase 1: 健康度服务 (2h)
1. 创建 `src/novel/models/health.py` — HealthMetrics 模型
2. 实现 `HealthService` — 5大指标计算逻辑
3. 测试：单元测试（模拟数据库查询）

#### Phase 2: Pipeline 集成 (1h)
1. 扩展 `NovelPipeline.get_status()` — 调用 HealthService
2. 扩展 `main.py novel status` — Rich 表格美化输出
3. 测试：端到端测试（真实项目）

#### Phase 3: 别名归一化 (1h)
1. 实现 `NovelPipeline.normalize_character_aliases()` — 角色别名合并
2. 新增 CLI 命令 `python main.py novel merge-aliases <project>`
3. 测试：模拟相似角色合并

---

## 总体任务优先级

### P0 实体索引 (优先级最高)
- 直接提升一致性检查质量
- 为 P1/P2 提供数据基础
- 预计 6-8 小时

### P1 伏笔图谱 (中等优先级)
- 解决长篇小说伏笔遗忘问题
- 依赖现有 NetworkX 图，改动小
- 预计 4-5 小时

### P2 健康度指标 (低优先级)
- 辅助监控功能，非核心写作流程
- 可后续迭代优化
- 预计 4 小时

**总计**: 14-17 小时（约 2 个工作日）

---

## 测试策略

### 单元测试
- `test_entity_extractor.py` — 规则提取器黑名单/正则测试
- `test_entity_service.py` — 注册/去重/别名合并
- `test_foreshadowing_service.py` — 图操作/遗忘检测
- `test_health_service.py` — 指标计算（Mock DB）

### 集成测试
- `test_entity_pipeline_integration.py` — 生成章节→提取实体→下章注入
- `test_foreshadowing_pipeline_integration.py` — 埋设→回收→遗忘警报
- `test_status_command.py` — CLI 命令输出格式

### 回归测试
- 确保现有 `generate_chapters()` 流程不受影响
- 确保 ConsistencyChecker 现有功能正常
- 确保 ContinuityService 输出格式兼容

---

## 文档更新

需同步更新以下文档：

1. **CLAUDE.md** — 新增 P0/P1/P2 功能说明
2. **Memory 文档** — 实体索引/伏笔图谱架构
3. **API 文档** — EntityService/ForeshadowingService 方法签名
4. **CLI 帮助** — `novel status` / `novel merge-aliases` 命令

---

## 风险与缓解

### 风险 1: 规则提取准确率低
**缓解**: 提供 LLM fallback，并支持手动编辑实体库

### 风险 2: NetworkX 图序列化性能问题
**缓解**: 已采用 JSON 格式（比 pickle 快），可选增量持久化

### 风险 3: 别名合并误判
**缓解**: 高相似度（95%+）自动合并，中等相似度（80-95%）需人工确认

### 风险 4: 健康度指标计算耗时
**缓解**: 仅在 `status` 命令时触发，不阻塞章节生成

---

## 后续迭代方向

1. **实体可视化**: Web UI 展示实体图谱
2. **伏笔推荐**: LLM 根据待回收伏笔生成回收建议
3. **健康度告警**: 自动发送项目健康度周报
4. **实体关系网**: 扩展为角色-地点-势力-器物多层关系图

---

## 结语

本设计规格完整覆盖三个功能的数据模型、提取逻辑、集成点、API 接口、省 Token 策略和任务拆分。所有功能均遵循"规则优先、LLM fallback"原则，与现有 pipeline 深度集成，最小化对现有代码的侵入。

**核心原则**:
- 写后提取→写前注入（闭环）
- 规则优先（省 Token）
- 增量索引（性能）
- 优雅降级（可选功能失败不阻塞主流程）

所有实现均为同步（SYNC），与现有 LLMClient 接口一致，可直接开始实施。

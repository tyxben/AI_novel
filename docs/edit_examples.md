# 小说设定编辑 — 自然语言示例库

`NovelEditService` 接受两种输入：**自然语言指令**（走 `IntentParser` 解析）
与 **结构化变更**（直接应用）。本文集中示例前者，用于 MCP / CLI /
Web UI 的常见场景。

---

## 1. 添加实体

### 添加角色
```
"添加一个17岁女主角柳青鸾，丹师，第6章出场"
"新增反派萧九幽，40岁魔修长老"
"给小说加一个配角王五，剑客"
```

解析后走 `add_character`：自动生成 `character_id`、补齐
`appearance`/`personality` 默认结构，写入 `novel.characters`。

### 新增章节大纲
```
"在第3章后插入一章：暗流涌动，反派联盟成立"
"补一个第12章的大纲：主角突破，与师兄切磋"
```

### 世界观扩展
```
"世界观增加魔法学院的设定"
"新增术语：真气 = 武者内力来源"
```

---

## 2. 修改现有实体

### 修改角色属性
```
"把张三的年龄改为20岁"
"主角的性格从冲动改为冷静"
"萧炎改名叫萧炎天"
```

### 修改章节
```
"第5章的情绪基调改为小爽"
"第10章的关键事件加入'师门背叛'"
```

### 修改世界观
```
"把设定时代改为上古洪荒"
"灵气术语的解释更精确：灵气 = 天地元气的凝练形态"
```

---

## 3. 删除（软删除）

```
"删除配角赵六"
"主角师父在第15章去世"
```

角色被软删除：`status` 变为 `retired`（或 `deceased`），
`deprecated_at_chapter` 设为生效章节。原角色仍保留在列表用于回溯查询。

---

## 4. 预览影响（dry-run）

高风险变更建议先预览再执行：

CLI：
```bash
python main.py novel edit workspace/novels/novel_xxx \
  -i "删除角色张三" --dry-run
```

MCP：
```python
novel_analyze_change_impact(
    project_path="workspace/novels/novel_xxx",
    instruction="删除角色张三",
)
```

返回 `impact_report`：
```json
{
  "affected_chapters": [5, 7, 10],
  "severity": "critical",
  "conflicts": ["角色「张三」在第 5,7,10 章大纲中被引用..."],
  "warnings": [],
  "summary": "删除角色「张三」影响 3 个章节，严重程度: critical。"
}
```

严重度分级：
- **low** — 新增 / 无后续章节引用
- **high** — 1-2 章受影响
- **critical** — ≥3 章受影响

---

## 5. 回滚

每次成功 `edit()` 写入 `changelogs/{change_id}.json`；查历史后按
`change_id` 回滚：

```bash
python main.py novel history workspace/novels/novel_xxx --limit 10
python main.py novel rollback workspace/novels/novel_xxx <change_id>
```

- 回滚本身作为新变更写入日志（`change_type="rollback"`，
  `reverted_change_id` 指向原变更）
- 默认检查后续是否有针对同实体的变更，若有则拒绝；
  `--force` 可绕过
- 拒绝回滚 rollback 本身

---

## 6. 批量操作

服务层 API（尚未暴露为 CLI）：
```python
from src.novel.services.edit_service import NovelEditService

service = NovelEditService(workspace="workspace")
results = service.batch_edit(
    project_path="workspace/novels/novel_xxx",
    changes=[
        {
            "change_type": "update",
            "entity_type": "outline",
            "data": {"chapter_number": i, "title": f"第{i}章新标题"},
        }
        for i in range(10, 16)
    ],
    stop_on_failure=False,  # 部分失败不中断
)
for r in results:
    print(r.status, r.change_id)
```

每条 change 产生独立 change_id + changelog 条目，保持回滚粒度。

---

## 7. 指令写作建议

- **指定实体要准确**：用角色名（"张三"）而非代词（"他"）
- **生效章节显式**：长期角色状态变更建议带 `effective_from_chapter`
- **一次只改一件事**：多意图混合（既改名又改年龄又换角色）IntentParser 解析不稳定，建议拆分或走 `structured_change`
- **先预览再执行**：删除 / 核心属性修改务必先 `--dry-run`

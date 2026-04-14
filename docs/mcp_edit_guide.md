# MCP 编辑工具指南

`mcp_server.py` 暴露了 3 个小说编辑工具，供 Claude Desktop / Claude Code
等 MCP 客户端调用。

---

## 工具一览

| 工具 | 用途 | 是否写盘 |
|------|------|---------|
| `novel_edit_setting` | 自然语言编辑角色/大纲/世界观 | 是（除非 `dry_run=True`） |
| `novel_analyze_change_impact` | 预览影响，不改文件 | 否 |
| `novel_get_change_history` | 查变更历史 | 否 |

所有工具都有路径穿越保护：`project_path` 必须在 `_DEFAULT_WORKSPACE`
之内；越界直接返回 `{"status": "failed", "error": ...}`。

---

## `novel_edit_setting`

**签名**：
```python
novel_edit_setting(
    project_path: str,
    instruction: str,
    effective_from_chapter: int | None = None,
    dry_run: bool = False,
) -> dict
```

**示例**：
```python
result = novel_edit_setting(
    project_path="workspace/novels/novel_abc12345",
    instruction="添加一个30岁女剑客反派角色柳青鸾，第10章出场",
)
```

**返回**（成功）：
```json
{
  "change_id": "c8e9f0a1-...",
  "status": "success",
  "change_type": "add",
  "entity_type": "character",
  "entity_id": "柳青鸾-的-character_id",
  "old_value": null,
  "new_value": { "name": "柳青鸾", "age": 30, ... },
  "effective_from_chapter": 10,
  "reasoning": "用户要求添加反派角色...",
  "impact_report": { "severity": "low", ... }
}
```

**dry_run=True**：`status="preview"`，仅返回解析结果 + 影响报告，不写盘。

---

## `novel_analyze_change_impact`

与 `novel_edit_setting(dry_run=True)` 等价，但更语义化，专用于"我想改
X，先告诉我后果"的场景。返回结构同 preview。

```python
impact = novel_analyze_change_impact(
    project_path="workspace/novels/novel_abc12345",
    instruction="删除主角张三",
)
if impact["impact_report"]["severity"] == "critical":
    print("危险！影响以下章节：", impact["impact_report"]["affected_chapters"])
```

---

## `novel_get_change_history`

```python
history = novel_get_change_history(
    project_path="workspace/novels/novel_abc12345",
    limit=20,
)
# {
#   "total": 12,
#   "changes": [
#     {"change_id": "...", "change_type": "update", "timestamp": "...", ...},
#     ...
#   ]
# }
```

`limit` 会被限制到 [1, 100]。按时间倒序返回（最新在前）。
回滚记录也在其中，`change_type="rollback"`，`reverted_change_id` 指向原
变更。

---

## Claude Desktop 配置

编辑 `~/Library/Application Support/Claude/claude_desktop_config.json`
（macOS）：

```json
{
  "mcpServers": {
    "novel": {
      "command": "python",
      "args": ["-m", "mcp_server"],
      "cwd": "/path/to/AI_novel",
      "env": {"PYTHONPATH": "/path/to/AI_novel"}
    }
  }
}
```

重启 Claude Desktop 后，对话框可直接调用 `novel_*` 工具。

---

## 典型交互流

```
User: 我想把主角从修炼者改成剑修，帮我看看影响大不大
Claude: (calls novel_analyze_change_impact)
        主角被修改为剑修会影响第 5, 7, 10 章的已写内容，severity: high。
        建议先执行 dry_run 预览，确认无误后再正式写入。

User: 确认，执行
Claude: (calls novel_edit_setting)
        已完成。change_id: xxx。受影响章节建议后续重写。

User: 我后悔了
Claude: (calls novel_get_change_history → novel_edit_setting /rollback)
        已查到 change_id xxx，正在回滚...
```

**注**：`rollback` 目前只有 CLI 与服务层 API，尚未暴露为 MCP 工具。

---

## 错误处理

所有工具在异常路径统一返回：
```json
{"status": "failed", "error": "<message>"}
```

常见错误：
- `路径不在工作空间内: ...` — project_path 穿越
- `小说项目不存在: novel_xxx` — novel_id 拼错
- `小说 'novel_xxx' 正被其他进程编辑` — 并发锁冲突（Unix），可重试
- LLM 解析失败 — IntentParser 3 次重试后抛错

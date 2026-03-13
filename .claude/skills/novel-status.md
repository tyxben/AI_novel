---
name: novel-status
description: 查看小说项目状态和进度
---

# 项目状态查看

当用户调用 `/novel-status` 时，展示小说项目的状态信息。

## 执行逻辑

### 无参数 — 列出所有项目

调用 `novel_list_projects` MCP 工具，或：

```python
from pathlib import Path
import json

novels_dir = Path("workspace/novels")
for d in sorted(novels_dir.iterdir()):
    if d.is_dir() and (d / "novel.json").exists():
        data = json.loads((d / "novel.json").read_text(encoding="utf-8"))
        outline = data.get("outline", {})
        total = len(outline.get("chapters", []))
        current = data.get("current_chapter", 0)
        print(f"{d.name} | {data.get('title', '?')} | {data.get('status')} | {current}/{total}章")
```

以表格形式展示：

| 项目 ID | 标题 | 状态 | 进度 |
|---------|------|------|------|
| novel_xxx | 少年修炼 | generating | 5/40 章 |

### 有参数 — 显示详细状态

如果用户指定了项目（`/novel-status novel_xxx`），调用 `novel_get_status` 获取详情：

- 标题、状态
- 章节进度：X / Y 章（附进度条）
- 已写字数 / 目标字数
- 笔名、目标读者
- 主角列表
- 标签
- 简介
- 错误数（如有）

### 输出格式示例

```
📖 少年修炼逆天改命
   状态: generating
   进度: ████████░░░░░░░░ 12/40 章 (30%)
   字数: 28,500 / 100,000
   主角: 林风, 苏瑶
   标签: 玄幻, 升级, 热血
```

---
name: novel-write
description: 批量生成小说章节，支持断点续写
---

# 生成小说章节

当用户调用 `/novel-write` 时，为已有项目生成章节。

## 步骤

### 1. 选择项目

如果用户没有指定项目：
- 列出所有项目（调用 `novel_list_projects` MCP 工具，或扫描 `workspace/novels/`）
- 显示每个项目的标题、状态、进度（已写/总章数）
- 让用户选择

如果用户指定了项目名或 ID，直接使用。

### 2. 确认续写进度

获取项目状态，显示：
- 当前进度：第 X / Y 章
- 已写字数
- 接下来要生成的范围

询问本次要生成多少章（默认 5 章）。

### 3. 执行生成

**方式 A — MCP 工具（优先）：**
```
调用 novel_generate_chapters(project_path="workspace/novels/novel_xxx", batch_size=5)
```

**方式 B — Python 直接调用：**
```python
from src.novel.pipeline import NovelPipeline
from src.novel.storage.file_manager import FileManager

pipe = NovelPipeline()
fm = FileManager("workspace")
novel_id = "novel_xxx"

# 检查进度
completed = fm.list_chapters(novel_id)
start = max(completed) + 1 if completed else 1

# 生成
result = pipe.generate_chapters(
    project_path=f"workspace/novels/{novel_id}",
    start_chapter=start,
    end_chapter=start + 4,
    silent=True,
)
```

### 4. 展示结果

每批生成完成后：
- 显示生成了哪些章节
- 读取最后一章的前 500 字作为预览
- 显示当前总进度
- 如有错误，列出具体信息

### 5. 循环询问

问用户：
- **继续写下一批？** — 再次执行生成
- **查看某章内容？** — 调用 `novel_read_chapter`
- **给反馈？** — 引导使用 `/novel-review`
- **结束** — 停止

### 注意事项

- 每章生成约需 30-60 秒，5 章约 3-5 分钟
- 生成过程中会自动保存 checkpoint，中断后可安全续写
- 连续 3 章失败会自动中止，需检查 LLM API 状态

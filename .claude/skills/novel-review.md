---
name: novel-review
description: 审阅小说章节并应用反馈修改
---

# 审阅与反馈

当用户调用 `/novel-review` 时，帮助他们审阅已生成的章节并应用修改。

## 步骤

### 1. 选择项目

列出项目，让用户选择（同 `/novel-write`）。

### 2. 显示概览

展示：
- 总章数、已写章数、总字数
- 章节目录列表（章号 + 标题）

### 3. 阅读章节

用户可以指定要看哪一章。读取章节内容：

**方式 A — MCP 工具：**
```
调用 novel_read_chapter(project_path="workspace/novels/novel_xxx", chapter_number=5)
```

**方式 B — Python：**
```python
from src.novel.storage.file_manager import FileManager
fm = FileManager("workspace")
text = fm.load_chapter_text("novel_xxx", 5)
```

展示完整章节文本。

### 4. 收集反馈

用户用自然语言描述问题，例如：
- "第 5 章主角性格突变了"
- "女主角描写太单薄"
- "节奏太快，战斗场面需要展开"

### 5. 先分析后执行

**第一步：干跑分析（dry_run=True）**

```
调用 novel_apply_feedback(
    project_path="workspace/novels/novel_xxx",
    feedback_text="第5章主角性格突变",
    chapter_number=5,
    dry_run=True,
)
```

向用户展示分析结果：
- 反馈类型和严重度
- 受影响的章节范围
- 重写指令预览

**第二步：确认后执行（dry_run=False）**

用户确认后，再次调用但 `dry_run=False`，实际执行重写。

### 6. 展示修改结果

- 列出被重写的章节
- 对比修改前后的字数变化
- 可选：读取重写后的章节供用户确认

### 注意事项

- 反馈重写会修改章节文件，但 checkpoint 会保留历史
- `max_propagation` 默认 10，即最多影响后续 10 章
- 建议先 dry_run 分析，避免不必要的大范围重写

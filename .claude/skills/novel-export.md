---
name: novel-export
description: 导出完成的小说为 TXT 文件
---

# 导出小说

当用户调用 `/novel-export` 时，将小说导出为完整的 TXT 文件。

## 步骤

### 1. 选择项目

如果未指定项目，列出所有项目并让用户选择。优先显示状态为 `completed` 或章节较多的项目。

### 2. 检查完成度

获取项目状态，告知用户：
- 已完成 X / Y 章
- 如果未全部完成，询问是否仍要导出当前已有章节

### 3. 执行导出

**方式 A — MCP 工具：**
```
调用 novel_export(project_path="workspace/novels/novel_xxx")
```

**方式 B — Python：**
```python
from src.novel.pipeline import NovelPipeline
pipe = NovelPipeline()
output_path = pipe.export_novel("workspace/novels/novel_xxx")
```

### 4. 展示结果

- 输出文件路径
- 文件大小
- 总字数统计
- 告知用户可以直接打开或复制文件

### 注意事项

- 导出文件默认保存在项目目录下
- 包含所有已生成的章节，按章节号排序
- 格式：章节标题 + 正文，章节间空行分隔

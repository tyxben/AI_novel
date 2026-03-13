---
name: novel-create
description: 交互式创建 AI 小说项目（大纲 + 世界观 + 角色）
---

# 创建 AI 小说项目

当用户调用 `/novel-create` 时，引导他们完成小说项目的创建。

## 步骤

### 1. 收集信息

如果用户没有在命令参数中提供，依次询问：

- **主题/灵感**（必填）：故事的核心概念，例如"少年修炼逆天改命"
- **题材**（默认"玄幻"）：都市 / 玄幻 / 武侠 / 科幻 / 言情 / 悬疑 / 轻小说 / 历史
- **目标字数**（默认 10 万字）
- **风格预设**（可选）：webnovel.shuangwen / wuxia.classical / lightnovel
- **大纲模板**（可选）：cyclic_upgrade（升级流）/ multi_thread（多线）/ classic_four_act（四幕）
- **笔名**（可选）
- **目标读者**（可选）：男频 / 女频 / 通用

如果用户提供了简短描述（如 `/novel-create 外卖小哥穿越异世界`），直接用它作为主题，其余参数用默认值，跳过询问。

### 2. 确认并执行

向用户确认参数后，调用 MCP 工具或 Python 代码创建项目：

**方式 A — MCP 工具（优先）：**
调用 `novel_create` 工具，传入收集到的参数。

**方式 B — Python 直接调用（MCP 不可用时）：**
```python
from src.novel.pipeline import NovelPipeline
pipe = NovelPipeline()
result = pipe.create_novel(
    genre="玄幻",
    theme="外卖小哥穿越异世界",
    target_words=100000,
    style="webnovel.shuangwen",
    template="cyclic_upgrade",
)
```

### 3. 展示结果

创建完成后，以易读格式展示：
- 项目 ID 和路径
- 大纲摘要（章节数、幕结构）
- 主要角色列表
- 世界观设定概要
- 建议下一步：使用 `/novel-write` 开始生成章节

### 注意事项

- 创建过程需要 1-3 分钟（LLM 生成大纲、世界观、角色），提前告知用户
- 需要有效的 LLM API Key（通过环境变量或 Web UI 设置）
- 项目文件保存在 `workspace/novels/novel_xxx/`

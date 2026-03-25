# 小说系统架构规范

## 文档索引

| 文档 | 解决什么问题 | 实施紧迫度 |
|------|-------------|-----------|
| [canonical-state.md](canonical-state.md) | checkpoint / novel.json 双源导致编辑对生成不可见 | P0 紧急 |
| [orchestration.md](orchestration.md) | graph 死代码 + 风格字段失效 + fallback 语义漂移 | P1 高 |
| [layer-contract.md](layer-contract.md) | 四层职责模糊，agent 绕过存储层等 | P2 渐进 |

## 实施路线

### 第一步: 修复数据同步 (1-2天)

对应 `canonical-state.md` 规则 3.1：

1. `generate_chapters()` 启动时从 novel.json 刷新 characters/outline/world_setting
2. `apply_feedback()` 同理
3. 编写回归测试：编辑角色 → 生成章节 → 验证新角色可见

### 第二步: 修复风格字段 + 删除死代码 (1天)

对应 `orchestration.md` 第 4-6 节：

1. Novel 模型统一为 `style_name`
2. StyleKeeper 改为读 `style_name`
3. 传播重写读 `style_name`
4. 删除 `build_init_graph()`
5. Fallback checker 串行化

### 第三步: 分层治理 (渐进)

对应 `layer-contract.md`：

1. web.py 表单编辑改走 edit_service (P1)
2. pipeline.py 中的 prompt 拼接移入 agent (P2)
3. 建立 lint 规则防止新增违规 (P2)

## 核心原则

1. **novel.json 是设定态唯一真源** — checkpoint 中的设定是快照
2. **Pipeline-first** — graph 是可选内部机制，不是架构承诺
3. **同一概念一种表达** — style_name 不再有三种写法
4. **分层禁止表比允许表更重要** — 明确谁不能做什么

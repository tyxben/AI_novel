"""ReAct Agent Framework — 通用推理循环引擎。

支持 Thought -> Action(tool call) -> Observe -> 循环。
每个具体 Agent 继承 ReactAgent 并注册自己的工具集。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from src.llm.llm_client import LLMClient

log = logging.getLogger("react")

MAX_ITERATIONS = 8  # 默认最大迭代次数


@dataclass
class ReactTool:
    """工具定义。"""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema 格式的参数描述
    func: Callable[..., Any]  # 实际执行函数
    check_tool: bool = False  # 是否是检查类工具（budget_mode 会跳过）


@dataclass
class ReactStep:
    """单次循环步骤记录。"""

    step: int
    thinking: str
    tool: str
    args: dict[str, Any]
    result: Any
    error: str | None = None


@dataclass
class ReactResult:
    """ReAct 循环最终结果。"""

    output: Any  # 最终输出（submit 工具的返回值）
    steps: list[ReactStep] = field(default_factory=list)
    total_steps: int = 0
    total_tokens: int = 0  # 总 token 消耗
    finished: bool = True  # 是否正常结束（vs 达到 max_iterations）


class ReactAgent:
    """通用 ReAct Agent 基类。

    子类继承后注册工具，调用 run() 进入循环。

    用法::

        class MyAgent(ReactAgent):
            def __init__(self, llm):
                super().__init__(llm)
                self.register_tool(ReactTool(
                    name="search",
                    description="搜索信息",
                    parameters={"query": {"type": "string", "description": "搜索关键词"}},
                    func=self._search,
                ))

            def _search(self, query: str) -> dict:
                return {"results": [...]}

        agent = MyAgent(llm_client)
        result = agent.run(task="帮我查找...", system_prompt="你是...")
    """

    def __init__(self, llm: LLMClient):
        self.llm = llm
        self._tools: dict[str, ReactTool] = {}
        # 内置 submit 工具（终止循环）
        self.register_tool(
            ReactTool(
                name="submit",
                description="提交最终结果，结束任务",
                parameters={
                    "result": {"type": "string", "description": "最终结果"}
                },
                func=lambda result: result,
            )
        )

    def register_tool(self, tool: ReactTool) -> None:
        """注册一个工具。"""
        self._tools[tool.name] = tool

    def _format_tools_for_prompt(self, budget_mode: bool = False) -> str:
        """将注册的工具转换为 LLM 可理解的工具描述。"""
        lines = []
        for t in self._tools.values():
            if budget_mode and t.check_tool:
                continue  # budget_mode 下隐藏检查类工具
            params = ", ".join(
                f'{k}: {v.get("type", "string")}'
                for k, v in t.parameters.items()
            )
            lines.append(f"- {t.name}({params}): {t.description}")
        return "\n".join(lines)

    def _build_system_prompt(
        self, system_prompt: str, budget_mode: bool = False
    ) -> str:
        """构建包含工具描述的完整 system prompt。"""
        tools_desc = self._format_tools_for_prompt(budget_mode)
        return f"""{system_prompt}

## 可用工具
{tools_desc}

## 工作方式
1. 分析任务，思考需要做什么
2. 每一步调用一个工具
3. 查看工具结果，决定下一步
4. 完成所有操作后，调用 submit 提交最终结果

## 回复格式
每次回复必须是 JSON：
{{"thinking": "你的思考过程", "tool": "工具名", "args": {{"参数": "值"}}}}

完成任务时：
{{"thinking": "任务完成", "tool": "submit", "args": {{"result": "最终结果"}}}}"""

    def _execute_tool(self, tool_name: str, args: dict) -> Any:
        """执行工具调用。"""
        tool = self._tools.get(tool_name)
        if not tool:
            return {"error": f"未知工具: {tool_name}"}
        try:
            return tool.func(**args)
        except Exception as e:
            log.exception("Tool %s execution failed", tool_name)
            return {"error": str(e)}

    def _parse_action(self, content: str) -> tuple[str, str, dict]:
        """解析 LLM 输出的 JSON 动作。返回 (thinking, tool_name, args)。"""
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # 如果不是 JSON，尝试提取 JSON 部分
            match = re.search(r"\{[\s\S]*\}", content)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    return content, "", {}
            else:
                return content, "", {}

        thinking = data.get("thinking", "")
        tool = data.get("tool", "")
        args = data.get("args", {})
        return thinking, tool, args

    def run(
        self,
        task: str,
        system_prompt: str = "",
        max_iterations: int = MAX_ITERATIONS,
        budget_mode: bool = False,
        temperature: float = 0.3,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> ReactResult:
        """执行 ReAct 循环。

        Args:
            task: 用户任务描述
            system_prompt: agent 特定的 system prompt（会附加工具描述）
            max_iterations: 最大迭代次数
            budget_mode: 省钱模式，跳过 check 类工具
            temperature: LLM 生成温度
            progress_callback: 进度回调 (step, message)

        Returns:
            ReactResult 包含最终输出和循环日志
        """
        full_system = self._build_system_prompt(system_prompt, budget_mode)
        messages = [
            {"role": "system", "content": full_system},
            {"role": "user", "content": task},
        ]

        steps: list[ReactStep] = []
        total_tokens = 0
        output = None
        finished = False

        for i in range(max_iterations):
            if progress_callback:
                progress_callback(i + 1, f"ReAct 步骤 {i + 1}/{max_iterations}")

            # 调用 LLM
            response = self.llm.chat(
                messages,
                temperature=temperature,
                json_mode=True,
                max_tokens=2048,
            )

            if response.usage:
                total_tokens += response.usage.get("total_tokens", 0)

            # 解析动作
            thinking, tool_name, tool_args = self._parse_action(response.content)

            if not tool_name:
                # LLM 没有返回工具调用，可能是直接回答了
                # 但如果内容看起来像截断的 tool-call JSON，不应作为最终输出
                raw = response.content.strip()
                if raw.startswith('{"thinking"') or raw.startswith('{"tool"'):
                    log.warning(
                        "ReAct step %d: malformed tool-call JSON, "
                        "skipping as output",
                        i + 1,
                    )
                    # 反馈给 LLM 让它重试
                    messages.append(
                        {"role": "assistant", "content": response.content}
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "[系统] 你的回复JSON格式有误，无法解析。"
                                "请重新输出正确的JSON格式。"
                            ),
                        }
                    )
                    continue
                log.warning(
                    "ReAct step %d: no tool call, treating as final output",
                    i + 1,
                )
                output = response.content
                finished = True
                break

            log.info("ReAct step %d: %s(%s)", i + 1, tool_name, tool_args)

            # 检查 budget_mode 下是否跳过 check 工具
            tool = self._tools.get(tool_name)
            if budget_mode and tool and tool.check_tool:
                # 告诉 LLM 这个工具在 budget_mode 下不可用
                result = {
                    "skipped": True,
                    "reason": "Budget mode: check tools disabled",
                }
            else:
                result = self._execute_tool(tool_name, tool_args)

            # 记录步骤
            step = ReactStep(
                step=i + 1,
                thinking=thinking,
                tool=tool_name,
                args=tool_args,
                result=result,
            )
            steps.append(step)

            # 检查是否是 submit
            if tool_name == "submit":
                output = result
                finished = True
                break

            # 将结果反馈给 LLM
            messages.append({"role": "assistant", "content": response.content})
            result_str = json.dumps(result, ensure_ascii=False, default=str)
            if len(result_str) > 3000:
                result_str = result_str[:3000] + "...(truncated)"
            messages.append(
                {
                    "role": "user",
                    "content": f"[工具结果] {tool_name}: {result_str}",
                }
            )

        if not finished:
            log.warning(
                "ReAct reached max iterations (%d), forcing output",
                max_iterations,
            )
            # 尝试从最后一步获取有用输出
            if steps and steps[-1].result:
                output = steps[-1].result

        return ReactResult(
            output=output,
            steps=steps,
            total_steps=len(steps),
            total_tokens=total_tokens,
            finished=finished,
        )

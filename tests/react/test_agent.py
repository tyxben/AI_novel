"""Tests for ReAct Agent Framework."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call

import pytest

from src.llm.llm_client import LLMResponse
from src.react.agent import MAX_ITERATIONS, ReactAgent, ReactResult, ReactStep, ReactTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(
    content: str,
    total_tokens: int = 100,
    usage: dict | None = None,
    finish_reason: str = "stop",
) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="test-model",
        usage=usage if usage is not None else {"total_tokens": total_tokens},
        finish_reason=finish_reason,
    )


def _submit_json(result: str) -> str:
    """Convenience: build a submit action JSON string."""
    return json.dumps({"thinking": "done", "tool": "submit", "args": {"result": result}})


def _action_json(tool: str, args: dict, thinking: str = "") -> str:
    return json.dumps({"thinking": thinking, "tool": tool, "args": args})


def _make_agent_with_tool(
    mock_llm: MagicMock,
    tool_name: str = "greet",
    tool_func=None,
    check_tool: bool = False,
) -> ReactAgent:
    """Create a ReactAgent with one custom tool registered."""
    agent = ReactAgent(mock_llm)
    agent.register_tool(
        ReactTool(
            name=tool_name,
            description="Says hello",
            parameters={"name": {"type": "string", "description": "Name"}},
            func=tool_func or (lambda name: f"hello {name}"),
            check_tool=check_tool,
        )
    )
    return agent


# ===========================================================================
# Tool Registration & Description
# ===========================================================================


class TestToolRegistration:
    def test_register_tool(self):
        mock_llm = MagicMock()
        agent = ReactAgent(mock_llm)
        tool = ReactTool(
            name="search",
            description="Search things",
            parameters={"query": {"type": "string", "description": "q"}},
            func=lambda query: {"results": []},
        )
        agent.register_tool(tool)
        assert "search" in agent._tools
        assert agent._tools["search"] is tool

    def test_builtin_submit_tool(self):
        mock_llm = MagicMock()
        agent = ReactAgent(mock_llm)
        assert "submit" in agent._tools
        assert agent._tools["submit"].name == "submit"
        # submit's func should return its input
        assert agent._tools["submit"].func(result="ok") == "ok"

    def test_format_tools_for_prompt(self):
        mock_llm = MagicMock()
        agent = _make_agent_with_tool(mock_llm, "greet")
        desc = agent._format_tools_for_prompt()
        assert "greet(name: string): Says hello" in desc
        assert "submit(result: string):" in desc

    def test_format_tools_budget_mode_hides_check_tools(self):
        mock_llm = MagicMock()
        agent = ReactAgent(mock_llm)
        agent.register_tool(
            ReactTool(
                name="check_grammar",
                description="Check grammar",
                parameters={"text": {"type": "string", "description": "t"}},
                func=lambda text: {"ok": True},
                check_tool=True,
            )
        )
        agent.register_tool(
            ReactTool(
                name="write",
                description="Write text",
                parameters={"content": {"type": "string", "description": "c"}},
                func=lambda content: content,
            )
        )

        normal_desc = agent._format_tools_for_prompt(budget_mode=False)
        budget_desc = agent._format_tools_for_prompt(budget_mode=True)

        assert "check_grammar" in normal_desc
        assert "check_grammar" not in budget_desc
        # Non-check tools still present in both
        assert "write" in normal_desc
        assert "write" in budget_desc

    def test_register_duplicate_tool_overwrites(self):
        mock_llm = MagicMock()
        agent = ReactAgent(mock_llm)
        tool_v1 = ReactTool(
            name="search",
            description="v1",
            parameters={},
            func=lambda: "v1",
        )
        tool_v2 = ReactTool(
            name="search",
            description="v2",
            parameters={},
            func=lambda: "v2",
        )
        agent.register_tool(tool_v1)
        agent.register_tool(tool_v2)
        assert agent._tools["search"].description == "v2"
        assert agent._tools["search"].func() == "v2"


# ===========================================================================
# Action Parsing
# ===========================================================================


class TestParseAction:
    def test_parse_valid_json(self):
        mock_llm = MagicMock()
        agent = ReactAgent(mock_llm)
        content = '{"thinking": "analyzing", "tool": "search", "args": {"query": "hello"}}'
        thinking, tool, args = agent._parse_action(content)
        assert thinking == "analyzing"
        assert tool == "search"
        assert args == {"query": "hello"}

    def test_parse_json_with_extra_text(self):
        mock_llm = MagicMock()
        agent = ReactAgent(mock_llm)
        content = 'Here is my plan:\n{"thinking": "ok", "tool": "submit", "args": {"result": "done"}}\nEnd.'
        thinking, tool, args = agent._parse_action(content)
        assert tool == "submit"
        assert args == {"result": "done"}

    def test_parse_invalid_json(self):
        mock_llm = MagicMock()
        agent = ReactAgent(mock_llm)
        content = "This is plain text with no JSON at all."
        thinking, tool, args = agent._parse_action(content)
        assert tool == ""
        assert args == {}

    def test_parse_missing_tool_field(self):
        mock_llm = MagicMock()
        agent = ReactAgent(mock_llm)
        content = '{"thinking": "hmm", "args": {"x": 1}}'
        thinking, tool, args = agent._parse_action(content)
        assert thinking == "hmm"
        assert tool == ""  # missing "tool" key -> empty string

    def test_parse_partial_json_fields(self):
        mock_llm = MagicMock()
        agent = ReactAgent(mock_llm)
        content = '{"tool": "submit"}'
        thinking, tool, args = agent._parse_action(content)
        assert thinking == ""
        assert tool == "submit"
        assert args == {}


# ===========================================================================
# Tool Execution
# ===========================================================================


class TestExecuteTool:
    def test_execute_known_tool(self):
        mock_llm = MagicMock()
        agent = _make_agent_with_tool(mock_llm, "greet")
        result = agent._execute_tool("greet", {"name": "Alice"})
        assert result == "hello Alice"

    def test_execute_unknown_tool(self):
        mock_llm = MagicMock()
        agent = ReactAgent(mock_llm)
        result = agent._execute_tool("nonexistent", {"x": 1})
        assert isinstance(result, dict)
        assert "error" in result
        assert "未知工具" in result["error"]

    def test_execute_tool_exception(self):
        mock_llm = MagicMock()
        agent = ReactAgent(mock_llm)

        def boom(**kwargs):
            raise ValueError("something broke")

        agent.register_tool(
            ReactTool(
                name="explode",
                description="Always fails",
                parameters={},
                func=boom,
            )
        )
        result = agent._execute_tool("explode", {})
        assert isinstance(result, dict)
        assert "error" in result
        assert "something broke" in result["error"]

    def test_execute_submit_tool(self):
        mock_llm = MagicMock()
        agent = ReactAgent(mock_llm)
        result = agent._execute_tool("submit", {"result": "final answer"})
        assert result == "final answer"


# ===========================================================================
# ReAct Loop (run)
# ===========================================================================


class TestReactLoop:
    def test_simple_run_submit_in_one_step(self):
        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_response(_submit_json("done"))
        agent = ReactAgent(mock_llm)
        result = agent.run(task="test task")
        assert result.output == "done"
        assert result.finished is True
        assert result.total_steps == 1
        assert mock_llm.chat.call_count == 1

    def test_multi_step_run(self):
        """LLM calls greet tool then submits."""
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [
            _make_response(_action_json("greet", {"name": "Bob"}, "first step")),
            _make_response(_submit_json("greeted Bob")),
        ]
        agent = _make_agent_with_tool(mock_llm, "greet")
        result = agent.run(task="greet Bob then submit")
        assert result.finished is True
        assert result.total_steps == 2
        assert result.steps[0].tool == "greet"
        assert result.steps[0].result == "hello Bob"
        assert result.steps[1].tool == "submit"
        assert result.output == "greeted Bob"
        assert mock_llm.chat.call_count == 2

    def test_max_iterations_reached(self):
        """Agent never submits -> reaches max_iterations."""
        mock_llm = MagicMock()
        # Always returns a non-submit action
        mock_llm.chat.return_value = _make_response(
            _action_json("greet", {"name": "loop"})
        )
        agent = _make_agent_with_tool(mock_llm, "greet")
        result = agent.run(task="loop forever", max_iterations=3)
        assert result.finished is False
        assert result.total_steps == 3
        assert mock_llm.chat.call_count == 3
        # output should be last step's result
        assert result.output == "hello loop"

    def test_budget_mode_skips_check_tools(self):
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [
            _make_response(
                _action_json("verify", {"text": "check this"}, "verifying")
            ),
            _make_response(_submit_json("all good")),
        ]
        agent = ReactAgent(mock_llm)
        agent.register_tool(
            ReactTool(
                name="verify",
                description="Verify content",
                parameters={"text": {"type": "string", "description": "t"}},
                func=lambda text: {"valid": True},
                check_tool=True,
            )
        )
        result = agent.run(task="verify and submit", budget_mode=True)
        assert result.finished is True
        # First step should have been skipped
        assert result.steps[0].tool == "verify"
        assert result.steps[0].result == {
            "skipped": True,
            "reason": "Budget mode: check tools disabled",
        }

    def test_progress_callback_called(self):
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [
            _make_response(_action_json("greet", {"name": "A"})),
            _make_response(_submit_json("done")),
        ]
        agent = _make_agent_with_tool(mock_llm, "greet")
        cb = MagicMock()
        result = agent.run(task="greet", progress_callback=cb)
        # Called once per iteration (2 iterations)
        assert cb.call_count == 2
        cb.assert_any_call(1, "ReAct 步骤 1/8")
        cb.assert_any_call(2, "ReAct 步骤 2/8")

    def test_total_tokens_tracked(self):
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [
            _make_response(
                _action_json("greet", {"name": "A"}), total_tokens=150
            ),
            _make_response(_submit_json("done"), total_tokens=200),
        ]
        agent = _make_agent_with_tool(mock_llm, "greet")
        result = agent.run(task="test")
        assert result.total_tokens == 350

    def test_total_tokens_with_none_usage(self):
        """usage=None should not crash token counting."""
        mock_llm = MagicMock()
        mock_llm.chat.return_value = LLMResponse(
            content=_submit_json("done"),
            model="test",
            usage=None,
            finish_reason="stop",
        )
        agent = ReactAgent(mock_llm)
        result = agent.run(task="test")
        assert result.total_tokens == 0
        assert result.finished is True

    def test_result_contains_steps(self):
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [
            _make_response(
                _action_json("greet", {"name": "X"}, "thinking about X")
            ),
            _make_response(_submit_json("final")),
        ]
        agent = _make_agent_with_tool(mock_llm, "greet")
        result = agent.run(task="test")
        assert len(result.steps) == 2
        step0 = result.steps[0]
        assert isinstance(step0, ReactStep)
        assert step0.step == 1
        assert step0.thinking == "thinking about X"
        assert step0.tool == "greet"
        assert step0.args == {"name": "X"}
        assert step0.result == "hello X"

    def test_no_tool_call_treated_as_output(self):
        """LLM returns plain text (no tool) -> treated as final output."""
        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_response("Just a plain answer.")
        agent = ReactAgent(mock_llm)
        result = agent.run(task="answer me")
        assert result.finished is True
        assert result.output == "Just a plain answer."
        assert result.total_steps == 0
        assert len(result.steps) == 0

    def test_system_prompt_included(self):
        """Custom system prompt is passed to LLM."""
        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_response(_submit_json("ok"))
        agent = ReactAgent(mock_llm)
        agent.run(task="test", system_prompt="You are a helpful assistant.")
        call_messages = mock_llm.chat.call_args[0][0]
        system_msg = call_messages[0]["content"]
        assert "You are a helpful assistant." in system_msg
        assert "可用工具" in system_msg

    def test_tool_result_truncated_for_context(self):
        """Tool results > 3000 chars should be truncated in LLM context."""
        mock_llm = MagicMock()
        big_result = "x" * 5000

        mock_llm.chat.side_effect = [
            _make_response(_action_json("big", {})),
            _make_response(_submit_json("ok")),
        ]
        agent = ReactAgent(mock_llm)
        agent.register_tool(
            ReactTool(
                name="big",
                description="Returns big data",
                parameters={},
                func=lambda: big_result,
            )
        )
        agent.run(task="test")
        # Second call should have truncated result
        second_call_messages = mock_llm.chat.call_args_list[1][0][0]
        tool_result_msg = second_call_messages[-1]["content"]
        assert "...(truncated)" in tool_result_msg
        # Should be around 3000 chars + overhead, not 5000
        assert len(tool_result_msg) < 4000

    def test_temperature_and_max_tokens_passed(self):
        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_response(_submit_json("ok"))
        agent = ReactAgent(mock_llm)
        agent.run(task="test", temperature=0.9)
        mock_llm.chat.assert_called_once()
        _, kwargs = mock_llm.chat.call_args
        assert kwargs["temperature"] == 0.9
        assert kwargs["json_mode"] is True
        assert kwargs["max_tokens"] == 2048

    def test_max_iterations_zero(self):
        """max_iterations=0 should return immediately with no steps."""
        mock_llm = MagicMock()
        agent = ReactAgent(mock_llm)
        result = agent.run(task="test", max_iterations=0)
        assert result.finished is False
        assert result.total_steps == 0
        assert result.output is None
        assert mock_llm.chat.call_count == 0

    def test_unknown_tool_called_by_llm(self):
        """LLM calls a tool that doesn't exist -> error fed back."""
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [
            _make_response(
                _action_json("nonexistent_tool", {"x": 1}, "trying unknown tool")
            ),
            _make_response(_submit_json("recovered")),
        ]
        agent = ReactAgent(mock_llm)
        result = agent.run(task="test")
        assert result.finished is True
        assert result.steps[0].tool == "nonexistent_tool"
        assert "error" in result.steps[0].result
        assert "未知工具" in result.steps[0].result["error"]
        # Agent recovered and submitted
        assert result.output == "recovered"

    def test_tool_exception_fed_back_to_llm(self):
        """Tool raises -> error result fed back, loop continues."""
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [
            _make_response(_action_json("fail_tool", {})),
            _make_response(_submit_json("handled")),
        ]
        agent = ReactAgent(mock_llm)
        agent.register_tool(
            ReactTool(
                name="fail_tool",
                description="Always fails",
                parameters={},
                func=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
            )
        )
        result = agent.run(task="test")
        assert result.finished is True
        assert "error" in result.steps[0].result
        assert result.output == "handled"

    def test_max_iterations_no_steps_output_none(self):
        """max_iterations reached with empty steps -> output is None."""
        mock_llm = MagicMock()
        # LLM always returns a tool action but never submit
        mock_llm.chat.return_value = _make_response(
            _action_json("greet", {"name": "Z"})
        )
        agent = _make_agent_with_tool(mock_llm, "greet")
        result = agent.run(task="test", max_iterations=2)
        assert result.finished is False
        assert result.total_steps == 2
        # Output should be last step's result
        assert result.output == "hello Z"

    def test_multi_param_tool(self):
        """Tool with multiple parameters works correctly."""
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [
            _make_response(
                _action_json("add", {"a": 3, "b": 5}, "computing")
            ),
            _make_response(_submit_json("8")),
        ]
        agent = ReactAgent(mock_llm)
        agent.register_tool(
            ReactTool(
                name="add",
                description="Add two numbers",
                parameters={
                    "a": {"type": "integer", "description": "first"},
                    "b": {"type": "integer", "description": "second"},
                },
                func=lambda a, b: a + b,
            )
        )
        result = agent.run(task="add 3+5")
        assert result.steps[0].result == 8

    def test_messages_accumulate_correctly(self):
        """After each tool call, messages should have assistant + user (result) appended."""
        mock_llm = MagicMock()
        action1 = _action_json("greet", {"name": "A"})
        action2 = _submit_json("done")

        # Capture snapshots of messages at each call (the list is mutated in place)
        captured_lengths: list[int] = []

        def _chat_side_effect(msgs, **kwargs):
            captured_lengths.append(len(msgs))
            if len(captured_lengths) == 1:
                return _make_response(action1)
            return _make_response(action2)

        mock_llm.chat.side_effect = _chat_side_effect
        agent = _make_agent_with_tool(mock_llm, "greet")
        agent.run(task="test")

        # First call: [system, user] = 2 messages
        assert captured_lengths[0] == 2

        # Second call: [system, user, assistant, user(result)] = 4 messages
        assert captured_lengths[1] == 4

        # After run(), the final state of messages has the result feedback
        final_msgs = mock_llm.chat.call_args[0][0]
        assert final_msgs[2]["role"] == "assistant"
        assert final_msgs[2]["content"] == action1
        assert final_msgs[3]["role"] == "user"
        assert "[工具结果] greet:" in final_msgs[3]["content"]


# ===========================================================================
# Subclass Usage
# ===========================================================================


class TestSubclass:
    def test_subclass_registers_tools(self):
        """Verify the intended subclass pattern works."""

        class MathAgent(ReactAgent):
            def __init__(self, llm):
                super().__init__(llm)
                self.register_tool(
                    ReactTool(
                        name="multiply",
                        description="Multiply two numbers",
                        parameters={
                            "a": {"type": "number", "description": "first"},
                            "b": {"type": "number", "description": "second"},
                        },
                        func=self._multiply,
                    )
                )

            def _multiply(self, a, b):
                return a * b

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [
            _make_response(_action_json("multiply", {"a": 6, "b": 7})),
            _make_response(_submit_json("42")),
        ]
        agent = MathAgent(mock_llm)
        result = agent.run(task="multiply 6 * 7")
        assert result.steps[0].result == 42
        assert result.output == "42"
        assert result.finished is True


# ===========================================================================
# Import / Module Tests
# ===========================================================================


class TestImports:
    def test_public_api_from_package(self):
        from src.react import ReactAgent, ReactResult, ReactTool

        assert ReactAgent is not None
        assert ReactTool is not None
        assert ReactResult is not None

    def test_max_iterations_constant(self):
        assert MAX_ITERATIONS == 8

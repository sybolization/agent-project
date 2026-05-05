"""Test: No-tool-call reminder injection into context."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.agent_loop import AgentLoop
from agent.phases.result import PhaseResult
from agent.hooks.types import HookExitCode, HookResult


def _make_agent():
    agent = AgentLoop.__new__(AgentLoop)
    agent.max_iterations = 5
    agent._context = []
    agent._last_response_text = ""
    agent._repeated_count = 0
    agent._max_repeated_allowed = 2
    agent._interaction_logger = MagicMock()
    agent._interaction_logger.emit = MagicMock()
    agent._interaction_logger.log_interaction = MagicMock()
    agent._interaction_logger.log_tool_execution = MagicMock()
    agent._interaction_logger.save = MagicMock(return_value=None)
    agent._interaction_logger.emit_error = MagicMock()
    agent._interaction_logger.clear = MagicMock()
    agent.state = MagicMock()
    agent.state.iteration_count = 0
    agent.state.phase = MagicMock()
    agent.state.phase.value = "DEFAULT"
    agent.state.agent_id = "test"
    agent.state.reset = MagicMock()
    agent.state.get_todo_progress = MagicMock(return_value={"total": 0, "completed": 0})
    agent.llm = MagicMock()
    agent.prompt_builder = MagicMock()
    agent.prompt_builder.build = MagicMock(return_value="system prompt")
    agent.context_compressor = MagicMock()
    agent.context_compressor.compress_if_needed = AsyncMock(return_value=([], {}))
    agent.session_memory = MagicMock()
    agent.hook_runner = MagicMock()
    agent.hook_runner.run_post_phase_execute = MagicMock(return_value=HookResult.continue_())
    agent.phases = {}
    mock_phase = MagicMock()
    mock_phase.execute = AsyncMock()
    agent.phases["DEFAULT"] = mock_phase
    agent._init_hooks = MagicMock()
    agent._init_phases = MagicMock()
    agent.tool_executor = MagicMock()
    agent.skill_manager = MagicMock()
    agent.opencli_client = MagicMock()
    return agent


@pytest.mark.asyncio
async def test_reminder_injected_on_no_tool_call():
    agent = _make_agent()
    mock_phase = agent.phases["DEFAULT"]

    no_tool_result = PhaseResult(
        status="continue",
        message="I will help you.",
        response_text="I will help you.",
        tool_calls=[],
        tool_results=[],
        reminder="\n\n[CRITICAL] You output text but did not call a tool.",
    )

    with_tool_result = PhaseResult(
        status="continue",
        message="done",
        response_text="done",
        tool_calls=[{"name": "task_complete", "arguments": {}}],
        tool_results=[],
        reminder="",
    )

    mock_phase.execute.side_effect = [no_tool_result, with_tool_result]

    await agent.run("test input", reset=True)

    reminder_msgs = [m for m in agent._context if m.get("role") == "user" and "[CRITICAL]" in m.get("content", "")]
    assert len(reminder_msgs) == 1, f"Expected 1 reminder in context, found {len(reminder_msgs)}"
    assert "[CRITICAL]" in reminder_msgs[0]["content"]


@pytest.mark.asyncio
async def test_no_reminder_when_tools_called():
    agent = _make_agent()
    mock_phase = agent.phases["DEFAULT"]

    with_tool_result = PhaseResult(
        status="continue",
        message="done",
        response_text="done",
        tool_calls=[{"name": "task_complete", "arguments": {}}],
        tool_results=[],
        reminder="",
    )

    complete_result = PhaseResult(
        status="complete",
        message="Task finished.",
        response_text="Task finished.",
        tool_calls=[],
        tool_results=[],
        reminder="",
    )

    mock_phase.execute.side_effect = [with_tool_result, complete_result]

    agent.hook_runner.run_post_phase_execute.side_effect = [
        HookResult(exit_code=HookExitCode.BLOCK, message="Task finished."),
    ]

    await agent.run("test input", reset=True)

    reminder_msgs = [m for m in agent._context if m.get("role") == "user" and "[CRITICAL]" in m.get("content", "")]
    assert len(reminder_msgs) == 0, f"Expected no reminder in context, found {len(reminder_msgs)}"


@pytest.mark.asyncio
async def test_no_reminder_when_reminder_empty():
    agent = _make_agent()
    mock_phase = agent.phases["DEFAULT"]

    no_tool_no_reminder = PhaseResult(
        status="continue",
        message="thinking...",
        response_text="thinking...",
        tool_calls=[],
        tool_results=[],
        reminder="",
    )

    complete_result = PhaseResult(
        status="complete",
        message="done",
        response_text="done",
        tool_calls=[],
        tool_results=[],
        reminder="",
    )

    mock_phase.execute.side_effect = [no_tool_no_reminder, complete_result]

    agent.hook_runner.run_post_phase_execute.side_effect = [
        HookResult(exit_code=HookExitCode.BLOCK, message="done"),
    ]

    await agent.run("test input", reset=True)

    assert len(agent._context) == 0, f"Expected empty context, got {agent._context}"


@pytest.mark.asyncio
async def test_reminder_not_injected_on_hook_block():
    agent = _make_agent()
    mock_phase = agent.phases["DEFAULT"]

    no_tool_result = PhaseResult(
        status="continue",
        message="I will help you.",
        response_text="I will help you.",
        tool_calls=[],
        tool_results=[],
        reminder="\n\n[CRITICAL] You output text but did not call a tool.",
    )

    mock_phase.execute.side_effect = [no_tool_result]

    agent.hook_runner.run_post_phase_execute.return_value = HookResult(
        exit_code=HookExitCode.BLOCK,
        message="blocked",
    )

    await agent.run("test input", reset=True)

    reminder_msgs = [m for m in agent._context if m.get("role") == "user" and "[CRITICAL]" in m.get("content", "")]
    assert len(reminder_msgs) == 0, "Reminder should not be injected when hook blocks"

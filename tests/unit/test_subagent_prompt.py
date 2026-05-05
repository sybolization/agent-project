"""Unit tests for subagent prompt formatting functions.

Tests for:
- _format_inherited_skills: Format inherited skill contents
- _format_action_history: Format parent agent action history
- _build_subagent_prompt: Integration test for subagent prompt building
"""

import pytest

from agent.tools.executors.subagent import (
    _format_inherited_skills,
    _format_action_history,
    SubagentExecutor,
)
from agent.execution_context import ExecutionContext


class TestFormatInheritedSkills:
    """Tests for _format_inherited_skills function."""

    def test_format_inherited_skills_empty(self):
        """Test that empty input returns empty string."""
        result = _format_inherited_skills({})
        assert result == ""

    def test_format_inherited_skills_single(self):
        """Test that single skill is correctly formatted."""
        skill_contents = {"test-skill": "This is skill content"}
        result = _format_inherited_skills(skill_contents)

        assert "test-skill" in result
        assert "This is skill content" in result
        assert "inherited skills" in result.lower() or "loaded" in result.lower() or "skill" in result.lower()

    def test_format_inherited_skills_multiple(self):
        """Test that multiple skills are correctly formatted."""
        skill_contents = {
            "skill-a": "Content for skill A",
            "skill-b": "Content for skill B"
        }
        result = _format_inherited_skills(skill_contents)

        assert "skill-a" in result
        assert "skill-b" in result
        assert "Content for skill A" in result
        assert "Content for skill B" in result

    def test_format_inherited_skills_structure(self):
        """Test that the output has correct structure with headers."""
        skill_contents = {"my-skill": "Some content"}
        result = _format_inherited_skills(skill_contents)

        # Should contain section header
        assert "##" in result
        # Should contain skill name as subsection
        assert "### my-skill" in result

    def test_format_inherited_skills_none_input(self):
        """Test that None input is handled gracefully."""
        result = _format_inherited_skills(None)
        assert result == ""


class TestFormatActionHistory:
    """Tests for _format_action_history function."""

    def test_format_action_history_empty(self):
        """Test that empty input returns empty string."""
        result = _format_action_history([])
        assert result == ""

    def test_format_action_history_single(self):
        """Test that single action record is correctly formatted."""
        action_history = [
            {"tool_name": "execute_command", "arguments": {"command": "test"}, "result_summary": "Success"}
        ]
        result = _format_action_history(action_history)

        assert "execute_command" in result
        assert "Success" in result

    def test_format_action_history_truncation(self):
        """Test that multiple records are truncated to recent rounds."""
        action_history = [
            {"tool_name": "tool1", "result_summary": "Result 1"},
            {"tool_name": "tool2", "result_summary": "Result 2"},
            {"tool_name": "tool3", "result_summary": "Result 3"},
            {"tool_name": "tool4", "result_summary": "Result 4"},
            {"tool_name": "tool5", "result_summary": "Result 5"},
        ]
        result = _format_action_history(action_history, max_rounds=3)

        # Should contain last 3 tools
        assert "tool3" in result
        assert "tool4" in result
        assert "tool5" in result
        # Should not contain first 2 tools
        assert "tool1" not in result
        assert "tool2" not in result

    def test_format_action_history_with_arguments(self):
        """Test that arguments are included in output."""
        action_history = [
            {"tool_name": "execute_command", "arguments": {"command": "ls -la"}, "result_summary": "Listed files"}
        ]
        result = _format_action_history(action_history)

        assert "execute_command" in result
        assert "ls -la" in result or "command" in result.lower()

    def test_format_action_history_structure(self):
        """Test that the output has correct structure."""
        action_history = [
            {"tool_name": "test_tool", "arguments": {}, "result_summary": "Test result"}
        ]
        result = _format_action_history(action_history)

        # Should contain section header
        assert "##" in result
        # Should contain call number
        assert "1" in result

    def test_format_action_history_none_input(self):
        """Test that None input is handled gracefully."""
        result = _format_action_history(None)
        assert result == ""

    def test_format_action_history_default_max_rounds(self):
        """Test that default max_rounds is 3."""
        action_history = [
            {"tool_name": f"tool{i}", "result_summary": f"Result {i}"}
            for i in range(10)
        ]
        result = _format_action_history(action_history)

        # Should only contain last 3
        assert "tool7" in result
        assert "tool8" in result
        assert "tool9" in result
        assert "tool6" not in result


class TestBuildSubagentPrompt:
    """Integration tests for _build_subagent_prompt method."""

    @pytest.fixture
    def executor(self):
        """Create a SubagentExecutor instance with mock context."""
        context = ExecutionContext()
        return SubagentExecutor(parent_context=context)

    def test_build_subagent_prompt_basic(self, executor):
        """Test basic prompt building without skills or history."""
        prompt = executor._build_subagent_prompt(
            task="Test task",
            available_tools=["execute_command"],
            tools_description="Tool descriptions here"
        )

        assert "Test task" in prompt
        assert "execute_command" in prompt
        assert "Tool descriptions here" in prompt

    def test_build_subagent_prompt_with_skills(self):
        """Test that skill content is correctly injected into prompt."""
        context = ExecutionContext(skill_contents={"test-skill": "Skill content here"})
        executor = SubagentExecutor(parent_context=context)

        prompt = executor._build_subagent_prompt(
            task="Test task",
            available_tools=["execute_command"],
            tools_description="Tool descriptions",
            parent_skill_contents={"test-skill": "Skill content here"}
        )

        assert "test-skill" in prompt
        assert "Skill content here" in prompt

    def test_build_subagent_prompt_with_action_history(self):
        """Test that action history is correctly injected into prompt."""
        context = ExecutionContext()
        executor = SubagentExecutor(parent_context=context)

        action_history = [
            {"tool_name": "execute_command", "arguments": {"command": "test"}, "result_summary": "Success"}
        ]

        prompt = executor._build_subagent_prompt(
            task="Test task",
            available_tools=["execute_command"],
            tools_description="Tool descriptions",
            parent_action_history=action_history
        )

        assert "execute_command" in prompt
        assert "Success" in prompt

    def test_build_subagent_prompt_with_both(self):
        """Test that both skills and history are correctly injected."""
        context = ExecutionContext(skill_contents={"test-skill": "Skill content"})
        executor = SubagentExecutor(parent_context=context)

        action_history = [
            {"tool_name": "execute_command", "result_summary": "Success"}
        ]

        prompt = executor._build_subagent_prompt(
            task="Test task",
            available_tools=["execute_command"],
            tools_description="Tool descriptions",
            parent_skill_contents={"test-skill": "Skill content"},
            parent_action_history=action_history
        )

        assert "test-skill" in prompt
        assert "Skill content" in prompt
        assert "execute_command" in prompt
        assert "Success" in prompt

    def test_build_subagent_prompt_multiple_tools(self, executor):
        """Test prompt with multiple available tools."""
        prompt = executor._build_subagent_prompt(
            task="Multi-tool task",
            available_tools=["execute_command", "update_todo", "task_complete"],
            tools_description="Multiple tools available"
        )

        assert "execute_command" in prompt
        assert "update_todo" in prompt
        assert "task_complete" in prompt

    def test_build_subagent_prompt_empty_skills_and_history(self, executor):
        """Test prompt with empty skills and history."""
        prompt = executor._build_subagent_prompt(
            task="Simple task",
            available_tools=["execute_command"],
            tools_description="Tool description",
            parent_skill_contents={},
            parent_action_history=[]
        )

        assert "Simple task" in prompt
        # Should not crash and should produce valid prompt

    def test_build_subagent_prompt_with_long_skill_content(self):
        """Test that long skill content is handled correctly."""
        long_content = "A" * 10000  # Very long content
        context = ExecutionContext(skill_contents={"long-skill": long_content})
        executor = SubagentExecutor(parent_context=context)

        prompt = executor._build_subagent_prompt(
            task="Test task",
            available_tools=["execute_command"],
            tools_description="Tool description",
            parent_skill_contents={"long-skill": long_content}
        )

        assert "long-skill" in prompt
        assert long_content in prompt

    def test_build_subagent_prompt_with_complex_action_history(self):
        """Test prompt with complex action history."""
        context = ExecutionContext()
        executor = SubagentExecutor(parent_context=context)

        action_history = [
            {
                "tool_name": "execute_command",
                "arguments": {"command": "git status", "cwd": "/project"},
                "result_summary": "Working tree clean"
            },
            {
                "tool_name": "execute_command",
                "arguments": {"command": "npm test"},
                "result_summary": "All tests passed"
            },
            {
                "tool_name": "update_todo",
                "arguments": {"todo_id": "1", "status": "completed"},
                "result_summary": "TODO updated"
            }
        ]

        prompt = executor._build_subagent_prompt(
            task="Complex task",
            available_tools=["execute_command", "update_todo"],
            tools_description="Tools for complex operations",
            parent_action_history=action_history
        )

        # Should contain all tools from history
        assert "execute_command" in prompt
        assert "update_todo" in prompt
        # Should contain result summaries
        assert "clean" in prompt.lower() or "passed" in prompt.lower() or "updated" in prompt.lower()


class TestSubagentExecutorInit:
    """Tests for SubagentExecutor initialization."""

    def test_init_with_context(self):
        """Test initialization with ExecutionContext."""
        context = ExecutionContext(
            skill_contents={"skill1": "content1"},
            action_history=[{"tool_name": "test"}]
        )
        executor = SubagentExecutor(parent_context=context)

        assert executor.parent_context is context

    def test_init_with_llm_client(self):
        """Test initialization with custom LLM client."""
        context = ExecutionContext()
        mock_llm = object()  # Mock LLM client
        executor = SubagentExecutor(parent_context=context, llm_client=mock_llm)

        assert executor.llm_client is mock_llm


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""Unit tests for load_skill_category and load_skill tools."""

import pytest
from pathlib import Path

from agent.skills.manager import SkillManager, SkillCategory
from agent.state import AgentState, AgentPhase
from agent.tools.executors import ToolExecutor
from agent.prompts.builder import PromptBuilder


class TestSkillCategory:
    """Tests for skill category functionality."""

    @pytest.fixture
    def skill_manager(self):
        """Create a SkillManager instance."""
        return SkillManager()

    @pytest.fixture
    def agent_state(self):
        """Create an AgentState instance."""
        state = AgentState()
        state.mode = 'default'
        state.phase = AgentPhase.DEFAULT
        return state

    def test_get_categories(self, skill_manager):
        """Test that categories are correctly scanned."""
        categories = skill_manager.get_categories()
        
        assert len(categories) == 2, "Should have 2 categories"
        
        category_names = [cat.name for cat in categories]
        assert "feishu" in category_names, "Should have feishu category"
        assert "opencli" in category_names, "Should have opencli category"

    def test_category_has_skills(self, skill_manager):
        """Test that categories have skills."""
        categories = skill_manager.get_categories()
        
        for cat in categories:
            assert len(cat.skills) > 0, f"Category {cat.name} should have skills"

    def test_get_category_index_prompt(self, skill_manager):
        """Test that category index prompt is generated."""
        prompt = skill_manager.get_category_index_prompt()
        
        assert "feishu" in prompt, "Prompt should mention feishu"
        assert "opencli" in prompt, "Prompt should mention opencli"
        assert "技能" in prompt or "skill" in prompt.lower(), "Prompt should mention skills"

    def test_get_category_skills_prompt_valid(self, skill_manager):
        """Test that category skills prompt is generated for valid category."""
        prompt = skill_manager.get_category_skills_prompt("opencli")
        
        assert "opencli" in prompt, "Prompt should mention opencli"
        assert len(prompt) > 50, "Prompt should have content"

    def test_get_category_skills_prompt_invalid(self, skill_manager):
        """Test that category skills prompt returns error for invalid category."""
        prompt = skill_manager.get_category_skills_prompt("invalid")
        
        assert "未找到" in prompt or "无效" in prompt, "Should return error message"


class TestLoadSkillCategoryTool:
    """Tests for load_skill_category tool."""

    @pytest.fixture
    def skill_manager(self):
        """Create a SkillManager instance."""
        return SkillManager()

    @pytest.fixture
    def agent_state(self):
        """Create an AgentState instance."""
        state = AgentState()
        state.mode = 'default'
        state.phase = AgentPhase.DEFAULT
        return state

    @pytest.fixture
    def tool_executor(self, skill_manager):
        """Create a ToolExecutor instance."""
        class MockOpenCLI:
            pass
        
        return ToolExecutor(skill_manager, MockOpenCLI(), None)

    def test_execute_load_category_success(self, tool_executor):
        """Test successful category loading."""
        result = tool_executor._execute_load_category({
            "arguments": {"category_name": "opencli"}
        })
        
        assert result["type"] == "category_loaded", "Should return category_loaded type"
        assert result["category_name"] == "opencli", "Should have correct category name"
        assert "content" in result, "Should have content"
        assert len(result["content"]) > 0, "Content should not be empty"

    def test_execute_load_category_invalid(self, tool_executor):
        """Test loading invalid category."""
        result = tool_executor._execute_load_category({
            "arguments": {"category_name": "invalid"}
        })
        
        assert result["type"] == "error", "Should return error type"
        assert "可用类别" in result["message"], "Should list available categories"


class TestLoadSkillTool:
    """Tests for load_skill tool."""

    @pytest.fixture
    def skill_manager(self):
        """Create a SkillManager instance."""
        return SkillManager()

    @pytest.fixture
    def agent_state(self):
        """Create an AgentState instance."""
        state = AgentState()
        state.mode = 'default'
        state.phase = AgentPhase.DEFAULT
        return state

    @pytest.fixture
    def tool_executor(self, skill_manager):
        """Create a ToolExecutor instance."""
        class MockOpenCLI:
            pass
        
        return ToolExecutor(skill_manager, MockOpenCLI(), None)

    def test_execute_load_skill_success(self, tool_executor):
        """Test successful skill loading."""
        result = tool_executor._execute_load_skill({
            "arguments": {"skill_name": "opencli/smart-search"}
        })
        
        assert result["type"] == "skill_loaded", "Should return skill_loaded type"
        assert result["skill_name"] == "opencli/smart-search", "Should have correct skill name"
        assert "content" in result, "Should have content"

    def test_execute_load_skill_invalid(self, tool_executor):
        """Test loading invalid skill."""
        result = tool_executor._execute_load_skill({
            "arguments": {"skill_name": "invalid/skill"}
        })
        
        assert result["type"] == "error", "Should return error type"


class TestStateUpdate:
    """Tests for state update after tool execution."""

    @pytest.fixture
    def skill_manager(self):
        """Create a SkillManager instance."""
        return SkillManager()

    @pytest.fixture
    def agent_state(self):
        """Create an AgentState instance."""
        state = AgentState()
        state.mode = 'default'
        state.phase = AgentPhase.DEFAULT
        return state

    def test_add_category(self, agent_state):
        """Test adding category to state."""
        agent_state.add_category("opencli", "Test content")
        
        assert "opencli" in agent_state.loaded_categories, "Category should be in loaded_categories"
        assert "opencli" in agent_state.category_contents, "Category should be in category_contents"
        assert agent_state.category_contents["opencli"] == "Test content", "Content should match"

    def test_add_skill(self, agent_state):
        """Test adding skill to state."""
        agent_state.add_skill("opencli/smart-search", "Test skill content")
        
        assert "opencli/smart-search" in agent_state.loaded_skills, "Skill should be in loaded_skills"
        assert "opencli/smart-search" in agent_state.skill_contents, "Skill should be in skill_contents"
        assert agent_state.skill_contents["opencli/smart-search"] == "Test skill content", "Content should match"

    def test_state_reset(self, agent_state):
        """Test state reset clears loaded skills and categories."""
        agent_state.add_category("opencli", "Test content")
        agent_state.add_skill("opencli/smart-search", "Test skill content")
        
        agent_state.reset()
        
        assert len(agent_state.loaded_categories) == 0, "loaded_categories should be empty"
        assert len(agent_state.category_contents) == 0, "category_contents should be empty"
        assert len(agent_state.loaded_skills) == 0, "loaded_skills should be empty"
        assert len(agent_state.skill_contents) == 0, "skill_contents should be empty"


class TestPromptBuilder:
    """Tests for PromptBuilder with skill and category content."""

    @pytest.fixture
    def skill_manager(self):
        """Create a SkillManager instance."""
        return SkillManager()

    @pytest.fixture
    def agent_state(self):
        """Create an AgentState instance."""
        state = AgentState()
        state.mode = 'default'
        state.phase = AgentPhase.DEFAULT
        return state

    def test_build_default_state_with_loaded_category(self, skill_manager, agent_state):
        """Test that build_default_state shows loaded categories."""
        agent_state.add_category("opencli", "Test category content")
        
        builder = PromptBuilder(skill_manager, agent_state)
        state_prompt = builder.build_default_state({"objective": "Test objective"})
        
        assert "opencli" in state_prompt, "State should show loaded category"

    def test_build_default_state_with_loaded_skill(self, skill_manager, agent_state):
        """Test that build_default_state shows loaded skills."""
        agent_state.add_skill("opencli/smart-search", "Test skill content")
        
        builder = PromptBuilder(skill_manager, agent_state)
        state_prompt = builder.build_default_state({"objective": "Test objective"})
        
        assert "smart-search" in state_prompt or "opencli" in state_prompt, "State should show loaded skill"

    def test_build_context_with_skill_content(self, skill_manager, agent_state):
        """Test that build_context includes skill content."""
        agent_state.add_skill("opencli/smart-search", "This is the skill content for testing.")
        
        builder = PromptBuilder(skill_manager, agent_state)
        context_prompt = builder.build_context(AgentPhase.DEFAULT)
        
        assert "skill content" in context_prompt.lower() or "smart-search" in context_prompt, "Context should include skill content"

    def test_build_context_with_category_content(self, skill_manager, agent_state):
        """Test that build_context includes category content."""
        agent_state.add_category("opencli", "This is the category content for testing.")
        
        builder = PromptBuilder(skill_manager, agent_state)
        context_prompt = builder.build_context(AgentPhase.DEFAULT)
        
        assert "category content" in context_prompt.lower() or "opencli" in context_prompt, "Context should include category content"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

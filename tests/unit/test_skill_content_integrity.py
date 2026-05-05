"""验证skill内容在所有模式下完整载入，不被截断的测试"""

import pytest
from pathlib import Path

from agent.skills.manager import SkillManager
from agent.state import AgentState, AgentPhase
from agent.prompts.builder import PromptBuilder


class TestSkillContentIntegrity:
    """测试skill内容在不同阶段是否完整载入。"""

    @pytest.fixture
    def skill_manager(self):
        """创建SkillManager实例。"""
        return SkillManager()

    @pytest.fixture
    def skill_file_path(self):
        """获取opencli-operate的SKILL.md文件路径。"""
        return Path(__file__).parent.parent.parent / "skills" / "opencli" / "opencli-operate" / "SKILL.md"

    def _create_state_for_phase(self, phase: AgentPhase) -> AgentState:
        """为指定阶段创建AgentState。"""
        state = AgentState()
        state.mode = 'default' if phase == AgentPhase.DEFAULT else 'research'
        state.phase = phase
        return state

    def _load_skill_and_build_prompt(self, skill_manager: SkillManager, phase: AgentPhase, skill_name: str) -> tuple[str, str]:
        """加载skill并构建prompt，返回prompt内容和原始skill内容。"""
        state = self._create_state_for_phase(phase)
        
        # 加载skill
        skill_content = skill_manager.load_skill(skill_name)
        assert skill_content is not None, f"Skill {skill_name} should exist"
        
        # 将skill内容添加到state
        state.add_skill(skill_name, skill_content)
        
        # 构建prompt
        builder = PromptBuilder(skill_manager, state)
        prompt = builder.build(phase.value, {"objective": "Test objective"})
        
        return prompt, skill_content

    @pytest.mark.parametrize("phase", [
        AgentPhase.DEFAULT,
        AgentPhase.COLLECT,
        AgentPhase.PLAN,
    ])
    def test_skill_content_not_truncated_in_phase(self, skill_manager, phase, skill_file_path):
        """验证在各阶段prompt中skill内容不被截断。"""
        skill_name = "opencli/opencli-operate"
        
        prompt, original_content = self._load_skill_and_build_prompt(skill_manager, phase, skill_name)
        
        # 验证prompt中包含完整的skill内容
        assert original_content in prompt, (
            f"Phase {phase.value}: prompt should contain complete skill content. "
            f"Original length: {len(original_content)}, "
            f"Prompt length: {len(prompt)}"
        )

    @pytest.mark.parametrize("phase", [
        AgentPhase.DEFAULT,
        AgentPhase.COLLECT,
        AgentPhase.PLAN,
    ])
    def test_skill_content_length_matches_original(self, skill_manager, phase, skill_file_path):
        """验证skill内容长度等于原始SKILL.md文件长度。"""
        skill_name = "opencli/opencli-operate"
        
        # 读取原始文件
        original_file_content = skill_file_path.read_text(encoding="utf-8")
        
        prompt, loaded_content = self._load_skill_and_build_prompt(skill_manager, phase, skill_name)
        
        # 验证加载的内容长度与原始文件一致
        assert len(loaded_content) == len(original_file_content), (
            f"Phase {phase.value}: loaded skill content length ({len(loaded_content)}) "
            f"should match original file length ({len(original_file_content)})"
        )

    @pytest.mark.parametrize("phase", [
        AgentPhase.DEFAULT,
        AgentPhase.COLLECT,
        AgentPhase.PLAN,
    ])
    def test_prompt_contains_key_skill_sections(self, skill_manager, phase):
        """验证prompt中包含skill的关键部分（不只是截断的前缀）。"""
        skill_name = "opencli/opencli-operate"
        
        prompt, original_content = self._load_skill_and_build_prompt(skill_manager, phase, skill_name)
        
        # 检查是否包含skill中的关键部分
        key_sections = [
            "Critical Rules",
            "Command Cost Guide",
            "Action Chaining Rules",
            "Core Workflow",
            "Commands",
            "Navigation",
            "Inspect",
            "Interact",
            "Wait",
            "Extract",
            "Network",
            "Sedimentation",
            "Example: Extract HN Stories",
            "Example: Fill a Form",
            "Strategy Guide",
            "Windows-Specific Notes",
        ]
        
        for section in key_sections:
            assert section in prompt, (
                f"Phase {phase.value}: prompt should contain section '{section}'. "
                f"This indicates the skill content may be truncated."
            )

    def test_collect_phase_shows_full_skill_content(self, skill_manager):
        """验证COLLECT阶段显示完整的skill内容。"""
        skill_name = "opencli/opencli-operate"
        
        prompt, original_content = self._load_skill_and_build_prompt(
            skill_manager, AgentPhase.COLLECT, skill_name
        )
        
        # COLLECT阶段应该包含完整的skill内容
        assert original_content.strip() in prompt.strip(), (
            "COLLECT phase should include complete skill content without truncation"
        )

    def test_plan_phase_shows_full_skill_content(self, skill_manager):
        """验证PLAN阶段显示完整的skill内容。"""
        skill_name = "opencli/opencli-operate"
        
        prompt, original_content = self._load_skill_and_build_prompt(
            skill_manager, AgentPhase.PLAN, skill_name
        )
        
        # PLAN阶段应该包含完整的skill内容
        assert original_content.strip() in prompt.strip(), (
            "PLAN phase should include complete skill content without truncation"
        )

    def test_default_phase_shows_full_skill_content(self, skill_manager):
        """验证DEFAULT阶段显示完整的skill内容。"""
        skill_name = "opencli/opencli-operate"
        
        prompt, original_content = self._load_skill_and_build_prompt(
            skill_manager, AgentPhase.DEFAULT, skill_name
        )
        
        # DEFAULT阶段应该包含完整的skill内容
        assert original_content.strip() in prompt.strip(), (
            "DEFAULT phase should include complete skill content without truncation"
        )

    def test_larger_skill_not_truncated(self, skill_manager):
        """验证较大的skill（如lark-base）不被截断。"""
        skill_name = "feishu/skills/lark-base"
        
        prompt, original_content = self._load_skill_and_build_prompt(
            skill_manager, AgentPhase.COLLECT, skill_name
        )
        
        # 验证完整内容在prompt中
        assert original_content in prompt, (
            f"Large skill '{skill_name}' should not be truncated. "
            f"Original length: {len(original_content)}, "
            f"Found in prompt: {original_content[:100]}..."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

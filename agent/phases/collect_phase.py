"""信息收集阶段"""

import logging

from .base import BasePhase
from .result import PhaseResult
from ..hooks.types import PhaseStatus
from ..state import AgentPhase
from ..tools.manager.manager import get_tool_manager
from .handlers import (
    ExecuteCommandHandler, ExecuteCommandFormatter,
    LoadSkillHandler, LoadSkillFormatter,
    LoadReferenceHandler, LoadReferenceFormatter,
    LoadSkillCategoryHandler, LoadSkillCategoryFormatter,
)

logger = logging.getLogger(__name__)


class CollectPhase(BasePhase):
    """信息收集阶段

    职责：
    - 加载技能 (load_skill)
    - 加载参考文档 (load_reference)
    - 收集必要信息
    - 调用 start_plan 进入下一阶段
    """

    @property
    def phase_name(self) -> str:
        return "COLLECT"

    @property
    def available_tools(self) -> list[dict]:
        return get_tool_manager().get_tools_for_phase(AgentPhase.COLLECT)

    def _register_default_handlers(self):
        """注册 CollectPhase 特有的处理器"""
        super()._register_default_handlers()
        self.register_handler(ExecuteCommandHandler(action_label="命令验证"))
        self.register_formatter(ExecuteCommandFormatter())
        self.register_handler(LoadSkillHandler())
        self.register_formatter(LoadSkillFormatter())
        self.register_handler(LoadReferenceHandler())
        self.register_formatter(LoadReferenceFormatter())
        self.register_handler(LoadSkillCategoryHandler())
        self.register_formatter(LoadSkillCategoryFormatter())

    def handle_tool_result(self, tool_name: str, result: dict, state) -> PhaseStatus:
        """处理工具执行结果并返回阶段状态

        Args:
            tool_name: 工具名称
            result: 工具执行结果
            state: 当前 AgentState

        Returns:
            PhaseStatus: 阶段状态枚举值
        """
        if tool_name == "start_plan":
            return PhaseStatus.TRANSITION
        phase_result = self._dispatch_tool_result(tool_name, result)
        status_map = {
            "continue": PhaseStatus.CONTINUE,
            "transition": PhaseStatus.TRANSITION,
            "complete": PhaseStatus.COMPLETE,
            "error": PhaseStatus.ERROR,
        }
        return status_map.get(phase_result.status, PhaseStatus.CONTINUE)

    def format_tool_result(self, tool_name: str, result: dict) -> str:
        """格式化工具执行结果为消息文本

        Args:
            tool_name: 工具名称
            result: 工具执行结果

        Returns:
            str: 格式化后的消息文本
        """
        return self._dispatch_format_result(tool_name, result)

    def cleanup_context(self) -> None:
        """清理COLLECT阶段的上下文

        - 保存阶段摘要（包含技能命令摘要）
        - 清空skill_contents和reference_contents
        - 不压缩对话历史，依赖渐进式压缩机制
        """
        summary_parts = []
        if self.state.loaded_skills:
            summary_parts.append(f"已加载技能: {', '.join(self.state.loaded_skills)}")

        command_summary_parts = []
        for skill_name, content in self.state.skill_contents.items():
            commands = self._extract_command_summary(content)
            if commands:
                command_summary_parts.append(f"[{skill_name}]\n{commands}")
        if command_summary_parts:
            summary_parts.append("关键命令参考:\n" + "\n".join(command_summary_parts))

        if self.state.loaded_references:
            refs = [f"{s}/{r}" for s, r in self.state.loaded_references]
            summary_parts.append(f"已加载参考文档: {', '.join(refs)}")

        summary = "\n".join(summary_parts) if summary_parts else "无技能或参考文档加载"
        self.state.set_phase_summary("collect", summary)

        self.state.clear_skill_contents()
        self.state.clear_reference_contents()

        logger.info(f"COLLECT context cleaned up. Summary: {summary[:100]}...")

    @staticmethod
    def _extract_command_summary(skill_content: str) -> str:
        """从技能内容中提取命令摘要

        提取包含命令格式的行，保留关键用法信息
        """
        commands = []
        for line in skill_content.split('\n'):
            stripped = line.strip()
            if '`opencli' in stripped or '`list' in stripped or '`operate' in stripped:
                commands.append(stripped)
            elif stripped.startswith('- `') and ('opencli' in stripped or 'search' in stripped or 'note' in stripped):
                commands.append(stripped)
            elif 'opencli(' in stripped:
                commands.append(stripped)
        return '\n'.join(commands[:15]) if commands else ""

    def _handle_start_plan(self, arguments: dict, original_request: str) -> PhaseResult:
        """处理 start_plan 工具调用"""
        if self.state.phase != AgentPhase.COLLECT:
            return PhaseResult(
                status="error",
                message=f"只能在COLLECT阶段调用start_plan，当前阶段: {self.state.phase.value}"
            )

        collected_info = arguments.get("collected_info", "")
        loaded_skills = arguments.get("loaded_skills", list(self.state.loaded_skills))

        return PhaseResult(
            status="transition",
            next_phase="PLAN",
            message="已进入规划阶段。请分析任务需求，制定执行计划，然后调用 start_execute 工具进入执行阶段。",
            data={
                "collected_info": collected_info,
                "loaded_skills": loaded_skills,
                "original_request": original_request
            }
        )

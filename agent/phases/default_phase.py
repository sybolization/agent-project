"""DefaultPhase - 默认阶段，支持直接执行任务"""

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
    UpdateTodoHandler, UpdateTodoFormatter,
    SpawnAgentsHandler, SpawnAgentsFormatter,
    TaskCompleteHandler,
    CdpConnectHandler, CdpConnectFormatter,
    CdpExecuteHandler, CdpExecuteFormatter,
    CdpGetStateHandler, CdpGetStateFormatter,
    CdpEditHelpersHandler, CdpEditHelpersFormatter,
)


class DefaultPhase(BasePhase):
    """默认阶段

    职责：
    - 直接执行任务，无需经过COLLECT/PLAN阶段
    - 支持加载技能和参考文档
    - 支持命令执行
    - 支持TODO管理和任务完成
    - 支持并行子Agent

    当所有TODO完成后自动进入汇报阶段
    """

    def __init__(self, prompt_builder, state):
        super().__init__(prompt_builder=prompt_builder, state=state)
        self._cdp_error_count = 0
        self._cdp_max_errors = 5

    @property
    def phase_name(self) -> str:
        return "DEFAULT"

    @property
    def available_tools(self) -> list[dict]:
        exclude_tools = None
        if self.state.agent_depth >= 1:
            exclude_tools = ["spawn_agents"]
        return get_tool_manager().get_tools_for_phase(AgentPhase.DEFAULT, exclude_tools)

    def _register_default_handlers(self):
        """注册 DefaultPhase 特有的处理器"""
        super()._register_default_handlers()
        self.register_handler(ExecuteCommandHandler(action_label="命令执行"))
        self.register_formatter(ExecuteCommandFormatter())
        self.register_handler(LoadSkillHandler())
        self.register_formatter(LoadSkillFormatter())
        self.register_handler(LoadReferenceHandler())
        self.register_formatter(LoadReferenceFormatter())
        self.register_handler(LoadSkillCategoryHandler())
        self.register_formatter(LoadSkillCategoryFormatter())
        # DefaultPhase: update_todo 全部完成时 status="complete"
        self.register_handler(UpdateTodoHandler(on_all_completed_status="complete"))
        self.register_formatter(UpdateTodoFormatter())
        self.register_handler(SpawnAgentsHandler())
        self.register_formatter(SpawnAgentsFormatter())
        # DefaultPhase: task_complete 返回 status="complete"
        self.register_handler(TaskCompleteHandler(completion_status="complete"))
        # CDP 处理器
        self.register_handler(CdpConnectHandler())
        self.register_formatter(CdpConnectFormatter())
        self.register_handler(CdpExecuteHandler())
        self.register_formatter(CdpExecuteFormatter())
        self.register_handler(CdpGetStateHandler())
        self.register_formatter(CdpGetStateFormatter())
        self.register_handler(CdpEditHelpersHandler())
        self.register_formatter(CdpEditHelpersFormatter())

    def _handle_tool_result(self, tool_name: str, result: dict) -> PhaseResult:
        """使用 Handler 分发机制处理工具结果"""
        if result.get("should_record"):
            self.state.add_action(
                result["record_data"]["tool_name"],
                result["record_data"]["arguments"],
                result["record_data"]["result_summary"]
            )
        return self._dispatch_tool_result(tool_name, result)

    def _format_tool_result_message(self, tool_name: str, result: dict) -> str:
        """使用 Formatter 分发机制格式化工具结果"""
        return self._dispatch_format_result(tool_name, result)

    def handle_tool_result(self, tool_name: str, result: dict, state) -> PhaseStatus:
        """处理工具执行结果并返回阶段状态

        通过 _handle_tool_result 分发处理，将 PhaseResult.status 映射为 PhaseStatus 枚举。

        Args:
            tool_name: 工具名称
            result: 工具执行结果
            state: 当前 AgentState

        Returns:
            PhaseStatus: 阶段状态枚举值
        """
        phase_result = self._handle_tool_result(tool_name, result)
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

"""ExecutePhase - Execution phase with multi-turn tool calling."""

from .base import BasePhase
from ..hooks.types import PhaseStatus
from ..state import AgentPhase
from ..tools.manager.manager import get_tool_manager
from .handlers import (
    ExecuteCommandHandler, ExecuteCommandFormatter,
    UpdateTodoHandler, UpdateTodoFormatter,
    SpawnAgentsHandler, SpawnAgentsFormatter,
    TaskCompleteHandler,
)


class ExecutePhase(BasePhase):
    """执行阶段

    职责：
    - 执行 execute_command 命令
    - 跟踪进度
    - 管理TODO列表并推进任务

    支持单次迭代内的多轮工具调用：
    LLM调用工具 -> 执行 -> 结果回传LLM -> LLM决定下一步
    当所有TODO完成后自动进入汇报阶段
    """

    def __init__(self, prompt_builder, state):
        super().__init__(prompt_builder=prompt_builder, state=state)
        self._max_repeat_count = 3

    @property
    def phase_name(self) -> str:
        return "EXECUTE"

    @property
    def available_tools(self) -> list[dict]:
        exclude_tools = None
        if self.state.agent_depth >= 1:
            exclude_tools = ["spawn_agents"]
        return get_tool_manager().get_tools_for_phase(AgentPhase.EXECUTE, exclude_tools)

    def _register_default_handlers(self):
        """注册 ExecutePhase 特有的处理器"""
        super()._register_default_handlers()
        self.register_handler(ExecuteCommandHandler(action_label="命令执行"))
        self.register_formatter(ExecuteCommandFormatter())
        # ExecutePhase: update_todo 全部完成时 status="transition", next_phase="REPORT"
        self.register_handler(UpdateTodoHandler(
            on_all_completed_status="transition",
            on_all_completed_next_phase="REPORT",
        ))
        self.register_formatter(UpdateTodoFormatter())
        self.register_handler(SpawnAgentsHandler())
        self.register_formatter(SpawnAgentsFormatter())
        # ExecutePhase: task_complete 返回 status="transition", next_phase="REPORT"
        self.register_handler(TaskCompleteHandler(
            completion_status="transition",
            completion_next_phase="REPORT",
        ))

    def handle_tool_result(self, tool_name: str, result: dict, state) -> PhaseStatus:
        """使用 Handler 分发机制处理工具结果，返回 PhaseStatus 枚举值

        Args:
            tool_name: 工具名称
            result: 工具执行结果
            state: 当前 AgentState

        Returns:
            PhaseStatus: 阶段状态枚举值
        """
        if result.get("should_record"):
            self.state.add_action(
                result["record_data"]["tool_name"],
                result["record_data"]["arguments"],
                result["record_data"]["result_summary"]
            )
        phase_result = self._dispatch_tool_result(tool_name, result)
        status_map = {
            "continue": PhaseStatus.CONTINUE,
            "transition": PhaseStatus.TRANSITION,
            "complete": PhaseStatus.COMPLETE,
            "error": PhaseStatus.ERROR,
        }
        return status_map.get(phase_result.status, PhaseStatus.CONTINUE)

    def format_tool_result(self, tool_name: str, result: dict) -> str:
        """使用 Formatter 分发机制格式化工具结果

        Args:
            tool_name: 工具名称
            result: 工具执行结果

        Returns:
            str: 格式化后的消息文本
        """
        return self._dispatch_format_result(tool_name, result)

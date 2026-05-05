"""task_complete 工具结果处理器"""

from typing import Optional

from . import ToolResultHandler
from ..result import PhaseResult


class TaskCompleteHandler(ToolResultHandler):
    """task_complete 工具结果处理器

    处理任务完成结果。不同阶段使用不同的完成状态和下一阶段配置：
    - DefaultPhase: status="complete"
    - ExecutePhase: status="transition", next_phase="REPORT"

    注意: task_complete 不需要格式化器，因为它在工具执行前就被拦截处理，
    不会走到 _format_tool_result_message 流程。

    Args:
        completion_status: 完成时的状态，默认 "complete"
        completion_next_phase: 完成时的下一阶段，默认 None
    """

    tool_name = "task_complete"

    def __init__(
        self,
        completion_status: str = "complete",
        completion_next_phase: Optional[str] = None,
    ):
        self.completion_status = completion_status
        self.completion_next_phase = completion_next_phase

    def handle(self, result: dict, state) -> PhaseResult:
        """处理 task_complete 工具结果

        Args:
            result: 工具执行结果字典
            state: Agent状态对象

        Returns:
            PhaseResult: 处理后的阶段结果
        """
        # DefaultPhase: status="complete", message="任务已完成"
        # ExecutePhase: status="transition", next_phase="REPORT", message="已调用强制完成，正在进入汇报阶段..."
        if self.completion_status == "transition":
            return PhaseResult(
                status="transition",
                next_phase=self.completion_next_phase,
                message="已调用强制完成，正在进入汇报阶段..."
            )
        return PhaseResult(
            status=self.completion_status,
            message="任务已完成"
        )

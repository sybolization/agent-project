"""ReportPhase - 工作汇报阶段"""

from .base import BasePhase
from ..hooks.types import PhaseStatus


class ReportPhase(BasePhase):
    """工作汇报阶段

    职责：
    - 让LLM基于完整context汇报工作结果
    - 无工具可用，LLM直接输出汇报内容
    - 输出后任务结束
    """

    @property
    def phase_name(self) -> str:
        return "REPORT"

    @property
    def available_tools(self) -> list[dict]:
        return []

    def handle_tool_result(self, tool_name: str, result: dict, state) -> PhaseStatus:
        """处理工具执行结果并返回阶段状态

        ReportPhase 无工具可用，直接返回 COMPLETE。

        Args:
            tool_name: 工具名称
            result: 工具执行结果
            state: 当前 AgentState

        Returns:
            PhaseStatus: PhaseStatus.COMPLETE
        """
        return PhaseStatus.COMPLETE

    def format_tool_result(self, tool_name: str, result: dict) -> str:
        """格式化工具执行结果为消息文本

        ReportPhase 无工具格式化需求。

        Args:
            tool_name: 工具名称
            result: 工具执行结果

        Returns:
            str: 固定提示消息
        """
        return "ReportPhase: no tool formatting needed"



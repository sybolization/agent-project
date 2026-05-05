"""规划阶段"""

import json
import logging

from .base import BasePhase, PhaseResult
from ..hooks.types import PhaseStatus
from ..state import AgentPhase
from ..tools.manager.manager import get_tool_manager

logger = logging.getLogger(__name__)


class PlanPhase(BasePhase):
    """规划阶段
    
    职责：
    - 分析任务需求
    - 制定执行计划
    - 调用 start_execute 进入下一阶段
    """
    
    @property
    def phase_name(self) -> str:
        return "PLAN"
    
    @property
    def available_tools(self) -> list[dict]:
        return get_tool_manager().get_tools_for_phase(AgentPhase.PLAN)

    def handle_tool_result(self, tool_name: str, result: dict, state) -> PhaseStatus:
        """处理工具执行结果并返回阶段状态

        PlanPhase 只接受 start_execute 工具，其他工具返回 ERROR。

        Args:
            tool_name: 工具名称
            result: 工具执行结果
            state: 当前 AgentState

        Returns:
            PhaseStatus: 阶段状态枚举值
        """
        if tool_name == "start_execute":
            return PhaseStatus.TRANSITION
        return PhaseStatus.ERROR

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
        """清理PLAN阶段的上下文

        - 不压缩对话历史，由渐进式压缩机制处理
        """
        logger.info("PLAN context cleaned up.")

    def _handle_start_execute(self, arguments: dict, original_request: str) -> PhaseResult:
        """处理 start_execute 工具调用"""
        if self.state.phase != AgentPhase.PLAN:
            return PhaseResult(
                status="error",
                message=f"只能在PLAN阶段调用start_execute，当前阶段: {self.state.phase.value}"
            )
        
        todo_list = arguments.get("todo_list", [])
        estimated_steps = arguments.get("estimated_steps", len(todo_list))
        
        if isinstance(todo_list, str):
            try:
                todo_list = json.loads(todo_list)
            except json.JSONDecodeError:
                todo_list = []
        
        if not todo_list or len(todo_list) == 0:
            return PhaseResult(
                status="error",
                message=(
                    "[!] start_execute 必须提供非空的 todo_list。\n"
                    "请将任务分解为具体的子任务，每个子任务包含 id、content、status。\n"
                    "示例：\n"
                    '{"id": "1", "content": "搜索笔记", "status": "pending"}'
                )
            )
        
        self.state.set_todo_list(todo_list)
        
        return PhaseResult(
            status="transition",
            next_phase="EXECUTE",
            message="已进入执行阶段。请按计划执行命令，完成后调用 task_complete 工具。",
            data={
                "estimated_steps": estimated_steps,
                "todo_list": todo_list,
                "original_request": original_request
            }
        )

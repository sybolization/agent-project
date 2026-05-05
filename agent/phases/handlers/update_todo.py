"""update_todo 工具结果处理器和格式化器"""

from typing import Optional

from . import ToolResultHandler, ToolResultFormatter
from ..result import PhaseResult


class UpdateTodoHandler(ToolResultHandler):
    """update_todo 工具结果处理器

    处理 TODO 更新结果，检测是否所有 TODO 已完成。
    不同阶段在所有 TODO 完成时使用不同的状态和下一阶段配置：
    - DefaultPhase: status="complete"
    - ExecutePhase: status="transition", next_phase="REPORT"

    Args:
        on_all_completed_status: 所有TODO完成时的状态，默认 "complete"
        on_all_completed_next_phase: 所有TODO完成时的下一阶段，默认 None
    """

    tool_name = "update_todo"

    def __init__(
        self,
        on_all_completed_status: str = "complete",
        on_all_completed_next_phase: Optional[str] = None,
    ):
        self.on_all_completed_status = on_all_completed_status
        self.on_all_completed_next_phase = on_all_completed_next_phase

    def handle(self, result: dict, state) -> PhaseResult:
        """处理 update_todo 工具结果

        Args:
            result: 工具执行结果字典
            state: Agent状态对象

        Returns:
            PhaseResult: 处理后的阶段结果
        """
        if result.get("type") == "todo_updated":
            progress = result.get("progress", {})
            message = result.get("message", "")

            # 检测是否所有TODO已完成
            if progress.get('total', 0) > 0 and progress.get('completed', 0) == progress.get('total', 0):
                phase_result = PhaseResult(
                    status=self.on_all_completed_status,
                    message=f"[OK] {message}\n\n任务已完成！",
                    next_phase=self.on_all_completed_next_phase,
                )
                # ExecutePhase 使用不同的消息
                if self.on_all_completed_status == "transition":
                    phase_result.message = f"[OK] {message}\n\n所有任务已完成！即将进入汇报阶段..."
                return phase_result

            return PhaseResult(
                status="continue",
                message=f"[OK] {message}",
                data={"progress": progress}
            )
        elif result.get("type") == "error":
            return PhaseResult(
                status="continue",
                message=f"[X] {result.get('message', 'TODO更新失败')}",
                data={"error": result.get("message")}
            )
        return PhaseResult(status="error", message="TODO更新失败")


class UpdateTodoFormatter(ToolResultFormatter):
    """update_todo 工具结果格式化器"""

    tool_name = "update_todo"

    def format(self, result: dict) -> str:
        """格式化 update_todo 工具结果

        Args:
            result: 工具执行结果字典

        Returns:
            str: 格式化后的消息文本
        """
        if result.get("type") == "todo_updated":
            return result.get("message", "[OK] TODO已更新")
        elif result.get("type") == "error":
            return f"[错误] TODO更新失败: {result.get('message', '未知错误')}"
        return "[错误] TODO更新失败"

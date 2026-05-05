"""update_task_status 工具 - 更新任务状态"""

from agent.tools.protocol import ToolDefinition
from agent.state import AgentPhase
from agent.phases.result import PhaseResult


SCHEMA = {
    "type": "function",
    "function": {
        "name": "update_task_status",
        "description": (
            "更新任务状态。"
            "当任务完成时，会自动解锁依赖此任务的其他任务。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "要更新的任务ID"
                },
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed", "failed", "cancelled"],
                    "description": "新的任务状态"
                }
            },
            "required": ["task_id", "status"]
        }
    }
}


class UpdateTaskStatusTool:
    def __init__(self, task_manager):
        self._task_manager = task_manager

    def execute(self, call: dict, context) -> dict:
        try:
            return self._task_manager.update_task_status(call.get("arguments", {}))
        except Exception as e:
            return {"type": "error", "message": str(e)}

    def handle(self, result: dict, state) -> PhaseResult:
        if result.get("type") == "error":
            return PhaseResult(status="continue", message=f"[错误] {result.get('message')}")
        return PhaseResult(status="continue", message=str(result))

    def format(self, result: dict) -> str:
        if result.get("type") == "error":
            return f"[错误] {result.get('message')}"
        return f"[OK] 任务状态已更新"


tool_definition = ToolDefinition(
    name="update_task_status",
    schema=SCHEMA,
    phases=[AgentPhase.DEFAULT, AgentPhase.EXECUTE],
    description="更新任务状态，完成时自动解锁依赖任务",
    usage_hint="update_task_status(task_id, status)",
    executor=UpdateTaskStatusTool(task_manager=None),
)

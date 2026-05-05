"""assign_task 工具 - 分配任务"""

from agent.tools.protocol import ToolDefinition
from agent.state import AgentPhase
from agent.phases.result import PhaseResult


SCHEMA = {
    "type": "function",
    "function": {
        "name": "assign_task",
        "description": (
            "将任务分配给指定的agent。"
            "用于多agent协作场景。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "要分配的任务ID"
                },
                "owner": {
                    "type": "string",
                    "description": "执行者名称"
                }
            },
            "required": ["task_id", "owner"]
        }
    }
}


class AssignTaskTool:
    def __init__(self, task_manager):
        self._task_manager = task_manager

    def execute(self, call: dict, context) -> dict:
        try:
            return self._task_manager.assign_task(call.get("arguments", {}))
        except Exception as e:
            return {"type": "error", "message": str(e)}

    def handle(self, result: dict, state) -> PhaseResult:
        if result.get("type") == "error":
            return PhaseResult(status="continue", message=f"[错误] {result.get('message')}")
        return PhaseResult(status="continue", message=str(result))

    def format(self, result: dict) -> str:
        if result.get("type") == "error":
            return f"[错误] {result.get('message')}"
        return f"[OK] 任务已分配"


tool_definition = ToolDefinition(
    name="assign_task",
    schema=SCHEMA,
    phases=[AgentPhase.DEFAULT, AgentPhase.EXECUTE],
    description="将任务分配给指定的agent",
    usage_hint="assign_task(task_id, owner)",
    executor=AssignTaskTool(task_manager=None),
)

"""add_task_dependency 工具 - 添加任务依赖"""

from agent.tools.protocol import ToolDefinition
from agent.state import AgentPhase
from agent.phases.result import PhaseResult


SCHEMA = {
    "type": "function",
    "function": {
        "name": "add_task_dependency",
        "description": (
            "添加任务依赖关系。"
            "任务B依赖任务A意味着：A完成后B才能开始。"
            "依赖关系会被双向维护。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "被依赖的任务ID（前置任务）"
                },
                "depends_on_task_id": {
                    "type": "integer",
                    "description": "依赖的任务ID（后置任务，需要等待前置任务完成）"
                }
            },
            "required": ["task_id", "depends_on_task_id"]
        }
    }
}


class AddTaskDependencyTool:
    def __init__(self, task_manager):
        self._task_manager = task_manager

    def execute(self, call: dict, context) -> dict:
        try:
            return self._task_manager.add_task_dependency(call.get("arguments", {}))
        except Exception as e:
            return {"type": "error", "message": str(e)}

    def handle(self, result: dict, state) -> PhaseResult:
        if result.get("type") == "error":
            return PhaseResult(status="continue", message=f"[错误] {result.get('message')}")
        return PhaseResult(status="continue", message=str(result))

    def format(self, result: dict) -> str:
        if result.get("type") == "error":
            return f"[错误] {result.get('message')}"
        return f"[OK] 任务依赖已添加"


tool_definition = ToolDefinition(
    name="add_task_dependency",
    schema=SCHEMA,
    phases=[AgentPhase.DEFAULT, AgentPhase.EXECUTE],
    description="添加任务依赖关系",
    usage_hint="add_task_dependency(task_id, depends_on_task_id)",
    executor=AddTaskDependencyTool(task_manager=None),
)

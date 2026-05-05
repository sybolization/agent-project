"""list_tasks 工具 - 列出任务"""

from agent.tools.protocol import ToolDefinition
from agent.state import AgentPhase
from agent.phases.result import PhaseResult


SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_tasks",
        "description": (
            "列出任务列表，支持按状态和执行者筛选。"
            "返回任务的详细信息，包括ID、主题、状态、依赖关系等。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed", "failed", "cancelled", "blocked"],
                    "description": "按状态筛选（可选）"
                },
                "owner": {
                    "type": "string",
                    "description": "按执行者筛选（可选）"
                }
            },
            "required": []
        }
    }
}


class ListTasksTool:
    def __init__(self, task_manager):
        self._task_manager = task_manager

    def execute(self, call: dict, context) -> dict:
        try:
            return self._task_manager.list_tasks(call.get("arguments", {}))
        except Exception as e:
            return {"type": "error", "message": str(e)}

    def handle(self, result: dict, state) -> PhaseResult:
        if result.get("type") == "error":
            return PhaseResult(status="continue", message=f"[错误] {result.get('message')}")
        tasks = result.get("tasks", [])
        return PhaseResult(status="continue", message=str(tasks))

    def format(self, result: dict) -> str:
        if result.get("type") == "error":
            return f"[错误] {result.get('message')}"
        tasks = result.get("tasks", [])
        lines = [f"[OK] 找到 {len(tasks)} 个任务:"]
        for t in tasks:
            lines.append(f"  - [{t.get('status', '?')}] {t.get('subject', t.get('id', '?'))}")
        return "\n".join(lines)


tool_definition = ToolDefinition(
    name="list_tasks",
    schema=SCHEMA,
    phases=[AgentPhase.DEFAULT, AgentPhase.EXECUTE],
    description="列出任务列表，支持按状态和执行者筛选",
    usage_hint="list_tasks(status, owner)",
    executor=ListTasksTool(task_manager=None),
)

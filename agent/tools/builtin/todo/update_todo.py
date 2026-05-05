"""update_todo 工具 - 更新TODO状态"""

from agent.tools.protocol import ToolDefinition
from agent.state import AgentPhase
from agent.phases.result import PhaseResult


SCHEMA = {
    "type": "function",
    "function": {
        "name": "update_todo",
        "description": (
            "更新TODO项的状态。"
            "当你开始或完成某个TODO项时，调用此工具更新状态。"
            "此工具只能在EXECUTE阶段调用。"
            "\n\n"
            "状态说明：\n"
            "- pending: 待处理\n"
            "- in_progress: 进行中\n"
            "- completed: 已完成"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "todo_id": {
                    "type": "string",
                    "description": "要更新的TODO项ID"
                },
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed"],
                    "description": "新的状态"
                }
            },
            "required": ["todo_id", "status"]
        }
    }
}


class UpdateTodoTool:
    def __init__(self, agent_state=None):
        self._agent_state = agent_state

    def execute(self, call: dict, context) -> dict:
        try:
            args = call.get("arguments", {})
            return {
                "type": "todo_updated",
                "todo_id": args.get("todo_id"),
                "status": args.get("status"),
            }
        except Exception as e:
            return {"type": "error", "message": str(e)}

    def handle(self, result: dict, state) -> PhaseResult:
        if result.get("type") == "error":
            return PhaseResult(status="continue", message=f"[错误] {result.get('message')}")

        status = result.get("status")
        todo_id = result.get("todo_id")

        if status == "completed":
            progress = state.get_todo_progress()
            all_completed = (
                progress.get("total", 0) > 0
                and progress.get("completed", 0) == progress.get("total", 0)
            )
            if all_completed:
                return PhaseResult(
                    status="transition",
                    next_phase=AgentPhase.REPORT,
                    message=f"TODO {todo_id} 已完成，所有TODO已完成，进入汇报阶段",
                )

        return PhaseResult(
            status="continue",
            message=f"TODO {todo_id} -> {status}",
        )

    def format(self, result: dict) -> str:
        if result.get("type") == "error":
            return f"[错误] {result.get('message')}"
        return f"[OK] TODO {result.get('todo_id')} -> {result.get('status')}"


tool_definition = ToolDefinition(
    name="update_todo",
    schema=SCHEMA,
    phases=[AgentPhase.EXECUTE],
    description="更新TODO项的状态",
    usage_hint="update_todo(todo_id, status)",
    executor=UpdateTodoTool(),
)

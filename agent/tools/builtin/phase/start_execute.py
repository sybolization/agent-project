"""start_execute 工具 - 进入执行阶段"""

from agent.tools.protocol import ToolDefinition
from agent.state import AgentPhase
from agent.phases.result import PhaseResult


SCHEMA = {
    "type": "function",
    "function": {
        "name": "start_execute",
        "description": (
            "标记规划阶段完成，进入执行阶段。"
            "当你准备好开始执行命令时，调用此工具。"
            "此工具只能在PLAN阶段调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "todo_list": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "TODO项ID"},
                            "content": {"type": "string", "description": "TODO项内容"},
                            "status": {"type": "string", "enum": ["pending", "in_progress", "completed"], "description": "TODO项状态"}
                        },
                        "required": ["id", "content", "status"]
                    },
                    "description": "TODO列表，将任务分解为可追踪的子任务。所有TODO必须完成后才能调用task_complete。"
                },
                "estimated_steps": {
                    "type": "integer",
                    "description": "预计执行步骤数"
                }
            },
            "required": ["todo_list"]
        }
    }
}


class StartExecuteTool:
    def execute(self, call: dict, context) -> dict:
        try:
            args = call.get("arguments", {})
            return {"type": "phase_transition", "todo_list": args.get("todo_list", [])}
        except Exception as e:
            return {"type": "error", "message": str(e)}

    def handle(self, result: dict, state) -> PhaseResult:
        if result.get("type") == "error":
            return PhaseResult(status="continue", message=f"[错误] {result.get('message')}")
        return PhaseResult(
            status="transition",
            next_phase=AgentPhase.EXECUTE,
            message="已进入执行阶段",
        )

    def format(self, result: dict) -> str:
        if result.get("type") == "error":
            return f"[错误] {result.get('message')}"
        todo_count = len(result.get("todo_list", []))
        return f"[OK] 进入执行阶段，共 {todo_count} 个TODO项"


tool_definition = ToolDefinition(
    name="start_execute",
    schema=SCHEMA,
    phases=[AgentPhase.PLAN],
    description="标记规划阶段完成，进入执行阶段",
    usage_hint="start_execute(todo_list, estimated_steps)",
    executor=StartExecuteTool(),
)

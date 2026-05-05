"""create_task 工具 - 创建持久化任务"""

from agent.tools.protocol import ToolDefinition
from agent.state import AgentPhase
from agent.phases.result import PhaseResult


SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_task",
        "description": (
            "创建一个新的持久化任务。"
            "任务会被保存到数据库，支持依赖关系和多agent分配。"
            "返回任务ID，可用于后续的任务管理操作。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "任务主题/标题，一句话描述任务内容"
                },
                "description": {
                    "type": "string",
                    "description": "任务详细描述（可选）"
                },
                "owner": {
                    "type": "string",
                    "description": "任务执行者名称（可选，用于多agent分配）"
                },
                "parent_id": {
                    "type": "integer",
                    "description": "父任务ID（可选，用于创建子任务）"
                }
            },
            "required": ["subject"]
        }
    }
}


class CreateTaskTool:
    def __init__(self, task_manager):
        self._task_manager = task_manager

    def execute(self, call: dict, context) -> dict:
        try:
            return self._task_manager.create_task(call.get("arguments", {}))
        except Exception as e:
            return {"type": "error", "message": str(e)}

    def handle(self, result: dict, state) -> PhaseResult:
        if result.get("type") == "error":
            return PhaseResult(status="continue", message=f"[错误] {result.get('message')}")
        task_id = result.get("task_id") or result.get("id", "?")
        return PhaseResult(status="continue", message=f"任务已创建: ID={task_id}")

    def format(self, result: dict) -> str:
        if result.get("type") == "error":
            return f"[错误] {result.get('message')}"
        task_id = result.get("task_id") or result.get("id", "?")
        return f"[OK] 任务已创建: ID={task_id}"


tool_definition = ToolDefinition(
    name="create_task",
    schema=SCHEMA,
    phases=[AgentPhase.DEFAULT, AgentPhase.EXECUTE],
    description="创建一个新的持久化任务",
    usage_hint="create_task(subject, description, owner, parent_id)",
    executor=CreateTaskTool(task_manager=None),
)

"""task_complete 工具 - 强制完成任务"""

from agent.tools.protocol import ToolDefinition
from agent.state import AgentPhase
from agent.phases.result import PhaseResult


SCHEMA = {
    "type": "function",
    "function": {
        "name": "task_complete",
        "description": (
            "[强制完成] 强制结束当前任务并进入汇报阶段。\n\n"
            "调用此工具后：\n"
            "1. 所有未完成的TODO将被自动标记为completed\n"
            "2. 系统将进入REPORT阶段，你需要汇报工作结果\n\n"
            "使用场景：\n"
            "- 你认为任务已完成，但TODO列表未全部完成\n"
            "- 需要提前结束任务\n\n"
            "注意：如果所有TODO已完成，系统会自动进入REPORT阶段，无需调用此工具。\n\n"
            "请提供 summary 和 results 参数以提交任务结果。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "任务完成摘要，简要说明你完成了什么"
                },
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object"
                    },
                    "description": "任务的关键数据结果。将你收集到的核心数据以结构化数组形式提交，每个元素是一个对象。例如搜索任务可提交 [{rank:1, title:'...', url:'...'}, ...]"
                }
            },
            "required": []
        }
    }
}


class TaskCompleteTool:
    def execute(self, call: dict, context) -> dict:
        try:
            args = call.get("arguments", {})
            return {
                "type": "task_completed",
                "summary": args.get("summary", ""),
                "results": args.get("results", []),
            }
        except Exception as e:
            return {"type": "error", "message": str(e)}

    def handle(self, result: dict, state) -> PhaseResult:
        if result.get("type") == "error":
            return PhaseResult(status="continue", message=f"[错误] {result.get('message')}")
        return PhaseResult(
            status="transition",
            next_phase=AgentPhase.REPORT,
            message=result.get("summary", "任务完成"),
        )

    def format(self, result: dict) -> str:
        if result.get("type") == "error":
            return f"[错误] {result.get('message')}"
        return f"[OK] 任务已完成，进入汇报阶段"


tool_definition = ToolDefinition(
    name="task_complete",
    schema=SCHEMA,
    phases=[AgentPhase.DEFAULT, AgentPhase.EXECUTE],
    description="强制结束当前任务并进入汇报阶段",
    usage_hint="task_complete(summary, results)",
    executor=TaskCompleteTool(),
)

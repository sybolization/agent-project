"""start_plan 工具 - 进入规划阶段"""

from agent.tools.protocol import ToolDefinition
from agent.state import AgentPhase
from agent.phases.result import PhaseResult


SCHEMA = {
    "type": "function",
    "function": {
        "name": "start_plan",
        "description": (
            "标记信息收集阶段完成，进入规划阶段。"
            "当你完成了必要的信息收集后调用此工具。"
            "此工具只能在COLLECT阶段调用。"
            "\n\n"
            "collected_info 必须包含以下内容：\n"
            "1. 已加载技能的完整名称列表\n"
            "2. 已加载参考文档的完整名称列表\n"
            "3. 关键命令和用法摘要（包括命令格式、参数说明）\n"
            "4. 站点说明（如果适用，包括支持的平台、搜索类型等）\n"
            "5. 验证结果（工具是否可用、是否有特殊限制）"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "collected_info": {
                    "type": "string",
                    "description": (
                        "已收集的信息摘要，必须包含："
                        "技能名称、参考文档名称、关键命令摘要、站点说明、验证结果"
                    )
                },
                "loaded_skills": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "已加载的技能名称列表"
                }
            },
            "required": ["collected_info"]
        }
    }
}


class StartPlanTool:
    def __init__(self, agent_state=None):
        self._agent_state = agent_state

    def execute(self, call: dict, context) -> dict:
        try:
            collected_info = call.get("arguments", {}).get("collected_info", "")
            loaded_skills = call.get("arguments", {}).get("loaded_skills", [])
            return {
                "type": "phase_transition",
                "from_phase": "COLLECT",
                "to_phase": "PLAN",
                "collected_info": collected_info,
                "loaded_skills": loaded_skills,
            }
        except Exception as e:
            return {"type": "error", "message": str(e)}

    def handle(self, result: dict, state) -> PhaseResult:
        if result.get("type") == "error":
            return PhaseResult(status="continue", message=f"[错误] {result.get('message')}")
        return PhaseResult(
            status="transition",
            next_phase=AgentPhase.PLAN,
            message=result.get("collected_info", ""),
        )

    def format(self, result: dict) -> str:
        if result.get("type") == "error":
            return f"[错误] {result.get('message')}"
        return f"[OK] 进入规划阶段"


tool_definition = ToolDefinition(
    name="start_plan",
    schema=SCHEMA,
    phases=[AgentPhase.COLLECT],
    description="标记信息收集阶段完成，进入规划阶段",
    usage_hint="start_plan(collected_info, loaded_skills)",
    executor=StartPlanTool(),
)

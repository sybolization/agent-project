"""load_reference 工具 - 加载技能参考文档"""

from agent.tools.protocol import ToolDefinition
from agent.tools.lib.skill_lib import SkillExecutor
from agent.state import AgentPhase
from agent.phases.result import PhaseResult


SCHEMA = {
    "type": "function",
    "function": {
        "name": "load_reference",
        "description": (
            "Load a skill's reference document. "
            "Use this after loading the main skill to get more specific guidance."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Name of the skill"
                },
                "reference_name": {
                    "type": "string",
                    "description": "Name of the reference document without .md, e.g., 'sources-media', 'sources-ai'"
                }
            },
            "required": ["skill_name", "reference_name"]
        }
    }
}


class LoadReferenceTool:
    def __init__(self, skill_executor: SkillExecutor):
        self._skill_executor = skill_executor

    def execute(self, call: dict, context) -> dict:
        try:
            return self._skill_executor.execute_load_reference(call)
        except Exception as e:
            return {"type": "error", "message": str(e)}

    def handle(self, result: dict, state) -> PhaseResult:
        if result.get("type") == "reference_loaded":
            return PhaseResult(status="continue", message=result.get("content", ""))
        if result.get("type") == "error":
            return PhaseResult(status="continue", message=f"[错误] {result.get('message')}")
        return PhaseResult(status="continue", message="")

    def format(self, result: dict) -> str:
        if result.get("type") == "reference_loaded":
            return result.get("content", "")
        if result.get("type") == "error":
            return f"[错误] {result.get('message')}"
        return str(result)


tool_definition = ToolDefinition(
    name="load_reference",
    schema=SCHEMA,
    phases=[AgentPhase.DEFAULT, AgentPhase.COLLECT],
    description="Load a skill's reference document for more specific guidance",
    usage_hint="load_reference(skill_name, reference_name)",
    executor=LoadReferenceTool(skill_executor=None),
)

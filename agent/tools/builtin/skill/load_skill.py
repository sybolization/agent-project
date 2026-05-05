"""load_skill 工具 - 加载技能内容"""

from agent.tools.protocol import ToolDefinition
from agent.tools.lib.skill_lib import SkillExecutor
from agent.state import AgentPhase
from agent.phases.result import PhaseResult


SCHEMA = {
    "type": "function",
    "function": {
        "name": "load_skill",
        "description": (
            "Load a skill's main content (SKILL.md). "
            "Use this when you need detailed guidance for a specific task type. "
            "After loading, you can use load_reference to get more specific guidance."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Name of the skill to load. Check the available skills list above for valid names."
                }
            },
            "required": ["skill_name"]
        }
    }
}


class LoadSkillTool:
    def __init__(self, skill_executor: SkillExecutor):
        self._skill_executor = skill_executor

    def execute(self, call: dict, context) -> dict:
        try:
            return self._skill_executor.execute_load_skill(call)
        except Exception as e:
            return {"type": "error", "message": str(e)}

    def handle(self, result: dict, state) -> PhaseResult:
        if result.get("type") == "skill_loaded":
            phase = state.phase if state else None
            if phase == AgentPhase.COLLECT:
                return PhaseResult(status="continue", message=result.get("content", ""))
            return PhaseResult(status="continue", message=result.get("content", ""))
        if result.get("type") == "error":
            return PhaseResult(status="continue", message=f"[错误] {result.get('message')}")
        return PhaseResult(status="continue", message="")

    def format(self, result: dict) -> str:
        if result.get("type") == "skill_loaded":
            return result.get("content", "")
        if result.get("type") == "error":
            return f"[错误] {result.get('message')}"
        return str(result)


tool_definition = ToolDefinition(
    name="load_skill",
    schema=SCHEMA,
    phases=[AgentPhase.DEFAULT, AgentPhase.COLLECT],
    description="Load a skill's main content for detailed task guidance",
    usage_hint="load_skill(skill_name)",
    executor=LoadSkillTool(skill_executor=None),
    handler=None,
    formatter=None,
)

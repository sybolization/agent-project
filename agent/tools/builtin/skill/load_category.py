"""load_skill_category 工具 - 加载技能类别"""

from agent.tools.protocol import ToolDefinition
from agent.tools.lib.skill_lib import SkillExecutor
from agent.state import AgentPhase
from agent.phases.result import PhaseResult


SCHEMA = {
    "type": "function",
    "function": {
        "name": "load_skill_category",
        "description": (
            "加载某个技能类别的技能描述列表。"
            "使用此工具渐进式加载技能：先加载类别，再根据描述选择具体技能。"
            "可用类别：feishu（飞书办公套件）、opencli（通用命令行工具）"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "category_name": {
                    "type": "string",
                    "description": "类别名称：feishu 或 opencli"
                }
            },
            "required": ["category_name"]
        }
    }
}


class LoadCategoryTool:
    def __init__(self, skill_executor: SkillExecutor):
        self._skill_executor = skill_executor

    def execute(self, call: dict, context) -> dict:
        try:
            return self._skill_executor.execute_load_category(call)
        except Exception as e:
            return {"type": "error", "message": str(e)}

    def handle(self, result: dict, state) -> PhaseResult:
        if result.get("type") == "category_loaded":
            return PhaseResult(status="continue", message=result.get("content", ""))
        if result.get("type") == "error":
            return PhaseResult(status="continue", message=f"[错误] {result.get('message')}")
        return PhaseResult(status="continue", message="")

    def format(self, result: dict) -> str:
        if result.get("type") == "category_loaded":
            return result.get("content", "")
        if result.get("type") == "error":
            return f"[错误] {result.get('message')}"
        return str(result)


tool_definition = ToolDefinition(
    name="load_skill_category",
    schema=SCHEMA,
    phases=[AgentPhase.DEFAULT, AgentPhase.COLLECT],
    description="加载某个技能类别的技能描述列表",
    usage_hint="load_skill_category(category_name)",
    executor=LoadCategoryTool(skill_executor=None),
)

"""cdp_get_state 工具 - 获取浏览器状态"""

from agent.tools.protocol import ToolDefinition
from agent.tools.lib.cdp_lib import CdpExecutor
from agent.errors import CdpExecutionError
from agent.state import AgentPhase
from agent.phases import PhaseResult


SCHEMA = {
    "type": "function",
    "function": {
        "name": "cdp_get_state",
        "description": (
            "Get current browser state including URL, title, interactive elements, DOM summary, "
            "and a screenshot of the current page. "
            "Use this to understand the current page VISUALLY before taking actions. "
            "IMPORTANT: Always call this after navigation or when page state may have changed to see popups or overlays."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
}


class CdpGetStateTool:
    def __init__(self, cdp_executor: CdpExecutor):
        self._cdp = cdp_executor

    async def execute(self, call: dict, context) -> dict:
        try:
            return await self._cdp.execute_cdp_get_state()
        except CdpExecutionError as e:
            return {"type": "error", "message": str(e)}
        except Exception as e:
            return {"type": "error", "message": str(e)}

    def handle(self, result: dict, state) -> PhaseResult:
        if result.get("type") == "error":
            return PhaseResult(status="continue", message=f"[错误] {result.get('message')}")
        return PhaseResult(status="continue", message=str(result))

    def format(self, result: dict) -> str:
        if result.get("type") == "error":
            return f"[错误] {result.get('message')}"
        return str(result)


tool_definition = ToolDefinition(
    name="cdp_get_state",
    schema=SCHEMA,
    phases=[AgentPhase.EXECUTE],
    description="Get current browser state including URL, title, elements and screenshot",
    usage_hint="cdp_get_state()",
    executor=CdpGetStateTool(cdp_executor=None),
)

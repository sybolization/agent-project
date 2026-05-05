"""cdp_connect 工具 - 连接Chrome DevTools Protocol"""

from agent.tools.protocol import ToolDefinition
from agent.tools.lib.cdp_lib import CdpExecutor
from agent.errors import CdpExecutionError
from agent.state import AgentPhase
from agent.phases import PhaseResult


SCHEMA = {
    "type": "function",
    "function": {
        "name": "cdp_connect",
        "description": (
            "Connect to Chrome via CDP (Chrome DevTools Protocol). "
            "Requires Chrome running with --remote-debugging-port=9222. "
            "After connecting, you can use cdp_execute to control the browser directly. "
            "Cookies are automatically persisted: loaded on connect, saved on disconnect, and flushed every 120 seconds."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Chrome CDP host (default: localhost)"
                },
                "port": {
                    "type": "integer",
                    "description": "Chrome CDP port (default: 9222)"
                },
                "cookie_store_path": {
                    "type": "string",
                    "description": "Path to cookie persistence file (default: .cdp_state/cookies.json). Cookies are auto-saved/loaded to maintain login state across sessions."
                }
            },
            "required": []
        }
    }
}


class CdpConnectTool:
    def __init__(self, cdp_executor: CdpExecutor):
        self._cdp = cdp_executor

    async def execute(self, call: dict, context) -> dict:
        try:
            return await self._cdp.execute_cdp_connect(call.get("arguments", {}))
        except CdpExecutionError as e:
            return {"type": "error", "message": str(e)}
        except Exception as e:
            return {"type": "error", "message": str(e)}

    def handle(self, result: dict, state) -> PhaseResult:
        if result.get("type") == "cdp_connected":
            return PhaseResult(status="continue", message=result.get("message", "CDP已连接"))
        if result.get("type") == "error":
            return PhaseResult(status="continue", message=f"[错误] {result.get('message')}")
        return PhaseResult(status="continue", message=str(result))

    def format(self, result: dict) -> str:
        if result.get("type") == "cdp_connected":
            return f"[OK] {result.get('message', 'CDP已连接')}"
        if result.get("type") == "error":
            return f"[错误] {result.get('message')}"
        return str(result)


tool_definition = ToolDefinition(
    name="cdp_connect",
    schema=SCHEMA,
    phases=[AgentPhase.DEFAULT, AgentPhase.COLLECT, AgentPhase.EXECUTE],
    description="Connect to Chrome via CDP",
    usage_hint="cdp_connect(host, port, cookie_store_path)",
    executor=CdpConnectTool(cdp_executor=None),
)

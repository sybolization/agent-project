"""cdp_execute 工具 - 执行CDP命令"""

from agent.tools.protocol import ToolDefinition
from agent.tools.lib.cdp_lib import CdpExecutor
from agent.errors import CdpExecutionError
from agent.state import AgentPhase
from agent.phases import PhaseResult


SCHEMA = {
    "type": "function",
    "function": {
        "name": "cdp_execute",
        "description": (
            "Execute a CDP helper function or raw CDP command. "
            "Use this to control the browser after cdp_connect.\n\n"
            "Available helper functions and their parameters:\n"
            "- navigate(url: str) - Navigate to URL\n"
            "- get_url() - Get current page URL\n"
            "- get_title() - Get current page title\n"
            "- evaluate(expression: str) - Execute JavaScript and return result. Parameter is 'expression', NOT 'code'\n"
            "- query_selector(selector: str) - Find first element matching CSS selector, returns nodeId\n"
            "- query_selector_all(selector: str) - Find all elements matching CSS selector, returns nodeIds\n"
            "- click(selector: str) - Click element matching selector\n"
            "- type_text(text: str) - Type text into currently focused element. Use click() to focus an element first.\n"
            "- press_key(key: str) - Press a keyboard key\n"
            "- screenshot() - Take a screenshot, returns base64 image\n"
            "- scroll_down(pixels: int=300) - Scroll down\n"
            "- scroll_up(pixels: int=300) - Scroll up\n"
            "- wait_for_selector(selector: str, timeout: float=5.0) - Wait for element to appear. timeout is in SECONDS.\n"
            "- get_interactive_elements() - Get all interactive elements on page\n\n"
            "If a function is missing, you can add it using cdp_edit_helpers."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "function": {
                    "type": "string",
                    "description": "Helper function name or 'raw' for raw CDP command"
                },
                "args": {
                    "type": "object",
                    "description": "Arguments for the function. Use exact parameter names as listed above."
                },
                "method": {
                    "type": "string",
                    "description": "CDP method name (only when function='raw')"
                },
                "params": {
                    "type": "object",
                    "description": "CDP method params (only when function='raw')"
                }
            },
            "required": ["function"]
        }
    }
}


class CdpExecuteTool:
    def __init__(self, cdp_executor: CdpExecutor):
        self._cdp = cdp_executor

    async def execute(self, call: dict, context) -> dict:
        try:
            return await self._cdp.execute_cdp_execute(call.get("arguments", {}))
        except CdpExecutionError as e:
            return {"type": "error", "message": str(e)}
        except Exception as e:
            return {"type": "error", "message": str(e)}

    def handle(self, result: dict, state) -> PhaseResult:
        if result.get("type") == "error":
            return PhaseResult(status="continue", message=f"[错误] {result.get('message')}")
        data = result.get("data") or result.get("result") or result
        return PhaseResult(status="continue", message=str(data))

    def format(self, result: dict) -> str:
        if result.get("type") == "error":
            return f"[错误] {result.get('message')}"
        data = result.get("data") or result.get("result") or result
        if isinstance(data, dict) and data.get("screenshot"):
            screenshot = data.pop("screenshot", None)
            return f"[CDP] {str(data)}"
        return str(data)


tool_definition = ToolDefinition(
    name="cdp_execute",
    schema=SCHEMA,
    phases=[AgentPhase.EXECUTE],
    description="Execute CDP helper functions or raw CDP commands to control the browser",
    usage_hint="cdp_execute(function, args)",
    executor=CdpExecuteTool(cdp_executor=None),
)

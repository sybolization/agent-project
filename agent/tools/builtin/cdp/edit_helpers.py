"""cdp_edit_helpers 工具 - 添加CDP辅助函数"""

from agent.tools.protocol import ToolDefinition
from agent.tools.lib.cdp_lib import CdpExecutor
from agent.errors import CdpExecutionError
from agent.state import AgentPhase
from agent.phases import PhaseResult


SCHEMA = {
    "type": "function",
    "function": {
        "name": "cdp_edit_helpers",
        "description": (
            "Add a new helper function to the CDP helpers module. "
            "Use this when cdp_execute reports a missing function. "
            "Write the function code that uses cdp_client.execute() to send CDP commands.\n\n"
            "Example code for an upload_file function:\n"
            "async def upload_file(selector: str, file_path: str):\n"
            "    root_id = cdp_client.get_document_node_id()\n"
            "    node_id = await cdp_client.execute('DOM.querySelector', {'nodeId': root_id, 'selector': selector})\n"
            "    await cdp_client.execute('DOM.setFileInputFiles', {'files': [file_path], 'nodeId': node_id.get('nodeId')})\n"
            "    return True\n\n"
            "The function name in code must match the name parameter."
            "\n\nIf you want to execute the function immediately after adding it, set execute_immediately=true and provide execute_args. This saves a separate cdp_execute call."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Function name to add"
                },
                "code": {
                    "type": "string",
                    "description": "Python function code. Must define an async function with the given name. Can use cdp_client and CDPError."
                },
                "execute_immediately": {
                    "type": "boolean",
                    "description": "Whether to execute the function immediately after adding. Default: false. Set to true to register and execute in one step."
                },
                "execute_args": {
                    "type": "object",
                    "description": "Arguments for immediate execution (only used when execute_immediately=true)"
                }
            },
            "required": ["name", "code"]
        }
    }
}


class CdpEditHelpersTool:
    def __init__(self, cdp_executor: CdpExecutor):
        self._cdp = cdp_executor

    async def execute(self, call: dict, context) -> dict:
        try:
            return await self._cdp.execute_cdp_edit_helpers(call.get("arguments", {}))
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
    name="cdp_edit_helpers",
    schema=SCHEMA,
    phases=[AgentPhase.EXECUTE],
    description="Add custom helper functions to the CDP helpers module",
    usage_hint="cdp_edit_helpers(name, code)",
    executor=CdpEditHelpersTool(cdp_executor=None),
)

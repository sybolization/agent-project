"""execute_command 工具 - 通用命令执行"""

from agent.tools.protocol import ToolDefinition
from agent.tools.lib.command_lib import CommandExecutor
from agent.state import AgentPhase


SCHEMA = {
    "type": "function",
    "function": {
        "name": "execute_command",
        "description": (
            "Execute CLI commands to interact with websites, apps, and various tools. "
            "This is a unified command execution tool supporting multiple CLI tools.\n\n"
            "Supported CLI tools:\n"
            "- opencli: Interact with websites and apps\n"
            "- lark-cli: Lark/Feishu operations\n"
            "- Other CLI tools as configured\n\n"
            "Usage: <cli_tool> <site> <command> [args] [--limit N] [-f json|yaml|md|csv|table]\n\n"
            "常用命令:\n"
            "- opencli list -f yaml: 列出所有可用站点\n"
            "- opencli <site> -h: 查看站点帮助\n"
            "- opencli browser open <url>: 打开网页\n"
            "- opencli browser state: 查看页面元素\n\n"
            "Do NOT use '&&' to chain commands on Windows."
            "\n\nIMPORTANT: When using 'opencli browser open', always use the complete URL "
            "returned by commands, including all query parameters "
            "(e.g., xsec_token, token, sign). Do NOT truncate or simplify URLs "
            "- missing query parameters will cause access failures."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "The raw CLI command to execute. Do NOT escape or quote arguments - "
                        "use plain text as-is. "
                        "Example: opencli xiaohongshu search Dyson卷发棒 --limit 10"
                    )
                }
            },
            "required": ["command"]
        }
    }
}


class ExecuteCommandTool:
    def __init__(self, command_executor: CommandExecutor):
        self._command_executor = command_executor

    async def execute(self, call: dict, context) -> dict:
        try:
            return await self._command_executor.execute_command(call, context)
        except Exception as e:
            return {"type": "error", "message": str(e)}


tool_definition = ToolDefinition(
    name="execute_command",
    schema=SCHEMA,
    phases=[AgentPhase.DEFAULT, AgentPhase.COLLECT, AgentPhase.EXECUTE],
    description="通用命令执行工具，用于执行系统命令和脚本",
    usage_hint="execute_command('command') - 执行指定的命令",
    executor=ExecuteCommandTool(command_executor=None),
    handler=None,
    formatter=None,
)

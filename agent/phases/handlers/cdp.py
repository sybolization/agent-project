"""CDP 工具结果处理器和格式化器

包含 cdp_connect, cdp_execute, cdp_get_state, cdp_edit_helpers 的处理器和格式化器。
"""

from . import ToolResultHandler, ToolResultFormatter
from ..result import PhaseResult


# --- cdp_connect ---

class CdpConnectHandler(ToolResultHandler):
    """cdp_connect 工具结果处理器"""

    tool_name = "cdp_connect"

    def handle(self, result: dict, state) -> PhaseResult:
        """处理 cdp_connect 工具结果

        Args:
            result: 工具执行结果字典
            state: Agent状态对象

        Returns:
            PhaseResult: 处理后的阶段结果
        """
        if result.get("type") == "cdp_connected":
            return PhaseResult(
                status="continue",
                message=result.get("message", "[OK] CDP已连接"),
                data={"cdp_connected": True, "target_id": result.get("target_id")}
            )
        elif result.get("type") == "cdp_already_connected":
            return PhaseResult(
                status="continue",
                message=result.get("message", "[OK] CDP已处于连接状态"),
                data={"cdp_connected": True}
            )
        return PhaseResult(
            status="error",
            message=f"[X] CDP连接失败: {result.get('message', '未知错误')}"
        )


class CdpConnectFormatter(ToolResultFormatter):
    """cdp_connect 工具结果格式化器"""

    tool_name = "cdp_connect"

    def format(self, result: dict) -> str:
        """格式化 cdp_connect 工具结果

        Args:
            result: 工具执行结果字典

        Returns:
            str: 格式化后的消息文本
        """
        if result.get("type") == "cdp_connected":
            funcs = result.get("available_functions", [])
            return f"[OK] CDP已连接\n目标ID: {result.get('target_id')}\n可用函数: {funcs}"
        elif result.get("type") == "cdp_already_connected":
            return f"[OK] CDP已处于连接状态\n目标ID: {result.get('target_id')}"
        return f"[错误] CDP连接失败: {result.get('message', '未知错误')}"


# --- cdp_execute ---

class CdpExecuteHandler(ToolResultHandler):
    """cdp_execute 工具结果处理器"""

    tool_name = "cdp_execute"

    def handle(self, result: dict, state) -> PhaseResult:
        """处理 cdp_execute 工具结果

        Args:
            result: 工具执行结果字典
            state: Agent状态对象

        Returns:
            PhaseResult: 处理后的阶段结果
        """
        if result.get("type") == "cdp_result":
            func = result.get("function", "raw")
            res = result.get("result")
            return PhaseResult(
                status="continue",
                message=f"[OK] CDP执行成功: {func}\n结果: {str(res)[:2000]}",
                data={"cdp_result": res}
            )
        elif result.get("type") == "missing_function":
            return PhaseResult(
                status="continue",
                message=(
                    f"[提示] 函数 '{result.get('missing_function')}' 不存在\n"
                    f"可用函数: {result.get('available_functions', [])}\n"
                    f"请使用 cdp_edit_helpers 添加缺失的函数。"
                ),
                data={"missing_function": result.get("missing_function")}
            )
        return PhaseResult(
            status="error",
            message=f"[X] CDP执行失败: {result.get('message', '未知错误')}"
        )


class CdpExecuteFormatter(ToolResultFormatter):
    """cdp_execute 工具结果格式化器"""

    tool_name = "cdp_execute"

    def format(self, result: dict) -> str:
        """格式化 cdp_execute 工具结果

        Args:
            result: 工具执行结果字典

        Returns:
            str: 格式化后的消息文本
        """
        if result.get("type") == "cdp_result":
            func = result.get("function", "raw")
            res = result.get("result")
            res_str = str(res)[:3000] if res else "None"
            return f"[OK] CDP执行成功: {func}\n结果: {res_str}"
        elif result.get("type") == "missing_function":
            return (
                f"[提示] 函数 '{result.get('missing_function')}' 不存在\n"
                f"可用函数: {result.get('available_functions', [])}\n"
                f"请使用 cdp_edit_helpers 添加缺失的函数。"
            )
        return f"[错误] CDP执行失败: {result.get('message', '未知错误')}"


# --- cdp_get_state ---

class CdpGetStateHandler(ToolResultHandler):
    """cdp_get_state 工具结果处理器"""

    tool_name = "cdp_get_state"

    def handle(self, result: dict, state) -> PhaseResult:
        """处理 cdp_get_state 工具结果

        Args:
            result: 工具执行结果字典
            state: Agent状态对象

        Returns:
            PhaseResult: 处理后的阶段结果
        """
        if result.get("type") == "cdp_state":
            formatted = result.get("formatted", "")
            return PhaseResult(
                status="continue",
                message=f"[OK] 浏览器状态:\n{formatted}",
                data={"cdp_state": result.get("context")}
            )
        return PhaseResult(
            status="error",
            message=f"[X] 获取浏览器状态失败: {result.get('message', '未知错误')}"
        )


class CdpGetStateFormatter(ToolResultFormatter):
    """cdp_get_state 工具结果格式化器"""

    tool_name = "cdp_get_state"

    def format(self, result: dict) -> str:
        """格式化 cdp_get_state 工具结果

        Args:
            result: 工具执行结果字典

        Returns:
            str: 格式化后的消息文本
        """
        if result.get("type") == "cdp_state":
            formatted = result.get("formatted", "")
            return f"[OK] 浏览器状态:\n{formatted}"
        return f"[错误] 获取浏览器状态失败: {result.get('message', '未知错误')}"


# --- cdp_edit_helpers ---

class CdpEditHelpersHandler(ToolResultHandler):
    """cdp_edit_helpers 工具结果处理器"""

    tool_name = "cdp_edit_helpers"

    def handle(self, result: dict, state) -> PhaseResult:
        """处理 cdp_edit_helpers 工具结果

        Args:
            result: 工具执行结果字典
            state: Agent状态对象

        Returns:
            PhaseResult: 处理后的阶段结果
        """
        if result.get("type") == "helpers_updated":
            return PhaseResult(
                status="continue",
                message=f"[OK] 已添加函数 '{result.get('function_name')}'\n可用函数: {result.get('available_functions', [])}",
                data={"function_added": result.get("function_name")}
            )
        return PhaseResult(
            status="error",
            message=f"[X] 添加函数失败: {result.get('message', '未知错误')}"
        )


class CdpEditHelpersFormatter(ToolResultFormatter):
    """cdp_edit_helpers 工具结果格式化器"""

    tool_name = "cdp_edit_helpers"

    def format(self, result: dict) -> str:
        """格式化 cdp_edit_helpers 工具结果

        Args:
            result: 工具执行结果字典

        Returns:
            str: 格式化后的消息文本
        """
        if result.get("type") == "helpers_updated":
            return f"[OK] 已添加函数 '{result.get('function_name')}'\n可用函数: {result.get('available_functions', [])}"
        return f"[错误] 添加函数失败: {result.get('message', '未知错误')}"

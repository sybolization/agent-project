"""execute_command 工具结果处理器和格式化器"""

import logging

from . import ToolResultHandler, ToolResultFormatter
from ..result import PhaseResult
from ...context.compression import compress_opencli_result

logger = logging.getLogger(__name__)


class ExecuteCommandHandler(ToolResultHandler):
    """execute_command 工具结果处理器

    处理命令执行结果，递增已完成步骤计数，
    并委托给 _handle_opencli_result 逻辑处理。

    Args:
        action_label: 动作标签，DefaultPhase 使用 "命令执行"，CollectPhase 使用 "命令验证"
    """

    tool_name = "execute_command"

    def __init__(self, action_label: str = "命令执行"):
        self.action_label = action_label

    def handle(self, result: dict, state) -> PhaseResult:
        """处理 execute_command 工具结果

        Args:
            result: 工具执行结果字典
            state: Agent状态对象

        Returns:
            PhaseResult: 处理后的阶段结果
        """
        state.completed_steps += 1
        return _handle_opencli_result(result, self.action_label)


class ExecuteCommandFormatter(ToolResultFormatter):
    """execute_command 工具结果格式化器

    将命令执行结果格式化为消息文本，包含 web_content 处理逻辑。
    """

    tool_name = "execute_command"

    def format(self, result: dict) -> str:
        """格式化 execute_command 工具结果

        Args:
            result: 工具执行结果字典

        Returns:
            str: 格式化后的消息文本
        """
        if result.get("type") != "command_executed":
            error_info = result.get("error", result.get("message", "未知错误"))
            return (
                f"[错误] 命令执行失败\n\n"
                f"错误: {error_info}\n\n"
                f"建议: 检查命令格式是否正确，或尝试其他可用命令。"
            )

        command = result.get("command", "")
        exec_result = result.get("result", {})
        web_content = result.get("web_content")

        logger.info(f"[FormatResult] command: {command}")
        logger.info(f"[FormatResult] exec_result.success: {exec_result.get('success')}")
        logger.info(f"[FormatResult] web_content exists: {web_content is not None}")
        if web_content:
            logger.info(f"[FormatResult] web_content.success: {web_content.get('success')}")
            logger.info(f"[FormatResult] web_content.content_length: {web_content.get('content_length')}")

        if exec_result.get("success"):
            output = exec_result.get("output", "")
            base_msg = ""
            if output and output.strip():
                base_msg = f"[成功] 命令执行成功: {command}\n\n结果:\n{output[:8000]}"
            else:
                base_msg = f"[成功] 命令执行成功: {command}"

            if web_content and web_content.get("success"):
                title = web_content.get("title", "")
                content = web_content.get("content", "")
                truncated = web_content.get("truncated", False)
                mode = web_content.get("mode", "")

                header = f"\n\n--- 网页内容 ---"
                if title:
                    header += f"\n标题: {title}"
                if mode:
                    header += f" (获取方式: {mode})"
                if truncated:
                    header += " [已截断]"

                formatted_result = f"{base_msg}{header}\n\n{content}"
                logger.info(f"[FormatResult] Formatted message with web_content, length: {len(formatted_result)}")
                return formatted_result
            elif not output or not output.strip():
                return (
                    f"[警告] 命令执行成功，但没有返回数据\n"
                    f"命令: {command}\n\n"
                    f"可能原因:\n"
                    f"1. 该命令尚未实现（pipeline为空）\n"
                    f"2. 参数无效或资源不存在\n"
                    f"3. 需要登录或权限不足\n\n"
                    f"建议: 尝试使用其他可用命令，或检查命令参数。"
                )
            else:
                return base_msg
        else:
            error_msg = exec_result.get("error", "Unknown error")

            if web_content and web_content.get("success"):
                title = web_content.get("title", "")
                content = web_content.get("content", "")
                truncated = web_content.get("truncated", False)
                mode = web_content.get("mode", "")

                base_msg = (
                    f"[警告] 命令返回失败，但浏览器已打开页面\n"
                    f"命令: {command}\n"
                    f"错误: {error_msg}\n"
                )

                header = f"\n--- 网页内容 ---"
                if title:
                    header += f"\n标题: {title}"
                if mode:
                    header += f" (获取方式: {mode})"
                if truncated:
                    header += " [已截断]"

                formatted_result = f"{base_msg}{header}\n\n{content}"
                logger.info(f"[FormatResult] Formatted message with web_content on failure, length: {len(formatted_result)}")
                return formatted_result

            return (
                f"[错误] 命令执行失败\n"
                f"命令: {command}\n\n"
                f"错误: {error_msg}\n\n"
                f"建议: 检查命令语法、参数格式，或尝试替代方案。"
            )


def _handle_opencli_result(result: dict, action_label: str = "命令执行") -> PhaseResult:
    """处理 opencli 工具执行结果的通用逻辑

    Args:
        result: 工具执行结果字典
        action_label: 动作标签，如"命令验证"或"命令执行"

    Returns:
        PhaseResult: 处理后的结果
    """
    if result.get("type") != "command_executed":
        return PhaseResult(status="error", message=result.get("error", "命令执行失败"))

    command = result.get("command", "")
    exec_result = result.get("result", {})

    if exec_result.get("success"):
        output = exec_result.get("output", "")
        if output:
            compressed = compress_opencli_result(command, output)
            return PhaseResult(
                status="continue",
                message=f"[OK] {action_label}成功: {command}\n\n结果:\n{compressed}",
                data={"command": command, "result": compressed}
            )
        return PhaseResult(
            status="continue",
            message=f"[OK] {action_label}成功: {command}",
            data={"command": command, "result": "Success"}
        )
    else:
        error_msg = exec_result.get("error", "Unknown error")
        return PhaseResult(
            status="continue",
            message=f"[X] {action_label}失败: {command}\n\n错误: {error_msg}",
            data={"command": command, "error": error_msg}
        )

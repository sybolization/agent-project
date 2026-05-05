"""权限检查 Hook"""

import logging
from typing import Optional

from ..types import HookEvent, HookResult, HookEventName, HookExitCode
from ...permission import PermissionChecker, PermissionBehavior

logger = logging.getLogger(__name__)


def create_permission_hook(checker: Optional[PermissionChecker] = None) -> callable:
    """创建权限检查 Hook

    Args:
        checker: 权限检查器实例，如果为 None 则使用默认配置

    Returns:
        Hook 处理函数
    """
    _checker = checker or PermissionChecker()

    def permission_hook(event: HookEvent) -> HookResult:
        """权限检查 Hook 处理器

        只处理 execute_command 工具的 PreToolUse 事件。
        根据权限检查结果决定是否阻止执行。
        """
        if event.name != HookEventName.PRE_TOOL_USE:
            return HookResult.continue_()

        tool_name = event.payload.get("tool_name", "")
        if tool_name != "execute_command":
            return HookResult.continue_()

        tool_input = event.payload.get("input", {})
        command = tool_input.get("command", "")

        if not command:
            return HookResult.continue_()

        decision = _checker.check(tool_name, command)

        if decision.behavior == PermissionBehavior.DENY:
            logger.warning(f"[权限拦截] 命令被拒绝: {command}, 原因: {decision.reason}")
            return HookResult.block(
                f"[权限拒绝] 命令 '{command}' 被拒绝执行。\n"
                f"原因: {decision.reason}\n"
                f"如果确实需要执行此命令，请联系管理员修改权限规则。"
            )

        if decision.behavior == PermissionBehavior.ASK:
            logger.info(f"[权限确认] 命令需要确认: {command}, 原因: {decision.reason}")
            return HookResult(
                exit_code=HookExitCode.INJECT,
                message=(
                    f"[权限确认] 命令 '{command}' 需要用户确认。\n"
                    f"原因: {decision.reason}\n"
                    f"请确认是否执行此命令。"
                )
            )

        return HookResult.continue_()

    permission_hook.__name__ = "permission_hook"
    return permission_hook

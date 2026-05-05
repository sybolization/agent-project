"""NeedsConfirmation 状态处理 Hook"""

import logging
from typing import Optional, List, Dict

from ..types import HookEvent, HookResult, HookEventName, HookExitCode, StatusHookResult

logger = logging.getLogger(__name__)


def create_needs_confirmation_status_hook(
    context: Optional[List[Dict]] = None,
) -> callable:
    """创建 NeedsConfirmation 状态处理 Hook

    处理 PhaseResult.status == "needs_confirmation" 的场景。
    构建确认提示，等待用户回复。

    Args:
        context: 上下文列表引用

    Returns:
        Hook 处理函数
    """
    _context = context

    def needs_confirmation_status_hook(event: HookEvent) -> HookResult:
        """NeedsConfirmation 状态处理 Hook 处理器

        只处理 PostPhaseExecute 事件。
        当 status == "needs_confirmation" 时，构建确认提示。
        """
        if event.name != HookEventName.POST_PHASE_EXECUTE:
            return HookResult.continue_()

        phase_result = event.payload.get("phase_result", {})
        status = phase_result.get("status", "")

        if status != "needs_confirmation":
            return HookResult.continue_()

        current_input = event.payload.get("current_input", "")
        message = phase_result.get("message", "")
        data = phase_result.get("data", {})

        if _context is None:
            logger.warning("[NeedsConfirmationStatusHook] 上下文未设置，跳过处理")
            return HookResult.continue_()

        _context.append({"role": "user", "content": current_input})

        tool_name = data.get("tool_name", "")
        arguments = data.get("arguments", {})

        confirmation_message = f"{message}\n\n请回复 'yes' 确认执行，或 'no' 取消执行。"

        _context.append({
            "role": "assistant",
            "content": confirmation_message
        })

        wait_input = f"[等待确认] 工具 '{tool_name}' 需要用户确认。参数: {arguments}"

        logger.info(f"[NeedsConfirmationStatusHook] 等待用户确认: {tool_name}")

        return HookResult(
            exit_code=HookExitCode.INJECT,
            message=wait_input
        )

    needs_confirmation_status_hook.__name__ = "needs_confirmation_status_hook"
    return needs_confirmation_status_hook

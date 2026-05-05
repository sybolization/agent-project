"""Complete 状态处理 Hook"""

import logging
from typing import Optional

from ..types import HookEvent, HookResult, HookEventName, HookExitCode, StatusHookResult

logger = logging.getLogger(__name__)


def create_complete_status_hook() -> callable:
    """创建 Complete 状态处理 Hook

    处理 PhaseResult.status == "complete" 的场景。
    返回终止信号，主循环结束并返回结果消息。

    Returns:
        Hook 处理函数
    """

    def complete_status_hook(event: HookEvent) -> HookResult:
        """Complete 状态处理 Hook 处理器

        只处理 PostPhaseExecute 事件。
        当 status == "complete" 时，返回终止信号。
        """
        if event.name != HookEventName.POST_PHASE_EXECUTE:
            return HookResult.continue_()

        phase_result = event.payload.get("phase_result", {})
        status = phase_result.get("status", "")

        if status != "complete":
            return HookResult.continue_()

        message = phase_result.get("message", "")
        logger.info(f"[CompleteStatusHook] 任务完成: {message[:100]}")

        return HookResult(
            exit_code=HookExitCode.BLOCK,
            message=message
        )

    complete_status_hook.__name__ = "complete_status_hook"
    return complete_status_hook

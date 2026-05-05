"""Error 状态处理 Hook"""

import logging
from typing import Optional, List, Dict

from ..types import HookEvent, HookResult, HookEventName, HookExitCode, StatusHookResult

logger = logging.getLogger(__name__)


def create_error_status_hook(
    context: Optional[List[Dict]] = None,
) -> callable:
    """创建 Error 状态处理 Hook

    处理 PhaseResult.status == "error" 的场景。
    记录错误信息，构造错误输入继续迭代。

    Args:
        context: 上下文列表引用

    Returns:
        Hook 处理函数
    """
    _context = context

    def error_status_hook(event: HookEvent) -> HookResult:
        """Error 状态处理 Hook 处理器

        只处理 PostPhaseExecute 事件。
        当 status == "error" 时，记录错误并构造错误输入。
        """
        if event.name != HookEventName.POST_PHASE_EXECUTE:
            return HookResult.continue_()

        phase_result = event.payload.get("phase_result", {})
        status = phase_result.get("status", "")

        if status != "error":
            return HookResult.continue_()

        current_input = event.payload.get("current_input", "")
        original_input = event.payload.get("original_input", "")
        message = phase_result.get("message", "")

        if _context is None:
            logger.warning("[ErrorStatusHook] 上下文未设置，跳过处理")
            return HookResult.continue_()

        _context.append({"role": "user", "content": current_input})

        error_input = f"[错误] {message}\n\n用户原始请求：{original_input}"

        logger.error(f"[ErrorStatusHook] 错误发生: {message[:200]}")

        return HookResult(
            exit_code=HookExitCode.INJECT,
            message=error_input
        )

    error_status_hook.__name__ = "error_status_hook"
    return error_status_hook

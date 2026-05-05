"""上下文压缩触发 Hook"""

import logging
from typing import Optional, Any, List, Dict

from ..types import HookEvent, HookResult, HookEventName, HookExitCode

logger = logging.getLogger(__name__)


def create_context_compression_hook(
    context: Optional[List[Dict]] = None,
    compressor: Optional[Any] = None,
    threshold: int = 4000
) -> callable:
    """创建上下文压缩触发 Hook

    在上下文超过阈值时触发压缩机制。

    Args:
        context: 上下文列表引用
        compressor: ContextCompressor 实例
        threshold: 压缩阈值（token 数）

    Returns:
        Hook 处理函数
    """
    _context = context
    _compressor = compressor
    _threshold = threshold

    def context_compression_hook(event: HookEvent) -> HookResult:
        """上下文压缩 Hook 处理器

        只处理 PreToolUse 事件。
        检查上下文长度，超过阈值时触发压缩。
        """
        if event.name != HookEventName.PRE_TOOL_USE:
            return HookResult.continue_()

        if _context is None or _compressor is None:
            return HookResult.continue_()

        # 估算上下文 token 数
        context_str = str(_context)
        estimated_tokens = len(context_str) // 4  # 简单估算

        if estimated_tokens > _threshold:
            logger.info(f"[ContextCompressionHook] 上下文超过阈值 ({estimated_tokens} > {_threshold})，触发压缩")
            # 注意：实际压缩逻辑需要在主循环中执行
            # 这里只注入提示消息
            return HookResult.inject(
                f"[上下文压缩] 当前上下文约 {estimated_tokens} tokens，建议进行压缩。"
            )

        return HookResult.continue_()

    context_compression_hook.__name__ = "context_compression_hook"
    return context_compression_hook

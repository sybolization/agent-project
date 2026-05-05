"""循环检测 Hook"""

import logging
from typing import Optional, Tuple

from ..types import HookEvent, HookResult, HookEventName

logger = logging.getLogger(__name__)


class LoopDetector:
    """循环检测器

    检测模型是否连续输出相同内容。
    """

    def __init__(self, max_repeated: int = 2):
        self.max_repeated = max_repeated
        self._last_response_text = ""
        self._repeated_count = 0

    def check(self, response_text: str) -> Tuple[bool, int]:
        """检查是否陷入循环

        Args:
            response_text: 当前响应文本

        Returns:
            (是否陷入循环, 重复次数)
        """
        if response_text and response_text == self._last_response_text:
            self._repeated_count += 1
            logger.warning(f"[循环检测] 模型重复输出相同内容 ({self._repeated_count}次)")

            if self._repeated_count >= self.max_repeated:
                return True, self._repeated_count
        else:
            self._repeated_count = 0
            self._last_response_text = response_text or ""

        return False, self._repeated_count

    def reset(self):
        """重置检测器状态"""
        self._last_response_text = ""
        self._repeated_count = 0


def create_loop_detection_hook(detector: Optional[LoopDetector] = None, max_repeated: int = 2) -> callable:
    """创建循环检测 Hook

    检测模型是否陷入循环输出。

    Args:
        detector: 可选的 LoopDetector 实例
        max_repeated: 最大允许重复次数

    Returns:
        Hook 处理函数
    """
    _detector = detector or LoopDetector(max_repeated=max_repeated)

    def loop_detection_hook(event: HookEvent) -> HookResult:
        """循环检测 Hook 处理器

        只处理 PostToolUse 事件。
        检测模型响应是否陷入循环。
        """
        if event.name != HookEventName.POST_TOOL_USE:
            return HookResult.continue_()

        # 从 payload 中获取响应文本
        response_text = event.payload.get("response_text", "")

        is_loop, count = _detector.check(response_text)

        if is_loop:
            logger.error(f"[循环检测] 模型陷入循环，强制终止")
            return HookResult.block(
                f"任务执行异常：模型陷入循环，已自动终止。最后输出：{response_text[:500]}"
            )

        return HookResult.continue_()

    loop_detection_hook.__name__ = "loop_detection_hook"
    return loop_detection_hook

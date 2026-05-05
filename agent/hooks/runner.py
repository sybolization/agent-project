"""Hook 运行器"""

import logging
from typing import Callable, Dict, List, Optional

from .types import HookEvent, HookEventName, HookResult, HookExitCode

logger = logging.getLogger(__name__)

HookHandler = Callable[[HookEvent], HookResult]


class HookRunner:
    """Hook 运行器

    管理和执行注册的 Hook 处理器。
    执行顺序：先注册的先执行。
    当某个 Hook 返回非 CONTINUE 时，停止执行后续 Hook。
    """

    def __init__(self):
        self._hooks: Dict[HookEventName, List[HookHandler]] = {
            HookEventName.SESSION_START: [],
            HookEventName.PRE_TOOL_USE: [],
            HookEventName.POST_TOOL_USE: [],
            HookEventName.POST_PHASE_EXECUTE: [],
        }

    def register(self, event_name: HookEventName, handler: HookHandler) -> None:
        """注册 Hook 处理器"""
        if event_name not in self._hooks:
            self._hooks[event_name] = []
        self._hooks[event_name].append(handler)
        logger.debug(f"Registered hook for {event_name.value}: {handler.__name__}")

    def unregister(self, event_name: HookEventName, handler: HookHandler) -> bool:
        """取消注册 Hook 处理器"""
        if event_name in self._hooks and handler in self._hooks[event_name]:
            self._hooks[event_name].remove(handler)
            return True
        return False

    def run(self, event: HookEvent) -> HookResult:
        """运行 Hook

        按顺序执行注册的 Hook 处理器。
        当某个 Hook 返回非 CONTINUE 时，停止执行并返回该结果。

        Args:
            event: Hook 事件

        Returns:
            最终的 Hook 结果
        """
        handlers = self._hooks.get(event.name, [])

        for handler in handlers:
            try:
                result = handler(event)
                logger.debug(f"Hook {handler.__name__} returned: {result.exit_code}")

                if result.exit_code != HookExitCode.CONTINUE:
                    return result
            except Exception as e:
                logger.error(f"Hook {handler.__name__} raised exception: {e}")
                return HookResult.block(f"Hook 执行错误: {e}")

        return HookResult.continue_()

    def run_pre_tool_use(self, tool_name: str, tool_input: Dict) -> HookResult:
        """便捷方法：运行 PreToolUse hook"""
        event = HookEvent.pre_tool_use(tool_name, tool_input)
        return self.run(event)

    def run_post_tool_use(
        self,
        tool_name: str,
        tool_input: Dict,
        tool_output: Dict
    ) -> HookResult:
        """便捷方法：运行 PostToolUse hook"""
        event = HookEvent.post_tool_use(tool_name, tool_input, tool_output)
        return self.run(event)

    def run_session_start(self) -> HookResult:
        """便捷方法：运行 SessionStart hook"""
        event = HookEvent.session_start()
        return self.run(event)

    def run_post_phase_execute(
        self,
        phase_result: Dict,
        current_input: str,
        original_input: str
    ) -> HookResult:
        """便捷方法：运行 PostPhaseExecute hook"""
        event = HookEvent.post_phase_execute(phase_result, current_input, original_input)
        return self.run(event)

"""阶段转换验证 Hook"""

import logging
from typing import Optional, Set

from ..types import HookEvent, HookResult, HookEventName, HookExitCode

logger = logging.getLogger(__name__)


VALID_TRANSITIONS: dict[str, Set[str]] = {
    "DEFAULT": {"REPORT"},
    "COLLECT": {"PLAN"},
    "PLAN": {"EXECUTE"},
    "EXECUTE": {"REPORT"},
    "REPORT": set(),  # REPORT 是最终阶段
}


def create_phase_transition_hook() -> callable:
    """创建阶段转换验证 Hook

    验证阶段转换是否符合规则。

    Returns:
        Hook 处理函数
    """
    def phase_transition_hook(event: HookEvent) -> HookResult:
        """阶段转换验证 Hook 处理器

        处理自定义的 PhaseTransition 事件。
        验证阶段转换是否合法。
        """
        if event.name != HookEventName.PRE_TOOL_USE:
            return HookResult.continue_()

        # 只处理阶段转换相关的工具
        tool_name = event.payload.get("tool_name", "")
        if tool_name not in ("start_plan", "start_execute", "task_complete"):
            return HookResult.continue_()

        # 从 payload 获取当前阶段和目标阶段
        current_phase = event.payload.get("current_phase", "")
        target_phase = event.payload.get("target_phase", "")

        if not current_phase or not target_phase:
            return HookResult.continue_()

        # 验证转换是否合法
        allowed_transitions = VALID_TRANSITIONS.get(current_phase, set())

        if target_phase not in allowed_transitions:
            logger.warning(f"[PhaseTransitionHook] 非法阶段转换: {current_phase} -> {target_phase}")
            return HookResult.block(
                f"非法阶段转换: {current_phase} -> {target_phase}。"
                f"允许的转换: {allowed_transitions}"
            )

        logger.info(f"[PhaseTransitionHook] 阶段转换验证通过: {current_phase} -> {target_phase}")
        return HookResult.continue_()

    phase_transition_hook.__name__ = "phase_transition_hook"
    return phase_transition_hook

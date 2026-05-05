"""Transition 状态处理 Hook"""

import logging
from typing import Optional, List, Dict, Any, Callable

from ..types import HookEvent, HookResult, HookEventName, HookExitCode, StatusHookResult

logger = logging.getLogger(__name__)


def create_transition_status_hook(
    context: Optional[List[Dict]] = None,
    transition_callback: Optional[Callable[[str], None]] = None,
    build_transition_input_callback: Optional[Callable[[Any, str], str]] = None,
) -> callable:
    """创建 Transition 状态处理 Hook

    处理 PhaseResult.status == "transition" 的场景。
    更新上下文，执行阶段转换，构建下一输入。

    Args:
        context: 上下文列表引用
        transition_callback: 阶段转换回调函数
        build_transition_input_callback: 构建转换输入的回调函数

    Returns:
        Hook 处理函数
    """
    _context = context
    _transition_callback = transition_callback
    _build_transition_input_callback = build_transition_input_callback

    def _format_tool_calls_for_api(tool_calls: list) -> list:
        """格式化工具调用为 API 格式"""
        formatted = []
        for tc in tool_calls:
            formatted.append({
                "id": tc.get("id", ""),
                "type": "function",
                "function": {
                    "name": tc.get("name", ""),
                    "arguments": tc.get("arguments", "{}")
                }
            })
        return formatted

    def transition_status_hook(event: HookEvent) -> HookResult:
        """Transition 状态处理 Hook 处理器

        只处理 PostPhaseExecute 事件。
        当 status == "transition" 时，更新上下文，执行阶段转换。
        """
        if event.name != HookEventName.POST_PHASE_EXECUTE:
            return HookResult.continue_()

        phase_result = event.payload.get("phase_result", {})
        status = phase_result.get("status", "")

        if status != "transition":
            return HookResult.continue_()

        current_input = event.payload.get("current_input", "")
        original_input = event.payload.get("original_input", "")

        if _context is None:
            logger.warning("[TransitionStatusHook] 上下文未设置，跳过处理")
            return HookResult.continue_()

        _context.append({"role": "user", "content": current_input})

        tool_calls = phase_result.get("tool_calls", [])
        response_text = phase_result.get("response_text", "")
        message = phase_result.get("message", "")

        if tool_calls:
            assistant_entry = {
                "role": "assistant",
                "content": response_text or "",
                "tool_calls": _format_tool_calls_for_api(tool_calls)
            }
            reasoning_content = phase_result.get("reasoning_content", "")
            if tool_calls and reasoning_content:
                assistant_entry["reasoning_content"] = reasoning_content
            _context.append(assistant_entry)
        else:
            _context.append({"role": "assistant", "content": response_text or message})

        next_phase = phase_result.get("next_phase")
        if next_phase and _transition_callback:
            logger.info(f"[TransitionStatusHook] 转换到阶段: {next_phase}")
            _transition_callback(next_phase)

        next_input = ""
        if _build_transition_input_callback:
            from dataclasses import dataclass
            from typing import Any

            @dataclass
            class MockResult:
                status: str
                message: str
                data: dict
                next_phase: Optional[str]
                tool_calls: list
                response_text: str
                tool_results: list

            mock_result = MockResult(
                status=status,
                message=message,
                data=phase_result.get("data", {}),
                next_phase=next_phase,
                tool_calls=tool_calls,
                response_text=response_text,
                tool_results=phase_result.get("tool_results", [])
            )
            next_input = _build_transition_input_callback(mock_result, original_input)

        logger.info(f"[TransitionStatusHook] 阶段转换完成，下一输入: {next_input[:100]}")

        return HookResult(
            exit_code=HookExitCode.INJECT,
            message=next_input
        )

    transition_status_hook.__name__ = "transition_status_hook"
    return transition_status_hook

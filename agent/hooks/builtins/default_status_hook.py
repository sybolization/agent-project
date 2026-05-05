"""Default 状态处理 Hook"""

import logging
from typing import Optional, List, Dict, Any, Callable

from ..types import HookEvent, HookResult, HookEventName, HookExitCode, StatusHookResult

logger = logging.getLogger(__name__)


def create_default_status_hook(
    context: Optional[List[Dict]] = None,
    state: Optional[Any] = None,
    transition_callback: Optional[Callable[[str], None]] = None,
) -> callable:
    """创建 Default 状态处理 Hook

    处理默认状态场景（status 不是 complete/transition/error/needs_confirmation）。
    更新上下文，记录工具结果，更新任务状态。

    Args:
        context: 上下文列表引用
        state: AgentState 引用
        transition_callback: 阶段转换回调函数

    Returns:
        Hook 处理函数
    """
    _context = context
    _state = state
    _transition_callback = transition_callback

    def _format_tool_calls_for_api(tool_calls: list) -> list:
        """格式化工具调用为 API 格式"""
        import json
        formatted = []
        for tc in tool_calls:
            args = tc.get("arguments", {})
            if isinstance(args, dict):
                args = json.dumps(args, ensure_ascii=False)
            formatted.append({
                "id": tc.get("id", ""),
                "type": "function",
                "function": {
                    "name": tc.get("name", ""),
                    "arguments": args
                }
            })
        return formatted

    def default_status_hook(event: HookEvent) -> HookResult:
        """Default 状态处理 Hook 处理器

        只处理 PostPhaseExecute 事件。
        作为默认处理器，处理工具调用结果和任务状态更新。
        """
        if event.name != HookEventName.POST_PHASE_EXECUTE:
            return HookResult.continue_()

        phase_result = event.payload.get("phase_result", {})
        status = phase_result.get("status", "")

        if status in ["complete", "transition", "error", "needs_confirmation"]:
            return HookResult.continue_()

        current_input = event.payload.get("current_input", "")
        original_input = event.payload.get("original_input", "")

        if _context is None:
            logger.warning("[DefaultStatusHook] 上下文未设置，跳过处理")
            return HookResult.continue_()

        _context.append({"role": "user", "content": current_input})

        tool_calls = phase_result.get("tool_calls", [])
        response_text = phase_result.get("response_text", "")
        message = phase_result.get("message", "")
        tool_results = phase_result.get("tool_results", [])

        if tool_calls:
            formatted_tcs = _format_tool_calls_for_api(tool_calls)
            assistant_entry = {
                "role": "assistant",
                "content": response_text or "",
                "tool_calls": formatted_tcs
            }
            reasoning_content = phase_result.get("reasoning_content", "")
            if tool_calls and reasoning_content:
                assistant_entry["reasoning_content"] = reasoning_content
            _context.append(assistant_entry)
            if tool_results:
                for i, tr in enumerate(tool_results):
                    tool_call_id = formatted_tcs[i].get("id", "") if i < len(formatted_tcs) else ""
                    content = tr.get("content", "")
                    if not content:
                        content = tr.get("message", str(tr))
                    
                    screenshot = tr.get("screenshot") if isinstance(tr, dict) else None
                    _context.append({
                        "role": "tool",
                        "content": content,
                        "tool_call_id": tool_call_id
                    })
                    if screenshot and len(screenshot) > 0:
                        _context.append({
                            "role": "user",
                            "content": [
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{screenshot}"}}
                            ]
                        })
            else:
                _context.append({
                    "role": "tool",
                    "content": message,
                    "tool_call_id": formatted_tcs[0].get("id", "") if formatted_tcs else ""
                })
        else:
            _context.append({"role": "assistant", "content": response_text or message})

        next_input = "[继续执行] 请根据以上工具结果决定下一步操作。"

        if _state is not None:
            from ...state import AgentPhase
            if hasattr(_state, 'phase') and _state.phase == AgentPhase.EXECUTE:
                if hasattr(_state, 'todos') and hasattr(_state.todos, 'items') and _state.todos.items:
                    if hasattr(_state, 'get_todo_progress'):
                        progress = _state.get_todo_progress()
                        if progress['completed'] == progress['total'] and progress['total'] > 0:
                            if _transition_callback:
                                logger.info("[DefaultStatusHook] 所有任务已完成，转换到 REPORT 阶段")
                                _transition_callback("REPORT")
                            next_input = "[继续执行] 所有任务已完成！正在进入REPORT阶段进行工作汇报..."
                        elif progress['completed'] > 0:
                            in_progress = [t for t in _state.todos.items if t.get("status") == "in_progress"]
                            if in_progress:
                                in_progress_names = ", ".join(t.get("content", t.get("id", "")) for t in in_progress)
                                next_input = f"[继续执行] 你有 {len(in_progress)} 个任务正在进行中：{in_progress_names}。请使用 update_todo 标记完成，或继续执行。"

        logger.debug(f"[DefaultStatusHook] 默认处理完成，下一输入: {next_input[:100]}")

        return HookResult(
            exit_code=HookExitCode.INJECT,
            message=next_input
        )

    default_status_hook.__name__ = "default_status_hook"
    return default_status_hook

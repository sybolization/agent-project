"""Hook 类型定义"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class PhaseStatus(str, Enum):
    """Phase 工具结果处理状态"""
    CONTINUE = "continue"        # 继续当前阶段
    TRANSITION = "transition"    # 阶段转换
    COMPLETE = "complete"        # 任务完成
    ERROR = "error"              # 工具执行出错


EventCallback = Callable[[str, dict], None]


class HookEventName(str, Enum):
    """Hook 事件名称"""
    SESSION_START = "SessionStart"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    POST_PHASE_EXECUTE = "PostPhaseExecute"


class HookExitCode(int, Enum):
    """Hook 退出码"""
    CONTINUE = 0  # 正常继续
    BLOCK = 1     # 阻止当前动作
    INJECT = 2    # 注入补充消息，再继续


@dataclass
class HookEvent:
    """Hook 事件"""
    name: HookEventName
    payload: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def pre_tool_use(cls, tool_name: str, tool_input: Dict[str, Any]) -> "HookEvent":
        """创建 PreToolUse 事件"""
        return cls(
            name=HookEventName.PRE_TOOL_USE,
            payload={
                "tool_name": tool_name,
                "input": tool_input,
            }
        )

    @classmethod
    def post_tool_use(
        cls,
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_output: Dict[str, Any]
    ) -> "HookEvent":
        """创建 PostToolUse 事件"""
        return cls(
            name=HookEventName.POST_TOOL_USE,
            payload={
                "tool_name": tool_name,
                "input": tool_input,
                "output": tool_output,
            }
        )

    @classmethod
    def session_start(cls) -> "HookEvent":
        """创建 SessionStart 事件"""
        return cls(name=HookEventName.SESSION_START)

    @classmethod
    def post_phase_execute(
        cls,
        phase_result: Dict[str, Any],
        current_input: str,
        original_input: str
    ) -> "HookEvent":
        """创建 PostPhaseExecute 事件"""
        return cls(
            name=HookEventName.POST_PHASE_EXECUTE,
            payload={
                "phase_result": phase_result,
                "current_input": current_input,
                "original_input": original_input,
            }
        )


@dataclass
class HookResult:
    """Hook 执行结果"""
    exit_code: HookExitCode = HookExitCode.CONTINUE
    message: str = ""

    @classmethod
    def continue_(cls) -> "HookResult":
        """继续执行"""
        return cls(exit_code=HookExitCode.CONTINUE)

    @classmethod
    def block(cls, message: str = "") -> "HookResult":
        """阻止执行"""
        return cls(exit_code=HookExitCode.BLOCK, message=message)

    @classmethod
    def inject(cls, message: str) -> "HookResult":
        """注入消息"""
        return cls(exit_code=HookExitCode.INJECT, message=message)


@dataclass
class StatusHookResult:
    """状态处理 Hook 执行结果"""
    should_terminate: bool = False
    terminate_message: Optional[str] = None
    next_input: Optional[str] = None
    context_updates: list = field(default_factory=list)
    phase_transition: Optional[str] = None

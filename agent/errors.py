"""Agent 异常层级体系 — 递归式异常传播的核心

三层架构中的错误传播契约：
- Tool 层：失败时 raise ToolError 子类
- Harness 层：catch → enrich context → emit_error() → 按 fatal 决定 re-raise
- Session 层：emit_error() 持久化完整错误链
"""

import traceback
from typing import Any


class AgentError(Exception):
    """所有 Agent 异常的基类

    Attributes:
        agent_id: 发生异常的 agent ID
        layer: 异常发生的层级 ("tool" | "harness" | "session")
        fatal: 是否阻断流程 (True=re-raise, False=记录后继续)
        context: 层级附加上下文（通过 add_context 链式追加）
    """

    def __init__(
        self,
        message: str,
        agent_id: str = "unknown",
        layer: str = "unknown",
        fatal: bool = True,
        context: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.agent_id = agent_id
        self.layer = layer
        self.fatal = fatal
        self.context = context or {}
        self._traceback_str: str | None = None

    def add_context(self, key: str, value: Any) -> "AgentError":
        """链式追加上下文信息"""
        self.context[key] = value
        return self

    def capture_traceback(self) -> "AgentError":
        """捕获当前 traceback 字符串"""
        self._traceback_str = traceback.format_exc()
        return self

    @property
    def traceback_str(self) -> str:
        if self._traceback_str:
            return self._traceback_str
        return "".join(traceback.format_exception(type(self), self, self.__traceback__)) if self.__traceback__ else ""

    def _chain_errors(self) -> list["AgentError"]:
        """遍历 __cause__ 链，收集所有 AgentError"""
        chain = []
        current: BaseException | None = self
        while current is not None:
            if isinstance(current, AgentError) and current is not self:
                chain.append(current)
            current = current.__cause__
        return chain

    def __str__(self) -> str:
        parts = [f"[{self.layer.upper()}] {type(self).__name__}: {super().__str__()}"]
        if self.agent_id != "unknown":
            parts.append(f"  agent_id: {self.agent_id}")
        if self.context:
            ctx_items = ", ".join(f"{k}={v!r}" for k, v in self.context.items())
            parts.append(f"  context: {{{ctx_items}}}")
        if self.fatal:
            parts.append("  fatal: True (will re-raise)")

        chain = self._chain_errors()
        if chain:
            parts.append("  caused by:")
            for i, err in enumerate(chain):
                parts.append(f"    {i+1}. [{err.layer.upper()}] {type(err).__name__}: {err.args[0] if err.args else ''}")

        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典（用于 JSONL 持久化）"""
        chain = []
        current: BaseException | None = self.__cause__
        while current is not None:
            if isinstance(current, AgentError):
                chain.append(current.to_dict())
            else:
                chain.append({
                    "error_type": type(current).__name__,
                    "error_message": str(current),
                    "layer": "native",
                })
            current = current.__cause__

        return {
            "error_type": type(self).__name__,
            "error_message": self.args[0] if self.args else "",
            "agent_id": self.agent_id,
            "layer": self.layer,
            "fatal": self.fatal,
            "context": self.context,
            "traceback": self.traceback_str,
            "error_chain": chain,
        }


# =============================================================================
# Tool 层异常
# =============================================================================

class ToolError(AgentError):
    """Tool 层异常基类"""

    def __init__(
        self,
        message: str,
        tool_name: str = "unknown",
        arguments: dict[str, Any] | None = None,
        agent_id: str = "unknown",
        fatal: bool = True,
        context: dict[str, Any] | None = None,
    ):
        ctx = context or {}
        ctx["tool_name"] = tool_name
        ctx["arguments"] = arguments or {}
        super().__init__(message, agent_id=agent_id, layer="tool", fatal=fatal, context=ctx)


class CommandExecutionError(ToolError):
    """命令执行失败"""


class CdpExecutionError(ToolError):
    """CDP 操作失败"""


class SubagentExecutionError(ToolError):
    """子代理执行失败"""


class SkillLoadError(ToolError):
    """技能加载失败"""


class ToolNotFoundError(ToolError):
    """工具未找到"""


# =============================================================================
# LLM 层异常
# =============================================================================

class LLMError(AgentError):
    """LLM 层异常基类 — API 调用失败、余额不足等"""

    def __init__(
        self,
        message: str,
        provider: str = "unknown",
        status_code: int = 0,
        response_body: str | None = None,
        agent_id: str = "unknown",
        fatal: bool = False,
        context: dict[str, Any] | None = None,
    ):
        ctx = context or {}
        ctx["provider"] = provider
        ctx["status_code"] = status_code
        ctx["response_body"] = response_body or ""
        super().__init__(message, agent_id=agent_id, layer="llm", fatal=fatal, context=ctx)


# =============================================================================
# Harness 层异常
# =============================================================================

class HarnessError(AgentError):
    """Harness 层异常基类"""

    def __init__(
        self,
        message: str,
        agent_id: str = "unknown",
        iteration: int = 0,
        phase: str = "unknown",
        fatal: bool = True,
        context: dict[str, Any] | None = None,
    ):
        ctx = context or {}
        ctx["iteration"] = iteration
        ctx["phase"] = phase
        super().__init__(message, agent_id=agent_id, layer="harness", fatal=fatal, context=ctx)


class PhaseExecutionError(HarnessError):
    """阶段执行异常"""


class ContextCompressionError(HarnessError):
    """上下文压缩失败"""


class LoopDetectionError(HarnessError):
    """循环检测"""


# =============================================================================
# Session 层异常
# =============================================================================

class SessionError(AgentError):
    """Session 层异常基类"""

    def __init__(
        self,
        message: str,
        agent_id: str = "unknown",
        fatal: bool = False,
        context: dict[str, Any] | None = None,
    ):
        super().__init__(message, agent_id=agent_id, layer="session", fatal=fatal, context=context or {})


class LogPersistenceError(SessionError):
    """日志写入失败"""


# =============================================================================
# 容器层异常
# =============================================================================

class ContainerError(AgentError):
    """容器层异常基类"""

    def __init__(
        self,
        message: str,
        container_id: str = "unknown",
        agent_id: str = "unknown",
        fatal: bool = True,
        context: dict[str, Any] | None = None,
    ):
        ctx = context or {}
        ctx["container_id"] = container_id
        super().__init__(message, agent_id=agent_id, layer="tool", fatal=fatal, context=ctx)


class ContainerStartupError(ContainerError):
    """容器启动失败"""


class ContainerStateError(ContainerError):
    """容器状态异常"""

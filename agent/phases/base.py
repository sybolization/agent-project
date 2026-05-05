"""阶段基类 - Agent执行阶段的抽象基类"""

import json
import logging
from abc import ABC, abstractmethod

from ..context.compression import compress_opencli_result
from ..hooks.types import PhaseStatus
from .result import PhaseResult
from .handlers import DefaultHandler, DefaultFormatter, ToolResultFormatter, ToolResultHandler

logger = logging.getLogger(__name__)


class BasePhase(ABC):
    """阶段基类
    
    所有阶段（COLLECT, PLAN, EXECUTE）的抽象基类。
    参考 Claude Code 的 Subagent 架构设计。
    """
    
    def __init__(
        self,
        prompt_builder,
        state,
    ):
        self.prompt_builder = prompt_builder
        self.state = state
        self._no_tool_call_rounds = 0
        self._handlers: dict[str, ToolResultHandler] = {}
        self._formatters: dict[str, ToolResultFormatter] = {}
        self._register_default_handlers()

    def _register_default_handlers(self):
        """注册默认的 handler 和 formatter

        子类可覆写此方法以注册阶段特定的处理器。
        """
        self.register_handler(DefaultHandler())
        self.register_formatter(DefaultFormatter())

    @abstractmethod
    def handle_tool_result(self, tool_name: str, result: dict, state) -> PhaseStatus:
        """处理工具执行结果并返回阶段状态

        Args:
            tool_name: 工具名称
            result: 工具执行结果
            state: 当前 AgentState

        Returns:
            PhaseStatus: 阶段状态枚举值 (CONTINUE/TRANSITION/COMPLETE/ERROR)
        """
        ...

    def format_tool_result(self, tool_name: str, result: dict) -> str:
        """格式化工具执行结果为消息文本

        委托 _dispatch_format_result 进行格式化。

        Args:
            tool_name: 工具名称
            result: 工具执行结果

        Returns:
            str: 格式化后的消息文本
        """
        return self._dispatch_format_result(tool_name, result)

    def register_handler(self, handler: ToolResultHandler):
        """注册工具结果处理器

        Args:
            handler: ToolResultHandler 实例
        """
        self._handlers[handler.tool_name] = handler

    def register_formatter(self, formatter: ToolResultFormatter):
        """注册工具结果格式化器

        Args:
            formatter: ToolResultFormatter 实例
        """
        self._formatters[formatter.tool_name] = formatter

    def _dispatch_tool_result(self, tool_name: str, result: dict) -> PhaseResult:
        """分发工具结果到对应的 handler 处理

        优先级: phase本地handler > ToolManager工具自带handler > default handler

        Args:
            tool_name: 工具名称
            result: 工具执行结果

        Returns:
            PhaseResult: 处理结果
        """
        handler = self._handlers.get(tool_name)
        if handler is None:
            handler = self._handlers.get("default")
        if handler is None:
            from ..tools.manager.manager import get_tool_manager
            mgr_handler = get_tool_manager().get_handler(tool_name)
            if mgr_handler:
                return mgr_handler(result, self.state)
        if handler:
            return handler.handle(result, self.state)
        return PhaseResult(status="continue", message=str(result))

    def _dispatch_format_result(self, tool_name: str, result: dict) -> str:
        """分发工具结果到对应的 formatter 格式化

        优先级: phase本地formatter > ToolManager工具自带formatter > default formatter

        Args:
            tool_name: 工具名称
            result: 工具执行结果

        Returns:
            str: 格式化后的消息文本
        """
        formatter = self._formatters.get(tool_name)
        if formatter is None:
            formatter = self._formatters.get("default")
        if formatter is None:
            from ..tools.manager.manager import get_tool_manager
            mgr_formatter = get_tool_manager().get_formatter(tool_name)
            if mgr_formatter:
                return mgr_formatter(result)
        if formatter:
            return formatter.format(result)
        return str(result)

    def build_no_tool_reminder(self) -> str:
        """当 LLM 一轮未调用工具时生成 <reminder> 形式化提醒

        只要有一轮没有调用工具，立即插入 <reminder> XML 形式化字符对，
        提示模型立刻根据任务要求调用工具。

        Returns:
            str: <reminder> 形式化提醒文本
        """
        self._no_tool_call_rounds += 1
        return "<reminder>请立刻根据任务要求调用工具。</reminder>"

    def note_tool_called(self) -> None:
        """重置无工具调用计数器

        当 Agent 成功调用工具后，由 AgentLoop 调用此方法清零计数器。
        """
        self._no_tool_call_rounds = 0

    def cleanup_context(self) -> None:
        """清理阶段上下文

        在阶段转换前调用，由子类覆写以执行阶段特定的清理逻辑。
        默认实现为空。
        """
        pass

    def check_command_loop(self, tool_name: str, args: dict, history: dict, max_repeat: int = 3) -> PhaseResult | None:
        """命令循环检测

        检查同一命令是否被重复调用超过阈值。

        Args:
            tool_name: 工具名称
            args: 工具参数
            history: 命令调用历史 dict（可在外部维护，如 AgentLoop._command_history）
            max_repeat: 最大允许的重复次数

        Returns:
            PhaseResult | None: 检测到循环时返回 PhaseResult，否则返回 None
        """
        key = f"{tool_name}:{json.dumps(args, sort_keys=True)}"
        history[key] = history.get(key, 0) + 1
        if history[key] >= max_repeat:
            return PhaseResult(
                status="error",
                message=f"检测到命令循环: {tool_name} 被连续调用 {history[key]} 次 ({key})"
            )
        return None

    @property
    @abstractmethod
    def phase_name(self) -> str:
        """阶段名称"""
        pass
    
    @property
    @abstractmethod
    def available_tools(self) -> list[dict]:
        """该阶段可用的工具列表"""
        pass

    def _build_messages(self, system_prompt: str, context: list[dict], user_input: str) -> list[dict]:
        """构建消息列表
        
        Args:
            system_prompt: 系统提示
            context: 上下文历史
            user_input: 用户输入
            
        Returns:
            消息列表
        """
        messages = [{"role": "system", "content": system_prompt}]
        
        for msg in context:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "user":
                messages.append({"role": "user", "content": content or ""})
            elif role == "assistant":
                if "tool_calls" in msg:
                    assistant_entry = {
                        "role": "assistant",
                        "content": content or "",
                        "tool_calls": msg["tool_calls"]
                    }
                    if msg.get("reasoning_content"):
                        assistant_entry["reasoning_content"] = msg["reasoning_content"]
                    messages.append(assistant_entry)
                else:
                    messages.append({"role": "assistant", "content": content or ""})
            elif role == "system":
                messages.append({"role": "system", "content": content or ""})
            elif role == "tool":
                messages.append({
                    "role": "tool",
                    "content": content,
                    "tool_call_id": msg.get("tool_call_id", "")
                })
        
        messages.append({"role": "user", "content": user_input})
        return messages

    def _handle_opencli_result(self, result: dict, action_label: str = "命令执行") -> PhaseResult:
        """处理opencli工具执行结果的通用逻辑
        
        Args:
            result: 工具执行结果字典
            action_label: 动作标签，如"命令验证"或"命令执行"
            
        Returns:
            PhaseResult: 处理后的结果
        """
        if result.get("type") != "command_executed":
            return PhaseResult(status="error", message=result.get("error", "命令执行失败"))
        
        command = result.get("command", "")
        exec_result = result.get("result", {})
        
        if exec_result.get("success"):
            output = exec_result.get("output", "")
            if output:
                compressed = compress_opencli_result(command, output)
                return PhaseResult(
                    status="continue",
                    message=f"[OK] {action_label}成功: {command}\n\n结果:\n{compressed}",
                    data={"command": command, "result": compressed}
                )
            return PhaseResult(
                status="continue",
                message=f"[OK] {action_label}成功: {command}",
                data={"command": command, "result": "Success"}
            )
        else:
            error_msg = exec_result.get("error", "Unknown error")
            return PhaseResult(
                status="continue",
                message=f"[X] {action_label}失败: {command}\n\n错误: {error_msg}",
                data={"command": command, "error": error_msg}
            )

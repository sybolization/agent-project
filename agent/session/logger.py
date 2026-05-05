"""交互日志记录器 - 记录LLM交互用于调试"""

import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

_logger = logging.getLogger(__name__)


class InteractionLogger:
    """LLM交互日志记录器，支持Session接口"""
    
    # 事件类型常量
    EVENT_LLM_CALL = "llm_call"
    EVENT_TOOL_CALL = "tool_call"
    EVENT_TOOL_RESULT = "tool_result"
    EVENT_STATE_CHANGE = "state_change"
    EVENT_AGENT_STARTED = "agent_started"
    EVENT_AGENT_COMPLETED = "agent_completed"
    EVENT_ITERATION_START = "iteration_start"
    EVENT_ITERATION_END = "iteration_end"
    EVENT_THINKING = "thinking"
    EVENT_SPAWN_AGENTS_STARTED = "spawn_agents_started"
    EVENT_SKILL_LOADED = "skill_loaded"  # 已废弃: skill 加载信息现已合并到 tool_result 事件的 skill_info 字段中
    EVENT_LLM_ERROR = "llm_error"
    
    def __init__(self, log_dir: str = "logs/interactions", enable: bool = True,
                 agent_id: str = "unknown", parent_agent_id: str | None = None,
                 parent_session_id: str | None = None):
        self.log_dir = Path(log_dir)
        self.enable = enable
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]
        self.interactions: list[dict] = []
        self._agent_id = agent_id
        self._parent_agent_id = parent_agent_id
        self._parent_session_id = parent_session_id

        # Session接口：事件缓存
        self.events: list[dict] = []
        self._event_counter = 0
        self._jsonl_file = None  # JSONL文件句柄，用于实时写入

        # 订阅/通知机制
        self._subscribers: dict[str, callable] = {}
        
        if self.enable:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            # 初始化JSONL文件
            self._init_jsonl_file()
    
    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def parent_agent_id(self) -> str | None:
        return self._parent_agent_id

    @property
    def parent_session_id(self) -> str | None:
        return self._parent_session_id

    def __del__(self):
        """析构时关闭文件句柄"""
        self._close_jsonl_file()
    
    def log_interaction(
        self,
        iteration: int,
        input_data: dict,
        output_data: dict,
        timing_ms: float
    ) -> None:
        """记录单次LLM交互
        
        Args:
            iteration: Agent循环中的迭代编号
            input_data: 输入数据（user_message, system_prompt, context_history）
            output_data: 输出数据（content, tool_calls, success）
            timing_ms: LLM调用耗时（毫秒）
        """
        if not self.enable:
            return
        
        record = {
            "timestamp": datetime.now().isoformat(),
            "session_id": self.session_id,
            "iteration": iteration,
            "input": input_data,
            "output": output_data,
            "timing_ms": round(timing_ms, 2)
        }
        self.interactions.append(record)
        
        self._notify("llm_response", {
            "iteration": iteration,
            "content": output_data.get("content", "") if isinstance(output_data, dict) else "",
            "reasoning_content": output_data.get("reasoning_content", "") if isinstance(output_data, dict) else "",
            "tool_calls": output_data.get("tool_calls", []) if isinstance(output_data, dict) else [],
            "timing_ms": round(timing_ms, 2),
        })
    
    def log_tool_execution(
        self,
        tool_name: str,
        arguments: dict,
        result: dict,
        iteration: int = 0
    ) -> None:
        """记录工具执行结果
        
        Args:
            tool_name: 工具名称
            arguments: 工具参数
            result: 执行结果
            iteration: 当前迭代编号
        """
        if not self.enable:
            return
        
        
        result_data = result.get("result", {})
        
        if result.get("type") == "agents_spawned":
            failed_count = result.get("failed", 0)
            total_count = result.get("total_agents", 0)
            completed_count = result.get("completed", 0)
            success = failed_count == 0
            output_content = f"{completed_count}/{total_count} agents completed"
            if failed_count > 0:
                failed_errors = []
                for agent_result in result.get("results", []):
                    if agent_result.get("status") == "failed":
                        failed_errors.append(agent_result.get("error", "unknown error"))
                error = "; ".join(failed_errors) if failed_errors else f"{failed_count} agent(s) failed"
            else:
                error = None
        elif isinstance(result_data, dict):
            output_content = result_data.get("output", "")
            success = result_data.get("success")
            error = result_data.get("error")
        else:
            output_content = ""
            success = None
            error = None

        
        web_content = result.get("web_content")
        if isinstance(web_content, dict):
            has_web_content = True
            web_content_success = web_content.get("success")
            web_content_length = web_content.get("content_length")
        else:
            has_web_content = False
            web_content_success = None
            web_content_length = None
        
        record = {
            "timestamp": datetime.now().isoformat(),
            "session_id": self.session_id,
            "iteration": iteration,
            "type": "tool_execution",
            "tool_name": tool_name,
            "arguments": arguments,
            "result": {
                "type": result.get("type"),
                "command": result.get("command"),
                "success": success,
                "output": output_content,
                "error": error,
                "has_web_content": has_web_content,
                "web_content_success": web_content_success,
                "web_content_length": web_content_length,
            }
        }
        self.interactions.append(record)
        
        self._notify("tool_result", {
            "tool_name": tool_name,
            "arguments": arguments,
            "result": result,
            "iteration": iteration,
        })
    
    # ========== 订阅/通知机制 ==========
    
    def subscribe(self, callback: callable) -> str:
        """订阅事件通知
        
        Args:
            callback: 回调函数，接收 dict 参数 {"event": str, "data": dict}
            
        Returns:
            订阅者ID，用于取消订阅
        """
        import uuid
        sid = str(uuid.uuid4())[:8]
        self._subscribers[sid] = callback
        return sid
    
    def unsubscribe(self, subscriber_id: str) -> None:
        """取消订阅
        
        Args:
            subscriber_id: subscribe() 返回的订阅者ID
        """
        self._subscribers.pop(subscriber_id, None)
    
    def _notify(self, event_type: str, data: dict) -> None:
        """通知所有订阅者
        
        Args:
            event_type: 事件类型
            data: 事件数据
        """
        for cb in list(self._subscribers.values()):
            try:
                cb({"event": event_type, "data": data})
            except Exception:
                _logger.exception(
                    "订阅者回调抛出异常 (event=%s)，已跳过并继续通知其他订阅者",
                    event_type,
                )
    
    def save(self) -> Optional[str]:
        """保存所有交互记录到JSONL和Markdown文件。
        
        Returns:
            JSONL文件路径，如果日志记录被禁用则返回None
        """
        if not self.enable:
            return None
        
        # 关闭实时写入的文件句柄
        self._close_jsonl_file()
        
        # 保存Markdown格式
        if self.interactions or self.events:
            self._save_markdown()
        
        jsonl_path = self.log_dir / f"{self.session_id}.jsonl"
        return str(jsonl_path) if jsonl_path.exists() else None
    
    def _save_markdown(self) -> str:
        """保存为Markdown格式（人类可读）"""
        file_path = self.log_dir / f"{self.session_id}.md"
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"# Agent Interaction Log\n\n")
            f.write(f"**Session ID**: {self.session_id}\n\n")
            f.write(f"**Total Interactions**: {len(self.interactions)}\n\n")
            f.write(f"**Total Events**: {len(self.events)}\n\n")
            f.write("---\n\n")
            
            # 写入交互记录
            for record in self.interactions:
                self._write_iteration(f, record)
            
            # 写入事件记录
            if self.events:
                f.write("## Events\n\n")
                for event in self.events:
                    self._write_event(f, event)
        
        return str(file_path)
    
    def _write_iteration(self, f, record: dict):
        """写入单个迭代
        
        Args:
            f: 文件句柄
            record: 交互记录字典
        """
        if record.get("type") == "tool_execution":
            self._write_tool_execution(f, record)
            return
        
        input_data = record.get('input', {})
        output_data = record.get('output', {})
        
        user_msg = input_data.get('user_message', '') if isinstance(input_data, dict) else ''
        if not user_msg:
            user_msg = record.get('user_message', '')
        
        f.write(f"## Iteration {record.get('iteration', '?')}\n\n")
        
        f.write("### 用户输入\n\n")
        f.write(f"{user_msg}\n\n")
        
        f.write("### 系统提示\n\n")
        system_prompt = input_data.get('system_prompt', '') if isinstance(input_data, dict) else ''
        if not system_prompt:
            system_prompt = record.get('system_prompt', '')
        if len(system_prompt) > 500:
            system_prompt = system_prompt[:500] + "\n...[已截断]..."
        f.write(f"```\n{system_prompt}\n```\n\n")
        
        f.write("### 模型输出\n\n")
        content = output_data.get('content', '') if isinstance(output_data, dict) else ''
        if not content:
            content = record.get('content', '')
        f.write(f"{content}\n\n")
        
        f.write("### 工具调用\n\n")
        tool_calls = output_data.get('tool_calls', []) if isinstance(output_data, dict) else []
        if not tool_calls:
            tool_calls = record.get('tool_calls', [])
        if tool_calls:
            f.write("| 工具名称 | 参数 |\n")
            f.write("|----------|------|\n")
            for tc in tool_calls:
                name = tc.get('name', 'unknown')
                args = tc.get('arguments', {})
                if isinstance(args, dict):
                    args_str = json.dumps(args, ensure_ascii=False)
                else:
                    args_str = str(args)
                if len(args_str) > 100:
                    args_str = args_str[:100] + "..."
                f.write(f"| {name} | {args_str} |\n")
        else:
            f.write("无工具调用\n")
        
        f.write("\n---\n\n")
    
    def _write_tool_execution(self, f, record: dict):
        """写入工具执行记录"""
        f.write(f"## 工具执行 (Iteration {record.get('iteration', '?')})\n\n")
        f.write(f"**工具**: {record.get('tool_name', 'unknown')}\n\n")
        
        args = record.get('arguments', {})
        if args:
            f.write("**参数**:\n```json\n")
            f.write(json.dumps(args, ensure_ascii=False, indent=2))
            f.write("\n```\n\n")
        
        result = record.get('result', {})
        f.write("**结果**:\n")
        f.write(f"- 类型: {result.get('type', 'unknown')}\n")
        f.write(f"- 命令: {result.get('command', 'N/A')}\n")
        f.write(f"- 成功: {result.get('success', 'N/A')}\n")
        f.write(f"- 包含网页内容: {result.get('has_web_content', False)}\n")
        if result.get('web_content_success'):
            f.write(f"- 网页内容长度: {result.get('web_content_length', 0)}\n")
        
        if result.get('error'):
            f.write(f"\n**错误**:\n```\n{result.get('error')}\n```\n")
        
        output = result.get('output', '')
        if output:
            f.write(f"\n**输出**:\n```\n{output}\n```\n")
        
        f.write("\n---\n\n")
    
    def _write_event(self, f, event: dict):
        """写入事件记录
        
        Args:
            f: 文件句柄
            event: 事件字典
        """
        event_id = event.get("event_id", "unknown")
        event_type = event.get("event_type", "unknown")
        timestamp = event.get("timestamp", "")
        data = event.get("data", {})
        
        f.write(f"### Event {event_id}\n\n")
        f.write(f"- **类型**: {event_type}\n")
        f.write(f"- **时间**: {timestamp}\n\n")
        
        if data:
            f.write("**数据**:\n```json\n")
            f.write(json.dumps(data, ensure_ascii=False, indent=2))
            f.write("\n```\n\n")
        
        f.write("---\n\n")
    
    def get_interactions(self) -> list[dict]:
        """获取所有交互记录"""
        return self.interactions.copy()    
    
    def clear(self) -> None:
        """清空内存中的事件缓存（不重置计数器，不关闭 JSONL）"""
        self.interactions = []
        self.events = []
        # 注意：不重置 _event_counter，避免与已写入 JSONL 的旧事件 ID 冲突
    
    # ========== Session接口方法 ==========
    
    def _init_jsonl_file(self) -> None:
        """初始化JSONL文件句柄，用于实时写入事件"""
        jsonl_path = self.log_dir / f"{self.session_id}.jsonl"
        try:
            self._jsonl_file = open(jsonl_path, "a", encoding="utf-8")
        except Exception as e:
            _logger.warning("日志文件打开失败，已禁用日志文件写入: %s: %s", jsonl_path, e)
            self._jsonl_file = None
    
    def _close_jsonl_file(self) -> None:
        """关闭JSONL文件句柄"""
        if self._jsonl_file:
            self._jsonl_file.close()
            self._jsonl_file = None
    
    def emit(self, event_type: str, data: dict,
             agent_id: str | None = None, iteration: int | None = None,
             phase: str | None = None, parent_agent_id: str | None = None,
             parent_session_id: str | None = None) -> str:
        """追加事件到日志，返回事件ID
        
        Args:
            event_type: 事件类型（llm_call, tool_call, tool_result, state_change, phase_transition）
            data: 事件数据
            
        Returns:
            事件ID（格式：evt_000001）
        """
        if not self.enable:
            _logger.debug("emit: 日志已禁用，跳过 event_type=%s", event_type)
            return ""
        
        self._event_counter += 1
        event_id = f"evt_{self._event_counter:06d}"
        
        event = {
            "event_id": event_id,
            "event_type": event_type,
            "timestamp": datetime.now().isoformat(),
            "session_id": self.session_id,
            "agent_id": agent_id if agent_id is not None else self._agent_id,
            "iteration": iteration if iteration is not None else 0,
            "phase": phase if phase is not None else "",
            "parent_agent_id": parent_agent_id if parent_agent_id is not None else self._parent_agent_id,
            "parent_session_id": parent_session_id if parent_session_id is not None else self._parent_session_id,
            "data": data
        }
        
        # 添加到内存缓存
        self.events.append(event)
        
        # 实时写入JSONL文件
        if self._jsonl_file:
            self._jsonl_file.write(json.dumps(event, ensure_ascii=False) + "\n")
            self._jsonl_file.flush()
        
        return event_id
    
    def emit_error(self, error: Any) -> str:
        """持久化 AgentError 完整错误链到 JSONL

        遍历 error.__cause__ 链构建 error_chain，写入完整 traceback。
        写入失败时 fallback 到 logging.exception()，不阻断主流程。

        Args:
            error: AgentError 实例（或任意 Exception）

        Returns:
            事件ID
        """
        if not self.enable:
            return ""

        try:
            from ..errors import AgentError
            if isinstance(error, AgentError):
                error_dict = error.to_dict()
            else:
                error_dict = {
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                    "layer": "native",
                    "fatal": True,
                    "context": {},
                    "traceback": "",
                    "error_chain": [],
                }
        except Exception:
            _logger.exception("emit_error: to_dict() 失败，使用简化格式")
            error_dict = {
                "error_type": type(error).__name__,
                "error_message": str(error),
                "layer": "unknown",
                "fatal": True,
                "context": {},
                "traceback": "",
                "error_chain": [],
            }

        try:
            return self.emit("error", error_dict)
        except Exception:
            _logger.exception("emit_error: 写入 JSONL 失败，fallback 到 logging")
            return ""

    def get_events(
        self, 
        start: int = 0, 
        end: int = -1, 
        event_type: str = None
    ) -> list[dict]:
        """获取事件列表
        
        Args:
            start: 起始索引（包含）
            end: 结束索引（不包含），-1表示到末尾
            event_type: 事件类型过滤，None表示不过滤
            
        Returns:
            事件列表
        """
        # 先按类型过滤
        if event_type:
            filtered = [e for e in self.events if e.get("event_type") == event_type]
        else:
            filtered = self.events
        
        # 处理分页
        if end == -1:
            return filtered[start:].copy()
        else:
            return filtered[start:end].copy()
    
    def get_last_event(self, event_type: str = None) -> dict | None:
        """获取最后一个事件
        
        Args:
            event_type: 事件类型过滤，None表示不过滤
            
        Returns:
            最后一个事件，如果没有则返回None
        """
        if not self.events:
            return None
        
        if event_type:
            # 从后往前查找
            for event in reversed(self.events):
                if event.get("event_type") == event_type:
                    return event.copy()
            return None
        else:
            return self.events[-1].copy()
    
    def get_session_id(self) -> str:
        """获取当前session ID
        
        Returns:
            Session ID
        """
        return self.session_id

"""Agent循环 - 阶段化执行的协调器

Harness 层核心实现，是系统中唯一的执行循环，协调 LLM 调用、Tool 执行、
Phase 状态管理和 Session 写入。遵循 Anthropic Managed Agents 三层架构：
Session（持久化日志）→ Harness（本模块）→ Sandbox（Tool 执行）。
"""

import json
import logging
from typing import Optional, Any, Callable, Awaitable

from .llm.interface import get_llm_interface
from .browser.opencli_client import OpenCLIClient
from .config import MAX_ITERATIONS, SUBAGENT_MAX_ITERATIONS
from .context.compression import (
    estimate_context_tokens, 
    ContextCompressor,
    save_transcript
)
from .execution_context import ExecutionContext
from .session.logger import InteractionLogger
from .session.memory import SessionMemory
from .phases import CollectPhase, PlanPhase, ExecutePhase, ReportPhase, DefaultPhase
from .phases.base import BasePhase
from .prompts.builder import PromptBuilder
from .skills.manager import SkillManager
from .state import AgentState, AgentPhase
from .tools.executors import ToolExecutor
from .hooks.runner import HookRunner
from .hooks.types import HookEventName, HookExitCode, PhaseStatus, EventCallback
from .hooks.builtins import (
    create_complete_status_hook,
    create_transition_status_hook,
    create_error_status_hook,
    create_needs_confirmation_status_hook,
    create_default_status_hook,
)
from .errors import (
    AgentError,
    ToolError,
    HarnessError,
    PhaseExecutionError,
    LoopDetectionError,
    LLMError,
)

logger = logging.getLogger(__name__)


def _format_tool_calls_for_api(tool_calls: list[dict]) -> list[dict]:
    """将内部tool_calls格式转换为OpenAI API要求的格式
    
    内部格式: {"id": "", "name": "", "arguments": {}}
    API格式: {"id": "", "type": "function", "function": {"name": "", "arguments": "..."}}
    """
    formatted = []
    for tc in tool_calls:
        args = tc.get("arguments", {})
        if isinstance(args, dict):
            args_str = json.dumps(args, ensure_ascii=False)
        else:
            args_str = str(args) if args else "{}"
        formatted.append({
            "id": tc.get("id", ""),
            "type": "function",
            "function": {
                "name": tc.get("name", ""),
                "arguments": args_str
            }
        })
    return formatted


from dataclasses import dataclass


@dataclass
class StepResult:
    """单步迭代的控制结果

    Attributes:
        action: 控制动作 - "continue" / "return" / "inject"
        message: 返回消息（action="return" 时使用）
        next_input: 注入的下一轮输入（action="inject" 时使用）
        llm_result: LLM 调用成功时的原始结果
    """
    action: str = "continue"
    message: str = ""
    next_input: str | None = None
    llm_result: dict | None = None


class AgentLoop:
    """Agent 协调器 — 管理阶段转换与执行循环

    参考 Anthropic Managed Agents 的 Harness 设计，AgentLoop 是系统中
    **唯一的执行循环**，负责：

    1. **LLM 调用** — 通过 `_handle_llm_call` 封装完整的 LLM 交互
    2. **Tool 执行** — 通过 `ToolExecutor` 外观模式路由工具调用
    3. **Phase 管理** — 维护阶段生命周期，按需转型（COLLECT→PLAN→EXECUTE→REPORT）
    4. **Session 写入** — 所有事件通过 `InteractionLogger` 持久化到 JSONL

    架构约束（需保持）：
    - Phase 层不持有 LLM / ToolExecutor / InteractionLogger
    - Tool 层不持有 InteractionLogger，子 Agent 事件通过 event_callback 回传
    - 状态修改使用指令模式（should_update_todo 等），由 Harness 统一执行

    使用示例：
        # 标准用法
        agent = AgentLoop(max_iterations=30, mode="default")
        result = await agent.run("帮我分析这个网页")

        # 从 Session 恢复
        agent = await AgentLoop.wake("20260503_215036_099a316c")
        result = await agent.run("继续上次的任务")

        # Subagent 场景（由 SpawnAgents 工具自动创建）
        sub = AgentLoop(
            max_iterations=SUBAGENT_MAX_ITERATIONS,
            agent_id="sub_1",
            agent_depth=1,
            assigned_task="读取文件内容",
            state=parent_state_copy,
        )
    """
    
    @classmethod
    async def wake(cls, session_id: str, log_dir: str = "logs/interactions") -> "AgentLoop":
        """从Session恢复AgentLoop
        
        Args:
            session_id: Session ID
            log_dir: 日志目录
            
        Returns:
            恢复的AgentLoop实例
            
        Raises:
            FileNotFoundError: Session文件不存在
        """
        from pathlib import Path
        from .tasks import TaskManager, TaskStatus
        
        # 加载Session
        session_file = Path(log_dir) / f"{session_id}.jsonl"
        if not session_file.exists():
            raise FileNotFoundError(f"Session not found: {session_id}")
        
        # 读取事件
        events = []
        with open(session_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    events.append(json.loads(line))
        
        # 查找最后的state_change事件
        last_state_data = None
        for event in reversed(events):
            if event.get("event_type") == "state_change":
                last_state_data = event.get("data", {}).get("state")
                break
        
        # 恢复状态
        if last_state_data:
            state = AgentState.from_dict(last_state_data)
        else:
            state = AgentState()
        
        # 恢复task数据
        if state.current_task_id:
            try:
                task_manager = TaskManager(state)
                task = task_manager.get_task(state.current_task_id)
                
                if task:
                    # 验证task状态是否有效（未完成且未取消）
                    valid_statuses = [TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED]
                    if task.status in valid_statuses:
                        logger.info(f"Session恢复: 成功加载task {state.current_task_id}, 状态={task.status.value}")
                    else:
                        # task已完成或取消，清除current_task_id
                        logger.warning(f"Session恢复: task {state.current_task_id} 状态无效 ({task.status.value})，已清除")
                        state.current_task_id = None
                else:
                    # task不存在，清除current_task_id
                    logger.warning(f"Session恢复: task {state.current_task_id} 不存在，已清除")
                    state.current_task_id = None
            except Exception as e:
                # 加载失败，清除current_task_id
                logger.error(f"Session恢复: 加载task {state.current_task_id} 失败: {e}，已清除")
                state.current_task_id = None
        
        # 创建AgentLoop
        return cls(
            state=state,
            log_dir=log_dir,
        )
    
    def __init__(
        self,
        max_iterations: int = 10,
        enable_logging: bool = True,
        log_dir: str = "logs/interactions",
        state: Optional[AgentState] = None,
        agent_depth: int = 0,
        agent_id: str = "main",
        assigned_task: Optional[str] = None,
        mode: str = "three_phase",
        skill_manager: Optional[SkillManager] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
    ):
        """初始化AgentLoop
        
        Args:
            max_iterations: 最大迭代次数
            enable_logging: 是否启用日志
            log_dir: 日志目录
            state: AgentState实例（用于Subagent场景）
            agent_depth: Agent深度
            agent_id: Agent ID
            assigned_task: 分配的任务
            mode: 执行模式，支持 "three_phase"（三阶段）或 "default"（默认模式）
            skill_manager: 可选的SkillManager实例（用于测试场景）
            provider: LLM 提供商，None 时使用 LLMConfig 默认
            model: 模型名，None 时使用提供商默认
            reasoning_effort: 思考强度（如 "minimal", "low", "medium", "high", "max"）
        """
        self._provider = provider
        self._model = model
        self._reasoning_effort = reasoning_effort
        self.llm = get_llm_interface(provider=provider, model=model, reasoning_effort=reasoning_effort)
        self.skill_manager = skill_manager if skill_manager is not None else SkillManager()
        self.opencli_client = OpenCLIClient()
        self.max_iterations = max_iterations
        
        self._context: list[dict] = []
        
        # 处理 state 参数
        if state is not None:
            # 使用传入的 state（Subagent 场景）
            self.state = state
        else:
            # 创建新的 AgentState 并设置属性
            self.state = AgentState()
            self.state.agent_depth = agent_depth
            self.state.agent_id = agent_id
            self.state.assigned_task = assigned_task
        
        # 设置执行模式
        self.state.mode = mode
        
        self._interaction_logger = InteractionLogger(log_dir=log_dir, enable=enable_logging, agent_id=agent_id)

        self._last_response_text = ""
        self._repeated_count = 0
        self._max_repeated_allowed = 2
        
        self.tool_executor = ToolExecutor(
            self.skill_manager, 
            self.opencli_client, 
            None,  # 使用动态CLI查找机制
            self.llm,
            self.state,  # 传入AgentState实例
        )
        self.prompt_builder = PromptBuilder(
            self.skill_manager,
            self.state
        )
        self.session_memory = SessionMemory()
        self.context_compressor = ContextCompressor()
        
        self._init_hooks()
        self._init_phases()
    
    def _init_hooks(self) -> None:
        """初始化状态处理 Hook
        
        按优先级注册状态处理 Hook：
        1. CompleteStatusHook - 处理 complete 状态
        2. TransitionStatusHook - 处理 transition 状态
        3. ErrorStatusHook - 处理 error 状态
        4. NeedsConfirmationStatusHook - 处理 needs_confirmation 状态
        5. DefaultStatusHook - 默认处理器
        """
        self.hook_runner = HookRunner()
        
        complete_hook = create_complete_status_hook()
        self.hook_runner.register(HookEventName.POST_PHASE_EXECUTE, complete_hook)
        
        transition_hook = create_transition_status_hook(
            context=self._context,
            transition_callback=self._transition_to,
            build_transition_input_callback=self._build_transition_input,
        )
        self.hook_runner.register(HookEventName.POST_PHASE_EXECUTE, transition_hook)
        
        error_hook = create_error_status_hook(context=self._context)
        self.hook_runner.register(HookEventName.POST_PHASE_EXECUTE, error_hook)
        
        confirmation_hook = create_needs_confirmation_status_hook(context=self._context)
        self.hook_runner.register(HookEventName.POST_PHASE_EXECUTE, confirmation_hook)
        
        default_hook = create_default_status_hook(
            context=self._context,
            state=self.state,
            transition_callback=self._transition_to,
        )
        self.hook_runner.register(HookEventName.POST_PHASE_EXECUTE, default_hook)
    
    def _build_execution_context(self) -> ExecutionContext:
        """构建执行上下文"""
        return ExecutionContext(
            phase=self.state.phase,
            agent_depth=self.state.agent_depth,
            action_history=list(self.state.action_history),  # 创建副本，避免并发问题
            todos=self.state.todos.items,
            subagent_todos=self.state.subagent_todos.items,
            loaded_skills=list(self.state.loaded_skills),
            loaded_references=list(self.state.loaded_references),
            skill_contents=dict(self.state.skill_contents),
            reference_contents=dict(self.state.reference_contents),
            subagent_max_iterations=SUBAGENT_MAX_ITERATIONS,  # 从配置文件读取
        )
    
    def _init_phases(self) -> None:
        """初始化阶段实例
        
        根据mode参数决定初始化哪些阶段：
        - "default": 初始化DEFAULT阶段
        - "three_phase": 初始化COLLECT阶段（及其他阶段）
        """
        # 始终初始化所有阶段实例，但根据mode决定初始阶段
        self.phases = {
            "DEFAULT": DefaultPhase(
                prompt_builder=self.prompt_builder,
                state=self.state,
            ),
            "COLLECT": CollectPhase(
                prompt_builder=self.prompt_builder,
                state=self.state,
            ),
            "PLAN": PlanPhase(
                prompt_builder=self.prompt_builder,
                state=self.state,
            ),
            "EXECUTE": ExecutePhase(
                prompt_builder=self.prompt_builder,
                state=self.state,
            ),
            "REPORT": ReportPhase(
                prompt_builder=self.prompt_builder,
                state=self.state,
            ),
        }
        
        # 根据mode设置初始阶段
        if self.state.mode == "default":
            self.state.phase = AgentPhase.DEFAULT
            logger.info("Initialized with DEFAULT phase (mode=default)")
        else:
            # 默认使用三阶段模式
            self.state.phase = AgentPhase.COLLECT
            logger.info("Initialized with COLLECT phase (mode=three_phase)")
    
    def reset_context(self) -> None:
        """重置对话上下文"""
        self._context = []
        self.state.reset()
        self._interaction_logger.clear()
        self._init_hooks()
        self._init_phases()
    
    def set_context(self, context: list[dict]) -> None:
        """设置对话上下文"""
        self._context = context.copy()
    
    def get_context(self) -> list[dict]:
        """获取当前上下文"""
        return self._context.copy()
    
    async def run(self, user_input: str, reset: bool = False) -> str:
        """运行 Agent 循环
        
        Args:
            user_input: 用户输入
            reset: 是否重置上下文
            
        Returns:
            最终响应字符串
        """
        if reset:
            self.reset_context()
        
        self.state.iteration_count = 0
        original_user_input = user_input
        current_input = user_input
        self._context.append({"role": "user", "content": user_input})
        
        self._interaction_logger.emit(InteractionLogger.EVENT_AGENT_STARTED, {
            "user_input": user_input[:200],
        }, agent_id=self.state.agent_id, iteration=0, phase=self.state.phase.value)
        
        _command_history = {}
        
        try:
            while self.state.iteration_count < self.max_iterations:
                self.state.iteration_count += 1
                current_phase = self.phases[self.state.phase.value]
                
                system_prompt = self.prompt_builder.build(
                    self.state.phase.value,
                    {"objective": original_user_input}
                )
                
                self._context, compression_stats = await self.context_compressor.compress_if_needed(
                    context=self._context,
                    system_prompt=system_prompt,
                    agent_state=self.state,
                    session_memory=self.session_memory,
                    llm_interface=self.llm,
                    update_memory_callback=self._update_session_memory_from_state,
                    iteration_id=f"iter{self.state.iteration_count}",
                )
                
                tools = current_phase.available_tools
                logger.info(f"Iteration {self.state.iteration_count}: phase={self.state.phase.value}")
                
                self._interaction_logger.emit(InteractionLogger.EVENT_ITERATION_START,
                    {"iteration": self.state.iteration_count, "phase": self.state.phase.value},
                    agent_id=self.state.agent_id, iteration=self.state.iteration_count, phase=self.state.phase.value)
                
                llm_step = await self._handle_llm_call(system_prompt, tools, current_input, original_user_input, current_phase)
                if llm_step.action == "return":
                    return llm_step.message
                if llm_step.action == "inject":
                    current_input = llm_step.next_input
                    self._context.append({"role": "user", "content": current_input})
                    continue
                if llm_step.llm_result is None:
                    continue
                
                content = llm_step.llm_result.get("content", "")
                reasoning = llm_step.llm_result.get("reasoning_content", "")
                tool_calls = llm_step.llm_result.get("tool_calls", [])
                
                self._interaction_logger.emit(InteractionLogger.EVENT_TOOL_RESULT,
                    {"tool_name": "llm_chat", "result_type": "llm_response",
                     "content_length": len(content), "tool_calls_count": len(tool_calls),
                     "reasoning_content": (reasoning or "")[:500],
                     "content": (content or "")[:500]},
                    agent_id=self.state.agent_id, iteration=self.state.iteration_count, phase=self.state.phase.value)
                
                if not tool_calls:
                    text_step = await self._handle_text_response(content, reasoning, current_phase, current_input, original_user_input)
                    if text_step.action == "return":
                        return text_step.message
                    if text_step.action == "inject":
                        current_input = text_step.next_input
                        self._context.append({"role": "user", "content": current_input})
                    continue
                
                tool_step = await self._handle_tool_execution(
                    content, reasoning, tool_calls, current_phase, current_input, original_user_input, _command_history
                )
                if tool_step.action == "return":
                    return tool_step.message
                if tool_step.action == "inject":
                    current_input = tool_step.next_input
                    self._context.append({"role": "user", "content": current_input})
            
            return "达到最大迭代次数，任务未完成。"
        
        except AgentError as e:
            e.add_context("iteration", self.state.iteration_count)
            e.add_context("phase", self.state.phase.value)
            e.add_context("agent_id", self.state.agent_id)
            e.capture_traceback()
            self._interaction_logger.emit_error(e)
            logger.error(f"Agent 执行致命错误:\n{e}")
            return f"[致命错误] {e}"
        except Exception as e:
            wrapped = PhaseExecutionError(
                f"Agent 循环异常: {e}",
                agent_id=self.state.agent_id,
                iteration=self.state.iteration_count,
                phase=self.state.phase.value,
                fatal=True,
            )
            wrapped.__cause__ = e
            wrapped.capture_traceback()
            self._interaction_logger.emit_error(wrapped)
            logger.error(f"Agent 循环异常: {e}", exc_info=True)
            return f"执行错误: {e}"
        finally:
            self._interaction_logger.emit(InteractionLogger.EVENT_AGENT_COMPLETED, {
                "total_iterations": self.state.iteration_count,
                "final_phase": self.state.phase.value,
                "action_count": len(self.state.action_history),
            }, agent_id=self.state.agent_id, iteration=self.state.iteration_count, phase=self.state.phase.value)
            log_path = self._interaction_logger.save()
            if log_path:
                logger.info(f"Interaction log saved to: {log_path}")
    
    def _build_phase_result_dict(
        self, status: str, message: str, content: str,
        reasoning: str, tool_calls: list[dict], tool_results: list[dict]
    ) -> dict[str, Any]:
        """构建 PhaseResult 字典用于 Hook 处理

        将分散的 LLM 响应字段组装为统一的 PhaseResult 字典结构，
        作为 HookRunner 的标准输入格式。

        Args:
            status: 阶段执行状态（"continue" / "complete" / "error" 等）
            message: 状态描述消息
            content: LLM 响应文本内容
            reasoning: LLM 思考链内容
            tool_calls: 工具调用列表
            tool_results: 工具执行结果列表

        Returns:
            标准 PhaseResult 字典
        """
        return {
            "status": status,
            "message": message,
            "data": {},
            "next_phase": None,
            "tool_calls": tool_calls,
            "response_text": content or "",
            "tool_results": tool_results,
            "reasoning_content": reasoning or "",
        }
    
    def _run_post_step(
        self, phase_result_dict: dict[str, Any], current_input: str, original_input: str
    ) -> StepResult:
        """执行单次迭代的后置处理

        顺序执行：
        1. 记录 iteration_end 事件
        2. 通过 HookRunner 处理阶段执行结果
        3. 根据 Hook 退出码决定控制流（继续/返回/注入）

        Args:
            phase_result_dict: 阶段执行结果字典
            current_input: 当前迭代的输入文本
            original_input: 用户原始输入文本

        Returns:
            StepResult 控制指令
        """
        self._interaction_logger.emit(InteractionLogger.EVENT_ITERATION_END,
            {"iteration": self.state.iteration_count,
             "has_tool_calls": bool(phase_result_dict.get("tool_calls")),
             "tool_calls_count": len(phase_result_dict.get("tool_calls", []))},
            agent_id=self.state.agent_id, iteration=self.state.iteration_count, phase=self.state.phase.value)
        
        hook_result = self.hook_runner.run_post_phase_execute(
            phase_result=phase_result_dict,
            current_input=current_input,
            original_input=original_input
        )
        
        if hook_result.exit_code == HookExitCode.BLOCK:
            return StepResult(action="return", message=hook_result.message)
        elif hook_result.exit_code == HookExitCode.INJECT:
            return StepResult(action="inject", next_input=hook_result.message)
        return StepResult(action="continue")
    
    async def _handle_llm_call(
        self, system_prompt: str, tools: list[dict],
        current_input: str, original_input: str, current_phase: "BasePhase"
    ) -> StepResult:
        self._interaction_logger.emit(InteractionLogger.EVENT_LLM_CALL,
            {"tool_name": "llm_chat", "arguments": {
                "system_prompt_length": len(system_prompt),
                "messages_count": len(self._context),
                "tools_count": len(tools)
            }},
            agent_id=self.state.agent_id, iteration=self.state.iteration_count, phase=self.state.phase.value)
        
        llm_result = await self.llm.chat_interleaved(
            messages=self._context,
            system_prompt=system_prompt,
            tools=tools,
        )
        
        if not llm_result.get("success", True):
            llm_error = LLMError(
                f"LLM调用失败: {llm_result.get('error', '')}",
                provider=llm_result.get("provider", "unknown"),
                status_code=llm_result.get("status_code", 0),
                response_body=str(llm_result.get("details", ""))[:500],
                agent_id=self.state.agent_id,
                fatal=False,
            )
            llm_error.add_context("iteration", self.state.iteration_count)
            llm_error.add_context("phase", self.state.phase.value)
            self._interaction_logger.emit_error(llm_error)
            
            phase_result_dict = self._build_phase_result_dict(
                "error", f"LLM调用失败: {llm_result.get('error', '')}", "", "", [], []
            )
            return self._run_post_step(phase_result_dict, current_input, original_input)
        
        return StepResult(llm_result=llm_result)
    
    async def _handle_text_response(
        self, content: str, reasoning: str, current_phase: BasePhase,
        current_input: str, original_input: str
    ) -> StepResult:
        if content:
            self._context.append({"role": "assistant", "content": content})
        if reasoning:
            self.state.last_reasoning = reasoning
        
        self._interaction_logger.emit(InteractionLogger.EVENT_THINKING,
            {"content": content[:200], "reasoning_content": (reasoning or "")[:200]},
            agent_id=self.state.agent_id, iteration=self.state.iteration_count, phase=self.state.phase.value)
        
        reminder = current_phase.build_no_tool_reminder()
        if reminder:
            self._context.append({"role": "user", "content": reminder})
        
        if content and content == self._last_response_text:
            self._repeated_count += 1
            if self._repeated_count >= self._max_repeated_allowed:
                logger.error("模型陷入循环，强制终止")
                return StepResult(action="return", message="任务执行异常：模型陷入循环，已自动终止。")
        else:
            self._repeated_count = 0
            self._last_response_text = content or ""
        
        phase_result_dict = self._build_phase_result_dict(
            "continue", content or "", content, reasoning, [], []
        )
        return self._run_post_step(phase_result_dict, current_input, original_input)
    
    async def _handle_tool_execution(
        self, content: str, reasoning: str, tool_calls: list[dict], current_phase: BasePhase,
        current_input: str, original_input: str, _command_history: dict[str, Any]
    ) -> StepResult:
        """处理 LLM 返回的工具调用

        逐个执行工具调用，负责：
        1. 构造 assistant 消息并写入 _context
        2. 循环检测（CommandLoopDetection）
        3. 调用 ToolExecutor.execute_single() 执行工具
        4. 应用状态更新指令
        5. 格式化工具结果并写入 _context
        6. 根据 PhaseStatus 决定继续/转换/完成/错误

        Args:
            content: LLM 响应文本内容
            reasoning: LLM 思考链内容
            tool_calls: 工具调用列表
            current_phase: 当前阶段的 Phase 实例
            current_input: 当前输入文本
            original_input: 原始用户输入
            _command_history: 命令历史记录（用于循环检测）

        Returns:
            StepResult 控制指令
        """
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
        if tool_calls:
            assistant_msg["tool_calls"] = _format_tool_calls_for_api(tool_calls)
        if reasoning:
            assistant_msg["reasoning_content"] = reasoning
        self._context.append(assistant_msg)
        
        all_tool_results = []
        for tc in tool_calls:
            t_name = tc.get("name", tc.get("function", {}).get("name", ""))
            t_args = tc.get("arguments", tc.get("function", {}).get("arguments", {}))
            if isinstance(t_args, str):
                try:
                    t_args = json.loads(t_args)
                except Exception:
                    t_args = {}
            t_id = tc.get("id", tc.get("function", {}).get("id", ""))
            
            loop_result = current_phase.check_command_loop(t_name, t_args, _command_history, 3)
            if loop_result:
                loop_error = LoopDetectionError(
                    f"检测到命令循环: {t_name} 重复调用",
                    agent_id=self.state.agent_id,
                    iteration=self.state.iteration_count,
                    phase=self.state.phase.value,
                    fatal=True,
                )
                loop_error.capture_traceback()
                self._interaction_logger.emit_error(loop_error)
                return StepResult(action="return", message=f"任务异常终止: {loop_result.message}")
            
            self._interaction_logger.emit(InteractionLogger.EVENT_TOOL_CALL,
                {"tool_name": t_name, "arguments": t_args if isinstance(t_args, dict) else {}, "call_index": 0},
                agent_id=self.state.agent_id, iteration=self.state.iteration_count, phase=self.state.phase.value)
            
            try:
                exec_ctx = self._build_execution_context()
                tool_result = await self.tool_executor.execute_single(
                    {"name": t_name, "arguments": t_args},
                    exec_ctx,
                    event_callback=self._on_child_event
                )
            except ToolError as e:
                e.add_context("iteration", self.state.iteration_count)
                e.add_context("phase", self.state.phase.value)
                e.add_context("agent_id", self.state.agent_id)
                e.capture_traceback()
                self._interaction_logger.emit_error(e)
                if e.fatal:
                    raise PhaseExecutionError(
                        f"工具执行致命错误: {e}",
                        agent_id=self.state.agent_id, iteration=self.state.iteration_count,
                        phase=self.state.phase.value, fatal=True,
                    ) from e
                tool_result = {"type": "error", "message": str(e), "non_fatal": True}
            
            if not isinstance(tool_result, dict):
                tool_result = {"type": "error", "message": "Tool returned non-dict result"}
            
            if tool_result.get("type") == "confirmation_required":
                return StepResult(action="return", message=str(tool_result))
            
            self._apply_tool_state_updates(t_name, t_args, tool_result)

            current_phase.note_tool_called()
            
            result_content = current_phase.format_tool_result(t_name, tool_result)
            tool_msg_id = t_id or f"call_{t_name}"
            self._context.append({"role": "tool", "tool_call_id": tool_msg_id, "content": result_content})
            
            self._log_tool_result(t_name, tool_result)
            
            all_tool_results.append({"tool_name": t_name, "result": tool_result})
            
            phase_status = current_phase.handle_tool_result(t_name, tool_result, self.state)
            
            if phase_status == PhaseStatus.TRANSITION:
                next_phase_name = tool_result.get("next_phase")
                if next_phase_name:
                    self._transition_to(next_phase_name)
                    break
            
            if phase_status == PhaseStatus.COMPLETE:
                final_response = content or "任务完成"
                self._interaction_logger.emit(InteractionLogger.EVENT_ITERATION_END,
                    {"iteration": self.state.iteration_count, "has_tool_calls": True,
                     "tool_calls_count": len(tool_calls)},
                    agent_id=self.state.agent_id, iteration=self.state.iteration_count, phase=self.state.phase.value)
                return StepResult(action="return", message=final_response)
            
            if phase_status == PhaseStatus.ERROR:
                self._context.append({"role": "user", "content": "<reminder>工具执行出错，请分析错误原因并调用适当的工具继续完成任务。</reminder>"})
        
        phase_result_dict = self._build_phase_result_dict(
            "continue", content or "", content, reasoning, tool_calls, all_tool_results
        )
        return self._run_post_step(phase_result_dict, current_input, original_input)
    
    def _apply_tool_state_updates(self, tool_name: str, tool_args: dict, tool_result: dict) -> None:
        """处理 tool_result 中携带的状态更新指令
        
        支持以下指令 key：
        - should_update_todo: 更新单个 TODO 状态
        - should_set_todos: 设置 TODO 列表并通知更新
        - should_record: 记录操作到 action_history
        - should_complete_todos: 批量完成 TODO
        - should_transition_to_report: 转换到 REPORT 阶段
        - should_stop: 仅记录日志
        """
        if not isinstance(tool_result, dict):
            return

        # 指令: 更新单个 TODO 状态
        if tool_result.get("should_update_todo"):
            todo_data = tool_result.get("should_update_todo", {})
            if isinstance(todo_data, dict):
                todo_id = todo_data.get("id") or tool_result.get("todo_id", "")
                new_status = todo_data.get("status") or tool_result.get("new_status", "")
            else:
                todo_id = tool_result.get("todo_id", "")
                new_status = tool_result.get("new_status", "")
            if todo_id and new_status:
                self.state.update_todo_status(todo_id, new_status)
                logger.info(f"TODO 状态更新: [{todo_id}] -> {new_status}")

        # 指令: 设置 TODO 列表
        if tool_result.get("should_set_todos"):
            todo_list = tool_result.get("todo_list", [])
            self.state.set_todo_list(todo_list)
            logger.info(f"TODO 列表已设置: {len(todo_list)} 项")

        # 指令: 记录操作到 action_history
        if tool_result.get("should_record"):
            record_data = tool_result.get("record_data", {})
            self.state.add_action(
                record_data.get("tool_name", tool_name),
                record_data.get("arguments", tool_args),
                record_data.get("result_summary", ""),
            )

        # 指令: 批量完成 TODO
        if tool_result.get("should_complete_todos"):
            todo_ids = tool_result.get("todo_ids_to_complete", [])
            for todo_id in todo_ids:
                self.state.update_todo_status(todo_id, "completed")
            logger.info(f"批量完成 TODO: {todo_ids}")

        # 指令: 转换到 REPORT 阶段
        if tool_result.get("should_transition_to_report"):
            self._transition_to("REPORT")

        # 指令: 停止（仅记录日志）
        if tool_result.get("should_stop"):
            logger.info(f"工具 [{tool_name}] 标记 should_stop，执行完成")

    def _log_tool_result(self, tool_name: str, tool_result: dict) -> None:
        result_type = tool_result.get("type", "")
        result_error = tool_result.get("error") or tool_result.get("message") if isinstance(tool_result, dict) else None
        tool_result_data = {
            "tool_name": tool_name,
            "result_type": result_type,
            "success": tool_result.get("success"),
            "output_length": len(str(tool_result.get("output", ""))),
            "error": (str(result_error)[:200] if result_error else None),
        }
        if isinstance(tool_result, dict) and tool_result.get("type") in ("skill_loaded", "category_loaded"):
            tool_result_data["skill_info"] = {
                "skill_name": tool_result.get("skill_name", tool_result.get("category_name", ""))[:100],
                "content_length": len(str(tool_result.get("content", ""))),
                "category": tool_result.get("category_name", tool_result.get("category_name", "")) if tool_result.get("type") == "category_loaded" else "",
                "success": True,
            }
        self._interaction_logger.emit(InteractionLogger.EVENT_TOOL_RESULT, tool_result_data,
                                      agent_id=self.state.agent_id, iteration=self.state.iteration_count, phase=self.state.phase.value)

    def _on_child_event(self, event_type: str, data: dict) -> None:
        """子 Agent 事件回调，将事件转发到 InteractionLogger"""
        self._interaction_logger.emit(event_type, data,
            agent_id=self.state.agent_id,
            iteration=self.state.iteration_count,
            phase=self.state.phase.value)
    
    def _transition_to(self, phase_name: str) -> None:
        """切换到指定阶段
        
        支持的阶段转换：
        - COLLECT -> PLAN
        - PLAN -> EXECUTE
        - EXECUTE -> REPORT
        - DEFAULT -> REPORT
        """
        from_phase = self.state.phase.value
        current_phase = self.phases.get(from_phase)
        if current_phase:
            current_phase.cleanup_context()

        if phase_name == "PLAN":
            self.state.transition_to_plan()
        elif phase_name == "EXECUTE":
            self.state.transition_to_execute()
        elif phase_name == "REPORT":
            self.state.phase = AgentPhase.REPORT
        
        self._interaction_logger.emit("phase_transition", {
            "from_phase": from_phase,
            "to_phase": phase_name,
        }, agent_id=self.state.agent_id, iteration=self.state.iteration_count, phase=phase_name)
        
        self._interaction_logger.emit(InteractionLogger.EVENT_STATE_CHANGE, {
            "state": self.state.to_dict(),
            "transition": phase_name,
        })
        
        logger.info(f"Phase transitioned to: {phase_name}")

    def _update_session_memory_from_state(self) -> None:
        """从 AgentState 同步 SessionMemory

        在上下文压缩前调用，确保压缩后的摘要不丢失 TODO 项和阶段信息。
        SessionMemory 在压缩过程中作为持久化锚点保留关键状态。
        """
        self.session_memory.current_phase = self.state.phase.value if hasattr(self.state, 'phase') else None
        
        if hasattr(self.state, 'todos') and self.state.todos.items:
            self.session_memory.todo_items = self.state.todos.items
        
        logger.info(f"Session memory updated from agent state: phase={self.session_memory.current_phase}, todos={len(self.session_memory.todo_items)}")
    
    def _build_transition_input(self, result: "PhaseResult", original_request: str) -> str:
        """构建阶段转换后的输入文本

        从 PhaseResult 中提取已收集信息和已加载技能，与用户原始请求
        拼接为下一阶段的初始输入。

        Args:
            result: 上一阶段的执行结果
            original_request: 用户原始请求文本

        Returns:
            格式化后的阶段转换输入文本
        """
        input_text = f"[阶段转换] {result.message}\n\n"
        
        if result.data:
            if "collected_info" in result.data:
                input_text += f"已收集信息: {result.data['collected_info']}\n"
            if "loaded_skills" in result.data:
                input_text += f"已加载技能: {', '.join(result.data['loaded_skills'])}\n"
        
        input_text += f"\n用户原始请求：{original_request}"
        return input_text
    
    def get_loaded_skills(self) -> list[str]:
        """获取已加载的技能名称列表

        Returns:
            技能名称列表（副本），如 ["browser-harness", "opencli/opencli-oneshot"]
        """
        return list(self.state.loaded_skills)
    
    def get_context_history(self) -> list[dict[str, Any]]:
        """获取完整的对话上下文历史

        Returns:
            消息列表副本，包含 user/assistant/tool 角色的全部消息
        """
        return self.get_context()

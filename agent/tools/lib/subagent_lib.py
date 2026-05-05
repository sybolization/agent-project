"""Subagent execution module for parallel task processing.

This module implements a direct execution mode for subagents, bypassing the
three-phase orchestration (COLLECT -> PLAN -> EXECUTE) for simpler and faster
task execution.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ...state import AgentState, AgentPhase
from ...whiteboard import Whiteboard
from ..manager.manager import get_tools_for_phase
from ...session.tracking import TodoTracker
from ...session.logger import InteractionLogger
from ...execution_context import ExecutionContext
from ...hooks.runner import HookRunner
from ...hooks.builtins.error_status_hook import create_error_status_hook
from ...hooks.builtins.complete_status_hook import create_complete_status_hook
from ...hooks.builtins.default_status_hook import create_default_status_hook
from ...hooks.types import HookExitCode, HookEventName
from ...errors import SubagentExecutionError

logger = logging.getLogger(__name__)


# =============================================================================
# Subagent Prompt Template (Simplified, Direct Execution)
# =============================================================================

SUBAGENT_SYSTEM_PROMPT = """你是子代理，负责执行分配给你的特定任务。

## 核心规则

1. 你是一个独立的执行单元，直接执行任务
2. 你可以使用以下工具: {available_tools}
3. 任务完成后必须调用 task_complete 工具提交结果
4. 输出文本不会结束任务，只有调用 task_complete 才能结束
5. 调用 task_complete 时，请提供 summary（任务摘要）和 results（关键数据数组）
   示例：task_complete(summary="搜索完成，获取10条笔记", results=[{{"rank":1,"title":"...","url":"..."}}])

{inherited_skills_section}
{action_history_section}
## 当前任务

{task_description}

## 可用工具说明

{tools_description}

## 执行指引

1. 分析任务需求，确定执行步骤
2. 使用 execute_command 工具执行任务步骤
3. 使用 update_todo 更新任务进度（如果有TODO列表）
4. 完成后调用 task_complete(summary="任务摘要", results=[...]) 提交结果

注意：
- 直接开始执行，不需要规划阶段
- 遇到问题时尝试解决，无法解决时在 task_complete 中说明
- 保持简洁高效，避免冗余操作
"""


def _format_inherited_skills(skill_contents: dict[str, str]) -> str:
    """格式化继承的技能内容
    
    Args:
        skill_contents: 技能名称到内容的映射
        
    Returns:
        格式化后的技能章节字符串
    """
    if not skill_contents:
        return ""
    
    lines = ["## 已加载的技能（继承自父 Agent）", ""]
    lines.append("以下技能已由父 Agent 加载，你可以直接使用，无需重新加载：")
    lines.append("")
    
    for skill_name, content in skill_contents.items():
        lines.append(f"### {skill_name}")
        lines.append("")
        lines.append(content)
        lines.append("")
    
    return "\n".join(lines)


def _format_action_history(action_history: list[dict[str, Any]], max_rounds: int = 3) -> str:
    """格式化父 Agent 的工具调用历史
    
    Args:
        action_history: 工具调用历史列表
        max_rounds: 最大保留轮数
        
    Returns:
        格式化后的工具调用历史字符串
    """
    if not action_history:
        return ""
    
    recent_actions = action_history[-max_rounds:]
    
    lines = ["## 父 Agent 的工具调用历史", ""]
    lines.append("以下是父 Agent 最近执行的工具调用，供你参考：")
    lines.append("")
    
    for i, action in enumerate(recent_actions, 1):
        tool_name = action.get("tool_name", "unknown")
        args = action.get("arguments", {})
        result_summary = action.get("result_summary", "")
        
        lines.append(f"### 调用 {i}: {tool_name}")
        if args:
            args_str = str(args)[:200]
            lines.append(f"参数: {args_str}")
        if result_summary:
            lines.append(f"结果: {result_summary}")
        lines.append("")
    
    return "\n".join(lines)


@dataclass
class SubagentResult:
    """Result from a subagent task execution."""
    agent_id: str
    task: str
    status: str  # "completed" or "failed"
    summary: Optional[str] = None
    actions_taken: List[str] = field(default_factory=list)
    error: Optional[str] = None
    partial_results: Optional[str] = None


class SubagentExecutor:
    """Executor for running subagents with assigned tasks.

    Subagents are independent agent instances that can execute tasks
    in parallel. Each subagent has its own state but inherits certain
    context from the parent agent (loaded skills, references).

    This implementation uses direct execution mode, bypassing the
    three-phase orchestration for simpler and faster task execution.
    """

    MAX_INNER_ROUNDS = 8

    def __init__(
        self,
        parent_context: ExecutionContext,
        llm_client=None,
        opencli_client=None,
        tool_executor=None,
        skill_manager=None,
        interaction_logger: Optional[InteractionLogger] = None,
        inherited_skills: Optional[List[str]] = None,
        excluded_skills: Optional[List[str]] = None,
    ):
        """Initialize SubagentExecutor.

        Args:
            parent_context: The parent agent's execution context to inherit from
            llm_client: LLM client for the subagent to use (optional, will create if not provided)
            opencli_client: OpenCLI client for browser operations (optional, will create if not provided)
            tool_executor: ToolExecutor instance (optional, will create if not provided)
            skill_manager: SkillManager instance (optional, will create if not provided)
            interaction_logger: InteractionLogger for session logging (optional, will create child logger if not provided)
            inherited_skills: Optional list of skill names to inherit from parent agent. If specified, only these skills will be passed.
            excluded_skills: Optional list of skill names to exclude from inheritance. Only used when inherited_skills is not specified.
        """
        self.parent_context = parent_context
        self.llm_client = llm_client
        self.opencli_client = opencli_client
        self.tool_executor = tool_executor
        self.skill_manager = skill_manager
        self.parent_interaction_logger = interaction_logger
        self.inherited_skills = inherited_skills
        self.excluded_skills = excluded_skills
        self._hook_runner = None
        self._last_reasoning = ""

    def _filter_inherited_skills(
        self,
        parent_loaded_skills: set[str],
        parent_skill_contents: dict[str, str],
        parent_reference_contents: Optional[dict[str, str]] = None,
    ) -> tuple[set[str], dict[str, str], dict[str, str]]:
        """Filter inherited skills based on inherited_skills and excluded_skills.

        Args:
            parent_loaded_skills: Set of skill names loaded in parent agent
            parent_skill_contents: Dictionary of skill contents from parent agent
            parent_reference_contents: Optional dictionary of reference contents from parent agent

        Returns:
            Tuple of (filtered_loaded_skills, filtered_skill_contents, filtered_reference_contents)
        """
        # If inherited_skills is specified, only inherit those skills
        if self.inherited_skills is not None:
            filtered_skills = set()
            for parent_skill in parent_loaded_skills:
                for inherited in self.inherited_skills:
                    if parent_skill == inherited or parent_skill.endswith("/" + inherited):
                        filtered_skills.add(parent_skill)
                        break
            filtered_contents = {k: v for k, v in parent_skill_contents.items() if k in filtered_skills}
            filtered_refs = {}
            if parent_reference_contents:
                for key, value in parent_reference_contents.items():
                    # Reference keys are in format "skill_name/reference_name"
                    skill_name = key.split("/")[0] if "/" in key else key
                    if skill_name in filtered_skills:
                        filtered_refs[key] = value
            return filtered_skills, filtered_contents, filtered_refs

        # If excluded_skills is specified, exclude those skills
        if self.excluded_skills is not None:
            filtered_skills = parent_loaded_skills - set(self.excluded_skills)
            filtered_contents = {k: v for k, v in parent_skill_contents.items() if k in filtered_skills}
            filtered_refs = {}
            if parent_reference_contents:
                for key, value in parent_reference_contents.items():
                    skill_name = key.split("/")[0] if "/" in key else key
                    if skill_name in filtered_skills:
                        filtered_refs[key] = value
            return filtered_skills, filtered_contents, filtered_refs

        # Default: inherit all skills (backward compatible)
        return parent_loaded_skills, parent_skill_contents, parent_reference_contents or {}

    def _create_simplified_subagent_state(
        self,
        agent_id: str,
        assigned_task: str,
        whiteboard: Optional[Whiteboard] = None,
    ) -> AgentState:
        """Create a simplified subagent state for direct execution.

        This creates a minimal state that skips the COLLECT and PLAN phases,
        starting directly in EXECUTE phase.

        Args:
            agent_id: Unique identifier for this subagent
            assigned_task: Task description assigned to this subagent
            whiteboard: Optional Whiteboard for shared context

        Returns:
            AgentState configured for direct execution
        """
        # Filter skills based on inherited_skills and excluded_skills
        filtered_skills, filtered_contents, filtered_refs = self._filter_inherited_skills(
            parent_loaded_skills=set(self.parent_context.loaded_skills),
            parent_skill_contents=dict(self.parent_context.skill_contents),
            parent_reference_contents=dict(self.parent_context.reference_contents) if self.parent_context.reference_contents else None,
        )

        # Create base state with filtered inherited context
        state = AgentState(
            phase=AgentPhase.EXECUTE,  # Start directly in EXECUTE phase
            iteration_count=0,
            completed_steps=0,
            loaded_skills=filtered_skills,
            loaded_references=set(filtered_refs.keys()),
            skill_contents=filtered_contents,
            reference_contents=filtered_refs,
            phase_summaries={},
            prompt_template="subagent",
            context_sections={},
            todos=TodoTracker(),
            action_history=[],
            agent_depth=self.parent_context.agent_depth + 1,
            agent_id=agent_id,
            assigned_task=assigned_task,
        )

        # If whiteboard provides shared context, add it to state
        if whiteboard and whiteboard.shared_context:
            for key, value in whiteboard.shared_context.items():
                if key == "todo_list" and isinstance(value, list):
                    state.set_todo_list(value)

        return state

    def _build_subagent_prompt(
        self,
        task: str,
        available_tools: List[str],
        tools_description: str,
        parent_skill_contents: Optional[Dict[str, str]] = None,
        parent_action_history: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Build the system prompt for subagent.

        Args:
            task: Task description
            available_tools: List of available tool names
            tools_description: Formatted tools description
            parent_skill_contents: Optional skill contents inherited from parent agent
            parent_action_history: Optional action history from parent agent

        Returns:
            System prompt string
        """
        inherited_skills_section = _format_inherited_skills(parent_skill_contents or {})
        action_history_section = _format_action_history(parent_action_history or [])
        
        return SUBAGENT_SYSTEM_PROMPT.format(
            available_tools=", ".join(available_tools),
            inherited_skills_section=inherited_skills_section,
            action_history_section=action_history_section,
            task_description=task,
            tools_description=tools_description,
        )

    def _init_hooks(self, context: list) -> HookRunner:
        runner = HookRunner()
        runner.register(HookEventName.POST_PHASE_EXECUTE, create_error_status_hook(context))
        runner.register(HookEventName.POST_PHASE_EXECUTE, create_complete_status_hook())
        runner.register(HookEventName.POST_PHASE_EXECUTE, create_default_status_hook(
            context=context,
            state=None,
            transition_callback=None
        ))
        return runner

    async def run_subagent(
        self,
        agent_id: str,
        assigned_task: str,
        whiteboard: Optional[Whiteboard] = None,
        max_iterations: int = 5,
    ) -> SubagentResult:
        """Run a single subagent with the assigned task using direct execution.

        This method bypasses the three-phase orchestration and directly
        executes the task in a simplified execution environment.

        Args:
            agent_id: Unique identifier for this subagent
            assigned_task: Task description assigned to this subagent
            whiteboard: Optional Whiteboard for shared context
            max_iterations: Maximum iterations for the subagent loop

        Returns:
            SubagentResult containing the task completion report
        """
        # Import here to avoid circular imports
        from ...llm.interface import get_llm_interface
        from ...browser.opencli_client import OpenCLIClient, find_opencli_path
        from ...skills.manager import SkillManager
        from ...tools.executors.executor import ToolExecutor
        from ...phases.base import PhaseResult

        # Create simplified subagent state
        subagent_state = self._create_simplified_subagent_state(
            agent_id=agent_id,
            assigned_task=assigned_task,
            whiteboard=whiteboard,
        )

        # Initialize components - use provided ones or create new
        llm = self.llm_client or get_llm_interface()
        skill_manager = self.skill_manager or SkillManager()
        
        # Use provided opencli_client or create new one
        if self.opencli_client is None:
            opencli_client = OpenCLIClient()
            opencli_path = find_opencli_path()
        else:
            opencli_client = self.opencli_client
            opencli_path = find_opencli_path()
        
        # Use provided tool_executor or create new one
        if self.tool_executor is not None:
            tool_executor = self.tool_executor
        else:
            tool_executor = ToolExecutor(
                skill_manager=skill_manager,
                opencli_client=opencli_client,
                opencli_path=opencli_path,
                llm_client=llm,
                state=subagent_state,
            )

        # Get available tools for EXECUTE phase (excluding spawn_agents for subagents)
        available_tools = get_tools_for_phase(AgentPhase.EXECUTE, exclude_tools=["spawn_agents"])
        tool_names = ["opencli", "update_todo", "task_complete"]

        # Build tools description
        tools_desc_lines = []
        for tool in available_tools:
            name = tool.get("function", {}).get("name", "")
            desc = tool.get("function", {}).get("description", "")
            tools_desc_lines.append(f"- {name}: {desc[:200]}")
        tools_description = "\n".join(tools_desc_lines)

        # Filter parent skills based on inherited_skills and excluded_skills
        filtered_loaded_skills, parent_skill_contents, filtered_refs = self._filter_inherited_skills(
            parent_loaded_skills=set(self.parent_context.loaded_skills),
            parent_skill_contents=dict(self.parent_context.skill_contents) if self.parent_context.skill_contents else {},
            parent_reference_contents=dict(self.parent_context.reference_contents) if self.parent_context.reference_contents else None,
        )

        # 获取父 agent 的工具调用历史（最近 3 轮）
        parent_action_history = list(self.parent_context.action_history) if self.parent_context.action_history else []
        
        logger.info(f"[Subagent {agent_id}] parent_context.action_history length: {len(self.parent_context.action_history) if self.parent_context.action_history else 0}")
        logger.info(f"[Subagent {agent_id}] parent_action_history length: {len(parent_action_history)}")
        logger.info(f"[Subagent {agent_id}] inherited_skills: {self.inherited_skills}")
        logger.info(f"[Subagent {agent_id}] excluded_skills: {self.excluded_skills}")
        logger.info(f"[Subagent {agent_id}] filtered skills: {filtered_loaded_skills}")
        if parent_action_history:
            logger.info(f"[Subagent {agent_id}] parent_action_history sample: {parent_action_history[0] if parent_action_history else 'empty'}")

        # Build system prompt
        try:
            system_prompt = self._build_subagent_prompt(
                task=assigned_task,
                available_tools=tool_names,
                tools_description=tools_description,
                parent_skill_contents=parent_skill_contents,
                parent_action_history=parent_action_history,
            )
        except Exception as e:
            raise SubagentExecutionError(
                f"子代理 prompt 构建失败: {e}",
                tool_name="spawn_agents",
                agent_id=agent_id,
                fatal=True,
                context={"init_failed": True},
            ) from e

        # Create subagent-specific InteractionLogger
        subagent_logger = None

        iteration = 0

        if self.parent_interaction_logger and self.parent_interaction_logger.enable:
            subagent_logger = InteractionLogger(
                log_dir=str(self.parent_interaction_logger.log_dir),
                enable=True,
                agent_id=agent_id,
                parent_agent_id=getattr(self.parent_interaction_logger, 'agent_id', self.parent_context.agent_id if hasattr(self.parent_context, 'agent_id') else 'unknown'),
                parent_session_id=self.parent_interaction_logger.session_id,
            )
            subagent_logger.emit("subagent_created", {
                "agent_id": agent_id,
                "task": assigned_task,
                "parent_session_id": self.parent_interaction_logger.session_id,
                "loaded_skills": list(filtered_loaded_skills),
                "loaded_references": list(filtered_refs.keys()),
                "parent_action_history_count": len(self.parent_context.action_history) if self.parent_context.action_history else 0,
                "parent_agent_depth": self.parent_context.agent_depth,
                "whiteboard_shared_context": dict(whiteboard.shared_context) if whiteboard and whiteboard.shared_context else None,
                "inherited_skills": self.inherited_skills,
                "excluded_skills": self.excluded_skills,
            }, iteration=iteration, phase="SUBAGENT")
            subagent_logger.emit("subagent_context", {
                "system_prompt": system_prompt[:5000],
                "parent_skill_contents": {k: v[:500] for k, v in (parent_skill_contents or {}).items()},
                "parent_action_history_count": len(parent_action_history),
                "available_tools": tool_names,
                "tools_description": tools_description[:2000],
                "parent_action_history": [{k: (str(v)[:500] if isinstance(v, (str, dict, list)) else v) for k, v in entry.items()} for entry in (parent_action_history or [])],
            }, iteration=iteration, phase="SUBAGENT")
            logger.info(f"[Subagent {agent_id}] Created subagent logger: {subagent_logger.session_id}")

        # Initialize conversation context
        context: List[dict] = []
        hook_runner = self._init_hooks(context)

        current_input = "请开始执行任务。"

        try:
            while iteration < max_iterations:
                iteration += 1
                subagent_state.iteration_count = iteration

                if subagent_logger:
                    subagent_logger.emit("subagent_iteration", {
                        "iteration": iteration,
                        "context_messages_count": len(context),
                        "action_history_count": len(subagent_state.action_history),
                    }, iteration=iteration, phase="SUBAGENT")

                # Build messages
                messages = [{"role": "system", "content": system_prompt}]
                messages.extend(context)
                messages.append({"role": "user", "content": current_input})

                if subagent_logger and iteration == 1:
                    subagent_logger.log_interaction(
                        iteration=0,
                        input_data={
                            "user_message": f"Subagent task: {assigned_task}",
                            "system_prompt": system_prompt[:3000],
                            "context_messages_count": len(context),
                        },
                        output_data={"content": "", "tool_calls": [], "success": True},
                        timing_ms=0,
                    )

                # Call LLM
                start_time = time.time()
                result = await llm.chat_interleaved(
                    messages=messages,
                    temperature=0.2,
                    tools=available_tools,
                )
                timing_ms = (time.time() - start_time) * 1000
                logger.info(f"[Subagent {agent_id}] Iteration {iteration}, timing: {timing_ms:.0f}ms")

                if subagent_logger:
                    subagent_logger.emit(InteractionLogger.EVENT_LLM_CALL, {
                        "iteration": iteration,
                        "timing_ms": round(timing_ms, 2),
                        "messages_count": len(messages),
                        "context_length": len(json.dumps(messages, ensure_ascii=False)),
                    }, iteration=iteration, phase="SUBAGENT")

                if not isinstance(result, dict):
                    error_msg = f"LLM returned non-dict result: {type(result).__name__}"
                    logger.error(f"[Subagent {agent_id}] {error_msg}")
                    phase_result = PhaseResult(status="error", message=error_msg,
                                              reasoning_content=self._last_reasoning)
                    hook_result = await asyncio.to_thread(
                        hook_runner.run_post_phase_execute,
                        phase_result=phase_result.__dict__,
                        current_input=current_input,
                        original_input=assigned_task
                    )
                    if hook_result.exit_code == HookExitCode.BLOCK:
                        return SubagentResult(agent_id=agent_id, task=assigned_task, status="failed", error=error_msg)
                    current_input = hook_result.message
                    if subagent_logger:
                        from ...errors import SubagentExecutionError  # noqa: F811
                        subagent_logger.emit_error(
                            SubagentExecutionError(error_msg, tool_name="llm_call", agent_id=agent_id, fatal=False)
                        )
                        subagent_logger.emit("llm_error", {
                            "iteration": iteration,
                            "error_message": str(error_msg)[:500],
                            "llm_provider": getattr(llm, 'provider', 'unknown') if llm else 'unknown',
                        }, iteration=iteration, phase="SUBAGENT")
                    continue

                if not result.get("success"):
                    error_msg = result.get("error", "LLM call failed")
                    details = result.get("details", "")
                    if "reasoning_content" in str(details or error_msg) and "must be passed back" in str(details or error_msg):
                        for msg in context:
                            if msg.get("role") == "assistant" and "reasoning_content" in msg:
                                del msg["reasoning_content"]
                        if hasattr(llm, '_adapter') and hasattr(llm._adapter, 'thinking_enabled'):
                            llm._adapter.thinking_enabled = False
                        logger.warning(f"[Subagent {agent_id}] DeepSeek reasoning_content 回传错误，已清理 reasoning_content 并关闭 thinking 后重试")
                        continue

                    logger.error(f"[Subagent {agent_id}] LLM error: {error_msg}")
                    phase_result = PhaseResult(status="error", message=error_msg,
                                              reasoning_content=self._last_reasoning)
                    hook_result = await asyncio.to_thread(
                        hook_runner.run_post_phase_execute,
                        phase_result=phase_result.__dict__,
                        current_input=current_input,
                        original_input=assigned_task
                    )
                    if hook_result.exit_code == HookExitCode.BLOCK:
                        return SubagentResult(agent_id=agent_id, task=assigned_task, status="failed", error=error_msg)
                    current_input = hook_result.message
                    if subagent_logger:
                        from ...errors import SubagentExecutionError  # noqa: F811
                        subagent_logger.emit_error(
                            SubagentExecutionError(error_msg, tool_name="llm_call", agent_id=agent_id, fatal=False)
                        )
                        subagent_logger.emit("llm_error", {
                            "iteration": iteration,
                            "error_message": str(error_msg)[:500],
                            "llm_provider": getattr(llm, 'provider', 'unknown') if llm else 'unknown',
                        }, iteration=iteration, phase="SUBAGENT")
                    continue

                response_text = result.get("content", "")
                tool_calls = result.get("tool_calls", [])
                reasoning_content = result.get("reasoning_content", "")
                if tool_calls:
                    self._last_reasoning = reasoning_content

                if subagent_logger:
                    subagent_logger.log_interaction(
                        iteration=iteration,
                        input_data={
                            "user_message": current_input[:2000] if isinstance(current_input, str) else str(current_input)[:2000],
                        },
                        output_data={
                            "content": response_text[:3000] if response_text else "",
                            "reasoning_content": reasoning_content[:3000] if reasoning_content else "",
                            "tool_calls": tool_calls,
                            "success": True,
                        },
                        timing_ms=timing_ms,
                    )
                    subagent_logger.emit("llm_response", {
                        "iteration": iteration,
                        "content_length": len(response_text) if response_text else 0,
                        "reasoning_length": len(reasoning_content) if reasoning_content else 0,
                        "tool_calls_count": len(tool_calls),
                    }, iteration=iteration, phase="SUBAGENT")

                if not tool_calls:
                    phase_result = PhaseResult(
                        status="default",
                        response_text=response_text,
                        message=response_text,
                        reasoning_content=self._last_reasoning
                    )
                    hook_result = await asyncio.to_thread(
                        hook_runner.run_post_phase_execute,
                        phase_result=phase_result.__dict__,
                        current_input=current_input,
                        original_input=assigned_task
                    )
                    if hook_result.exit_code == HookExitCode.BLOCK:
                        return SubagentResult(agent_id=agent_id, task=assigned_task, status="failed", error="No tool calls")
                    current_input = hook_result.message
                    continue

                # Process tool calls
                tool_results = []
                is_complete = False
                complete_summary = ""
                complete_success = True
                complete_results = []

                for tc in tool_calls:
                    tc_name = tc.get("name", "")
                    tc_args = tc.get("arguments", {})
                    tc_id = tc.get("id", "")

                    logger.info(f"[Subagent {agent_id}] Tool call: {tc_name}, args: {tc_args}")

                    if subagent_logger:
                        subagent_logger.emit(InteractionLogger.EVENT_TOOL_CALL, {
                            "iteration": iteration,
                            "tool_name": tc_name,
                            "arguments": json.dumps(tc_args, ensure_ascii=False)[:2000] if isinstance(tc_args, dict) else str(tc_args)[:2000],
                        }, iteration=iteration, phase="SUBAGENT")

                    exec_context = ExecutionContext(
                        phase=AgentPhase.EXECUTE,
                        agent_depth=subagent_state.agent_depth,
                        action_history=subagent_state.action_history,
                        todos=subagent_state.todos.items,
                        loaded_skills=list(subagent_state.loaded_skills),
                        loaded_references=list(subagent_state.loaded_references),
                        skill_contents=subagent_state.skill_contents,
                        reference_contents=subagent_state.reference_contents,
                    )

                    tc_result = await tool_executor.execute_single(tc, exec_context)

                    if not isinstance(tc_result, dict):
                        logger.error(f"[Subagent {agent_id}] Tool {tc_name} returned non-dict: {type(tc_result).__name__}")
                        tc_result = {"type": "error", "message": f"Tool returned non-dict result: {type(tc_result).__name__}"}

                    if subagent_logger:
                        subagent_logger.log_tool_execution(
                            tool_name=tc_name,
                            arguments=tc_args if isinstance(tc_args, dict) else {},
                            result=tc_result,
                            iteration=iteration,
                        )

                    if tc_result.get("should_record"):
                        record_data = tc_result.get("record_data")
                        if isinstance(record_data, dict):
                            subagent_state.action_history.append(record_data)
                    if tc_result.get("should_update_todo"):
                        update = tc_result["should_update_todo"]
                        if isinstance(update, dict):
                            todo_id = update.get("id")
                            new_status = update.get("status")
                            if todo_id and new_status:
                                subagent_state.todos.update_status(todo_id, new_status)

                    if tc_name == "task_complete" and tc_result.get("type") != "error":
                        is_complete = True
                        complete_summary = tc_args.get("summary", "")
                        complete_success = tc_args.get("success", True)
                        complete_results = tc_args.get("results", [])

                    tool_results.append(tc_result)
                    logger.info(f"[Subagent {agent_id}] Tool result: {str(tc_result)[:500]}")

                    if is_complete:
                        actions_taken = []
                        for action in subagent_state.get_recent_actions(10):
                            tool_name = action.get("tool_name", "")
                            args = action.get("arguments", {})
                            if tool_name == "opencli":
                                cmd = args.get("command", "")
                                actions_taken.append(f"opencli: {cmd}")
                            else:
                                actions_taken.append(f"{tool_name}: {str(args)[:50]}")

                        if subagent_logger:
                            subagent_logger.emit("subagent_completed", {
                                "agent_id": agent_id,
                                "status": "completed" if complete_success else "failed",
                                "summary": complete_summary[:500],
                                "total_iterations": iteration,
                                "actions_count": len(subagent_state.action_history),
                                "tool_results_count": len(tool_results),
                                "action_history": subagent_state.action_history,
                                "final_todos": subagent_state.todos.items if subagent_state.todos else [],
                            }, iteration=iteration, phase="SUBAGENT")
                            subagent_logger.save()

                        phase_result = PhaseResult(
                            status="complete",
                            message=complete_summary,
                            tool_calls=tool_calls,
                            tool_results=tool_results,
                            response_text=response_text,
                            reasoning_content=self._last_reasoning
                        )
                        hook_result = await asyncio.to_thread(
                            hook_runner.run_post_phase_execute,
                            phase_result=phase_result.__dict__,
                            current_input=current_input,
                            original_input=assigned_task
                        )
                        return SubagentResult(
                            agent_id=agent_id,
                            task=assigned_task,
                            status="completed" if complete_success else "failed",
                            summary=complete_summary,
                            actions_taken=actions_taken,
                            partial_results="\n".join(str(r) for r in complete_results) if complete_results else None,
                        )
                else:
                    # Build assistant message with reasoning_content for context
                    assistant_msg = {"role": "assistant", "content": response_text or ""}
                    formatted_tc = []
                    for tc in tool_calls:
                        args = tc.get("arguments", {})
                        if isinstance(args, dict):
                            args_str = json.dumps(args, ensure_ascii=False)
                        else:
                            args_str = str(args) if args else "{}"
                        formatted_tc.append({
                            "id": tc.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": tc.get("name", ""),
                                "arguments": args_str
                            }
                        })
                    assistant_msg["tool_calls"] = formatted_tc
                    if tool_calls and reasoning_content:
                        assistant_msg["reasoning_content"] = reasoning_content
                    context.append(assistant_msg)

                    # Append tool result messages
                    for tc, tr in zip(tool_calls, tool_results):
                        tc_id = tc.get("id", "")
                        result_str = json.dumps(tr, ensure_ascii=False, default=str)
                        context.append({
                            "role": "tool",
                            "content": result_str,
                            "tool_call_id": tc_id
                        })

                    phase_result = PhaseResult(
                        status="default",
                        tool_calls=tool_calls,
                        tool_results=tool_results,
                        response_text=response_text,
                        reasoning_content=self._last_reasoning
                    )
                    hook_result = await asyncio.to_thread(
                        hook_runner.run_post_phase_execute,
                        phase_result=phase_result.__dict__,
                        current_input=current_input,
                        original_input=assigned_task
                    )
                    if hook_result.exit_code == HookExitCode.BLOCK:
                        return SubagentResult(agent_id=agent_id, task=assigned_task, status="failed", error="Unexpected block from default hook")
                    current_input = hook_result.message

            # Max iterations reached
            logger.warning(f"[Subagent {agent_id}] Max iterations ({max_iterations}) reached")

            if subagent_logger:
                subagent_logger.emit("subagent_failed", {
                    "agent_id": agent_id,
                    "reason": "max_iterations_reached",
                    "total_iterations": max_iterations,
                    "action_history_count": len(subagent_state.action_history),
                }, iteration=iteration, phase="SUBAGENT")
                subagent_logger.save()

            # Extract partial results
            partial_results = None
            if subagent_state.action_history:
                partial_results = "\n".join(
                    f"- {a.get('tool_name', 'unknown')}: {a.get('result_summary', '')}"
                    for a in subagent_state.action_history[-5:]
                )

            return SubagentResult(
                agent_id=agent_id,
                task=assigned_task,
                status="failed",
                error="Max iterations reached without task_complete",
                partial_results=partial_results,
            )

        except SubagentExecutionError:
            if subagent_logger:
                subagent_logger.save()
            raise
        except Exception as e:
            logger.error(f"[Subagent {agent_id}] 未预期异常: {e}")
            if subagent_logger:
                subagent_logger.emit("subagent_failed", {
                    "agent_id": agent_id,
                    "reason": "unexpected_exception",
                    "error": str(e),
                    "action_history_count": len(subagent_state.action_history) if subagent_state else 0,
                }, iteration=iteration, phase="SUBAGENT")
                subagent_logger.save()
            raise SubagentExecutionError(
                f"子代理执行异常: {e}",
                tool_name="spawn_agents",
                agent_id=agent_id,
                fatal=True,
            ) from e

    async def run_subagents_parallel(
        self,
        tasks: List[str],
        shared_context: Optional[Dict[str, Any]] = None,
        available_tools: Optional[List[str]] = None,
        max_iterations_per_agent: int = 5,
    ) -> Dict[str, Any]:
        """Run multiple subagents in parallel with shared context.

        Args:
            tasks: List of task descriptions, one per subagent
            shared_context: Shared context data to pass to all subagents
            available_tools: List of tools available to subagents (default: opencli, task_complete)
            max_iterations_per_agent: Maximum iterations for each subagent

        Returns:
            Aggregated results from all subagents containing:
            - total_agents: Number of subagents created
            - completed: Number of successfully completed subagents
            - failed: Number of failed subagents
            - results: List of individual subagent results
        """
        timestamp = int(time.time() * 1000)

        # Create shared Whiteboard
        whiteboard = Whiteboard(
            task="Parallel execution",
            available_tools=available_tools or ["opencli", "task_complete"],
            parent_agent_id="main",
            shared_context=shared_context or {},
            instructions="Execute your assigned task and report results via task_complete.",
        )

        # Create subagent tasks
        subagent_tasks = []
        for idx, task in enumerate(tasks):
            agent_id = f"sub_{timestamp}_{idx}"
            subagent_tasks.append(
                self.run_subagent(
                    agent_id=agent_id,
                    assigned_task=task,
                    whiteboard=whiteboard,
                    max_iterations=max_iterations_per_agent,
                )
            )

        # Run all subagents in parallel
        results = await asyncio.gather(*subagent_tasks, return_exceptions=True)

        # Process results
        completed = 0
        failed = 0
        result_list = []

        for result in results:
            if isinstance(result, Exception):
                failed += 1
                result_list.append({
                    "agent_id": "unknown",
                    "task": "unknown",
                    "status": "failed",
                    "error": str(result),
                })
            elif isinstance(result, SubagentResult):
                if result.status == "completed":
                    completed += 1
                else:
                    failed += 1
                result_list.append({
                    "agent_id": result.agent_id,
                    "task": result.task,
                    "status": result.status,
                    "summary": result.summary,
                    "actions_taken": result.actions_taken,
                    "error": result.error,
                    "partial_results": result.partial_results,
                })

        return {
            "total_agents": len(tasks),
            "completed": completed,
            "failed": failed,
            "results": result_list,
        }

    def get_aggregated_summary(self, parallel_result: Dict[str, Any]) -> str:
        """Generate a human-readable summary from parallel execution results.

        Args:
            parallel_result: Result dict from run_subagents_parallel

        Returns:
            Formatted summary string
        """
        lines = [
            f"Subagent Execution Summary",
            f"=" * 40,
            f"Total agents: {parallel_result['total_agents']}",
            f"Completed: {parallel_result['completed']}",
            f"Failed: {parallel_result['failed']}",
            "",
        ]

        for result in parallel_result["results"]:
            status_icon = "[OK]" if result["status"] == "completed" else "[FAIL]"
            lines.append(f"{status_icon} Agent: {result['agent_id']}")
            lines.append(f"   Task: {result['task'][:200]}...")

            if result["status"] == "completed":
                if result.get("summary"):
                    lines.append(f"   Summary: {result['summary'][:500]}...")
                if result.get("actions_taken"):
                    lines.append(f"   Actions: {len(result['actions_taken'])} steps")
            else:
                if result.get("error"):
                    lines.append(f"   Error: {result['error'][:500]}")
                if result.get("partial_results"):
                    lines.append(f"   Partial: {result['partial_results'][:500]}")

            lines.append("")

        return "\n".join(lines)

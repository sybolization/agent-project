"""工具执行器 - 外观类，委托具体执行到子执行器"""

import asyncio
import dataclasses
import json
import logging
from typing import Any, Optional

from ...skills.manager import SkillManager
from ...state import AgentPhase, AgentState
from ...execution_context import ExecutionContext
from ..manager.manager import get_available_tool_names
from ..manager import get_tool_manager
from ...browser.opencli_client import OpenCLIClient
from ...hooks import HookRunner, HookEventName, HookExitCode
from ...hooks.types import EventCallback
from ...hooks.builtins import create_permission_hook
from ...tasks import TaskManager
from ...errors import AgentError, SubagentExecutionError

from ..lib.command_lib import CommandExecutor
from ..lib.cdp_lib import CdpExecutor
from ..lib.skill_lib import SkillExecutor
from ..lib.subagent_lib import SubagentResult, SubagentExecutor
from ..lib.task_lib import TaskExecutor

logger = logging.getLogger(__name__)


from ..registry import ToolRegistry, ToolHandler


class ToolExecutor:
    """工具执行器外观类

    职责：
    - 执行工具调用并返回结果
    - 不直接修改任何外部状态
    - 所有状态修改通过返回指令，由Harness执行
    - 委托具体执行到 CommandExecutor / CdpExecutor / SkillExecutor / TaskExecutor
    """

    PARALLEL_TOOLS = {"load_skill", "load_skill_category", "load_reference"}
    PHASE_TRANSITION_TOOLS = {"start_plan", "start_execute"}

    def __init__(
        self,
        skill_manager: SkillManager,
        opencli_client: OpenCLIClient,
        opencli_path: str | None = None,
        llm_client = None,
        state: AgentState | None = None,
        browser_lock_enabled: bool | None = None,
    ):
        self.skill_manager = skill_manager
        self.opencli_client = opencli_client
        self.opencli_path = opencli_path
        self.llm_client = llm_client
        self.state = state

        # 初始化子执行器
        self._command_executor = CommandExecutor(
            opencli_client=opencli_client,
            opencli_path=opencli_path,
            browser_lock_enabled=browser_lock_enabled,
        )
        self._cdp_executor = CdpExecutor()
        self._skill_executor = SkillExecutor(skill_manager)
        self._task_executor = TaskExecutor(TaskManager(state) if state else None)

        # Hook 系统
        self.hook_runner = HookRunner()
        self.hook_runner.register(
            HookEventName.PRE_TOOL_USE,
            create_permission_hook()
        )

        # 工具注册表
        self._tool_registry = ToolRegistry()
        self._register_tools()
    # ---- 子执行器属性访问 ----

    @property
    def cdp_executor(self) -> CdpExecutor:
        """提供对 CDP 执行器的访问，用于外部状态查询"""
        return self._cdp_executor

    # ---- 阶段验证 ----

    def validate_tool_for_phase(self, tool_name: str, phase: AgentPhase) -> tuple[bool, str]:
        """验证工具是否在当前阶段可用

        Args:
            tool_name: 工具名称
            phase: 当前Agent阶段

        Returns:
            (是否可用, 错误信息)
        """
        available = get_available_tool_names(phase)
        if tool_name not in available:
            return False, (
                f"工具 '{tool_name}' 在 {phase.value} 阶段不可用。"
                f"当前可用工具: {', '.join(available)}"
            )
        return True, ""

    def _get_context_or_default(self, context: Optional[ExecutionContext]) -> ExecutionContext:
        """获取context或返回默认值（保持向后兼容）"""
        return context if context is not None else ExecutionContext()

    def _register_tools(self) -> None:
        """从 ToolManager 构建路由表——注册所有已注册工具的 executor"""
        from ..manager.manager import get_tool_manager

        manager = get_tool_manager()
        deps = {
            "_skill_executor": self._skill_executor,
            "_command_executor": self._command_executor,
            "_cdp_executor": self._cdp_executor,
            "_task_executor": self._task_executor,
            "_tool_executor": self,
            "_agent_state": self.state,
        }

        for tool_name in manager.get_available_tool_names():
            tool_def = manager.get_tool(tool_name)
            if tool_def is None or tool_def.executor is None:
                continue

            executor_obj = tool_def.executor
            for attr, value in deps.items():
                if hasattr(executor_obj, attr):
                    setattr(executor_obj, attr, value)

            for attr in ("_skill_executor", "_command_executor", "_cdp_executor", "_task_executor", "_tool_executor"):
                if hasattr(executor_obj, attr) and getattr(executor_obj, attr) is None:
                    logger.error(
                        "工具 '%s' 的依赖 '%s' 注入失败，工具将无法正常执行", tool_name, attr
                    )

            is_async = asyncio.iscoroutinefunction(executor_obj.execute)
            self._tool_registry.register(
                tool_name, executor_obj.execute,
                is_async=is_async, pass_call=True, pass_ctx=True,
            )

    # ---- 主执行入口 ----

    async def execute_single(
        self,
        call: dict,
        context: Optional[ExecutionContext] = None,
        event_callback: EventCallback = None
    ) -> dict:
        """执行单个工具调用

        Args:
            call: 工具调用字典，包含name和arguments
            context: 执行上下文，用于状态访问

        Returns:
            结果字典，包含type和对应结果
        """
        ctx = self._get_context_or_default(context)
        phase = ctx.phase
        call_name = call["name"]

        # 阶段验证
        if phase is not None:
            is_valid, error_msg = self.validate_tool_for_phase(call_name, phase)
            if not is_valid:
                return {"type": "error", "message": error_msg}

        # === 运行 PreToolUse Hook ===
        hook_result = self.hook_runner.run_pre_tool_use(
            call_name,
            call.get("arguments", {})
        )

        if hook_result.exit_code == HookExitCode.BLOCK:
            return {
                "type": "error",
                "message": hook_result.message,
                "blocked_by_hook": True,
            }

        # 如果 Hook 返回 INJECT，在结果中添加需要确认的标记
        if hook_result.exit_code == HookExitCode.INJECT:
            return {
                "type": "confirmation_required",
                "message": hook_result.message,
                "tool_name": call_name,
                "arguments": call.get("arguments", {}),
                "reason": "需要用户确认",
            }
        # === Hook 处理结束 ===

        # ---- 使用注册表路由到子执行器 ----
        th = self._tool_registry.get(call_name)

        if th is None:
            return self._handle_unknown_tool(call)

        # 注入 event_callback 到 handler，供 spawn_agents 等工具使用
        if event_callback is not None:
            th._event_callback = event_callback

        args_list = []
        if not th.no_args:
            args_list.append(call if th.pass_call else call.get("arguments", {}))
        if th.pass_ctx:
            args_list.append(ctx)

        if th.is_async:
            result = await th.handler(*args_list)
        else:
            result = th.handler(*args_list)

        return result

    # ---- 阶段转换工具 ----

    def _execute_start_plan(self, call: dict) -> dict:
        """Execute start_plan tool call - phase transition COLLECT -> PLAN."""
        collected_info = call["arguments"].get("collected_info", "")
        loaded_skills = call["arguments"].get("loaded_skills", [])

        return {
            "type": "phase_transition",
            "transition": "COLLECT_to_PLAN",
            "collected_info": collected_info,
            "loaded_skills": loaded_skills,
            "message": "已进入规划阶段。请分析任务需求，制定执行计划，然后调用 start_execute 工具。"
        }

    def _execute_start_execute(self, call: dict, context: ExecutionContext) -> dict:
        """执行start_execute工具调用 - 阶段转换 PLAN -> EXECUTE

        返回should_set_todos指令，由Harness执行状态修改
        """
        todo_list = call["arguments"].get("todo_list", [])

        if isinstance(todo_list, str):
            try:
                todo_list = json.loads(todo_list)
            except json.JSONDecodeError:
                todo_list = []

        estimated_steps = call["arguments"].get("estimated_steps", len(todo_list))

        if not todo_list or len(todo_list) == 0:
            return {
                "type": "error",
                "message": (
                    "[!] start_execute 必须提供非空的 todo_list。\n"
                    "请将任务分解为具体的子任务，每个子任务包含 id、content、status。\n"
                    "示例：\n"
                    '{"id": "1", "content": "搜索笔记", "status": "pending"}'
                )
            }

        # 返回should_set_todos指令，不直接修改状态
        return {
            "type": "phase_transition",
            "transition": "PLAN_to_EXECUTE",
            "estimated_steps": estimated_steps,
            "todo_list": todo_list,
            "should_set_todos": True,
            "message": "已进入执行阶段。请按计划执行命令，完成后调用 task_complete 工具。"
        }

    # ---- TODO 管理工具 ----

    def _execute_update_todo(self, call: dict, context: ExecutionContext) -> dict:
        """执行update_todo工具调用

        使用context方法查找TODO，返回should_update_todo指令
        """
        todo_id = call["arguments"].get("todo_id", "")
        status = call["arguments"].get("status", "")

        if not context.todos:
            return {
                "type": "error",
                "message": "TODO列表为空。请先在start_execute中创建TODO列表。"
            }

        todo = context.get_todo_by_id(todo_id)
        if not todo:
            available_ids = [t.get("id") for t in context.todos]
            return {
                "type": "error",
                "message": f"未找到TODO项: {todo_id}。可用的TODO ID: {available_ids}"
            }

        old_status = todo.get("status", "pending")
        todo_content = todo.get("content", "")

        # 获取当前进度（用于反馈）
        progress = context.get_todo_progress()

        # 返回should_update_todo指令，不直接修改状态
        return {
            "type": "todo_updated",
            "todo_id": todo_id,
            "old_status": old_status,
            "new_status": status,
            "content": todo_content,
            "progress": progress,
            "should_update_todo": True,
            "should_record": True,
            "record_data": {
                "tool_name": "update_todo",
                "arguments": {"todo_id": todo_id, "status": status},
                "result_summary": f"TODO [{todo_id}] {old_status} -> {status}"
            },
            "message": f"TODO [{todo_id}] {todo_content}: {old_status} -> {status}\n进度: {progress['completed']}/{progress['total']} 已完成"
        }

    def _execute_task_complete(self, call: dict, context: ExecutionContext) -> dict:
        """执行task_complete工具调用

        强制完成所有未完成的TODO，并转换到REPORT阶段
        """
        # 收集所有未完成的TODO ID（pending和in_progress）
        incomplete_ids = []
        for todo in context.todos:
            if todo.get("status") != "completed":
                incomplete_ids.append(todo.get("id", ""))

        return {
            "type": "task_complete",
            "should_complete_todos": True,
            "todo_ids_to_complete": incomplete_ids,
            "should_transition_to_report": True,
            "should_record": True,
            "record_data": {
                "tool_name": "task_complete",
                "arguments": {},
                "result_summary": f"任务完成: 强制完成所有TODO（{len(incomplete_ids)}项）"
            },
            "should_stop": True,
            "message": f"已强制完成所有TODO（{len(incomplete_ids)}项），即将进入汇报阶段。"
        }

    # ---- 子Agent派生 ----

    async def _execute_spawn_agents(self, args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        """执行spawn_agents工具，并行运行多个子Agent

        Args:
            args: 工具参数，包含：
                - agent_count: 子Agent数量
                - tasks: 单个任务或任务列表
                - subagent_todos: 原子化的子任务列表
                - shared_context: 可选的共享上下文字典
                - available_tools: 可选的子Agent可用工具列表
                - inherited_skills: 可选的继承技能列表
                - excluded_skills: 可选的排除技能列表

        Returns:
            所有子Agent的聚合结果
        """
        # 使用context.agent_depth进行深度检查
        if context.agent_depth >= 1:
            return {
                "type": "error",
                "message": "Maximum subagent depth (1) reached. Cannot spawn more agents."
            }

        # 验证并规范化参数
        agent_count = args.get("agent_count", 1)
        tasks = args.get("tasks", [])
        subagent_todos = args.get("subagent_todos")
        shared_context = args.get("shared_context")
        available_tools = args.get("available_tools")
        inherited_skills = args.get("inherited_skills")
        excluded_skills = args.get("excluded_skills")

        # 从 ExecutionContext 或配置中读取 max_iterations
        from ...config import SUBAGENT_MAX_ITERATIONS
        max_iterations = context.subagent_max_iterations if context.subagent_max_iterations is not None else SUBAGENT_MAX_ITERATIONS

        # === 前置条件验证 ===

        # 验证1: 已收集必要信息
        has_loaded_skills = bool(context.loaded_skills)
        has_shared_context = shared_context is not None and len(shared_context) > 0

        if not has_loaded_skills and not has_shared_context:
            return {
                "type": "error",
                "message": (
                    "[错误] 调用 spawn_agents 前必须先收集必要的信息。\n\n"
                    "请先完成以下步骤：\n"
                    "1. 使用 load_skill 加载相关技能，或\n"
                    "2. 在 shared_context 中提供足够的任务上下文\n"
                    "3. 了解工具的使用方式和可用命令\n"
                    "4. 然后再调用 spawn_agents\n\n"
                    "示例：load_skill('smart-search') 或 load_skill_category('opencli')"
                )
            }

        # 验证2: 已提供 subagent_todos 参数
        if subagent_todos is None:
            return {
                "type": "error",
                "message": (
                    "[错误] 调用 spawn_agents 前必须先创建 subagent_todos。\n\n"
                    "subagent_todos 是原子化的子任务列表，用于：\n"
                    "1. 验证任务拆解的合理性\n"
                    "2. 确保每个 subagent 执行不同的子任务\n"
                    "3. 避免重复工作\n\n"
                    "请先完成以下步骤：\n"
                    "1. 将任务拆解为原子化的子任务\n"
                    "2. 创建 subagent_todos 参数\n"
                    "3. 确保每个子任务对应一个 subagent\n"
                    "4. 然后再调用 spawn_agents\n\n"
                    "示例：subagent_todos=[\n"
                    "  {'id': 'sub1', 'content': '搜寻品牌A', 'status': 'pending'},\n"
                    "  {'id': 'sub2', 'content': '搜寻品牌B', 'status': 'pending'}\n"
                    "]"
                )
            }

        # 验证3: subagent_todos 非空
        if not subagent_todos or len(subagent_todos) == 0:
            return {
                "type": "error",
                "message": (
                    "[错误] subagent_todos 不能为空。\n\n"
                    "请提供至少一个子任务，每个子任务对应一个 subagent。"
                )
            }

        # 验证4: tasks 参数是列表（拒绝单个字符串）
        if isinstance(tasks, str):
            return {
                "type": "error",
                "message": (
                    f"[错误] tasks 参数应该是任务列表，而非单个任务字符串。\n\n"
                    f"当前：tasks=\"{tasks[:50]}...\"\n"
                    f"期望：tasks=[\"子任务1\", \"子任务2\", \"子任务3\"]\n\n"
                    f"请将任务拆解为不同的子任务，每个 subagent 执行不同的子任务。"
                )
            }

        # 验证5: subagent_todos 长度与 agent_count 匹配
        if len(subagent_todos) != agent_count:
            return {
                "type": "error",
                "message": (
                    f"[错误] subagent_todos 的长度必须与 agent_count 匹配。\n\n"
                    f"当前：agent_count={agent_count}, subagent_todos 长度={len(subagent_todos)}\n"
                    f"期望：subagent_todos 长度={agent_count}\n\n"
                    f"请确保每个 subagent 对应一个 subagent_todo 项。"
                )
            }

        # 处理任务列表
        if isinstance(tasks, list):
            if len(tasks) != agent_count:
                return {
                    "type": "error",
                    "message": f"Number of tasks ({len(tasks)}) must match agent_count ({agent_count})"
                }
        else:
            return {
                "type": "error",
                "message": "tasks must be a list of strings"
            }

        # 检索 event_callback（由 execute_single 注入到 handler 上的属性）
        th = self._tool_registry.get("spawn_agents")
        event_callback = getattr(th, '_event_callback', None) if th else None

        # 使用容器化的并行执行
        result = await self._run_subagents_with_containers(
            tasks=tasks,
            parent_context=context,
            shared_context=shared_context,
            max_iterations=max_iterations,
            inherited_skills=inherited_skills,
            excluded_skills=excluded_skills,
            event_callback=event_callback,
        )

        return result

    async def _run_subagents_with_containers(
        self,
        tasks: list[str],
        parent_context: ExecutionContext,
        shared_context: Optional[dict[str, Any]] = None,
        event_callback: EventCallback = None,
        max_iterations: int = 5,
        inherited_skills: Optional[list[str]] = None,
        excluded_skills: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """使用容器化的方式并行运行多个 subagent

        Args:
            tasks: 任务列表
            parent_context: 父 Agent 的执行上下文
            shared_context: 共享上下文
            event_callback: 事件回调函数，用于回传 spawn_agents_started 等事件
            max_iterations: 每个 subagent 的最大迭代次数
            inherited_skills: 指定继承的技能列表
            excluded_skills: 指定排除的技能列表

        Returns:
            聚合的结果
        """
        from ...container import ContainerManager, ContainerConfig
        from ...config import CONTAINER_CONFIG

        # 使用配置创建 ContainerManager
        container_config = ContainerConfig(
            max_containers=min(len(tasks), CONTAINER_CONFIG.max_containers),
            base_port=CONTAINER_CONFIG.base_port,
            daemon_startup_timeout=CONTAINER_CONFIG.daemon_startup_timeout,
            container_reuse=CONTAINER_CONFIG.container_reuse,
        )

        async with ContainerManager(config=container_config) as manager:
            # 并行创建容器并执行任务
            results = []
            containers = []

            # 创建容器
            for task in tasks:
                try:
                    container = await manager.create_container()
                    containers.append((container, task))
                except Exception as e:
                    logger.error(f"[spawn_agents] 创建容器失败: {e}")
                    results.append({
                        "agent_id": "failed",
                        "task": task,
                        "status": "failed",
                        "error": f"创建容器失败: {e}",
                    })

            # 并行执行任务
            async def execute_in_container(container, task):
                try:
                    result = await container.execute_task(
                        task=task,
                        parent_context=parent_context,
                        max_iterations=max_iterations,
                        inherited_skills=inherited_skills,
                        excluded_skills=excluded_skills,
                    )
                    return result
                except AgentError as e:
                    logger.error(f"[spawn_agents] 容器 {container.container_id} AgentError: {e}")
                    raise
                except Exception as e:
                    logger.error(f"[spawn_agents] 容器 {container.container_id} 执行失败: {e}")
                    wrapped = SubagentExecutionError(
                        f"容器执行异常: {e}",
                        tool_name="spawn_agents",
                        agent_id=container.container_id,
                        fatal=False,
                    )
                    raise wrapped

            # 并行执行所有任务
            execution_tasks = [
                execute_in_container(container, task)
                for container, task in containers
            ]

            if execution_tasks:
                if event_callback:
                    event_callback("spawn_agents_started", {
                        "total_agents": len(containers),
                        "tasks": tasks,
                        "child_agent_ids": [c.container_id for c, _ in containers],
                    })
                execution_results = await asyncio.gather(*execution_tasks, return_exceptions=True)

                for result in execution_results:
                    if isinstance(result, Exception):
                        logger.warning(f"[spawn_agents] asyncio.gather 返回异常: {type(result).__name__}: {result}")
                        results.append({
                            "agent_id": "unknown",
                            "task": "unknown",
                            "status": "failed",
                            "error": str(result),
                        })
                    elif isinstance(result, SubagentResult):
                        results.append(dataclasses.asdict(result))
                    elif isinstance(result, dict):
                        results.append(result)
                    else:
                        logger.warning(
                            f"[spawn_agents] 未知结果类型: {type(result).__name__}，已跳过"
                        )

            # 聚合结果
            completed = sum(1 for r in results if r.get("status") == "completed")
            failed = sum(1 for r in results if r.get("status") != "completed")

            if not results and containers:
                return {
                    "type": "agents_spawned",
                    "total_agents": len(tasks),
                    "completed": 0,
                    "failed": len(tasks),
                    "results": [],
                    "error": "所有子代理结果被丢弃（内部错误）",
                }

            return {
                "type": "agents_spawned",
                "total_agents": len(tasks),
                "completed": completed,
                "failed": failed,
                "results": results,
            }

    # ---- 未知工具处理 ----

    def _handle_unknown_tool(self, call: dict) -> dict:
        """Handle unknown tool calls."""
        call_name = call["name"]
        skill_names = [s["name"] for s in self.skill_manager.get_skill_descriptions()]
        if call_name in skill_names:
            return {
                "type": "error",
                "message": f"Tool '{call_name}' not found. '{call_name}' is a SKILL, not a tool. Use load_skill(\"{call_name}\") to load its content first."
            }
        else:
            all_tools = get_tool_manager().get_tool_names_for_phase(AgentPhase.EXECUTE)
            return {
                "type": "error",
                "message": f"Tool '{call_name}' not found. Available tools depend on current phase."
            }

    # ---- 并行执行 ----

    async def execute_parallel(
        self,
        tool_calls: list[dict],
        context: Optional[ExecutionContext] = None
    ) -> list[dict]:
        """Execute tool calls in parallel (with safety partitioning).

        load_skill and load_reference can be executed in parallel (read-only).
        opencli needs serial execution (browser operations may have side effects).
        Phase transition tools are handled separately.

        Args:
            tool_calls: List of tool calls
            context: Execution context for state access

        Returns:
            List of results in original order
        """
        parallel_calls = []
        serial_calls = []
        parallel_indices = []
        serial_indices = []

        for i, call in enumerate(tool_calls):
            if call["name"] in self.PARALLEL_TOOLS:
                parallel_calls.append(call)
                parallel_indices.append(i)
            else:
                serial_calls.append(call)
                serial_indices.append(i)

        results: list[dict | None] = [None] * len(tool_calls)

        if parallel_calls:
            parallel_results = await asyncio.gather(
                *[self.execute_single(call, context) for call in parallel_calls],
                return_exceptions=True
            )
            for idx, result in zip(parallel_indices, parallel_results):
                if isinstance(result, Exception):
                    results[idx] = {"type": "error", "message": str(result)}
                else:
                    results[idx] = result

        for idx, call in zip(serial_indices, serial_calls):
            result = await self.execute_single(call, context)
            results[idx] = result

        return results

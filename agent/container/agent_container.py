"""AgentContainer - 容器化的 Agent 执行环境

每个 AgentContainer 实例代表一个独立的 Agent 执行环境，
拥有自己的 OpenCLI daemon 实例和隔离的资源。

职责：
- 管理容器生命周期（启动/停止 daemon）
- 提供容器化的组件实例
- 将任务执行委托给 SubagentExecutor
"""

import asyncio
import logging
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..browser.opencli_client import OpenCLIClient, find_opencli_path
from ..execution_context import ExecutionContext
from ..skills.manager import SkillManager
from ..state import AgentPhase, AgentState
from ..tools.executors import ToolExecutor, SubagentExecutor, SubagentResult
from ..errors import ContainerStartupError, ContainerStateError
from .container_config import ContainerConfig
from .container_status import ContainerStatus

logger = logging.getLogger(__name__)


class AgentContainer:
    """容器化的 Agent 执行环境

    每个 AgentContainer 实例代表一个独立的 Agent 执行环境，
    拥有自己的 OpenCLI daemon 实例和隔离的资源。

    职责分离：
    - AgentContainer: 容器生命周期管理、组件初始化
    - SubagentExecutor: 任务执行逻辑（复用现有实现）

    Attributes:
        container_id: 容器的唯一标识符
        port: OpenCLI daemon 监听的端口号
        status: 容器当前状态
        opencli_client: OpenCLI 客户端实例
        state: Agent 状态管理实例
        tool_executor: 工具执行器实例
        skill_manager: 技能管理器实例
        llm_client: LLM 接口实例
    """

    def __init__(
        self,
        container_id: str,
        port: int,
        config: Optional[ContainerConfig] = None,
    ):
        """初始化 AgentContainer

        Args:
            container_id: 容器的唯一标识符
            port: OpenCLI daemon 监听的端口号
            config: 容器配置，如果为 None 则使用默认配置
        """
        self.container_id = container_id
        self.port = port
        self.config = config or ContainerConfig()
        self.status = ContainerStatus.CREATED

        # 组件实例（延迟初始化）
        self.opencli_client: Optional[OpenCLIClient] = None
        self.state: Optional[AgentState] = None
        self.tool_executor: Optional[ToolExecutor] = None
        self.skill_manager: Optional[SkillManager] = None
        self.llm_client: Optional[Any] = None

        # SubagentExecutor 实例（延迟初始化）
        self._subagent_executor: Optional[SubagentExecutor] = None

        # daemon 进程句柄
        self._daemon_process: Optional[subprocess.Popen] = None

        logger.info(f"[AgentContainer {container_id}] 创建完成，端口: {port}")

    def _init_components(self) -> None:
        """初始化容器内的组件实例

        创建 OpenCLI 客户端、Agent 状态、工具执行器等组件。
        """
        # 延迟导入以避免循环导入
        from ..llm.interface import get_llm_interface

        # 创建 OpenCLI 客户端（使用指定端口）
        self.opencli_client = OpenCLIClient(port=self.port)

        # 创建 Agent 状态（直接进入 EXECUTE 阶段）
        self.state = AgentState(
            phase=AgentPhase.EXECUTE,
            iteration_count=0,
            completed_steps=0,
            loaded_skills=set(),
            loaded_references=set(),
            skill_contents={},
            reference_contents={},
            agent_depth=1,  # 容器内的 Agent 深度为 1
            agent_id=self.container_id,
        )

        # 创建技能管理器
        self.skill_manager = SkillManager()

        # 获取 LLM 接口
        self.llm_client = get_llm_interface()

        # 创建工具执行器
        opencli_path = find_opencli_path()
        self.tool_executor = ToolExecutor(
            skill_manager=self.skill_manager,
            opencli_client=self.opencli_client,
            opencli_path=opencli_path,
            llm_client=self.llm_client,
            state=self.state,
        )

        logger.info(f"[AgentContainer {self.container_id}] 组件初始化完成")

    def _init_subagent_executor(
        self,
        parent_context: ExecutionContext,
        interaction_logger=None,
        inherited_skills: Optional[List[str]] = None,
        excluded_skills: Optional[List[str]] = None,
    ) -> None:
        """初始化 SubagentExecutor

        Args:
            parent_context: 父 Agent 的执行上下文
            inherited_skills: 指定继承的技能列表
            excluded_skills: 指定排除的技能列表
        """
        # 创建容器化的 ExecutionContext
        container_context = ExecutionContext(
            phase=AgentPhase.EXECUTE,
            agent_depth=1,
            action_history=list(parent_context.action_history) if parent_context.action_history else [],
            todos=[],
            loaded_skills=list(parent_context.loaded_skills) if parent_context.loaded_skills else [],
            loaded_references=list(parent_context.loaded_references) if parent_context.loaded_references else [],
            skill_contents=dict(parent_context.skill_contents) if parent_context.skill_contents else {},
            reference_contents=dict(parent_context.reference_contents) if parent_context.reference_contents else {},
        )

        # 创建 SubagentExecutor，传入容器化的组件和技能过滤参数
        self._subagent_executor = SubagentExecutor(
            parent_context=container_context,
            llm_client=self.llm_client,
            opencli_client=self.opencli_client,
            tool_executor=self.tool_executor,
            skill_manager=self.skill_manager,
            interaction_logger=interaction_logger,
            inherited_skills=inherited_skills,
            excluded_skills=excluded_skills,
        )

        logger.debug(f"[AgentContainer {self.container_id}] SubagentExecutor 初始化完成")

    async def start(self) -> bool:
        """启动容器并等待就绪

        启动 OpenCLI daemon 进程，并等待其就绪。

        Returns:
            True 如果启动成功

        Raises:
            ContainerStartupError: daemon 启动失败或超时
        """
        if self.status == ContainerStatus.RUNNING:
            logger.warning(f"[AgentContainer {self.container_id}] 容器已在运行中")
            return True

        if self.status == ContainerStatus.DESTROYED:
            raise ContainerStateError(
                "容器已销毁，无法启动",
                container_id=self.container_id,
                agent_id=self.container_id,
                fatal=True,
            )

        try:
            if not await self._start_daemon():
                raise ContainerStartupError(
                    "daemon 进程启动失败",
                    container_id=self.container_id,
                    agent_id=self.container_id,
                    fatal=True,
                )

            if not await self._wait_daemon_ready():
                raise ContainerStartupError(
                    f"daemon 启动超时 ({self.config.daemon_startup_timeout}s)",
                    container_id=self.container_id,
                    agent_id=self.container_id,
                    fatal=True,
                )

            self._init_components()

            self.status = ContainerStatus.RUNNING
            logger.info(f"[AgentContainer {self.container_id}] 启动成功")
            return True

        except (ContainerStartupError, ContainerStateError):
            self.status = ContainerStatus.ERROR
            raise
        except Exception as e:
            self.status = ContainerStatus.ERROR
            raise ContainerStartupError(
                f"容器启动失败: {e}",
                container_id=self.container_id,
                agent_id=self.container_id,
                fatal=True,
            ) from e

    async def stop(self) -> None:
        """停止容器并释放资源

        停止 OpenCLI daemon 进程，释放容器资源。
        """
        if self.status == ContainerStatus.STOPPED:
            logger.warning(f"[AgentContainer {self.container_id}] 容器已停止")
            return

        if self.status == ContainerStatus.DESTROYED:
            logger.warning(f"[AgentContainer {self.container_id}] 容器已销毁")
            return

        try:
            # 1. 停止 daemon
            await self._stop_daemon()

            # 2. 关闭 OpenCLI 客户端
            if self.opencli_client:
                await self.opencli_client.close()
                self.opencli_client = None

            # 3. 清理组件引用
            self.tool_executor = None
            self.skill_manager = None
            self.llm_client = None
            self.state = None
            self._subagent_executor = None

            self.status = ContainerStatus.STOPPED
            logger.info(f"[AgentContainer {self.container_id}] 已停止")

        except Exception as e:
            logger.error(f"[AgentContainer {self.container_id}] 停止失败: {e}")
            self.status = ContainerStatus.ERROR

    async def destroy(self) -> None:
        """完全销毁容器

        停止容器并完全清理所有资源，容器将无法再使用。
        """
        await self.stop()
        self.status = ContainerStatus.DESTROYED
        logger.info(f"[AgentContainer {self.container_id}] 已销毁")

    async def execute_task(
        self,
        task: str,
        parent_context: ExecutionContext,
        max_iterations: Optional[int] = None,
        interaction_logger=None,
        inherited_skills: Optional[List[str]] = None,
        excluded_skills: Optional[List[str]] = None,
    ) -> SubagentResult:
        """在容器中执行任务

        使用容器内的独立环境执行指定任务。
        任务执行逻辑委托给 SubagentExecutor。

        Args:
            task: 任务描述
            parent_context: 父 Agent 的执行上下文，用于继承技能和参考信息
            max_iterations: 最大迭代次数
            inherited_skills: 指定继承的技能列表
            excluded_skills: 指定排除的技能列表

        Returns:
            SubagentResult 包含任务执行结果

        Raises:
            ContainerStateError: 容器状态异常
            SubagentExecutionError: 子代理执行失败
        """
        if self.status != ContainerStatus.RUNNING:
            raise ContainerStateError(
                f"容器状态异常: {self.status.value}",
                container_id=self.container_id,
                agent_id=self.container_id,
                fatal=True,
            )

        self._init_subagent_executor(
            parent_context,
            interaction_logger=interaction_logger,
            inherited_skills=inherited_skills,
            excluded_skills=excluded_skills,
        )

        result = await self._subagent_executor.run_subagent(
            agent_id=self.container_id,
            assigned_task=task,
            whiteboard=None,
            max_iterations=max_iterations or 5,
        )

        logger.info(f"[AgentContainer {self.container_id}] 任务执行完成，状态: {result.status}")
        return result

    async def _start_daemon(self) -> bool:
        """启动 OpenCLI daemon 进程

        Returns:
            True 如果启动成功，False 如果启动失败
        """
        opencli_path = find_opencli_path()
        if not opencli_path:
            logger.error(f"[AgentContainer {self.container_id}] 未找到 opencli 命令")
            return False

        try:
            # 使用指定端口启动 daemon
            # 注意：OpenCLI daemon 需要支持 --port 参数
            self._daemon_process = subprocess.Popen(
                [opencli_path, "daemon", "--port", str(self.port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            logger.info(f"[AgentContainer {self.container_id}] daemon 进程已启动，PID: {self._daemon_process.pid}")
            return True

        except Exception as e:
            logger.error(f"[AgentContainer {self.container_id}] 启动 daemon 失败: {e}")
            return False

    async def _wait_daemon_ready(self) -> bool:
        """等待 daemon 就绪

        Returns:
            True 如果 daemon 就绪，False 如果超时
        """
        timeout = self.config.daemon_startup_timeout
        start_time = time.time()

        # 创建临时客户端用于检查状态
        temp_client = OpenCLIClient(port=self.port)

        while time.time() - start_time < timeout:
            try:
                status = await temp_client.status()
                if status and status.ok:
                    logger.info(f"[AgentContainer {self.container_id}] daemon 已就绪")
                    return True
            except Exception:
                logger.debug(f"[AgentContainer {self.container_id}] daemon status check failed, retrying...")

            await asyncio.sleep(0.5)

        logger.error(f"[AgentContainer {self.container_id}] daemon 启动超时")
        return False

    async def _stop_daemon(self) -> None:
        """停止 daemon 进程"""
        if self._daemon_process:
            try:
                self._daemon_process.terminate()
                self._daemon_process.wait(timeout=5)
                logger.info(f"[AgentContainer {self.container_id}] daemon 进程已停止")
            except subprocess.TimeoutExpired:
                self._daemon_process.kill()
                logger.warning(f"[AgentContainer {self.container_id}] daemon 进程被强制终止")
            except Exception as e:
                logger.error(f"[AgentContainer {self.container_id}] 停止 daemon 失败: {e}")
            finally:
                self._daemon_process = None

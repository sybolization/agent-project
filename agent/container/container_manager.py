"""ContainerManager - 容器管理器

负责管理 AgentContainer 实例的生命周期，包括创建、复用、释放和销毁。
支持容器池化管理，提供端口分配和资源追踪功能。
"""

import asyncio
import logging
import uuid
from typing import Dict, List, Optional, Set

from .agent_container import AgentContainer
from .container_config import ContainerConfig
from .container_status import ContainerStatus

logger = logging.getLogger(__name__)


class ContainerManager:
    """容器管理器

    负责管理 AgentContainer 实例的生命周期，包括：
    - 容器的创建和销毁
    - 端口资源的分配和释放
    - 容器复用策略
    - 并发访问控制

    Attributes:
        config: 容器配置
        _active_containers: 活跃容器字典，key 为 container_id
        _available_ports: 可用端口集合
        _lock: 异步锁，用于并发控制
    """

    def __init__(self, config: Optional[ContainerConfig] = None):
        """初始化容器管理器

        Args:
            config: 容器配置，如果为 None 则使用默认配置
        """
        self.config = config or ContainerConfig()
        self._active_containers: Dict[str, AgentContainer] = {}
        self._available_ports: Set[int] = set()
        self._lock = asyncio.Lock()

        # 初始化可用端口池
        self._init_port_pool()

        logger.info(
            f"[ContainerManager] 初始化完成，"
            f"最大容器数: {self.config.max_containers}，"
            f"基础端口: {self.config.base_port}，"
            f"容器复用: {self.config.container_reuse}"
        )

    def _init_port_pool(self) -> None:
        """初始化可用端口池

        根据配置的 max_containers 和 base_port 初始化端口池。
        """
        for i in range(self.config.max_containers):
            port = self.config.get_port_for_container(i)
            self._available_ports.add(port)

        logger.debug(
            f"[ContainerManager] 端口池初始化完成，"
            f"可用端口: {sorted(self._available_ports)}"
        )

    def _get_available_port(self) -> int:
        """获取可用端口

        从端口池中获取一个可用端口。

        Returns:
            可用的端口号

        Raises:
            RuntimeError: 当没有可用端口时抛出
        """
        if not self._available_ports:
            raise RuntimeError("没有可用的端口，无法创建新容器")

        # 从集合中取出一个端口
        port = self._available_ports.pop()
        logger.debug(f"[ContainerManager] 分配端口: {port}")
        return port

    def _release_port(self, port: int) -> None:
        """释放端口

        将端口归还到端口池。

        Args:
            port: 要释放的端口号
        """
        self._available_ports.add(port)
        logger.debug(f"[ContainerManager] 释放端口: {port}")

    def _generate_container_id(self) -> str:
        """生成唯一的容器 ID

        Returns:
            唯一的容器标识符
        """
        return f"container-{uuid.uuid4().hex[:8]}"

    async def create_container(self) -> AgentContainer:
        """创建新容器

        创建并启动一个新的 AgentContainer 实例。
        如果启用了容器复用且有空闲容器，则返回空闲容器。

        Returns:
            已启动的 AgentContainer 实例

        Raises:
            RuntimeError: 当无法创建新容器时抛出
        """
        async with self._lock:
            # 检查是否可以复用容器
            if self.config.container_reuse:
                idle_container = self._find_idle_container()
                if idle_container:
                    logger.info(
                        f"[ContainerManager] 复用空闲容器: {idle_container.container_id}"
                    )
                    return idle_container

            # 检查是否达到最大容器数
            if len(self._active_containers) >= self.config.max_containers:
                raise RuntimeError(
                    f"已达到最大容器数限制 ({self.config.max_containers})，"
                    "无法创建新容器"
                )

            # 获取可用端口
            port = self._get_available_port()

            # 生成容器 ID
            container_id = self._generate_container_id()

            # 创建容器实例
            container = AgentContainer(
                container_id=container_id,
                port=port,
                config=self.config,
            )

            # 启动容器
            success = await container.start()
            if not success:
                # 启动失败，归还端口
                self._release_port(port)
                raise RuntimeError(f"容器启动失败: {container_id}")

            # 添加到活跃容器列表
            self._active_containers[container_id] = container

            logger.info(
                f"[ContainerManager] 容器创建成功: {container_id}，"
                f"端口: {port}，"
                f"当前活跃容器数: {len(self._active_containers)}"
            )

            return container

    def _find_idle_container(self) -> Optional[AgentContainer]:
        """查找空闲容器

        在活跃容器中查找状态为 RUNNING 且当前未执行任务的容器。

        Returns:
            空闲的 AgentContainer 实例，如果没有则返回 None
        """
        for container in self._active_containers.values():
            # 检查容器是否处于运行状态且没有正在执行任务
            if container.status == ContainerStatus.RUNNING:
                # 可以添加更多判断逻辑，例如检查是否有正在执行的任务
                # 目前简单返回第一个运行中的容器
                return container
        return None

    async def release_container(self, container: AgentContainer) -> None:
        """释放容器资源

        根据配置决定是停止容器还是保留容器以供复用。

        Args:
            container: 要释放的容器实例
        """
        async with self._lock:
            container_id = container.container_id

            # 检查容器是否属于此管理器
            if container_id not in self._active_containers:
                logger.warning(
                    f"[ContainerManager] 容器 {container_id} 不属于此管理器"
                )
                return

            if self.config.container_reuse:
                # 容器复用模式：只重置容器状态，不停止
                logger.info(
                    f"[ContainerManager] 容器 {container_id} 已释放（复用模式）"
                )
                # 可以在这里重置容器状态，例如清理临时数据
            else:
                # 非复用模式：停止并移除容器
                await container.stop()
                self._release_port(container.port)
                del self._active_containers[container_id]

                logger.info(
                    f"[ContainerManager] 容器 {container_id} 已停止并移除"
                )

    async def get_running_containers(self) -> List[AgentContainer]:
        """获取运行中的容器列表

        Returns:
            所有处于 RUNNING 状态的容器列表
        """
        async with self._lock:
            running_containers = [
                container
                for container in self._active_containers.values()
                if container.status == ContainerStatus.RUNNING
            ]
            return running_containers

    async def shutdown_all(self) -> None:
        """关闭所有容器

        停止并销毁所有活跃容器，释放所有资源。
        """
        async with self._lock:
            logger.info(
                f"[ContainerManager] 开始关闭所有容器，"
                f"当前活跃容器数: {len(self._active_containers)}"
            )

            # 收集所有容器 ID
            container_ids = list(self._active_containers.keys())

            for container_id in container_ids:
                container = self._active_containers.get(container_id)
                if container:
                    try:
                        await container.destroy()
                        self._release_port(container.port)
                    except Exception as e:
                        logger.error(
                            f"[ContainerManager] 销毁容器 {container_id} 失败: {e}"
                        )

            # 清空活跃容器列表
            self._active_containers.clear()

            logger.info("[ContainerManager] 所有容器已关闭")

    async def get_container_by_id(self, container_id: str) -> Optional[AgentContainer]:
        """根据 ID 获取容器

        Args:
            container_id: 容器 ID

        Returns:
            AgentContainer 实例，如果不存在则返回 None
        """
        async with self._lock:
            return self._active_containers.get(container_id)

    async def get_container_count(self) -> int:
        """获取当前活跃容器数量

        Returns:
            活跃容器数量
        """
        async with self._lock:
            return len(self._active_containers)

    async def get_available_port_count(self) -> int:
        """获取可用端口数量

        Returns:
            可用端口数量
        """
        async with self._lock:
            return len(self._available_ports)

    async def __aenter__(self) -> "ContainerManager":
        """异步上下文管理器入口

        Returns:
            ContainerManager 实例
        """
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """异步上下文管理器退出

        确保所有容器被正确关闭。
        """
        await self.shutdown_all()

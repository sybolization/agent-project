"""Container Config - 容器配置数据类"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ContainerConfig:
    """容器配置数据类

    管理容器创建和运行时的配置参数。

    Attributes:
        max_containers: 最大容器数量，默认为 5
        base_port: 基础端口号，默认为 19825
        daemon_startup_timeout: 守护进程启动超时时间（秒），默认为 30.0
        container_reuse: 是否复用容器，默认为 True
        browser_lock_timeout: 浏览器锁等待超时时间（秒），默认为 120.0
        browser_lock_enabled: 是否启用浏览器锁，默认为 True
    """
    max_containers: int = 5
    base_port: int = 19825
    daemon_startup_timeout: float = 30.0
    container_reuse: bool = True

    # 浏览器锁相关配置
    browser_lock_timeout: float = 120.0
    browser_lock_enabled: bool = True

    def __post_init__(self):
        """初始化后验证配置"""
        self.validate()

    def validate(self) -> None:
        """验证配置参数的有效性

        Raises:
            ValueError: 当配置参数无效时抛出
        """
        # 容器配置验证
        if self.max_containers < 1:
            raise ValueError(
                f"max_containers 必须大于等于 1，当前值: {self.max_containers}"
            )

        if self.max_containers > 100:
            raise ValueError(
                f"max_containers 不能超过 100，当前值: {self.max_containers}"
            )

        if self.base_port < 1024 or self.base_port > 65535:
            raise ValueError(
                f"base_port 必须在 1024-65535 范围内，当前值: {self.base_port}"
            )

        if self.daemon_startup_timeout <= 0:
            raise ValueError(
                f"daemon_startup_timeout 必须大于 0，当前值: {self.daemon_startup_timeout}"
            )

        if self.daemon_startup_timeout > 300:
            raise ValueError(
                f"daemon_startup_timeout 不能超过 300 秒，当前值: {self.daemon_startup_timeout}"
            )

        # 浏览器锁配置验证
        if self.browser_lock_timeout <= 0:
            raise ValueError(
                f"browser_lock_timeout 必须大于 0，当前值: {self.browser_lock_timeout}"
            )

    def get_port_for_container(self, container_index: int) -> int:
        """根据容器索引获取端口号

        Args:
            container_index: 容器索引（从 0 开始）

        Returns:
            分配给该容器的端口号

        Raises:
            ValueError: 当容器索引超出范围时抛出
        """
        if container_index < 0 or container_index >= self.max_containers:
            raise ValueError(
                f"container_index 必须在 0-{self.max_containers - 1} 范围内，"
                f"当前值: {container_index}"
            )

        port = self.base_port + container_index
        if port > 65535:
            raise ValueError(
                f"计算出的端口号 {port} 超出有效范围（最大 65535）"
            )

        return port

    def to_dict(self) -> dict:
        """将配置序列化为字典

        Returns:
            包含所有配置参数的字典
        """
        return {
            "max_containers": self.max_containers,
            "base_port": self.base_port,
            "daemon_startup_timeout": self.daemon_startup_timeout,
            "container_reuse": self.container_reuse,
            "browser_lock_timeout": self.browser_lock_timeout,
            "browser_lock_enabled": self.browser_lock_enabled,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ContainerConfig":
        """从字典恢复配置

        Args:
            data: 序列化的配置数据

        Returns:
            ContainerConfig 实例
        """
        return cls(
            max_containers=data.get("max_containers", 5),
            base_port=data.get("base_port", 19825),
            daemon_startup_timeout=data.get("daemon_startup_timeout", 30.0),
            container_reuse=data.get("container_reuse", True),
            browser_lock_timeout=data.get("browser_lock_timeout", 120.0),
            browser_lock_enabled=data.get("browser_lock_enabled", True),
        )

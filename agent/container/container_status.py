"""Container Status - 容器状态枚举定义"""

from enum import Enum


class ContainerStatus(str, Enum):
    """容器状态枚举

    状态说明：
    - CREATED: 容器已创建但未启动
    - RUNNING: 容器正在运行
    - STOPPED: 容器已停止
    - DESTROYED: 容器已销毁
    - ERROR: 容器处于错误状态
    """
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    DESTROYED = "DESTROYED"
    ERROR = "ERROR"

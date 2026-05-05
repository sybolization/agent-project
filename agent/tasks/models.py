"""Task Models - 任务管理相关的数据模型"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    """任务状态枚举
    
    状态说明：
    - PENDING: 待处理，任务已创建但尚未开始
    - IN_PROGRESS: 进行中，任务正在执行
    - COMPLETED: 已完成，任务成功完成
    - FAILED: 失败，任务执行失败
    - CANCELLED: 已取消，任务被取消
    - BLOCKED: 阻塞中，任务被其他任务阻塞
    """
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


@dataclass
class TaskRecord:
    """任务记录数据类
    
    用于存储和管理单个任务的完整信息，包括任务状态、依赖关系、元数据等。
    
    Attributes:
        id: 任务唯一标识符
        subject: 任务主题/标题
        description: 任务详细描述
        status: 任务当前状态
        blocked_by: 阻塞此任务的任务ID列表
        blocks: 被此任务阻塞的任务ID列表
        owner: 任务负责人
        created_at: 任务创建时间
        updated_at: 任务最后更新时间
        parent_id: 父任务ID，用于任务层级关系
        metadata: 任务元数据，存储额外信息
    """
    id: int
    subject: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    blocked_by: list[int] = field(default_factory=list)
    blocks: list[int] = field(default_factory=list)
    owner: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    parent_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """将TaskRecord转换为字典
        
        用于序列化和持久化任务记录。
        
        Returns:
            包含任务所有属性的字典
        """
        return {
            "id": self.id,
            "subject": self.subject,
            "description": self.description,
            "status": self.status.value,
            "blocked_by": self.blocked_by,
            "blocks": self.blocks,
            "owner": self.owner,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "parent_id": self.parent_id,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskRecord":
        """从字典创建TaskRecord实例
        
        用于反序列化和恢复任务记录。
        
        Args:
            data: 包含任务属性的字典
            
        Returns:
            TaskRecord实例
        """
        # 处理时间字段
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.now()
        
        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        elif updated_at is None:
            updated_at = datetime.now()
        
        # 处理状态字段
        status_value = data.get("status", "pending")
        if isinstance(status_value, str):
            status = TaskStatus(status_value)
        else:
            status = status_value
        
        return cls(
            id=data["id"],
            subject=data["subject"],
            description=data.get("description", ""),
            status=status,
            blocked_by=data.get("blocked_by", []),
            blocks=data.get("blocks", []),
            owner=data.get("owner", ""),
            created_at=created_at,
            updated_at=updated_at,
            parent_id=data.get("parent_id"),
            metadata=data.get("metadata", {}),
        )

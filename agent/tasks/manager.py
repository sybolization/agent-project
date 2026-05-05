"""
任务管理器

提供任务的高级管理操作，包括创建、依赖管理、状态更新等
"""
from datetime import datetime
from typing import TYPE_CHECKING

from .models import TaskRecord, TaskStatus

if TYPE_CHECKING:
    from ..state import AgentState


class TaskManager:
    """
    任务管理器

    提供任务的创建、依赖管理、状态更新等高级操作
    使用AgentState中的tasks列表存储任务
    """

    def __init__(self, state: "AgentState"):
        """
        初始化TaskManager

        Args:
            state: AgentState实例，用于存储任务数据
        """
        self._state = state

    def create_task(
        self,
        subject: str,
        description: str = "",
        owner: str = "",
        parent_id: int | None = None,
        metadata: dict | None = None
    ) -> TaskRecord:
        """
        创建新任务并返回任务记录

        Args:
            subject: 任务主题/标题
            description: 任务详细描述
            owner: 任务负责人
            parent_id: 父任务ID
            metadata: 任务元数据

        Returns:
            TaskRecord: 创建的任务记录
        """
        task_id = self._state.get_next_task_id()
        task = TaskRecord(
            id=task_id,
            subject=subject,
            description=description,
            status=TaskStatus.PENDING,
            owner=owner,
            parent_id=parent_id,
            metadata=metadata or {},
        )
        self._state.add_task(task)
        return task

    def add_dependency(self, task_id: int, blocks_id: int) -> bool:
        """
        添加依赖关系（双向维护）

        任务 blocks_id 依赖任务 task_id
        - task_id 的 blocks 列表添加 blocks_id
        - blocks_id 的 blocked_by 列表添加 task_id

        Args:
            task_id: 被依赖的任务ID
            blocks_id: 依赖的任务ID

        Returns:
            bool: 是否添加成功
        """
        task = self._state.get_task_by_id(task_id)
        blocked = self._state.get_task_by_id(blocks_id)

        if not task or not blocked:
            return False

        if blocks_id not in task.blocks:
            task.blocks.append(blocks_id)
            self._state.update_task(task)

        if task_id not in blocked.blocked_by:
            blocked.blocked_by.append(task_id)
            self._state.update_task(blocked)

        return True

    def complete_task(self, task_id: int) -> bool:
        """
        完成任务并自动解锁后续任务

        1. 将任务状态设为 COMPLETED
        2. 从所有被此任务阻塞的任务的 blocked_by 中移除此任务ID

        Args:
            task_id: 要完成的任务ID

        Returns:
            bool: 是否完成成功
        """
        task = self._state.get_task_by_id(task_id)

        if not task:
            return False

        task.status = TaskStatus.COMPLETED
        task.updated_at = datetime.now()
        self._state.update_task(task)

        for blocked_id in task.blocks:
            blocked_task = self._state.get_task_by_id(blocked_id)
            if blocked_task and task_id in blocked_task.blocked_by:
                blocked_task.blocked_by.remove(task_id)
                self._state.update_task(blocked_task)

        return True

    def is_ready(self, task: TaskRecord) -> bool:
        """
        判断任务是否可以开始

        Ready Rule: status=PENDING 且 blocked_by 为空

        Args:
            task: 任务记录

        Returns:
            bool: 任务是否可以开始
        """
        return task.status == TaskStatus.PENDING and len(task.blocked_by) == 0

    def assign_task(self, task_id: int, owner: str) -> bool:
        """
        分配任务给指定agent

        Args:
            task_id: 任务ID
            owner: 执行者名称

        Returns:
            bool: 是否分配成功
        """
        task = self._state.get_task_by_id(task_id)

        if not task:
            return False

        task.owner = owner
        task.updated_at = datetime.now()
        self._state.update_task(task)
        return True

    def get_task(self, task_id: int) -> TaskRecord | None:
        """
        获取单个任务

        Args:
            task_id: 任务ID

        Returns:
            TaskRecord | None: 任务记录，不存在则返回 None
        """
        return self._state.get_task_by_id(task_id)

    def list_tasks(self, status: TaskStatus | None = None, owner: str | None = None) -> list[TaskRecord]:
        """
        列出任务，支持按状态和执行者筛选

        Args:
            status: 任务状态筛选条件
            owner: 执行者筛选条件

        Returns:
            list[TaskRecord]: 任务列表
        """
        tasks = self._state.tasks

        if status:
            return [t for t in tasks if t.status == status]
        elif owner:
            return [t for t in tasks if t.owner == owner]
        else:
            return tasks

    def get_ready_tasks(self) -> list[TaskRecord]:
        """
        获取所有可执行的任务

        Returns:
            list[TaskRecord]: 可执行的任务列表
        """
        return [t for t in self._state.tasks if self.is_ready(t)]

    def update_status(self, task_id: int, status: TaskStatus) -> bool:
        """
        更新任务状态

        Args:
            task_id: 任务ID
            status: 新状态

        Returns:
            bool: 是否更新成功
        """
        task = self._state.get_task_by_id(task_id)

        if not task:
            return False

        task.status = status
        task.updated_at = datetime.now()
        self._state.update_task(task)
        return True

    def delete_task(self, task_id: int) -> bool:
        """
        删除任务

        Args:
            task_id: 任务ID

        Returns:
            bool: 是否删除成功
        """
        return self._state.remove_task(task_id)

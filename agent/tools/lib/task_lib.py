"""任务执行器 - 处理任务管理相关工具调用"""

import logging

from ...tasks import TaskManager, TaskStatus

logger = logging.getLogger(__name__)


class TaskExecutor:
    """任务执行器

    负责任务管理系统的工具执行：
    - 创建任务
    - 列出任务
    - 更新任务状态
    - 添加任务依赖
    - 分配任务
    """

    def __init__(self, task_manager: TaskManager | None):
        self.task_manager = task_manager

    def execute_create_task(self, args: dict) -> dict:
        """执行 create_task 工具"""
        # 检查task_manager是否可用
        if not self.task_manager:
            return {
                "type": "error",
                "message": "Task management not available. AgentState is required."
            }

        subject = args.get("subject", "")
        description = args.get("description", "")
        owner = args.get("owner", "")
        parent_id = args.get("parent_id")

        if not subject:
            return {"type": "error", "message": "subject is required"}

        task = self.task_manager.create_task(
            subject=subject,
            description=description,
            owner=owner,
            parent_id=parent_id,
        )

        return {
            "type": "task_created",
            "task_id": task.id,
            "subject": task.subject,
            "status": task.status.value,
            "message": f"Task created: ID={task.id}, Subject={task.subject}"
        }

    def execute_list_tasks(self, args: dict) -> dict:
        """执行 list_tasks 工具"""
        # 检查task_manager是否可用
        if not self.task_manager:
            return {
                "type": "error",
                "message": "Task management not available. AgentState is required."
            }

        status_str = args.get("status")
        owner = args.get("owner")

        status = None
        if status_str:
            try:
                status = TaskStatus(status_str)
            except ValueError:
                return {"type": "error", "message": f"Invalid status: {status_str}"}

        tasks = self.task_manager.list_tasks(status=status, owner=owner)

        task_list = [
            {
                "id": t.id,
                "subject": t.subject,
                "status": t.status.value,
                "owner": t.owner,
                "blocked_by": t.blocked_by,
                "blocks": t.blocks,
            }
            for t in tasks
        ]

        return {
            "type": "task_list",
            "tasks": task_list,
            "count": len(task_list),
        }

    def execute_update_task_status(self, args: dict) -> dict:
        """执行 update_task_status 工具"""
        # 检查task_manager是否可用
        if not self.task_manager:
            return {
                "type": "error",
                "message": "Task management not available. AgentState is required."
            }

        task_id = args.get("task_id")
        status_str = args.get("status")

        if task_id is None or status_str is None:
            return {"type": "error", "message": "task_id and status are required"}

        try:
            status = TaskStatus(status_str)
        except ValueError:
            return {"type": "error", "message": f"Invalid status: {status_str}"}

        if status == TaskStatus.COMPLETED:
            success = self.task_manager.complete_task(task_id)
        else:
            success = self.task_manager.update_status(task_id, status)

        if success:
            return {
                "type": "task_updated",
                "task_id": task_id,
                "status": status_str,
                "message": f"Task {task_id} status updated to {status_str}"
            }
        else:
            return {"type": "error", "message": f"Task {task_id} not found"}

    def execute_add_task_dependency(self, args: dict) -> dict:
        """执行 add_task_dependency 工具"""
        # 检查task_manager是否可用
        if not self.task_manager:
            return {
                "type": "error",
                "message": "Task management not available. AgentState is required."
            }

        task_id = args.get("task_id")
        depends_on_task_id = args.get("depends_on_task_id")

        if task_id is None or depends_on_task_id is None:
            return {"type": "error", "message": "task_id and depends_on_task_id are required"}

        success = self.task_manager.add_dependency(task_id, depends_on_task_id)

        if success:
            return {
                "type": "dependency_added",
                "task_id": task_id,
                "depends_on_task_id": depends_on_task_id,
                "message": f"Task {depends_on_task_id} now depends on task {task_id}"
            }
        else:
            return {"type": "error", "message": "Failed to add dependency, task not found"}

    def execute_assign_task(self, args: dict) -> dict:
        """执行 assign_task 工具"""
        # 检查task_manager是否可用
        if not self.task_manager:
            return {
                "type": "error",
                "message": "Task management not available. AgentState is required."
            }

        task_id = args.get("task_id")
        owner = args.get("owner")

        if task_id is None or not owner:
            return {"type": "error", "message": "task_id and owner are required"}

        success = self.task_manager.assign_task(task_id, owner)

        if success:
            return {
                "type": "task_assigned",
                "task_id": task_id,
                "owner": owner,
                "message": f"Task {task_id} assigned to {owner}"
            }
        else:
            return {"type": "error", "message": f"Task {task_id} not found"}

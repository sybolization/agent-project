"""TODO追踪器 - 管理Agent执行过程中的任务进度"""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class TodoTracker:
    """TODO任务追踪器
    
    防止Agent过早结束任务，确保所有子任务都被执行。
    """
    items: list[dict[str, Any]] = field(default_factory=list)
    
    def set_items(self, todos: list[dict[str, Any]]) -> None:
        """设置TODO列表"""
        self.items = todos
    
    def set(self, items: list[dict[str, Any]], task_id: int | None = None) -> None:
        """设置TODO列表
        
        Args:
            items: TODO项列表
            task_id: 关联的任务ID（可选）
        """
        if task_id is not None:
            for item in items:
                item["task_id"] = task_id
        self.items = items
    
    def get_by_id(self, todo_id: str) -> Optional[dict[str, Any]]:
        """通过ID获取TODO项"""
        for todo in self.items:
            if todo.get("id") == todo_id:
                return todo
        return None
    
    def update_status(self, todo_id: str, status: str) -> bool:
        """更新TODO状态
        
        Args:
            todo_id: TODO ID
            status: 新状态 (pending/in_progress/completed)
            
        Returns:
            是否成功更新
        """
        for todo in self.items:
            if todo.get("id") == todo_id:
                todo["status"] = status
                return True
        return False
    
    def get_incomplete(self) -> list[dict[str, Any]]:
        """获取所有未完成的TODO项"""
        return [
            todo for todo in self.items
            if todo.get("status") in ("pending", "in_progress")
        ]
    
    def has_incomplete(self) -> bool:
        """检查是否有未完成的TODO"""
        return len(self.get_incomplete()) > 0
    
    def get_progress(self) -> dict[str, Any]:
        """获取TODO进度信息"""
        total = len(self.items)
        completed = sum(1 for t in self.items if t.get("status") == "completed")
        in_progress = sum(1 for t in self.items if t.get("status") == "in_progress")
        pending = sum(1 for t in self.items if t.get("status") == "pending")
        
        return {
            "total": total,
            "completed": completed,
            "in_progress": in_progress,
            "pending": pending,
            "progress_percentage": (completed / total * 100) if total > 0 else 100
        }
    
    def clear(self) -> None:
        """清空TODO列表"""
        self.items.clear()
    
    def get_todos_by_task(self, task_id: int) -> list[dict[str, Any]]:
        """获取关联到指定任务的所有Todo
        
        Args:
            task_id: 任务ID
            
        Returns:
            关联的Todo列表
        """
        return [todo for todo in self.items if todo.get("task_id") == task_id]
    
    def are_all_todos_completed(self, task_id: int) -> bool:
        """检查指定任务的所有Todo是否都已完成
        
        Args:
            task_id: 任务ID
            
        Returns:
            是否全部完成
        """
        task_todos = self.get_todos_by_task(task_id)
        if not task_todos:
            return True
        return all(todo.get("status") == "completed" for todo in task_todos)

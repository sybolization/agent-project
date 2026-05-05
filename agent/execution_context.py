"""ExecutionContext - Agent执行上下文数据类

用于解耦ToolExecutor与AgentLoop，提供轻量级的执行上下文传递。
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from .state import AgentPhase


@dataclass
class ExecutionContext:
    """Agent执行上下文

    封装执行过程中需要的上下文信息，避免ToolExecutor直接依赖AgentLoop。
    """

    # 当前执行阶段
    phase: AgentPhase = AgentPhase.COLLECT

    # Agent深度（用于Subagent）
    agent_depth: int = 0

    # 行动历史（用于去重检查）
    action_history: list[dict[str, Any]] = field(default_factory=list)

    # TODO列表
    todos: list[dict[str, Any]] = field(default_factory=list)

    # Subagent TODO列表
    subagent_todos: list[dict[str, Any]] = field(default_factory=list)

    # 已加载技能列表
    loaded_skills: list[str] = field(default_factory=list)

    # 已加载参考文档列表
    loaded_references: list[tuple[str, str]] = field(default_factory=list)

    # 技能内容字典
    skill_contents: dict[str, str] = field(default_factory=dict)

    # 参考文档内容字典
    reference_contents: dict[str, str] = field(default_factory=dict)

    # Subagent最大迭代次数（用户控制参数）
    # 如果为None，则使用config.py中的SUBAGENT_MAX_ITERATIONS
    subagent_max_iterations: Optional[int] = None

    def find_duplicate_action(self, command: str) -> Optional[dict[str, Any]]:
        """查找重复操作

        在行动历史中查找是否已执行过相同的命令。

        Args:
            command: 要检查的命令字符串

        Returns:
            如果找到重复操作，返回该操作记录；否则返回None
        """
        for action in reversed(self.action_history):
            if action.get("tool_name") == "opencli":
                args = action.get("arguments", {})
                if args.get("command", "") == command:
                    return action
        return None

    def get_todo_by_id(self, todo_id: str) -> Optional[dict[str, Any]]:
        """根据ID获取TODO项

        Args:
            todo_id: TODO项的唯一标识符

        Returns:
            如果找到，返回TODO项字典；否则返回None
        """
        for todo in self.todos:
            if todo.get("id") == todo_id:
                return todo
        return None

    def has_incomplete_todos(self) -> bool:
        """检查是否有未完成的TODO

        Returns:
            如果存在未完成的TODO，返回True；否则返回False
        """
        for todo in self.todos:
            if todo.get("status") != "completed":
                return True
        return False

    def get_todo_progress(self) -> dict[str, Any]:
        """获取TODO进度统计

        Returns:
            包含总数、已完成数、进行中数、待处理数和完成百分比的字典
        """
        total = len(self.todos)
        completed = sum(1 for todo in self.todos if todo.get("status") == "completed")
        in_progress = sum(1 for todo in self.todos if todo.get("status") == "in_progress")
        pending = sum(1 for todo in self.todos if todo.get("status") == "pending")

        return {
            "total": total,
            "completed": completed,
            "in_progress": in_progress,
            "pending": pending,
            "progress_percentage": (completed / total * 100) if total > 0 else 0,
        }

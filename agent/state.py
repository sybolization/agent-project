"""Agent State - 管理Agent执行状态的数据类"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from .session.tracking import TodoTracker
from .tasks.models import TaskRecord, TaskStatus

if TYPE_CHECKING:
    from .whiteboard import Whiteboard

MAX_ACTION_HISTORY = 50


class AgentPhase(str, Enum):
    """Agent执行阶段
    
    阶段说明：
    - DEFAULT: 初始默认阶段，用于Agent初始化和状态重置
    - COLLECT: 信息收集阶段，收集必要的上下文和资源
    - PLAN: 规划阶段，制定执行计划
    - EXECUTE: 执行阶段，按计划执行具体任务
    - REPORT: 报告阶段，生成最终结果报告
    """
    DEFAULT = "DEFAULT"
    COLLECT = "COLLECT"
    PLAN = "PLAN"
    EXECUTE = "EXECUTE"
    REPORT = "REPORT"


@dataclass
class AgentState:
    """Agent执行状态管理
    
    管理Agent在各个阶段（DEFAULT, COLLECT, PLAN, EXECUTE, REPORT）的状态转换和数据存储。
    
    状态转换流程：
    DEFAULT -> COLLECT -> PLAN -> EXECUTE -> REPORT
    
    Attributes:
        mode: Agent执行模式标识，默认为 "three_phase"（三阶段模式）
              支持不同的执行模式，如 "three_phase"（三阶段）、"direct"（直接执行）等
    """
    phase: AgentPhase = AgentPhase.COLLECT
    mode: str = "three_phase"  # Agent执行模式标识
    iteration_count: int = 0
    completed_steps: int = 0
    loaded_skills: set[str] = field(default_factory=set)
    loaded_categories: set[str] = field(default_factory=set)
    loaded_references: set[tuple[str, str]] = field(default_factory=set)
    skill_contents: dict[str, str] = field(default_factory=dict)
    category_contents: dict[str, str] = field(default_factory=dict)
    reference_contents: dict[str, str] = field(default_factory=dict)
    
    phase_summaries: dict[str, str] = field(default_factory=dict)
    
    prompt_template: str = "default"
    context_sections: dict[str, str] = field(default_factory=dict)
    last_reasoning: str = ""
    
    todos: TodoTracker = field(default_factory=TodoTracker)
    action_history: list[dict[str, Any]] = field(default_factory=list)

    # Subagent TODO列表（区别于execution_todos）
    subagent_todos: TodoTracker = field(default_factory=TodoTracker)
    
    # Subagent相关属性
    agent_depth: int = 0
    agent_id: str = "main"
    assigned_task: Optional[str] = None
    whiteboard: Optional["Whiteboard"] = None
    
    # Task相关属性
    current_task_id: int | None = None
    # Task列表（替代独立的SQLite存储）
    tasks: list[TaskRecord] = field(default_factory=list)
    
    @property
    def is_subagent(self) -> bool:
        """判断当前是否为Subagent"""
        return self.agent_depth > 0
    
    def create_subagent_state(self, agent_id: str, assigned_task: str) -> "AgentState":
        """创建Subagent的状态副本
        
        Subagent拥有独立的状态，通过whiteboard访问共享信息。
        
        Args:
            agent_id: Subagent的唯一标识符
            assigned_task: 分配给Subagent的任务描述
            
        Returns:
            新的AgentState实例，depth+1，继承whiteboard引用
        """
        return AgentState(
            agent_depth=self.agent_depth + 1,
            agent_id=agent_id,
            assigned_task=assigned_task,
            whiteboard=self.whiteboard,
        )
    
    def transition_to_plan(self) -> None:
        """从COLLECT阶段转换到PLAN阶段"""
        if self.phase != AgentPhase.COLLECT:
            raise ValueError(f"只能从COLLECT阶段转换到PLAN阶段，当前阶段: {self.phase}")
        self.phase = AgentPhase.PLAN
    
    def transition_to_execute(self) -> None:
        """从PLAN阶段转换到EXECUTE阶段"""
        if self.phase != AgentPhase.PLAN:
            raise ValueError(f"只能从PLAN阶段转换到EXECUTE阶段，当前阶段: {self.phase}")
        self.phase = AgentPhase.EXECUTE
    
    def reset(self) -> None:
        """重置所有状态到初始值
        
        注意：mode 属性不会被重置，保持用户设置的执行模式。
        根据 mode 决定初始阶段：
        - "default": 初始阶段为 DEFAULT
        - "three_phase": 初始阶段为 COLLECT
        """
        # 根据 mode 决定初始阶段
        if self.mode == "default":
            self.phase = AgentPhase.DEFAULT
        else:
            self.phase = AgentPhase.COLLECT
        # mode 不重置，保持用户设置
        
        self.iteration_count = 0
        self.completed_steps = 0
        self.loaded_skills.clear()
        self.loaded_categories.clear()
        self.loaded_references.clear()
        self.skill_contents.clear()
        self.category_contents.clear()
        self.reference_contents.clear()
        self.phase_summaries.clear()
        self.prompt_template = "default"
        self.context_sections.clear()
        self.last_reasoning = ""
        self.todos.clear()
        self.subagent_todos.clear()
        self.action_history.clear()
        self.agent_depth = 0
        self.agent_id = "main"
        self.assigned_task = None
        self.whiteboard = None
    
    def add_skill(self, skill_name: str, content: str) -> None:
        """添加已加载的技能"""
        self.loaded_skills.add(skill_name)
        self.skill_contents[skill_name] = content
    
    def add_reference(self, skill_name: str, reference_name: str, content: str = "") -> None:
        """添加已加载的参考文档"""
        self.loaded_references.add((skill_name, reference_name))
        if content:
            key = f"{skill_name}/{reference_name}"
            self.reference_contents[key] = content
    
    def add_category(self, category_name: str, content: str) -> None:
        """添加已加载的类别"""
        self.loaded_categories.add(category_name)
        self.category_contents[category_name] = content
    
    def increment_iteration(self) -> None:
        """增加迭代计数"""
        self.iteration_count += 1
    
    def increment_completed_steps(self) -> None:
        """增加已完成步骤计数"""
        self.completed_steps += 1
    
    def is_collect_phase(self) -> bool:
        return self.phase == AgentPhase.COLLECT
    
    def is_plan_phase(self) -> bool:
        return self.phase == AgentPhase.PLAN
    
    def is_execute_phase(self) -> bool:
        return self.phase == AgentPhase.EXECUTE
    
    def get_progress(self) -> dict[str, Any]:
        """获取当前进度信息"""
        return {
            "phase": self.phase.value,
            "iteration": self.iteration_count,
            "completed_steps": self.completed_steps,
            "loaded_skills_count": len(self.loaded_skills),
            "loaded_references_count": len(self.loaded_references),
        }
    
    def add_context_section(self, name: str, content: str) -> None:
        """添加或更新上下文Section缓存"""
        self.context_sections[name] = content
    
    def get_context_section(self, name: str) -> Optional[str]:
        """获取缓存的Section内容"""
        return self.context_sections.get(name)
    
    def clear_context_sections(self) -> None:
        """清空所有缓存的Section"""
        self.context_sections.clear()
    
    def clear_skill_contents(self) -> None:
        """清空技能内容（保留技能名称列表）"""
        self.skill_contents.clear()
    
    def clear_reference_contents(self) -> None:
        """清空参考文档内容（保留参考文档名称列表）"""
        self.reference_contents.clear()
    
    def set_phase_summary(self, phase_name: str, summary: str) -> None:
        """设置阶段摘要"""
        self.phase_summaries[phase_name] = summary
    
    def get_phase_summary(self, phase_name: str) -> Optional[str]:
        """获取阶段摘要"""
        return self.phase_summaries.get(phase_name)
    
    # ==================== TODO系统代理方法 ====================
    
    def set_todo_list(self, todos: list[dict[str, Any]]) -> None:
        self.todos.set_items(todos)
    
    def get_todo_by_id(self, todo_id: str) -> Optional[dict[str, Any]]:
        return self.todos.get_by_id(todo_id)
    
    def update_todo_status(self, todo_id: str, status: str) -> bool:
        return self.todos.update_status(todo_id, status)
    
    def get_incomplete_todos(self) -> list[dict[str, Any]]:
        return self.todos.get_incomplete()
    
    def has_incomplete_todos(self) -> bool:
        return self.todos.has_incomplete()
    
    def get_todo_progress(self) -> dict[str, Any]:
        return self.todos.get_progress()
    
    def clear_todo_list(self) -> None:
        self.todos.clear()

    # ==================== Subagent TODO系统方法 ====================

    def has_subagent_todos(self) -> bool:
        """检查是否有 subagent_todos"""
        return len(self.subagent_todos.items) > 0

    def set_subagent_todos(self, todos: list[dict[str, Any]]) -> None:
        """设置 subagent_todos"""
        self.subagent_todos.set_items(todos)

    def clear_subagent_todos(self) -> None:
        """清空 subagent_todos"""
        self.subagent_todos.clear()

    def can_spawn_agents(self) -> bool:
        """检查是否满足启动 subagent 的条件

        Returns:
            True 如果已加载技能或有足够的上下文
        """
        return len(self.loaded_skills) > 0

    def get_spawn_agents_prerequisites(self) -> list[str]:
        """返回缺失的前置条件

        Returns:
            缺失的前置条件列表
        """
        missing = []
        if not self.loaded_skills:
            missing.append("需要加载至少一个 skill（使用 load_skill 或 load_skill_category）")
        return missing

    # ==================== Task系统方法 ====================

    def get_task_by_id(self, task_id: int) -> Optional[TaskRecord]:
        """根据ID获取任务"""
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    def add_task(self, task: TaskRecord) -> None:
        """添加任务到列表"""
        self.tasks.append(task)

    def update_task(self, task: TaskRecord) -> bool:
        """更新任务，返回是否成功"""
        for i, t in enumerate(self.tasks):
            if t.id == task.id:
                self.tasks[i] = task
                return True
        return False

    def get_next_task_id(self) -> int:
        """获取下一个任务ID"""
        if not self.tasks:
            return 1
        return max(t.id for t in self.tasks) + 1

    def remove_task(self, task_id: int) -> bool:
        """删除任务，返回是否成功"""
        for i, t in enumerate(self.tasks):
            if t.id == task_id:
                self.tasks.pop(i)
                return True
        return False

    # ==================== 行动历史方法 ====================

    def add_action(self, tool_name: str, arguments: dict, result_summary: str) -> None:
        self.action_history.append({
            "tool_name": tool_name,
            "arguments": arguments,
            "result_summary": result_summary[:500],
            "timestamp": datetime.now().isoformat(),
        })
        if len(self.action_history) > MAX_ACTION_HISTORY:
            self.action_history = self.action_history[-MAX_ACTION_HISTORY:]

    def get_recent_actions(self, n: int = 10) -> list[dict[str, Any]]:
        return self.action_history[-n:]

    def find_action_by_command(self, command: str) -> Optional[dict[str, Any]]:
        for action in reversed(self.action_history):
            if action.get("tool_name") == "opencli":
                args = action.get("arguments", {})
                if args.get("command", "") == command:
                    return action
        return None
    
    # ==================== 序列化/反序列化方法 ====================
    
    def to_dict(self) -> dict:
        """序列化状态为字典
        
        用于Session恢复和状态持久化
        """
        # 将set转换为list，tuple转换为list以便JSON序列化
        loaded_refs_list = [[s, r] for s, r in self.loaded_references]
        
        return {
            "phase": self.phase.value,
            "mode": self.mode,  # 序列化模式标识
            "iteration_count": self.iteration_count,
            "completed_steps": self.completed_steps,
            "loaded_skills": list(self.loaded_skills),
            "loaded_categories": list(self.loaded_categories),
            "loaded_references": loaded_refs_list,
            "skill_contents": self.skill_contents,
            "category_contents": self.category_contents,
            "reference_contents": self.reference_contents,
            "phase_summaries": self.phase_summaries,
            "todos": {"items": self.todos.items},
            "subagent_todos": {"items": self.subagent_todos.items},
            "action_history": self.action_history[-20:],  # 保留最近20条
            "agent_depth": self.agent_depth,
            "agent_id": self.agent_id,
            "assigned_task": self.assigned_task,
            "current_task_id": self.current_task_id,
            "tasks": [task.to_dict() for task in self.tasks],
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "AgentState":
        """从字典恢复状态
        
        Args:
            data: 序列化的状态数据
            
        Returns:
            恢复的AgentState实例
        """
        # 恢复todos
        todos_data = data.get("todos", {})
        todos = TodoTracker()
        todos.items = todos_data.get("items", [])
        
        # 恢复 subagent_todos
        subagent_todos_data = data.get("subagent_todos", {})
        subagent_todos = TodoTracker()
        subagent_todos.items = subagent_todos_data.get("items", [])
        
        # 恢复tasks
        tasks_data = data.get("tasks", [])
        tasks = [TaskRecord.from_dict(t) for t in tasks_data]
        
        # 恢复loaded_references（从list转换回set of tuples）
        loaded_refs_list = data.get("loaded_references", [])
        loaded_references = {tuple(item) for item in loaded_refs_list}
        
        return cls(
            phase=AgentPhase(data.get("phase", "COLLECT")),
            mode=data.get("mode", "three_phase"),  # 反序列化模式标识
            iteration_count=data.get("iteration_count", 0),
            completed_steps=data.get("completed_steps", 0),
            loaded_skills=set(data.get("loaded_skills", [])),
            loaded_categories=set(data.get("loaded_categories", [])),
            loaded_references=loaded_references,
            skill_contents=data.get("skill_contents", {}),
            category_contents=data.get("category_contents", {}),
            reference_contents=data.get("reference_contents", {}),
            phase_summaries=data.get("phase_summaries", {}),
            prompt_template="recovered",
            context_sections={},
            todos=todos,
            subagent_todos=subagent_todos,
            action_history=data.get("action_history", []),
            agent_depth=data.get("agent_depth", 0),
            agent_id=data.get("agent_id", "main"),
            assigned_task=data.get("assigned_task"),
            current_task_id=data.get("current_task_id"),
            tasks=tasks,
        )

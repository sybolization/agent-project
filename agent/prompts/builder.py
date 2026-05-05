"""提示词构建器 - 分段式动态组装架构"""

import re
from typing import Optional, Dict
from dataclasses import dataclass

from .templates import (
    HEAD_TEMPLATE,
    STATE_TEMPLATE,
    CONTEXT_TEMPLATE,
    TAIL_TEMPLATE,
    format_last_round_section,
    format_todo_section,
    format_skills_section,
    format_skill_contents,
    format_reference_contents,
    format_tool_history,
    format_action_history_for_report,
    get_phase_reminder,
    get_next_action_hint,
    format_task_section,
    format_task_dependency_graph,
)
from .default_templates import (
    DEFAULT_MODE_HEAD_TEMPLATE,
    DEFAULT_MODE_STATE_TEMPLATE,
    DEFAULT_MODE_CONTEXT_TEMPLATE,
    DEFAULT_MODE_TAIL_TEMPLATE,
    format_default_todo_section,
    format_default_skills_section,
    format_default_tool_history,
    get_default_next_action_hint,
    format_category_index,
)
from .rules import RuleManager
from ..skills.manager import SkillManager
from ..state import AgentState, AgentPhase
from ..tools.manager.manager import get_available_tool_names, get_phase_tools_description, get_tool_manager


@dataclass
class TokenBudget:
    """Token预算配置
    
    用于控制各区域的token使用量，避免上下文膨胀。
    """
    head: int = 300
    state: int = 500
    context: int = 2000
    tail: int = 400
    
    def get_total_budget(self) -> int:
        """获取总token预算"""
        return self.head + self.state + self.context + self.tail


class SectionCache:
    """Section级别缓存
    
    用于缓存HEAD区域的静态内容，避免重复构建。
    """
    
    def __init__(self):
        self._cache: dict[str, str] = {}
    
    def get(self, name: str) -> Optional[str]:
        return self._cache.get(name)
    
    def set(self, name: str, content: str) -> None:
        self._cache[name] = content
    
    def clear(self) -> None:
        self._cache.clear()
    
    def has(self, name: str) -> bool:
        return name in self._cache


class PromptBuilder:
    """分段式Prompt构建器
    
    架构说明：
    - HEAD: 静态内容（身份定义、核心规则）- 可缓存
    - STATE: 动态状态快照（阶段、目标、TODO、计划、技能列表）
    - CONTEXT: 按需加载上下文（技能内容、参考文档、工具历史）
    - TAIL: 行动指引（可用工具、阶段提醒、下一步行动）
    
    缓存策略：
    - HEAD区域使用Section缓存
    - STATE、CONTEXT、TAIL动态生成，不缓存
    
    Token预算控制：
    - 通过TokenBudget配置控制各区域token使用量
    - 动态调整skill内容长度，避免上下文膨胀
    """
    
    CACHE_KEY_HEAD = "head_section"
    
    def __init__(
        self,
        skill_manager: SkillManager,
        agent_state: AgentState,
        token_budget: Optional[TokenBudget] = None,
    ):
        self.skill_manager = skill_manager
        self.agent_state = agent_state
        self._section_cache = SectionCache()
        self.token_budget = token_budget or TokenBudget()
        self.rule_manager = RuleManager()
        self.rule_manager.load_builtin_rules()
    
    def build_head(self) -> str:
        """构建HEAD区域（静态内容，可缓存）
        
        Returns:
            HEAD_TEMPLATE内容
        """
        cached = self._section_cache.get(self.CACHE_KEY_HEAD)
        if cached:
            return cached
        
        # 根据 agent_depth 决定是否过滤 spawn_agents 工具
        exclude_tools = None
        if self.agent_state.agent_depth >= 1:
            exclude_tools = ["spawn_agents"]
        
        # 动态注入工具列表
        collect_tools = get_phase_tools_description(AgentPhase.COLLECT, exclude_tools)
        plan_tools = get_phase_tools_description(AgentPhase.PLAN, exclude_tools)
        execute_tools = get_phase_tools_description(AgentPhase.EXECUTE, exclude_tools)
        
        content = HEAD_TEMPLATE.format(
            collect_tools=collect_tools,
            plan_tools=plan_tools,
            execute_tools=execute_tools
        )
        self._section_cache.set(self.CACHE_KEY_HEAD, content)
        return content
    
    def build_default_head(self) -> str:
        """构建DEFAULT阶段的HEAD区域
        
        DEFAULT阶段使用简化的模板，不包含阶段转换逻辑。
        类别列表动态生成，支持测试时禁用特定类别。
        
        Returns:
            DEFAULT_MODE_HEAD_TEMPLATE内容（含动态类别列表）
        """
        disabled_cats = tuple(sorted(self.skill_manager.get_disabled_categories()))
        cache_key = f"default_head_section_{disabled_cats}"
        cached = self._section_cache.get(cache_key)
        if cached:
            return cached
        
        category_index = format_category_index(self.skill_manager)
        content = DEFAULT_MODE_HEAD_TEMPLATE.format(category_index=category_index)
        self._section_cache.set(cache_key, content)
        return content
    
    def build_state(self, context: dict) -> str:
        """构建STATE区域（动态状态快照）
        
        包含：
        - 当前阶段、目标
        - TODO列表及进度
        - 任务列表及依赖关系
        - 已加载技能名称列表
        - URL引用索引
        
        Args:
            context: 上下文字典，包含objective等信息
            
        Returns:
            格式化后的STATE区域内容
        """
        phase = self.agent_state.phase.value
        objective = context.get("objective", "")
        
        # TODO列表
        todo_list = []
        if hasattr(self.agent_state, 'todos') and self.agent_state.todos.items:
            todo_list = self.agent_state.todos.items
        
        # 任务信息
        task_section = ""
        if self.agent_state.current_task_id:
            from ..tasks import TaskManager
            manager = TaskManager(self.agent_state)
            tasks = manager.list_tasks()
            if tasks:
                task_section = format_task_section(tasks)
        
        # 技能信息
        skill_index = self.skill_manager.get_skill_index_prompt()
        loaded_skills = list(self.agent_state.loaded_skills) if self.agent_state.loaded_skills else []

        last_action = self.agent_state.action_history[-1] if self.agent_state.action_history else None
        last_round_section = format_last_round_section(self.agent_state.last_reasoning, last_action)

        return STATE_TEMPLATE.format(
            phase=phase,
            objective=objective,
            last_round_section=last_round_section,
            todo_section=format_todo_section(todo_list),
            task_section=task_section,
            skills_section=format_skills_section(skill_index, loaded_skills),
        )
    
    def build_default_state(self, context: dict) -> str:
        """构建DEFAULT阶段的STATE区域（动态状态快照）
        
        包含：
        - 任务目标
        - 任务列表及依赖关系
        - 技能类别概览
        - 已加载类别和技能名称列表
        
        Args:
            context: 上下文字典，包含objective等信息
            
        Returns:
            格式化后的STATE区域内容
        """
        objective = context.get("objective", "")
        
        # 获取类别列表
        categories = self.skill_manager.get_categories()
        
        # 已加载类别和技能
        loaded_categories = list(self.agent_state.loaded_categories) if self.agent_state.loaded_categories else []
        loaded_skills = list(self.agent_state.loaded_skills) if self.agent_state.loaded_skills else []
        
        # 任务信息
        task_section = ""
        if self.agent_state.current_task_id:
            from ..tasks import TaskManager
            manager = TaskManager(self.agent_state)
            tasks = manager.list_tasks()
            if tasks:
                task_section = format_task_section(tasks)
        
        last_action = self.agent_state.action_history[-1] if self.agent_state.action_history else None

        return DEFAULT_MODE_STATE_TEMPLATE.format(
            objective=objective,
            last_round_section=format_last_round_section(self.agent_state.last_reasoning, last_action),
            task_section=task_section,
            skills_section=format_default_skills_section(categories, loaded_skills, loaded_categories),
        )
    
    def build_context(self, context: dict) -> str:
        """构建CONTEXT区域（按需加载上下文）
        
        根据阶段加载不同内容：
        - COLLECT阶段：显示完整技能内容、参考文档
        - PLAN阶段：显示完整技能内容
        - EXECUTE阶段：显示最近工具调用历史（<=5条）
        - REPORT阶段：显示完整工具调用历史（<=10条）
        
        Args:
            context: 上下文字典
            
        Returns:
            格式化后的CONTEXT区域内容
        """
        phase = self.agent_state.phase
        
        # 类别内容
        category_contents_dict = {}
        if phase == AgentPhase.DEFAULT:
            for cat_name, content in self.agent_state.category_contents.items():
                category_contents_dict[cat_name] = content
        
        # 技能内容
        skill_contents_dict = {}
        if phase == AgentPhase.COLLECT:
            # COLLECT阶段：显示完整技能内容
            for skill_name, content in self.agent_state.skill_contents.items():
                skill_contents_dict[skill_name] = content
        elif phase == AgentPhase.PLAN:
            # PLAN阶段：显示完整技能内容
            for skill_name, content in self.agent_state.skill_contents.items():
                skill_contents_dict[skill_name] = content
        elif phase == AgentPhase.DEFAULT:
            # DEFAULT阶段：显示完整技能内容
            for skill_name, content in self.agent_state.skill_contents.items():
                skill_contents_dict[skill_name] = content
            # 将类别内容合并到技能内容字典中
            skill_contents_dict.update(category_contents_dict)
        # EXECUTE和REPORT阶段不显示技能内容
        
        # 参考文档（完整加载）
        reference_contents_dict = {}
        if phase == AgentPhase.COLLECT:
            # COLLECT阶段：显示完整参考文档
            for ref_name, content in self.agent_state.reference_contents.items():
                reference_contents_dict[ref_name] = content
        elif phase == AgentPhase.DEFAULT:
            # DEFAULT阶段：显示完整参考文档
            for ref_name, content in self.agent_state.reference_contents.items():
                reference_contents_dict[ref_name] = content
        # PLAN、EXECUTE和REPORT阶段不显示参考文档
        
        # 工具调用历史
        tool_history = []
        if phase == AgentPhase.EXECUTE:
            # EXECUTE阶段：显示最近工具调用历史（<=5条）
            if hasattr(self.agent_state, 'action_history') and self.agent_state.action_history:
                recent_actions = self.agent_state.get_recent_actions(5)
                for action in recent_actions:
                    tool_history.append({
                        "name": action.get("tool_name", "unknown"),
                        "status": "completed" if action.get("result_summary") else "unknown"
                    })
        elif phase == AgentPhase.DEFAULT:
            # DEFAULT阶段：显示最近工具调用历史（<=5条，与EXECUTE相同）
            if hasattr(self.agent_state, 'action_history') and self.agent_state.action_history:
                recent_actions = self.agent_state.get_recent_actions(5)
                for action in recent_actions:
                    tool_history.append({
                        "name": action.get("tool_name", "unknown"),
                        "status": "completed" if action.get("result_summary") else "unknown"
                    })
        elif phase == AgentPhase.REPORT:
            # REPORT阶段：显示完整工具调用历史（<=10条）
            if hasattr(self.agent_state, 'action_history') and self.agent_state.action_history:
                recent_actions = self.agent_state.get_recent_actions(10)
                for action in recent_actions:
                    tool_history.append({
                        "name": action.get("tool_name", "unknown"),
                        "status": "completed",
                        "summary": action.get("result_summary", "")[:300]
                    })
        
        # 根据阶段选择不同的格式化方式
        if phase == AgentPhase.REPORT:
            tool_history_str = format_action_history_for_report(tool_history, max_items=10)
        else:
            tool_history_str = format_tool_history(tool_history, max_items=5)
        
        return CONTEXT_TEMPLATE.format(
            skill_contents=format_skill_contents(skill_contents_dict),
            reference_contents=format_reference_contents(reference_contents_dict),
            tool_history=tool_history_str,
        )
    
    def build_tail(self, context: dict) -> str:
        """构建TAIL区域（行动指引）
        
        包含：
        - 当前可用工具列表
        - 阶段转换提醒
        - 下一步行动指引
        
        Args:
            context: 上下文字典
            
        Returns:
            格式化后的TAIL区域内容
        """
        phase = self.agent_state.phase
        
        # 根据 agent_depth 决定是否过滤 spawn_agents 工具
        exclude_tools = None
        if self.agent_state.agent_depth >= 1:
            exclude_tools = ["spawn_agents"]
        
        # 使用ToolManager获取工具描述
        available_tools = get_tool_manager().get_phase_tools_description(phase, exclude_tools)
        
        return TAIL_TEMPLATE.format(
            available_tools=available_tools,
            phase_reminder=get_phase_reminder(phase.value),
            next_action_hint=get_next_action_hint(phase.value),
        )
    
    def build_default_tail(self, context: dict) -> str:
        """构建DEFAULT阶段的TAIL区域（行动指引）
        
        包含：
        - 当前可用工具列表（排除start_plan、start_execute、update_todo）
        - 下一步行动指引
        
        Args:
            context: 上下文字典
            
        Returns:
            格式化后的TAIL区域内容
        """
        # DEFAULT阶段排除start_plan、start_execute、update_todo工具
        exclude_tools = ["start_plan", "start_execute", "update_todo"]
        
        # 根据 agent_depth 决定是否过滤 spawn_agents 工具
        if self.agent_state.agent_depth >= 1:
            exclude_tools.append("spawn_agents")
        
        # 使用ToolManager获取DEFAULT阶段的工具描述
        available_tools = get_tool_manager().get_phase_tools_description(AgentPhase.DEFAULT, exclude_tools)
        
        return DEFAULT_MODE_TAIL_TEMPLATE.format(
            available_tools=available_tools,
            next_action_hint=get_default_next_action_hint(
                self.agent_state.skill_contents,
                list(self.agent_state.loaded_categories) if self.agent_state.loaded_categories else None
            ),
        )
    
    def build(self, phase: str, context: Optional[dict] = None) -> str:
        """分段组装主方法
        
        Args:
            phase: 当前阶段（DEFAULT/COLLECT/PLAN/EXECUTE/REPORT）
            context: 上下文字典
            
        Returns:
            完整的prompt字符串
        """
        if context is None:
            context = {}
        
        # 根据阶段选择不同的构建逻辑
        if phase == AgentPhase.DEFAULT.value or phase == AgentPhase.DEFAULT:
            # DEFAULT阶段使用默认模式构建方法
            head = self.build_default_head()
            state = self.build_default_state(context)
            ctx = self.build_context(context)
            tail = self.build_default_tail(context)
        else:
            # 三阶段模式使用原有构建方法
            head = self.build_head()
            state = self.build_state(context)
            ctx = self.build_context(context)
            tail = self.build_tail(context)
        
        rules_content = self.rule_manager.get_rules_content_for_phase(phase)
        if rules_content:
            head = self._inject_rules_into_head(head, rules_content)
        return f"{head}\n\n{state}\n\n{ctx}\n\n{tail}"

    def _inject_rules_into_head(self, head: str, rules_content: str) -> str:
        rules_close_tag = "</rules>"
        pos = head.find(rules_close_tag)
        if pos >= 0:
            return head[:pos] + "\n\n" + rules_content + "\n" + head[pos:]
        return head + "\n\n<rules>\n" + rules_content + "\n</rules>"
    
    def get_token_budget(self) -> TokenBudget:
        """获取token预算配置
        
        Returns:
            TokenBudget对象，包含各区域的token预算
        """
        return self.token_budget
    
    def clear_cache(self) -> None:
        """清空缓存"""
        self._section_cache.clear()
    
    def get_cache_status(self) -> dict[str, bool]:
        """获取缓存状态
        
        Returns:
            字典，包含各区域的缓存状态
        """
        return {
            "head_section": self._section_cache.has(self.CACHE_KEY_HEAD),
        }

"""默认模式提示词模板 - 直接执行模式（XML标签结构化）"""

from .templates import format_skill_contents, format_reference_contents, format_task_section
from ..tools import get_tool_manager
from ..state import AgentPhase
from ..skills.manager import SkillManager


DEFAULT_MODE_HEAD_TEMPLATE = """<role>
你是强大的智能助手，能够直接执行任务并高效完成用户请求。
</role>

<rules>
1. 直接执行任务，无需阶段转换
2. 文本输出显示给用户，不是执行命令
3. 任务必须通过 task_complete 工具结束
4. 根据任务复杂度灵活使用工具
</rules>

<skill_loading>
技能按类别组织，请按以下步骤加载：
1. 先加载类别：使用 load_skill_category 加载相关类别，获取该类别下的技能描述列表
2. 再加载技能：根据类别描述，使用 load_skill 加载具体技能
3. 参考文档：使用 load_reference 获取额外的参考资料
4. 按技能指导执行：根据加载的技能内容执行命令

{category_index}

错误示例（禁止）：
- 未加载类别直接猜测技能名称
- 未加载技能直接猜测命令格式

正确示例：
- 先调用 load_skill_category 加载相关类别描述
- 阅读描述后调用 load_skill 加载具体技能
- 按技能指导执行命令
</skill_loading>

<completion_conditions>
任务完成需满足以下条件：
1. 已向用户汇报执行结果
2. 调用 task_complete 工具结束任务
</completion_conditions>

<guide name="spawn_agents">
spawn_agents 用于并行执行多个独立的子任务，而非重复执行相同任务。

使用前提:
1. 已收集必要的信息（已加载 skills 或提供足够的上下文）
2. 已创建 subagent_todos（原子化的子任务列表）
3. 已将任务拆解为可并行的子任务

任务拆解原则:
1. 识别可并行部分：找出任务中可以同时执行的部分
2. 创建原子化子任务：每个子任务应该是不可再分的叶节点任务
3. 确保独立性：子任务之间不应有依赖关系
4. 明确任务边界：每个子任务应该有明确的输入和输出

正确用法:
- 每个subagent执行不同的子任务
- 子任务应该是叶节点任务（不可再分）
- 子任务之间相互独立，可并行执行
- 必须提供 subagent_todos 参数

错误用法:
- 所有subagent执行相同的高层任务
- 未先收集信息就启动subagent
- 未创建 subagent_todos 就启动subagent
- 未拆解任务就启动subagent

示例:
任务: 在淘宝上搜寻笔记本电脑
1. 加载相关 skill
2. 了解搜索命令用法
3. 拆解任务: 子任务1搜寻品牌A，子任务2搜寻品牌B，子任务3搜寻品牌C
4. 创建 subagent_todos 并启动 subagent
</guide>
"""

DEFAULT_MODE_STATE_TEMPLATE = """<state>
<objective>{objective}</objective>
{last_round_section}
{task_section}
{skills_section}
</state>
"""

DEFAULT_MODE_CONTEXT_TEMPLATE = """<context>
{skill_contents}
{reference_contents}
{tool_history}
</context>
"""

DEFAULT_MODE_TAIL_TEMPLATE = """<tools>
可用工具: {available_tools}
</tools>

<action>
当前状态: 直接执行模式
下一步: {next_action_hint}
</action>
"""


def format_default_todo_section(todo_list: list = None) -> str:
    """格式化默认模式的TODO列表"""
    if not todo_list:
        return "<todos>无待办事项</todos>"

    lines = ["<todos>"]
    for todo in todo_list:
        status_icon = {
            "pending": "[ ]",
            "in_progress": "[>]",
            "completed": "[x]"
        }.get(todo.get("status", "pending"), "[ ]")

        content = todo.get("content", "")
        todo_id = todo.get("id", "?")
        lines.append(f"  {status_icon} {todo_id}. {content}")
    lines.append("</todos>")

    return "\n".join(lines)


def format_category_section(categories: list = None, loaded_categories: list = None) -> str:
    """格式化类别概览
    
    Args:
        categories: 所有可用类别列表
        loaded_categories: 已加载的类别名称列表
        
    Returns:
        格式化后的类别信息字符串
    """
    lines = []
    
    if categories:
        lines.append("<categories>")
        for cat in categories:
            skill_count = len(cat.skills) if hasattr(cat, 'skills') else 0
            lines.append(f"  <category name=\"{cat.name}\" skill_count=\"{skill_count}\">")
            lines.append(f"    {cat.description}")
            lines.append(f"  </category>")
        lines.append("</categories>")
    
    if loaded_categories:
        cats_str = ", ".join(loaded_categories)
        lines.append(f"<loaded_categories>{cats_str}</loaded_categories>")
    else:
        lines.append("<loaded_categories>无</loaded_categories>")
    
    return "\n".join(lines)


def format_default_skills_section(categories: list = None, loaded_skills: list = None, loaded_categories: list = None) -> str:
    """格式化默认模式的技能信息
    
    Args:
        categories: 所有可用类别列表
        loaded_skills: 已加载技能名称列表
        loaded_categories: 已加载的类别名称列表
        
    Returns:
        格式化后的技能信息字符串
    """
    lines = []
    
    if categories:
        lines.append(format_category_section(categories, loaded_categories))
    
    if loaded_skills:
        skills_str = ", ".join(loaded_skills)
        lines.append(f"<loaded_skills>{skills_str}</loaded_skills>")
    else:
        lines.append("<loaded_skills>无</loaded_skills>")
    
    return "\n".join(lines)


def format_default_tool_history(tool_history: list = None, max_items: int = 5) -> str:
    """格式化默认模式的工具调用历史"""
    if not tool_history:
        return "<history>无</history>"

    recent_history = tool_history[-max_items:] if len(tool_history) > max_items else tool_history

    lines = ["<history>"]
    for i, record in enumerate(recent_history, 1):
        tool_name = record.get("name", "unknown")
        status = record.get("status", "unknown")
        lines.append(f"  {i}. {tool_name} - {status}")
    lines.append("</history>")

    return "\n".join(lines)


def format_category_index(skill_manager: SkillManager = None) -> str:
    """格式化类别索引
    
    Args:
        skill_manager: SkillManager实例，如未提供则创建新实例
        
    Returns:
        格式化后的类别索引字符串
    """
    if skill_manager is None:
        skill_manager = SkillManager()
    
    categories = skill_manager.get_categories()
    
    if not categories:
        return "<available_categories>无</available_categories>"
    
    lines = ["<available_categories>"]
    for cat in categories:
        skill_count = len(cat.skills) if hasattr(cat, 'skills') else 0
        lines.append(f"  <category name=\"{cat.name}\" skill_count=\"{skill_count}\">")
        lines.append(f"    {cat.description}")
        lines.append(f"  </category>")
    lines.append("</available_categories>")
    
    return "\n".join(lines)


def get_default_next_action_hint(skill_contents: dict = None, loaded_categories: list = None) -> str:
    """获取默认模式的下一步行动提示
    
    Args:
        skill_contents: 已加载的技能内容字典
        loaded_categories: 已加载的类别列表
        
    Returns:
        下一步行动提示字符串
    """
    if not loaded_categories:
        return "先加载相关类别（load_skill_category），了解该类别下的技能列表"
    
    if not skill_contents:
        return "根据类别描述加载具体技能（load_skill），再根据技能指导行动"
    
    return "根据已加载的技能内容执行命令，完成后调用 task_complete 结束任务"


def format_default_mode_context(
    objective: str = "",
    categories: list = None,
    loaded_skills: list = None,
    loaded_categories: list = None,
    skill_contents: dict = None,
    reference_contents: dict = None,
    tool_history: list = None,
    available_tools: str = None,
    tasks: list = None,
    skill_manager: SkillManager = None,
) -> str:
    """
    格式化默认模式的完整会话上下文

    Args:
        objective: 任务目标
        categories: 所有可用类别列表
        loaded_skills: 已加载技能列表
        loaded_categories: 已加载的类别列表
        skill_contents: 技能内容字典
        reference_contents: 参考文档字典
        tool_history: 工具调用历史
        available_tools: 可用工具列表（如未提供，将动态获取）
        tasks: TaskRecord对象列表
        skill_manager: SkillManager实例（用于动态获取类别列表）

    Returns:
        格式化后的完整上下文字符串
    """
    if available_tools is None:
        exclude_tools = ["start_plan", "start_execute", "update_todo"]
        available_tools = get_tool_manager().get_phase_tools_description(AgentPhase.DEFAULT, exclude_tools)
    
    category_index = format_category_index(skill_manager)
    head_template = DEFAULT_MODE_HEAD_TEMPLATE.format(category_index=category_index)
    
    if categories is None and skill_manager is not None:
        categories = skill_manager.get_categories()
    
    state_section = DEFAULT_MODE_STATE_TEMPLATE.format(
        objective=objective,
        last_round_section="",
        task_section=format_task_section(tasks),
        skills_section=format_default_skills_section(categories, loaded_skills, loaded_categories),
    )

    context_section = DEFAULT_MODE_CONTEXT_TEMPLATE.format(
        skill_contents=format_skill_contents(skill_contents),
        reference_contents=format_reference_contents(reference_contents),
        tool_history=format_default_tool_history(tool_history),
    )

    tail_section = DEFAULT_MODE_TAIL_TEMPLATE.format(
        available_tools=available_tools,
        next_action_hint=get_default_next_action_hint(skill_contents, loaded_categories),
    )

    return f"{head_template}\n{state_section}\n{context_section}\n{tail_section}"

"""Agent prompt templates - 分段式动态组装架构（XML标签结构化）"""

HEAD_TEMPLATE = """<role>
你是强大的智能助手，能够根据用户意图，收集必要信息，拆解复杂步骤，执行复杂任务。
</role>

<rules>
1. 文本输出显示给用户，不是执行命令
2. 任务必须通过 task_complete 工具结束
3. 遵循阶段转换：COLLECT -> PLAN -> EXECUTE -> REPORT
</rules>

<phases>
<phase name="COLLECT">
可用工具: {collect_tools}
职责: 
  1. 加载技能内容和参考文档
  2. 收集必要信息，确保了解工具的使用方式
退出条件（必须全部满足）:
  - [ ] 已加载必要的技能和参考文档
  - [ ] 已验证关键命令的可用性和参数
  - [ ] 已收集足够的信息来制定执行计划
退出: 调用 `start_plan` 进入规划阶段
</phase>

<phase name="PLAN">
可用工具: {plan_tools}
职责: 分析任务需求、制定执行计划
退出: 调用 `start_execute` 进入执行阶段
</phase>

<phase name="EXECUTE">
可用工具: {execute_tools}
职责: 按计划执行命令、跟踪进度
重要: 当所有TODO完成时，系统会自动进入REPORT阶段
退出: 所有TODO完成后自动进入REPORT阶段
</phase>

<phase name="REPORT">
可用工具: 无
职责: 基于执行结果向用户汇报工作成果
退出: 输出汇报内容后任务结束
</phase>
</phases>

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

STATE_TEMPLATE = """<state>
<current>
阶段: {phase}
目标: {objective}
</current>
{last_round_section}
{todo_section}
{task_section}
{skills_section}
</state>
"""

CONTEXT_TEMPLATE = """<context>
{skill_contents}
{reference_contents}
{tool_history}
</context>
"""

TAIL_TEMPLATE = """<tools>
可用工具: {available_tools}
</tools>

<action>
{phase_reminder}
下一步: {next_action_hint}
</action>
"""


def format_last_round_section(reasoning: str = "", last_action: dict = None) -> str:
    if not reasoning and not last_action:
        return ""
    parts = ["<last_round>"]
    if reasoning:
        parts.append(f"  <thinking>\n  {reasoning}\n  </thinking>")
    if last_action:
        tool_name = last_action.get("tool_name", "unknown")
        result_summary = last_action.get("result_summary", "")
        args = last_action.get("arguments", {})
        args_str = ""
        if isinstance(args, dict):
            args_str = ", ".join(f"{k}={v}" for k, v in args.items())
        parts.append(f"  <action tool=\"{tool_name}\" args=\"{args_str}\">")
        parts.append(f"    {result_summary}")
        parts.append("  </action>")
    parts.append("</last_round>")
    return "\n".join(parts)


def format_todo_section(todo_list: list = None) -> str:
    """格式化TODO列表"""
    if not todo_list:
        return ""

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


def format_skills_section(skill_index: str = "", loaded_skills: list = None) -> str:
    """格式化技能信息"""
    sections = []

    if skill_index:
        sections.append(f"<skill_index>\n{skill_index}\n</skill_index>")

    if loaded_skills:
        skills_str = ", ".join(loaded_skills)
        sections.append(f"<loaded_skills>{skills_str}</loaded_skills>")

    return "\n".join(sections) if sections else ""


def format_task_section(tasks: list = None) -> str:
    """格式化任务列表
    
    Args:
        tasks: TaskRecord对象列表
        
    Returns:
        格式化后的任务列表字符串
    """
    if not tasks:
        return ""
    
    lines = ["<tasks>"]
    for task in tasks:
        status_icon = {
            "pending": "[ ]",
            "in_progress": "[>]",
            "completed": "[x]",
            "failed": "[!]",
            "cancelled": "[-]",
            "blocked": "[B]"
        }.get(task.status.value if hasattr(task.status, 'value') else task.status, "[ ]")
        
        task_id = task.id
        subject = task.subject
        owner = task.owner if task.owner else "未分配"
        
        lines.append(f"  {status_icon} #{task_id} {subject} ({owner})")
    lines.append("</tasks>")
    
    return "\n".join(lines)


def format_task_dependency_graph(tasks: list = None) -> str:
    """格式化任务依赖关系图
    
    Args:
        tasks: TaskRecord对象列表
        
    Returns:
        格式化后的依赖关系图字符串
    """
    if not tasks:
        return ""
    
    has_deps = any(task.blocked_by or task.blocks for task in tasks)
    if not has_deps:
        return ""
    
    lines = ["<dependencies>"]
    for task in tasks:
        if task.blocked_by:
            blocked_by_str = ", ".join(f"#{bid}" for bid in task.blocked_by)
            lines.append(f"  #{task.id} 被阻塞于: {blocked_by_str}")
        if task.blocks:
            blocks_str = ", ".join(f"#{bid}" for bid in task.blocks)
            lines.append(f"  #{task.id} 阻塞: {blocks_str}")
    lines.append("</dependencies>")
    
    return "\n".join(lines)


def format_skill_contents(skill_contents: dict = None) -> str:
    """格式化技能内容"""
    if not skill_contents:
        return "<skills>无</skills>"

    lines = ["<skills>"]
    for skill_name, content in skill_contents.items():
        lines.append(f"  <skill name=\"{skill_name}\">")
        if content:
            lines.append(f"    {content}")
        lines.append(f"  </skill>")
    lines.append("</skills>")

    return "\n".join(lines)


def format_reference_contents(reference_contents: dict = None) -> str:
    """格式化参考文档"""
    if not reference_contents:
        return "<references>无</references>"

    lines = ["<references>"]
    for ref_name, content in reference_contents.items():
        lines.append(f"  <reference name=\"{ref_name}\">")
        if content:
            lines.append(f"    {content}")
        lines.append(f"  </reference>")
    lines.append("</references>")

    return "\n".join(lines)


def format_tool_history(tool_history: list = None, max_items: int = 5) -> str:
    """格式化工具调用历史"""
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


def format_action_history_for_report(action_history: list = None, max_items: int = 10) -> str:
    """格式化REPORT阶段的工具调用历史
    
    Args:
        action_history: 工具调用历史列表
        max_items: 最大显示条数
        
    Returns:
        格式化后的工具调用历史字符串
    """
    if not action_history:
        return "<execution_history>无</execution_history>"
    
    recent_history = action_history[-max_items:] if len(action_history) > max_items else action_history
    
    lines = ["<execution_history>"]
    for i, action in enumerate(recent_history, 1):
        tool_name = action.get("name", action.get("tool_name", "unknown"))
        summary = action.get("summary", action.get("result_summary", ""))[:200]
        lines.append(f"  {i}. {tool_name}: {summary}")
    lines.append("</execution_history>")
    
    return "\n".join(lines)


def get_phase_reminder(phase: str) -> str:
    """获取阶段提醒"""
    reminders = {
        "COLLECT": "信息收集阶段 - 加载技能和参考文档，验证命令可用性",
        "PLAN": "规划阶段 - 分析任务需求，制定执行计划",
        "EXECUTE": "执行阶段 - 按计划执行命令，跟踪进度",
        "REPORT": "汇报阶段 - 基于执行结果向用户汇报工作成果"
    }
    return reminders.get(phase, "未知阶段")


def get_next_action_hint(phase: str) -> str:
    """获取下一步行动提示"""
    hints = {
        "COLLECT": "加载必要技能和参考文档，然后调用 start_plan",
        "PLAN": "制定执行计划，然后调用 start_execute",
        "EXECUTE": "执行计划中的命令，完成后系统会自动进入汇报阶段",
        "REPORT": "向用户汇报工作成果，总结任务执行结果"
    }
    return hints.get(phase, "等待指示")


def format_session_context(
    phase: str = "COLLECT",
    objective: str = "",
    todo_list: list = None,
    tasks: list = None,
    skill_index: str = "",
    loaded_skills: list = None,
    skill_contents: dict = None,
    reference_contents: dict = None,
    tool_history: list = None,
    available_tools: str = "",
) -> str:
    """
    格式化完整的会话上下文（新版分段式）

    Args:
        phase: 当前阶段 (COLLECT/PLAN/EXECUTE)
        objective: 任务目标
        todo_list: TODO列表
        tasks: TaskRecord对象列表
        skill_index: 技能索引
        loaded_skills: 已加载技能列表
        skill_contents: 技能内容字典
        reference_contents: 参考文档字典
        tool_history: 工具调用历史
        available_tools: 可用工具列表

    Returns:
        格式化后的完整上下文字符串
    """
    state_section = STATE_TEMPLATE.format(
        phase=phase,
        objective=objective,
        last_round_section="",
        todo_section=format_todo_section(todo_list),
        task_section=format_task_section(tasks),
        skills_section=format_skills_section(skill_index, loaded_skills),
    )

    context_section = CONTEXT_TEMPLATE.format(
        skill_contents=format_skill_contents(skill_contents),
        reference_contents=format_reference_contents(reference_contents),
        tool_history=format_tool_history(tool_history),
    )

    tail_section = TAIL_TEMPLATE.format(
        available_tools=available_tools,
        phase_reminder=get_phase_reminder(phase),
        next_action_hint=get_next_action_hint(phase),
    )

    return f"{HEAD_TEMPLATE}\n{state_section}\n{context_section}\n{tail_section}"


def format_task_context(
    phase: str = "COLLECT",
    objective: str = "",
    **kwargs
) -> str:
    """
    格式化任务上下文（兼容旧版接口）

    Args:
        phase: 当前阶段
        objective: 任务目标
        **kwargs: 其他参数

    Returns:
        格式化后的上下文字符串
    """
    return format_session_context(
        phase=phase,
        objective=objective,
        **kwargs
    )

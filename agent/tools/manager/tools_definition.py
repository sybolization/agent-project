"""工具定义 - 所有工具的ToolDefinition定义"""

from ..protocol import ToolDefinition

from ..builtin.skill.load_skill import tool_definition as load_skill_td
from ..builtin.skill.load_category import tool_definition as load_category_td
from ..builtin.skill.load_reference import tool_definition as load_reference_td
from ..builtin.command.execute_command import tool_definition as execute_command_td
from ..builtin.cdp.connect import tool_definition as cdp_connect_td
from ..builtin.cdp.execute import tool_definition as cdp_execute_td
from ..builtin.cdp.get_state import tool_definition as cdp_get_state_td
from ..builtin.cdp.edit_helpers import tool_definition as cdp_edit_helpers_td
from ..builtin.task.create import tool_definition as create_task_td
from ..builtin.task.list import tool_definition as list_tasks_td
from ..builtin.task.update_status import tool_definition as update_task_status_td
from ..builtin.task.add_dependency import tool_definition as add_task_dependency_td
from ..builtin.task.assign import tool_definition as assign_task_td
from ..builtin.phase.start_plan import tool_definition as start_plan_td
from ..builtin.phase.start_execute import tool_definition as start_execute_td
from ..builtin.todo.update_todo import tool_definition as update_todo_td
from ..builtin.todo.task_complete import tool_definition as task_complete_td
from ..builtin.spawn.spawn_agents import tool_definition as spawn_agents_td

ALL_TOOLS = [
    execute_command_td,
    load_skill_td,
    load_category_td,
    load_reference_td,
    start_plan_td,
    start_execute_td,
    update_todo_td,
    task_complete_td,
    spawn_agents_td,
    create_task_td,
    list_tasks_td,
    update_task_status_td,
    add_task_dependency_td,
    assign_task_td,
    cdp_connect_td,
    cdp_execute_td,
    cdp_get_state_td,
    cdp_edit_helpers_td,
]

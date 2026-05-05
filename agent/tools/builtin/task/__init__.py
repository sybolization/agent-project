"""Task 管理工具集"""

from .create import tool_definition as create_task_def
from .list import tool_definition as list_tasks_def
from .update_status import tool_definition as update_task_status_def
from .add_dependency import tool_definition as add_task_dependency_def
from .assign import tool_definition as assign_task_def

TASK_TOOLS = [create_task_def, list_tasks_def, update_task_status_def, add_task_dependency_def, assign_task_def]

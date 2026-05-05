"""TODO 管理工具集"""

from .update_todo import tool_definition as update_todo_def
from .task_complete import tool_definition as task_complete_def

TODO_TOOLS = [update_todo_def, task_complete_def]

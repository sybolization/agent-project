"""Phase 转换工具集"""

from .start_plan import tool_definition as start_plan_def
from .start_execute import tool_definition as start_execute_def

PHASE_TOOLS = [start_plan_def, start_execute_def]

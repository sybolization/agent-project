"""CDP 工具集"""

from .connect import tool_definition as cdp_connect_def
from .execute import tool_definition as cdp_execute_def
from .get_state import tool_definition as cdp_get_state_def
from .edit_helpers import tool_definition as cdp_edit_helpers_def

CDP_TOOLS = [cdp_connect_def, cdp_execute_def, cdp_get_state_def, cdp_edit_helpers_def]

"""内置 Hook 处理器"""

from .permission_hook import create_permission_hook
from .duplicate_command_hook import create_duplicate_command_hook
from .loop_detection_hook import create_loop_detection_hook, LoopDetector
from .tool_result_logging_hook import create_tool_result_logging_hook
from .context_compression_hook import create_context_compression_hook
from .phase_transition_hook import create_phase_transition_hook
from .complete_status_hook import create_complete_status_hook
from .transition_status_hook import create_transition_status_hook
from .error_status_hook import create_error_status_hook
from .needs_confirmation_status_hook import create_needs_confirmation_status_hook
from .default_status_hook import create_default_status_hook

__all__ = [
    "create_permission_hook",
    "create_duplicate_command_hook",
    "create_loop_detection_hook",
    "LoopDetector",
    "create_tool_result_logging_hook",
    "create_context_compression_hook",
    "create_phase_transition_hook",
    "create_complete_status_hook",
    "create_transition_status_hook",
    "create_error_status_hook",
    "create_needs_confirmation_status_hook",
    "create_default_status_hook",
]

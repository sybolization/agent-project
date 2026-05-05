"""阶段执行结果数据类"""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class PhaseResult:
    """阶段执行结果"""
    status: str
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    next_phase: Optional[str] = None
    tool_calls: list[dict] = field(default_factory=list)
    response_text: str = ""
    tool_results: list[dict] = field(default_factory=list)
    reasoning_content: str = ""

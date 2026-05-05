"""工具协议 - 定义工具单元的标准契约"""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, List

from ..state import AgentPhase


@dataclass
class ToolDefinition:
    """工具定义——工具接入系统的唯一入口

    一个 ToolDefinition 实例包含工具的全部信息：
    - name / schema / phases: 工具元数据，决定 LLM 何时可见该工具
    - executor: 实现了 execute(call, context) 方法的对象，执行+错误处理内聚
    - handler: 可选，实现了 handle(result, state) -> PhaseResult 的结果处理器
    - formatter: 可选，实现了 format(result) -> str 的 LLM 消息格式化器
    """
    name: str
    schema: dict
    phases: List[AgentPhase]
    description: str = ""
    usage_hint: str = ""
    executor: Optional[Any] = None
    handler: Optional[Any] = None
    formatter: Optional[Any] = None

    def is_available_for_phase(self, phase: AgentPhase) -> bool:
        """检查工具是否在指定阶段可用"""
        return phase in self.phases

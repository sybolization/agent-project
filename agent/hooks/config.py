"""Hook 配置"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from .runner import HookHandler, HookRunner
from .types import HookEventName


@dataclass
class HookConfig:
    """单个 Hook 的配置"""
    enabled: bool = True
    priority: int = 0  # 优先级，数值越小越先执行
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HooksConfig:
    """所有 Hook 的配置"""
    hooks: Dict[str, HookConfig] = field(default_factory=dict)

    def get(self, hook_name: str) -> HookConfig:
        """获取 Hook 配置，如果不存在返回默认配置"""
        return self.hooks.get(hook_name, HookConfig())

    def is_enabled(self, hook_name: str) -> bool:
        """检查 Hook 是否启用"""
        return self.get(hook_name).enabled

    def get_params(self, hook_name: str) -> Dict[str, Any]:
        """获取 Hook 参数"""
        return self.get(hook_name).params


DEFAULT_HOOKS_CONFIG = HooksConfig(
    hooks={
        "permission_hook": HookConfig(enabled=True, priority=0),
        "duplicate_command_hook": HookConfig(enabled=True, priority=10),
        "tool_result_logging_hook": HookConfig(enabled=True, priority=30),
        "loop_detection_hook": HookConfig(enabled=True, priority=40, params={"max_repeated": 2}),
        "context_compression_hook": HookConfig(enabled=True, priority=50, params={"threshold": 4000}),
        "phase_transition_hook": HookConfig(enabled=True, priority=60),
        "complete_status_hook": HookConfig(enabled=True, priority=100),
        "transition_status_hook": HookConfig(enabled=True, priority=90),
        "error_status_hook": HookConfig(enabled=True, priority=80),
        "needs_confirmation_status_hook": HookConfig(enabled=True, priority=70),
        "default_status_hook": HookConfig(enabled=True, priority=10),
    }
)


class HookRegistry:
    """Hook 注册表

    管理所有 Hook 的注册、配置和生命周期。
    """

    def __init__(self, config: Optional[HooksConfig] = None):
        self.config = config or DEFAULT_HOOKS_CONFIG
        self._hooks: Dict[str, Dict[str, Any]] = {}
        self._runner: Optional[HookRunner] = None

    def register(self, name: str, factory: Callable, **kwargs: Any) -> None:
        """注册 Hook 工厂函数

        Args:
            name: Hook 名称
            factory: Hook 工厂函数
            **kwargs: 传递给工厂函数的额外参数
        """
        self._hooks[name] = {"factory": factory, "kwargs": kwargs}

    def create_runner(self) -> HookRunner:
        """创建并配置 HookRunner

        根据配置创建 Hook 实例并注册到 Runner。

        Returns:
            配置好的 HookRunner 实例
        """
        runner = HookRunner()

        # 按优先级排序
        sorted_hooks = sorted(
            self._hooks.items(),
            key=lambda x: self.config.get(x[0]).priority
        )

        for name, hook_info in sorted_hooks:
            if not self.config.is_enabled(name):
                continue

            factory = hook_info["factory"]
            kwargs = hook_info["kwargs"]
            params = self.config.get_params(name)

            # 合并配置参数和传入参数
            merged_kwargs = {**params, **kwargs}

            # 创建 Hook 实例
            hook_instance: HookHandler = factory(**merged_kwargs)

            # 注册到 Runner（假设所有 Hook 都处理 PreToolUse 和 PostToolUse）
            runner.register(HookEventName.PRE_TOOL_USE, hook_instance)
            runner.register(HookEventName.POST_TOOL_USE, hook_instance)

        self._runner = runner
        return runner

    def get_runner(self) -> Optional[HookRunner]:
        """获取当前的 HookRunner"""
        return self._runner

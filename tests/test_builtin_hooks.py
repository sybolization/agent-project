"""内置 Hook 测试"""

import pytest
from agent.hooks import (
    HookRunner,
    HookEvent,
    HookEventName,
    HookResult,
    HookExitCode,
    HookConfig,
    HooksConfig,
    HookRegistry,
    DEFAULT_HOOKS_CONFIG,
)
from agent.hooks.builtins import (
    create_permission_hook,
    create_duplicate_command_hook,
    create_url_reference_hook,
    create_tool_result_logging_hook,
    create_loop_detection_hook,
    create_context_compression_hook,
    create_phase_transition_hook,
)
from agent.hooks.builtins.loop_detection_hook import LoopDetector


class TestDuplicateCommandHook:
    """测试 DuplicateCommandHook"""

    def test_new_command_passes(self):
        """测试新命令通过"""
        action_history = []
        hook = create_duplicate_command_hook(action_history)
        runner = HookRunner()
        runner.register(HookEventName.PRE_TOOL_USE, hook)

        result = runner.run_pre_tool_use(
            "execute_command",
            {"command": "git status"}
        )
        assert result.exit_code == HookExitCode.CONTINUE

    def test_duplicate_command_injects_warning(self):
        """测试重复命令注入警告"""
        action_history = [
            {
                "tool_name": "execute_command",
                "arguments": {"command": "git status"},
                "result_summary": "成功"
            }
        ]
        hook = create_duplicate_command_hook(action_history)
        runner = HookRunner()
        runner.register(HookEventName.PRE_TOOL_USE, hook)

        result = runner.run_pre_tool_use(
            "execute_command",
            {"command": "git status"}
        )
        assert result.exit_code == HookExitCode.INJECT
        assert "重复操作警告" in result.message

    def test_other_tools_not_affected(self):
        """测试其他工具不受影响"""
        action_history = []
        hook = create_duplicate_command_hook(action_history)
        runner = HookRunner()
        runner.register(HookEventName.PRE_TOOL_USE, hook)

        result = runner.run_pre_tool_use(
            "load_skill",
            {"skill_name": "test"}
        )
        assert result.exit_code == HookExitCode.CONTINUE


class TestLoopDetectionHook:
    """测试 LoopDetectionHook"""

    def test_normal_execution(self):
        """测试正常执行"""
        hook = create_loop_detection_hook(max_repeated=2)
        runner = HookRunner()
        runner.register(HookEventName.POST_TOOL_USE, hook)

        # 第一次执行
        result = runner.run(HookEvent(
            name=HookEventName.POST_TOOL_USE,
            payload={"response_text": "response 1"}
        ))
        assert result.exit_code == HookExitCode.CONTINUE

        # 第二次不同内容
        result = runner.run(HookEvent(
            name=HookEventName.POST_TOOL_USE,
            payload={"response_text": "response 2"}
        ))
        assert result.exit_code == HookExitCode.CONTINUE

    def test_loop_detected(self):
        """测试检测到循环"""
        hook = create_loop_detection_hook(max_repeated=2)
        runner = HookRunner()
        runner.register(HookEventName.POST_TOOL_USE, hook)

        # 连续输出相同内容
        for _ in range(2):
            result = runner.run(HookEvent(
                name=HookEventName.POST_TOOL_USE,
                payload={"response_text": "same response"}
            ))

        # 第三次应该被阻止
        assert result.exit_code == HookExitCode.BLOCK
        assert "循环" in result.message


class TestLoopDetector:
    """测试 LoopDetector"""

    def test_no_loop_initially(self):
        """测试初始状态无循环"""
        detector = LoopDetector(max_repeated=2)
        is_loop, count = detector.check("response")
        assert is_loop is False
        assert count == 0

    def test_detects_loop(self):
        """测试检测到循环"""
        detector = LoopDetector(max_repeated=2)

        # 第一次相同
        detector.check("same")
        is_loop, count = detector.check("same")
        assert is_loop is False
        assert count == 1

        # 第二次相同，达到阈值
        is_loop, count = detector.check("same")
        assert is_loop is True
        assert count == 2

    def test_reset_on_different(self):
        """测试不同内容重置计数"""
        detector = LoopDetector(max_repeated=2)

        detector.check("same")
        detector.check("same")

        # 不同内容重置
        is_loop, count = detector.check("different")
        assert is_loop is False
        assert count == 0


class TestPhaseTransitionHook:
    """测试 PhaseTransitionHook"""

    def setup_method(self):
        self.runner = HookRunner()
        self.runner.register(HookEventName.PRE_TOOL_USE, create_phase_transition_hook())

    def test_valid_transition_collect_to_plan(self):
        """测试合法转换 COLLECT -> PLAN"""
        result = self.runner.run_pre_tool_use(
            "start_plan",
            {"current_phase": "COLLECT", "target_phase": "PLAN"}
        )
        assert result.exit_code == HookExitCode.CONTINUE

    def test_valid_transition_plan_to_execute(self):
        """测试合法转换 PLAN -> EXECUTE"""
        result = self.runner.run_pre_tool_use(
            "start_execute",
            {"current_phase": "PLAN", "target_phase": "EXECUTE"}
        )
        assert result.exit_code == HookExitCode.CONTINUE

    def test_invalid_transition(self):
        """测试非法转换"""
        result = self.runner.run_pre_tool_use(
            "start_execute",
            {"current_phase": "COLLECT", "target_phase": "EXECUTE"}
        )
        assert result.exit_code == HookExitCode.BLOCK
        assert "非法阶段转换" in result.message


class TestHookConfig:
    """测试 Hook 配置"""

    def test_default_config_has_all_hooks(self):
        """测试默认配置包含所有 Hook"""
        assert "permission_hook" in DEFAULT_HOOKS_CONFIG.hooks
        assert "duplicate_command_hook" in DEFAULT_HOOKS_CONFIG.hooks
        assert "loop_detection_hook" in DEFAULT_HOOKS_CONFIG.hooks

    def test_config_is_enabled(self):
        """测试配置启用检查"""
        config = HooksConfig(
            hooks={
                "enabled_hook": HookConfig(enabled=True),
                "disabled_hook": HookConfig(enabled=False),
            }
        )
        assert config.is_enabled("enabled_hook")
        assert not config.is_enabled("disabled_hook")

    def test_config_get_params(self):
        """测试获取参数"""
        config = HooksConfig(
            hooks={
                "test_hook": HookConfig(params={"threshold": 1000}),
            }
        )
        params = config.get_params("test_hook")
        assert params["threshold"] == 1000


class TestHookRegistry:
    """测试 Hook 注册表"""

    def test_register_and_create_runner(self):
        """测试注册和创建 Runner"""
        registry = HookRegistry()
        registry.register("test_hook", create_permission_hook)

        runner = registry.create_runner()
        assert runner is not None

    def test_disabled_hook_not_registered(self):
        """测试禁用的 Hook 不会被注册"""
        config = HooksConfig(
            hooks={
                "test_hook": HookConfig(enabled=False),
            }
        )
        registry = HookRegistry(config=config)
        registry.register("test_hook", create_permission_hook)

        runner = registry.create_runner()
        # 禁用的 Hook 不应该影响执行
        result = runner.run_pre_tool_use("execute_command", {"command": "test"})
        assert result.exit_code == HookExitCode.CONTINUE

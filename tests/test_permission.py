"""权限系统测试"""

import pytest
from agent.permission import (
    PermissionChecker,
    PermissionRule,
    PermissionBehavior,
    DEFAULT_DENY_RULES,
    DEFAULT_ASK_RULES,
    DEFAULT_ALLOW_RULES,
)


class TestPermissionRule:
    """测试 PermissionRule"""

    def test_matches_deny_rule(self):
        """测试 deny 规则匹配"""
        rule = PermissionRule(
            tool="execute_command",
            behavior=PermissionBehavior.DENY,
            pattern=r"rm\s+(-[rf]+\s+|-r\s+-f\s+|--recursive\s+--force\s+)",
            reason="禁止强制递归删除"
        )

        # -[rf]+ 会匹配 -r, -f, -rf, -fr 等
        assert rule.matches("execute_command", "rm -rf /home/user")
        assert rule.matches("execute_command", "rm -rf /")
        assert rule.matches("execute_command", "rm -r /home")  # -r 也会匹配 -[rf]+
        assert not rule.matches("execute_command", "rm /home")  # 没有选项不匹配
        assert not rule.matches("other_tool", "rm -rf /")

    def test_matches_case_insensitive(self):
        """测试大小写不敏感匹配"""
        rule = PermissionRule(
            tool="execute_command",
            behavior=PermissionBehavior.DENY,
            pattern=r"del\s+/[sS]",
            reason="禁止强制删除"
        )

        assert rule.matches("execute_command", "del /s folder")
        assert rule.matches("execute_command", "DEL /S folder")

    def test_matches_format_disk(self):
        """测试格式化磁盘规则匹配"""
        rule = PermissionRule(
            tool="execute_command",
            behavior=PermissionBehavior.DENY,
            pattern=r"format\s+[a-zA-Z]:",
            reason="禁止格式化磁盘"
        )

        assert rule.matches("execute_command", "format c:")
        assert rule.matches("execute_command", "format D:")
        assert not rule.matches("execute_command", "format")

    def test_matches_sudo_rule(self):
        """测试 sudo 规则匹配"""
        rule = PermissionRule(
            tool="execute_command",
            behavior=PermissionBehavior.ASK,
            pattern=r"sudo\s+",
            reason="提权操作需要确认"
        )

        assert rule.matches("execute_command", "sudo apt update")
        assert rule.matches("execute_command", "sudo rm file")
        assert not rule.matches("execute_command", "apt update")

    def test_matches_git_rule(self):
        """测试 git 规则匹配"""
        rule = PermissionRule(
            tool="execute_command",
            behavior=PermissionBehavior.ALLOW,
            pattern=r"^git\s+",
            reason="git 命令默认允许"
        )

        assert rule.matches("execute_command", "git status")
        assert rule.matches("execute_command", "git commit -m 'test'")
        assert not rule.matches("execute_command", "sudo git status")


class TestPermissionChecker:
    """测试 PermissionChecker"""

    def setup_method(self):
        self.checker = PermissionChecker()

    def test_deny_dangerous_command(self):
        """测试危险命令被拒绝"""
        decision = self.checker.check("execute_command", "rm -rf /")
        assert decision.behavior == PermissionBehavior.DENY

        decision = self.checker.check("execute_command", "del /s folder")
        assert decision.behavior == PermissionBehavior.DENY

        decision = self.checker.check("execute_command", "format c:")
        assert decision.behavior == PermissionBehavior.DENY

    def test_allow_safe_command(self):
        """测试安全命令被允许"""
        decision = self.checker.check("execute_command", "git status")
        assert decision.behavior == PermissionBehavior.ALLOW

        decision = self.checker.check("execute_command", "opencli list")
        assert decision.behavior == PermissionBehavior.ALLOW

        decision = self.checker.check("execute_command", "ls")
        assert decision.behavior == PermissionBehavior.ALLOW

    def test_ask_sudo_command(self):
        """测试 sudo 命令需要确认"""
        decision = self.checker.check("execute_command", "sudo apt update")
        assert decision.behavior == PermissionBehavior.ASK

        decision = self.checker.check("execute_command", "sudo rm file")
        assert decision.behavior == PermissionBehavior.ASK

    def test_unknown_command_needs_confirmation(self):
        """测试未知命令需要确认"""
        decision = self.checker.check("execute_command", "some-unknown-command")
        assert decision.behavior == PermissionBehavior.ASK

    def test_custom_rule(self):
        """测试自定义规则"""
        custom_rule = PermissionRule(
            tool="execute_command",
            behavior=PermissionBehavior.DENY,
            pattern=r"dangerous-cmd",
            reason="自定义危险命令"
        )

        checker = PermissionChecker()
        checker.add_rule(custom_rule)

        decision = checker.check("execute_command", "dangerous-cmd --force")
        assert decision.behavior == PermissionBehavior.DENY
        assert decision.matched_rule == custom_rule

    def test_deny_takes_priority_over_allow(self):
        """测试 deny 规则优先于 allow 规则"""
        # rm -rf 是 deny 规则，应该被拒绝
        decision = self.checker.check("execute_command", "rm -rf /home")
        assert decision.behavior == PermissionBehavior.DENY

    def test_allow_takes_priority_over_ask(self):
        """测试 allow 规则优先于 ask 规则"""
        # git 命令是 allow 规则，应该被允许
        decision = self.checker.check("execute_command", "git status")
        assert decision.behavior == PermissionBehavior.ALLOW

    def test_decision_has_reason(self):
        """测试决策结果包含原因"""
        decision = self.checker.check("execute_command", "rm -rf /")
        assert decision.reason != ""
        assert decision.matched_rule is not None

    def test_decision_for_unknown_has_reason(self):
        """测试未知命令决策包含原因"""
        decision = self.checker.check("execute_command", "unknown-command")
        assert decision.reason == "未知命令，需要用户确认"
        assert decision.matched_rule is None

    def test_custom_checker_with_custom_rules(self):
        """测试使用自定义规则创建检查器"""
        custom_deny = [
            PermissionRule(
                tool="execute_command",
                behavior=PermissionBehavior.DENY,
                pattern=r"custom-deny",
                reason="自定义拒绝"
            )
        ]
        custom_allow = [
            PermissionRule(
                tool="execute_command",
                behavior=PermissionBehavior.ALLOW,
                pattern=r"custom-allow",
                reason="自定义允许"
            )
        ]

        checker = PermissionChecker(
            deny_rules=custom_deny,
            allow_rules=custom_allow,
        )

        decision = checker.check("execute_command", "custom-deny")
        assert decision.behavior == PermissionBehavior.DENY

        decision = checker.check("execute_command", "custom-allow")
        assert decision.behavior == PermissionBehavior.ALLOW

        # 没有默认规则，未知命令应该需要确认
        decision = checker.check("execute_command", "unknown")
        assert decision.behavior == PermissionBehavior.ASK


class TestDefaultRules:
    """测试默认规则"""

    def test_default_deny_rules_exist(self):
        """测试默认 deny 规则存在"""
        assert len(DEFAULT_DENY_RULES) > 0

        # 检查关键规则
        deny_patterns = [r.pattern for r in DEFAULT_DENY_RULES]
        assert any("rm" in p for p in deny_patterns)
        assert any("del" in p for p in deny_patterns)
        assert any("format" in p for p in deny_patterns)

    def test_default_ask_rules_exist(self):
        """测试默认 ask 规则存在"""
        assert len(DEFAULT_ASK_RULES) > 0

        # 检查关键规则
        ask_patterns = [r.pattern for r in DEFAULT_ASK_RULES]
        assert any("sudo" in p for p in ask_patterns)

    def test_default_allow_rules_exist(self):
        """测试默认 allow 规则存在"""
        assert len(DEFAULT_ALLOW_RULES) > 0

        # 检查关键规则
        allow_patterns = [r.pattern for r in DEFAULT_ALLOW_RULES]
        assert any("git" in p for p in allow_patterns)
        assert any("opencli" in p for p in allow_patterns)

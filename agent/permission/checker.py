"""权限检查器"""

from dataclasses import dataclass
from typing import List, Optional

from .rules import PermissionRule, PermissionBehavior, DEFAULT_DENY_RULES, DEFAULT_ASK_RULES, DEFAULT_ALLOW_RULES


@dataclass
class PermissionDecision:
    """权限决策结果"""
    behavior: PermissionBehavior
    reason: str
    matched_rule: Optional[PermissionRule] = None


class PermissionChecker:
    """权限检查器

    检查顺序：
    1. deny rules -> 命中了就拒绝
    2. allow rules -> 命中了就放行
    3. ask user -> 剩下的交给用户确认
    """

    def __init__(
        self,
        deny_rules: Optional[List[PermissionRule]] = None,
        ask_rules: Optional[List[PermissionRule]] = None,
        allow_rules: Optional[List[PermissionRule]] = None,
    ):
        self.deny_rules = deny_rules or DEFAULT_DENY_RULES
        self.ask_rules = ask_rules or DEFAULT_ASK_RULES
        self.allow_rules = allow_rules or DEFAULT_ALLOW_RULES

    def check(self, tool_name: str, content: str) -> PermissionDecision:
        """检查权限

        Args:
            tool_name: 工具名称
            content: 命令内容

        Returns:
            权限决策结果
        """
        # 1. 检查 deny rules
        for rule in self.deny_rules:
            if rule.matches(tool_name, content):
                return PermissionDecision(
                    behavior=PermissionBehavior.DENY,
                    reason=rule.reason,
                    matched_rule=rule,
                )

        # 2. 检查 allow rules
        for rule in self.allow_rules:
            if rule.matches(tool_name, content):
                return PermissionDecision(
                    behavior=PermissionBehavior.ALLOW,
                    reason=rule.reason,
                    matched_rule=rule,
                )

        # 3. 检查 ask rules
        for rule in self.ask_rules:
            if rule.matches(tool_name, content):
                return PermissionDecision(
                    behavior=PermissionBehavior.ASK,
                    reason=rule.reason,
                    matched_rule=rule,
                )

        # 4. 默认行为：需要确认
        return PermissionDecision(
            behavior=PermissionBehavior.ASK,
            reason="未知命令，需要用户确认",
            matched_rule=None,
        )

    def add_rule(self, rule: PermissionRule) -> None:
        """添加规则"""
        if rule.behavior == PermissionBehavior.DENY:
            self.deny_rules.append(rule)
        elif rule.behavior == PermissionBehavior.ALLOW:
            self.allow_rules.append(rule)
        elif rule.behavior == PermissionBehavior.ASK:
            self.ask_rules.append(rule)

"""权限系统"""

from .rules import PermissionRule, PermissionBehavior, DEFAULT_DENY_RULES, DEFAULT_ASK_RULES, DEFAULT_ALLOW_RULES
from .checker import PermissionChecker, PermissionDecision

__all__ = [
    "PermissionRule",
    "PermissionBehavior",
    "PermissionChecker",
    "PermissionDecision",
    "DEFAULT_DENY_RULES",
    "DEFAULT_ASK_RULES",
    "DEFAULT_ALLOW_RULES",
]

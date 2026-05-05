"""权限规则定义"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional
import re


class PermissionBehavior(str, Enum):
    """权限行为"""
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass
class PermissionRule:
    """权限规则"""
    tool: str  # 工具名称
    behavior: PermissionBehavior  # 行为
    pattern: str  # 匹配模式（正则表达式）
    reason: str  # 原因说明

    def matches(self, tool_name: str, content: str) -> bool:
        """检查是否匹配"""
        if self.tool != tool_name:
            return False
        return bool(re.search(self.pattern, content, re.IGNORECASE))


DEFAULT_DENY_RULES: List[PermissionRule] = [
    # 危险删除命令
    PermissionRule(
        tool="execute_command",
        behavior=PermissionBehavior.DENY,
        pattern=r"rm\s+(-[rf]+\s+|-r\s+-f\s+|--recursive\s+--force\s+)",
        reason="禁止强制递归删除"
    ),
    PermissionRule(
        tool="execute_command",
        behavior=PermissionBehavior.DENY,
        pattern=r"del\s+/[sS]",
        reason="禁止强制删除目录"
    ),
    PermissionRule(
        tool="execute_command",
        behavior=PermissionBehavior.DENY,
        pattern=r"format\s+[a-zA-Z]:",
        reason="禁止格式化磁盘"
    ),
    PermissionRule(
        tool="execute_command",
        behavior=PermissionBehavior.DENY,
        pattern=r"rmdir\s+/[sS]",
        reason="禁止强制删除目录"
    ),
    PermissionRule(
        tool="execute_command",
        behavior=PermissionBehavior.DENY,
        pattern=r"rd\s+/[sS]",
        reason="禁止强制删除目录"
    ),
    # 系统破坏命令
    PermissionRule(
        tool="execute_command",
        behavior=PermissionBehavior.DENY,
        pattern=r"mkfs\.",
        reason="禁止格式化文件系统"
    ),
    PermissionRule(
        tool="execute_command",
        behavior=PermissionBehavior.DENY,
        pattern=r"dd\s+if=.*of=/dev/",
        reason="禁止直接写入设备"
    ),
    PermissionRule(
        tool="execute_command",
        behavior=PermissionBehavior.DENY,
        pattern=r">\s*/dev/sd",
        reason="禁止直接写入磁盘设备"
    ),
]

DEFAULT_ASK_RULES: List[PermissionRule] = [
    # 需要确认的命令
    PermissionRule(
        tool="execute_command",
        behavior=PermissionBehavior.ASK,
        pattern=r"sudo\s+",
        reason="提权操作需要确认"
    ),
    PermissionRule(
        tool="execute_command",
        behavior=PermissionBehavior.ASK,
        pattern=r"chmod\s+(-R\s+)?777",
        reason="危险权限设置需要确认"
    ),
    PermissionRule(
        tool="execute_command",
        behavior=PermissionBehavior.ASK,
        pattern=r"chown\s+(-R\s+)?",
        reason="修改文件所有者需要确认"
    ),
    PermissionRule(
        tool="execute_command",
        behavior=PermissionBehavior.ASK,
        pattern=r"kill\s+(-9\s+|-KILL\s+)",
        reason="强制终止进程需要确认"
    ),
    PermissionRule(
        tool="execute_command",
        behavior=PermissionBehavior.ASK,
        pattern=r"taskkill\s+/[fF]",
        reason="强制终止进程需要确认"
    ),
]

DEFAULT_ALLOW_RULES: List[PermissionRule] = [
    # 安全命令
    PermissionRule(
        tool="execute_command",
        behavior=PermissionBehavior.ALLOW,
        pattern=r"^opencli\s+",
        reason="opencli 命令默认允许"
    ),
    PermissionRule(
        tool="execute_command",
        behavior=PermissionBehavior.ALLOW,
        pattern=r"^lark-cli\s+",
        reason="lark-cli 命令默认允许"
    ),
    PermissionRule(
        tool="execute_command",
        behavior=PermissionBehavior.ALLOW,
        pattern=r"^git\s+",
        reason="git 命令默认允许"
    ),
    PermissionRule(
        tool="execute_command",
        behavior=PermissionBehavior.ALLOW,
        pattern=r"^ls\s*",
        reason="ls 命令默认允许"
    ),
    PermissionRule(
        tool="execute_command",
        behavior=PermissionBehavior.ALLOW,
        pattern=r"^dir\s*",
        reason="dir 命令默认允许"
    ),
    PermissionRule(
        tool="execute_command",
        behavior=PermissionBehavior.ALLOW,
        pattern=r"^cat\s+",
        reason="cat 命令默认允许"
    ),
    PermissionRule(
        tool="execute_command",
        behavior=PermissionBehavior.ALLOW,
        pattern=r"^type\s+",
        reason="type 命令默认允许"
    ),
]

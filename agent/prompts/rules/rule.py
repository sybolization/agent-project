from dataclasses import dataclass
from typing import Optional
from enum import Enum


class RuleScope(Enum):
    ALL = "all"
    EXECUTE = "execute"
    DEFAULT = "default"
    COLLECT = "collect"
    PLAN = "plan"
    REPORT = "report"


@dataclass
class Rule:
    name: str
    content: str
    scope: RuleScope = RuleScope.ALL
    enabled: bool = True
    priority: int = 0
    description: str = ""

    def format_for_prompt(self) -> str:
        if not self.enabled:
            return ""
        return self.content.strip()

    def __lt__(self, other):
        return self.priority < other.priority

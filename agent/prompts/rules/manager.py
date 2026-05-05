import logging
from pathlib import Path
from typing import Optional, List
from .rule import Rule, RuleScope

logger = logging.getLogger(__name__)

_BUILTIN_RULES_DIR = Path(__file__).parent / "builtin"


class RuleManager:
    def __init__(self):
        self._rules: dict[str, Rule] = {}
        self._loaded: bool = False

    def load_builtin_rules(self) -> None:
        if self._loaded:
            return
        self._load_rules_from_dir(_BUILTIN_RULES_DIR)
        self._loaded = True
        logger.info(f"[RuleManager] Loaded {len(self._rules)} builtin rules")

    def _load_rules_from_dir(self, rules_dir: Path) -> None:
        if not rules_dir.exists():
            logger.warning(f"[RuleManager] Rules directory not found: {rules_dir}")
            return
        for rule_file in sorted(rules_dir.glob("*.md")):
            self._load_rule_file(rule_file)

    def _load_rule_file(self, rule_file: Path) -> None:
        try:
            content = rule_file.read_text(encoding="utf-8").strip()
            if not content:
                return
            name = rule_file.stem
            scope = self._parse_scope_from_content(content)
            priority = self._parse_priority_from_content(content)
            description = self._parse_description_from_content(content)
            clean_content = self._clean_metadata(content)
            rule = Rule(
                name=name,
                content=clean_content,
                scope=scope,
                priority=priority,
                description=description,
            )
            self._rules[name] = rule
            logger.debug(f"[RuleManager] Loaded rule: {name} (scope={scope.value}, priority={priority})")
        except Exception as e:
            logger.error(f"[RuleManager] Failed to load rule file {rule_file}: {e}")

    def _parse_scope_from_content(self, content: str) -> RuleScope:
        for line in content.split("\n"):
            line = line.strip().lower()
            if line.startswith("<!-- scope:"):
                scope_str = line.replace("<!-- scope:", "").replace("-->", "").strip()
                try:
                    return RuleScope(scope_str)
                except ValueError:
                    pass
        return RuleScope.ALL

    def _parse_priority_from_content(self, content: str) -> int:
        for line in content.split("\n"):
            line = line.strip().lower()
            if line.startswith("<!-- priority:"):
                priority_str = line.replace("<!-- priority:", "").replace("-->", "").strip()
                try:
                    return int(priority_str)
                except ValueError:
                    pass
        return 0

    def _parse_description_from_content(self, content: str) -> str:
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("<!-- description:"):
                return line.replace("<!-- description:", "").replace("-->", "").strip()
        return ""

    def _clean_metadata(self, content: str) -> str:
        lines = []
        for line in content.split("\n"):
            stripped = line.strip().lower()
            if stripped.startswith("<!-- scope:") or stripped.startswith("<!-- priority:") or stripped.startswith("<!-- description:"):
                continue
            lines.append(line)
        return "\n".join(lines).strip()

    def add_rule(self, rule: Rule) -> None:
        self._rules[rule.name] = rule

    def remove_rule(self, name: str) -> bool:
        if name in self._rules:
            del self._rules[name]
            return True
        return False

    def enable_rule(self, name: str) -> bool:
        if name in self._rules:
            self._rules[name].enabled = True
            return True
        return False

    def disable_rule(self, name: str) -> bool:
        if name in self._rules:
            self._rules[name].enabled = False
            return True
        return False

    def get_rule(self, name: str) -> Optional[Rule]:
        return self._rules.get(name)

    def get_rules_for_phase(self, phase: str) -> List[Rule]:
        self.load_builtin_rules()
        phase_lower = phase.lower()
        matching = []
        for rule in self._rules.values():
            if not rule.enabled:
                continue
            if rule.scope == RuleScope.ALL or rule.scope.value == phase_lower:
                matching.append(rule)
        matching.sort()
        return matching

    def format_rules_for_prompt(self, phase: str) -> str:
        rules = self.get_rules_for_phase(phase)
        if not rules:
            return ""
        sections = []
        for rule in rules:
            formatted = rule.format_for_prompt()
            if formatted:
                sections.append(formatted)
        if not sections:
            return ""
        return "<rules>\n" + "\n\n".join(sections) + "\n</rules>"

    def get_rules_content_for_phase(self, phase: str) -> str:
        rules = self.get_rules_for_phase(phase)
        if not rules:
            return ""
        sections = []
        for rule in rules:
            formatted = rule.format_for_prompt()
            if formatted:
                sections.append(formatted)
        if not sections:
            return ""
        return "\n\n".join(sections)

    def list_rules(self) -> List[dict]:
        self.load_builtin_rules()
        return [
            {
                "name": r.name,
                "scope": r.scope.value,
                "enabled": r.enabled,
                "priority": r.priority,
                "description": r.description,
            }
            for r in sorted(self._rules.values())
        ]

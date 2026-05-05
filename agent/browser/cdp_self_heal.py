import re
from typing import Optional

from .cdp_helpers import CDPHelpers

FORBIDDEN_PATTERNS = [
    re.compile(r'\bsubprocess\b'),
    re.compile(r'\bos\.system\b'),
    re.compile(r'\bos\.popen\b'),
    re.compile(r'\beval\s*\('),
    re.compile(r'\bexec\s*\('),
    re.compile(r'\b__import__\b'),
    re.compile(r"\bopen\s*\([^)]*['\"][wa]\+?['\"]"),
    re.compile(r'\bimport\s+os\b'),
    re.compile(r'\bshutil\b'),
    re.compile(r'\bsocket\b'),
    re.compile(r'\bctypes\b'),
]


class SelfHealEngine:

    def __init__(self, helpers: CDPHelpers):
        self.helpers = helpers

    def detect_missing_function(self, error_message: str) -> Optional[str]:
        patterns = [
            re.compile(r"has no attribute '(\w+)'"),
            re.compile(r"'module' object has no attribute '(\w+)'"),
            re.compile(r"function '(\w+)' not found"),
            re.compile(r"missing function:\s*(\w+)"),
        ]
        for pattern in patterns:
            match = pattern.search(error_message)
            if match:
                return match.group(1)
        return None

    def detect_stale_node_id(self, error_message: str) -> bool:
        return "Could not find node with given id" in error_message or "node not found" in error_message.lower()

    async def heal_stale_node_id(self) -> dict:
        try:
            await self.helpers._cdp._refresh_document_node()
            return {"success": True, "message": "Document node ID refreshed"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def validate_code_safety(self, code: str) -> tuple[bool, str]:
        for pattern in FORBIDDEN_PATTERNS:
            match = pattern.search(code)
            if match:
                return False, f"Forbidden pattern detected: {match.group()}"
        return True, ""

    async def add_function(self, name: str, code: str) -> dict:
        is_safe, reason = self.validate_code_safety(code)
        if not is_safe:
            return {"success": False, "message": reason}
        try:
            success = self.helpers.add_function_from_code(name, code)
            if success:
                return {"success": True, "message": f"Function '{name}' added successfully"}
            else:
                return {"success": False, "message": f"Failed to add function '{name}' (code validation or compilation failed)"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def get_helpers_content(self) -> str:
        return self.helpers.get_helpers_source()

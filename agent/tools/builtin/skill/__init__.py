"""Skill 工具集"""

from .load_skill import tool_definition as load_skill_def
from .load_category import tool_definition as load_category_def
from .load_reference import tool_definition as load_reference_def

SKILL_TOOLS = [load_skill_def, load_category_def, load_reference_def]

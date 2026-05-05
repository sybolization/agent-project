"""技能执行器 - 处理技能加载相关工具调用"""

import logging

from ...skills.manager import SkillManager

logger = logging.getLogger(__name__)


class SkillExecutor:
    """技能执行器

    负责技能系统的工具执行：
    - 加载技能内容
    - 加载技能类别
    - 加载参考文档
    """

    def __init__(self, skill_manager: SkillManager):
        self.skill_manager = skill_manager

    def execute_load_skill(self, call: dict) -> dict:
        """Execute load_skill tool call."""
        skill_name = call["arguments"].get("skill_name", "")
        content = self.skill_manager.load_skill(skill_name)
        if content:
            return {
                "type": "skill_loaded",
                "skill_name": skill_name,
                "content": content
            }
        else:
            descriptions = self.skill_manager.get_skill_descriptions()
            if "/" in skill_name:
                category = skill_name.split("/")[0]
                matching = [d["name"] for d in descriptions if d.get("category") == category]
                if matching:
                    available = ", ".join(matching)
                    message = f"技能 '{skill_name}' 不存在。类别 '{category}' 下的可用技能: {available}"
                else:
                    all_names = [d["name"] for d in descriptions[:20]]
                    available = ", ".join(all_names)
                    message = f"技能 '{skill_name}' 不存在。类别 '{category}' 下没有找到技能。可用技能: {available}"
            else:
                all_names = [d["name"] for d in descriptions[:20]]
                available = ", ".join(all_names)
                message = f"技能 '{skill_name}' 不存在。可用技能: {available}"
            return {
                "type": "error",
                "message": message
            }

    def execute_load_category(self, call: dict) -> dict:
        """Execute load_skill_category tool call."""
        category_name = call["arguments"].get("category_name", "")
        content = self.skill_manager.get_category_skills_prompt(category_name)

        if "未找到类别" in content or "没有技能" in content:
            # 获取可用类别列表
            categories = self.skill_manager.get_categories()
            available = [cat.name for cat in categories]
            return {
                "type": "error",
                "message": f"类别 '{category_name}' 无效。可用类别: {', '.join(available)}"
            }

        return {
            "type": "category_loaded",
            "category_name": category_name,
            "content": content
        }

    def execute_load_reference(self, call: dict) -> dict:
        """Execute load_reference tool call."""
        skill_name = call["arguments"].get("skill_name", "")
        ref_name = call["arguments"].get("reference_name", "")
        content = self.skill_manager.load_reference(skill_name, ref_name)
        if content:
            return {
                "type": "reference_loaded",
                "skill_name": skill_name,
                "reference_name": ref_name,
                "content": content
            }
        else:
            refs = self.skill_manager.list_references(skill_name)
            if refs:
                available = ", ".join(refs)
                message = f"Reference '{ref_name}' not found in skill '{skill_name}'. 可用参考文档: {available}"
            else:
                message = f"Reference '{ref_name}' not found in skill '{skill_name}'. 该技能没有可用的参考文档"
            return {
                "type": "error",
                "message": message
            }

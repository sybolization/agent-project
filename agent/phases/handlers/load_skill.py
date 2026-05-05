"""load_skill 工具结果处理器和格式化器"""

from . import ToolResultHandler, ToolResultFormatter
from ..result import PhaseResult


class LoadSkillHandler(ToolResultHandler):
    """load_skill 工具结果处理器

    处理技能加载结果，成功时将技能添加到状态中。
    """

    tool_name = "load_skill"

    def handle(self, result: dict, state) -> PhaseResult:
        """处理 load_skill 工具结果

        Args:
            result: 工具执行结果字典
            state: Agent状态对象

        Returns:
            PhaseResult: 处理后的阶段结果
        """
        if result.get("type") == "skill_loaded":
            skill_name = result.get("skill_name", "")
            content = result.get("content", "")
            state.add_skill(skill_name, content)
            return PhaseResult(
                status="continue",
                message=f"[OK] 已成功加载技能 '{skill_name}'，内容已注入系统提示词。",
                data={"skill_loaded": skill_name, "content": content}
            )
        return PhaseResult(
            status="error",
            message=f"[X] 加载技能失败: {result.get('message', '未知错误')}"
        )


class LoadSkillFormatter(ToolResultFormatter):
    """load_skill 工具结果格式化器"""

    tool_name = "load_skill"

    def format(self, result: dict) -> str:
        """格式化 load_skill 工具结果

        Args:
            result: 工具执行结果字典

        Returns:
            str: 格式化后的消息文本
        """
        if result.get("type") == "skill_loaded":
            skill_name = result.get("skill_name", "")
            return f"[OK] 已成功加载技能 '{skill_name}'，内容已注入系统提示词。"
        return f"[错误] 加载技能失败: {result.get('message', '未知错误')}"

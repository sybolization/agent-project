"""load_skill_category 工具结果处理器和格式化器"""

from . import ToolResultHandler, ToolResultFormatter
from ..result import PhaseResult


class LoadSkillCategoryHandler(ToolResultHandler):
    """load_skill_category 工具结果处理器

    处理技能类别加载结果，成功时将类别添加到状态中。
    """

    tool_name = "load_skill_category"

    def handle(self, result: dict, state) -> PhaseResult:
        """处理 load_skill_category 工具结果

        Args:
            result: 工具执行结果字典
            state: Agent状态对象

        Returns:
            PhaseResult: 处理后的阶段结果
        """
        if result.get("type") == "category_loaded":
            category_name = result.get("category_name", "")
            content = result.get("content", "")
            state.add_category(category_name, content)
            return PhaseResult(
                status="continue",
                message=f"[OK] 已成功加载类别 '{category_name}'，技能描述已注入系统提示词。\n\n{content}",
                data={"category_loaded": category_name, "content": content}
            )
        return PhaseResult(
            status="error",
            message=f"[X] 加载类别失败: {result.get('message', '未知错误')}"
        )


class LoadSkillCategoryFormatter(ToolResultFormatter):
    """load_skill_category 工具结果格式化器"""

    tool_name = "load_skill_category"

    def format(self, result: dict) -> str:
        """格式化 load_skill_category 工具结果

        Args:
            result: 工具执行结果字典

        Returns:
            str: 格式化后的消息文本
        """
        if result.get("type") == "category_loaded":
            category_name = result.get("category_name", "")
            content = result.get("content", "")
            return f"[OK] 已成功加载类别 '{category_name}'，技能描述已注入系统提示词。\n\n{content}"
        return f"[错误] 加载类别失败: {result.get('message', '未知错误')}"

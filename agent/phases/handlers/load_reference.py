"""load_reference 工具结果处理器和格式化器"""

from . import ToolResultHandler, ToolResultFormatter
from ..result import PhaseResult


class LoadReferenceHandler(ToolResultHandler):
    """load_reference 工具结果处理器

    处理参考文档加载结果，成功时将参考文档添加到状态中。
    """

    tool_name = "load_reference"

    def handle(self, result: dict, state) -> PhaseResult:
        """处理 load_reference 工具结果

        Args:
            result: 工具执行结果字典
            state: Agent状态对象

        Returns:
            PhaseResult: 处理后的阶段结果
        """
        if result.get("type") == "reference_loaded":
            skill_name = result.get("skill_name", "")
            ref_name = result.get("reference_name", "")
            content = result.get("content", "")
            state.add_reference(skill_name, ref_name, content)
            return PhaseResult(
                status="continue",
                message=f"[OK] 已成功加载参考文档 '{skill_name}/{ref_name}'，内容已注入系统提示词。",
                data={"reference_loaded": f"{skill_name}/{ref_name}", "content": content}
            )
        return PhaseResult(
            status="error",
            message=f"[X] 加载参考文档失败: {result.get('message', '未知错误')}"
        )


class LoadReferenceFormatter(ToolResultFormatter):
    """load_reference 工具结果格式化器"""

    tool_name = "load_reference"

    def format(self, result: dict) -> str:
        """格式化 load_reference 工具结果

        Args:
            result: 工具执行结果字典

        Returns:
            str: 格式化后的消息文本
        """
        if result.get("type") == "reference_loaded":
            skill_name = result.get("skill_name", "")
            ref_name = result.get("reference_name", "")
            return f"[OK] 已成功加载参考文档 '{skill_name}/{ref_name}'，内容已注入系统提示词。"
        return f"[错误] 加载参考文档失败: {result.get('message', '未知错误')}"

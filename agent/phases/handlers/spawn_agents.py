"""spawn_agents 工具结果处理器和格式化器"""

from . import ToolResultHandler, ToolResultFormatter
from ..result import PhaseResult


class SpawnAgentsHandler(ToolResultHandler):
    """spawn_agents 工具结果处理器

    处理子 Agent 启动结果。
    """

    tool_name = "spawn_agents"

    def handle(self, result: dict, state) -> PhaseResult:
        """处理 spawn_agents 工具结果

        Args:
            result: 工具执行结果字典
            state: Agent状态对象

        Returns:
            PhaseResult: 处理后的阶段结果
        """
        if result.get("type") == "agents_spawned":
            total = result.get("total_agents", 0)
            completed = result.get("completed", 0)
            failed = result.get("failed", 0)
            summary_msg = f"[OK] 子Agent执行完成 ({total}个代理: {completed}成功, {failed}失败)"
            return PhaseResult(
                status="continue",
                message=summary_msg,
                data={"agents_spawned": result.get("total_agents", 0), "results": result.get("results", [])}
            )
        return PhaseResult(
            status="continue",
            message=f"[X] 子Agent启动失败: {result.get('message', '未知错误')}",
            data={"error": result.get("message")}
        )


class SpawnAgentsFormatter(ToolResultFormatter):
    """spawn_agents 工具结果格式化器

    生成包含各子代理详细结果的格式化消息。
    """

    tool_name = "spawn_agents"

    def format(self, result: dict) -> str:
        """格式化 spawn_agents 工具结果

        Args:
            result: 工具执行结果字典

        Returns:
            str: 格式化后的消息文本
        """
        if result.get("type") == "agents_spawned":
            total = result.get("total_agents", 0)
            completed = result.get("completed", 0)
            failed = result.get("failed", 0)
            header = f"[OK] 子Agent执行完成 ({total}个代理: {completed}成功, {failed}失败)"
            agent_results = result.get("results", [])
            if not agent_results:
                return header
            parts = [header, ""]
            for idx, ar in enumerate(agent_results, 1):
                parts.append(f"--- 子代理 {idx} ---")
                parts.append(f"任务: {ar.get('task', '未知任务')}")
                status_text = "完成" if ar.get("status") == "completed" else "失败"
                parts.append(f"状态: {status_text}")
                summary = ar.get("summary")
                if summary:
                    parts.append(f"摘要: {summary}")
                error = ar.get("error")
                if error:
                    parts.append(f"错误: {error}")
                partial = ar.get("partial_results")
                if partial:
                    partial_str = str(partial)[:4000]
                    parts.append("关键数据:")
                    parts.append(partial_str)
                parts.append("")
            return "\n".join(parts)
        elif result.get("type") == "error":
            return f"[错误] 子Agent启动失败: {result.get('message', '未知错误')}"
        return f"工具 spawn_agents 执行结果: {result}"

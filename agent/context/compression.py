"""上下文工具 - Token估算和分级上下文压缩

三级渐进式压缩策略：
- L1 compact_by_rounds: 按轮次保留最近N轮，更早消息替换为简短摘要（零额外成本）
- L2 compress_context: LLM生成结构化摘要，保留关键状态（复用现有模型）
- L3 emergency_compact: 紧急压缩，仅保留摘要+最近2轮对话（最后手段）

结构化上下文组织：
- 状态区：当前阶段、TODO进度、执行计划等关键状态（压缩时完整保留）
- 历史区：早期对话历史（可压缩）
- 工作区：最近N轮对话（保留最近记录）
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Callable

import yaml

from ..config import (
    MAX_RESULT_LENGTH, 
    CONTEXT_KEEP_ROUNDS,
    CONTEXT_COMPRESS_THRESHOLD,
    CONTEXT_WINDOW_MAX,
    COMPRESSION_ENABLED
)

logger = logging.getLogger(__name__)

TRANSCRIPT_DIR = Path(__file__).parent.parent.parent / ".transcripts"


def compress_opencli_result(command: str, output: str, max_length: int = MAX_RESULT_LENGTH) -> str:
    if not output:
        return output
    
    if len(output) <= max_length:
        return output
    
    cmd_parts = command.split()
    subcommand = cmd_parts[0] if cmd_parts else ""
    
    if subcommand == "list":
        try:
            data = yaml.safe_load(output)
            if isinstance(data, list):
                sites = set()
                for item in data:
                    if isinstance(item, dict) and "site" in item:
                        sites.add(item["site"])
                site_list = sorted(sites)
                return f"[共 {len(site_list)} 个站点]\n站点列表: {', '.join(site_list)}"
        except Exception:
            pass
    
    lines = output.split("\n")
    if len(lines) > 50:
        return "\n".join(lines[:30]) + f"\n\n... [已省略 {len(lines) - 50} 行] ...\n" + "\n".join(lines[-20:])
    
    return output[:max_length] + f"\n\n... [已截断，原始长度: {len(output)} 字符]"


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - chinese_chars
    return chinese_chars + other_chars // 4


def estimate_context_tokens(context: list[dict], system_prompt: str = "") -> int:
    total = estimate_tokens(system_prompt)
    for msg in context:
        total += estimate_tokens(msg.get("content", ""))
        
        if "tool_calls" in msg:
            for tc in msg["tool_calls"]:
                if isinstance(tc, dict):
                    total += estimate_tokens(tc.get("id", ""))
                    if "function" in tc:
                        total += estimate_tokens(tc["function"].get("name", ""))
                        total += estimate_tokens(tc["function"].get("arguments", ""))
        
        if "tool_call_id" in msg:
            total += estimate_tokens(msg.get("tool_call_id", ""))
    
    return total


def _identify_rounds(context: list[dict]) -> list[tuple[int, int]]:
    """识别对话轮次边界
    
    一轮对话 = user消息 + assistant回复(可能含tool_calls) + tool结果
    
    Returns:
        每轮的 (start_index, end_index) 列表
    """
    rounds = []
    round_start = None
    
    for i, msg in enumerate(context):
        role = msg.get("role", "")
        
        if role == "user":
            if round_start is not None:
                rounds.append((round_start, i - 1))
            round_start = i
    
    if round_start is not None:
        rounds.append((round_start, len(context) - 1))
    
    return rounds


def _summarize_message(msg: dict) -> str:
    """将单条消息压缩为简短摘要"""
    role = msg.get("role", "")
    content = msg.get("content", "")
    
    if role == "user":
        preview = content[:80].replace('\n', ' ')
        return f"[用户] {preview}{'...' if len(content) > 80 else ''}"
    
    elif role == "assistant":
        tool_calls = msg.get("tool_calls", [])
        if tool_calls:
            tool_names = []
            for tc in tool_calls:
                if isinstance(tc, dict):
                    func = tc.get("function", {})
                    name = func.get("name", "")
                    args = func.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    if name == "opencli" and isinstance(args, dict):
                        cmd = args.get("command", "")
                        tool_names.append(f"opencli({cmd[:200]})")
                    else:
                        tool_names.append(name)
            return f"[助手→调用工具] {', '.join(tool_names)}"
        preview = content[:80].replace('\n', ' ')
        return f"[助手] {preview}{'...' if len(content) > 80 else ''}"
    
    elif role == "tool":
        is_success = "成功" in content or "Success" in content or "[OK]" in content
        is_error = "失败" in content or "Error" in content or "[X]" in content or "[错误]" in content

        ref_matches = re.findall(r'\[ref:\d+\]', content)
        ref_info = f" (引用: {', '.join(ref_matches[:5])})" if ref_matches else ""

        if is_success:
            key_info = ""
            for line in content.split('\n')[:5]:
                if any(kw in line for kw in ["标题", "title", "结果", "result", "找到", "found"]):
                    key_info = f": {line.strip()[:60]}"
                    break
            return f"[工具结果] 成功{key_info}{ref_info}"
        elif is_error:
            preview = content[:60].replace('\n', ' ')
            return f"[工具结果] 失败: {preview}"
        preview = content[:60].replace('\n', ' ')
        return f"[工具结果] {preview}{'...' if len(content) > 60 else ''}{ref_info}"
    
    elif role == "system":
        preview = content[:60].replace('\n', ' ')
        return f"[系统] {preview}{'...' if len(content) > 60 else ''}"
    
    return f"[{role}] {content[:40]}"


def compact_by_rounds(
    context: list[dict],
    keep_rounds: int = CONTEXT_KEEP_ROUNDS,
    keep_tool_results: int = 3,
) -> list[dict]:
    """L1 轻量压缩：按轮次保留最近N轮完整对话，更早消息替换为摘要
    
    Args:
        context: 对话上下文
        keep_rounds: 保留最近几轮完整对话
        keep_tool_results: 保留最近几个工具结果的完整内容
    
    Returns:
        压缩后的上下文
    """
    if not context:
        return []
    
    rounds = _identify_rounds(context)
    
    if not rounds or len(rounds) <= keep_rounds:
        return _compact_long_content(context, keep_tool_results)
    
    split_point = rounds[-keep_rounds][0]
    
    old_messages = context[:split_point]
    recent_messages = context[split_point:]
    
    summary_lines = []
    for msg in old_messages:
        summary_lines.append(_summarize_message(msg))
    
    old_summary = "[早期对话摘要]\n" + "\n".join(summary_lines)
    
    compressed = [{"role": "system", "content": old_summary}]
    
    recent_compressed = _compact_long_content(recent_messages, keep_tool_results)
    compressed.extend(recent_compressed)
    
    return compressed


def _compact_long_content(
    messages: list[dict],
    keep_tool_results: int = 3,
    max_content_length: int = 4000,
) -> list[dict]:
    """压缩过长内容，保留最近N个工具结果的完整内容"""
    tool_result_count = 0
    total_tool_results = sum(1 for m in messages if m.get("role") == "tool")
    
    compressed = []
    for msg in reversed(messages):
        new_msg = {"role": msg["role"]}
        content = msg.get("content", "")
        
        if msg.get("role") == "tool":
            tool_result_count += 1
            if tool_result_count > keep_tool_results and len(content) > 500:
                is_success = "成功" in content or "[OK]" in content
                is_error = "失败" in content or "[错误]" in content or "[X]" in content
                if is_success:
                    new_msg["content"] = "[工具结果已压缩: 执行成功]"
                elif is_error:
                    new_msg["content"] = content[:300] + "\n...[已压缩]"
                else:
                    new_msg["content"] = content[:300] + "\n...[已压缩]"
            elif len(content) > max_content_length:
                new_msg["content"] = content[:max_content_length] + f"\n\n... [已截断，原始长度: {len(content)}]"
            else:
                new_msg["content"] = content
        elif len(content) > max_content_length:
            new_msg["content"] = content[:max_content_length] + f"\n\n... [已截断，原始长度: {len(content)}]"
        else:
            new_msg["content"] = content
        
        if "tool_calls" in msg:
            new_msg["tool_calls"] = msg["tool_calls"]
        if "tool_call_id" in msg:
            new_msg["tool_call_id"] = msg["tool_call_id"]
        
        compressed.append(new_msg)
    
    compressed.reverse()
    return compressed


def _build_state_snapshot(agent_state) -> str:
    """从 AgentState 构建状态快照摘要
    
    Args:
        agent_state: AgentState 实例
    
    Returns:
        结构化的状态快照字符串
    """
    parts = []
    
    parts.append(f"当前阶段: {agent_state.phase.value}")
    
    if agent_state.loaded_skills:
        parts.append(f"已加载技能: {', '.join(sorted(agent_state.loaded_skills))}")
    
    if agent_state.todos.items:
        todo_lines = []
        progress = agent_state.get_todo_progress()
        for todo in agent_state.todos.items:
            status_icon = {"pending": "⬜", "in_progress": "🔄", "completed": "✅"}.get(
                todo.get("status", "pending"), "⬜"
            )
            todo_lines.append(f"  {status_icon} [{todo.get('id', '?')}] {todo.get('content', '')} ({todo.get('status', 'pending')})")
        parts.append(f"TODO进度 ({progress['completed']}/{progress['total']}):\n" + "\n".join(todo_lines))
    
    if agent_state.phase_summaries:
        for phase_name, summary in agent_state.phase_summaries.items():
            parts.append(f"[{phase_name}阶段摘要] {summary[:200]}")

    if hasattr(agent_state, 'action_history') and agent_state.action_history:
        recent_actions = agent_state.action_history[-15:]
        action_lines = []
        for i, action in enumerate(recent_actions, 1):
            tool_name = action.get("tool_name", "")
            args = action.get("arguments", {})
            result_summary = action.get("result_summary", "")
            if tool_name == "opencli":
                cmd = args.get("command", "")
                args_summary = cmd[:80]
            else:
                args_summary = ", ".join(f"{k}={v}" for k, v in list(args.items())[:3])
            action_lines.append(f"  {i}. {tool_name}: {args_summary} → {result_summary}")
        parts.append(f"已执行操作 (最近{len(recent_actions)}条):\n" + "\n".join(action_lines))

    return "\n".join(parts)


def _build_llm_summary_prompt(
    state_snapshot: str,
    history_summary: str,
    recent_messages: list[dict]
) -> str:
    """构建 LLM 摘要生成的提示
    
    Args:
        state_snapshot: 状态快照
        history_summary: 历史摘要
        recent_messages: 最近消息列表
    
    Returns:
        LLM 提示字符串
    """
    prompt = """请为以下对话生成一个结构化摘要，用于上下文压缩。

要求：
1. 摘要必须包含以下部分：
   - 当前阶段和任务状态
   - TODO 进度详情（已完成/总数）
   - 关键发现和结论
   - **重要提醒**：必须调用 task_complete 工具来结束任务

2. 摘要应该简洁明了，突出关键信息

3. 格式示例：
## 当前状态
- 阶段: EXECUTE
- TODO: 3/5 已完成

## 执行计划
1. 收集信息 ✓
2. 制定计划 ✓
3. 执行任务A (进行中)
4. 执行任务B (待处理)
5. 总结报告 (待处理)

## 关键发现
- 发现1: ...
- 发现2: ...

## 重要提醒
任务完成后必须调用 task_complete 工具结束任务！

---

以下是当前状态和历史信息：

"""
    
    if state_snapshot:
        prompt += f"【状态快照】\n{state_snapshot}\n\n"
    
    if history_summary:
        prompt += f"【历史摘要】\n{history_summary}\n\n"
    
    if recent_messages:
        prompt += "【最近对话】\n"
        for msg in recent_messages[-4:]:
            role = msg.get("role", "")
            content = msg.get("content", "")[:200]
            prompt += f"[{role}] {content}\n"
    
    return prompt


async def _generate_llm_summary(
    llm_interface,
    prompt: str
) -> str:
    """调用 LLM 生成摘要
    
    Args:
        llm_interface: LLM 接口实例
        prompt: 提示字符串
    
    Returns:
        LLM 生成的摘要
    """
    if llm_interface is None:
        logger.warning("LLM interface not provided, falling back to basic summary")
        return None
    
    try:
        messages = [{"role": "user", "content": prompt}]
        
        response = await llm_interface.chat(
            messages=messages,
            temperature=0.3,  # 使用较低温度以获得更稳定的摘要
            max_tokens=1500
        )
        
        if response and "content" in response:
            summary = response["content"]
            logger.info(f"LLM summary generated: {len(summary)} chars")
            return summary
        else:
            logger.warning("LLM response format unexpected")
            return None
            
    except Exception as e:
        logger.error(f"Failed to generate LLM summary: {e}")
        return None


def _organize_context_regions(
    messages: list[dict],
    keep_rounds: int = 4
) -> dict:
    """组织上下文区域
    
    将上下文分为三个区域：
    - 状态区：系统消息和关键状态信息
    - 历史区：早期对话历史
    - 工作区：最近N轮对话
    
    Args:
        messages: 消息列表
        keep_rounds: 工作区保留的轮次数
    
    Returns:
        包含三个区域的字典
    """
    regions = {
        "state_zone": [],  # 状态区
        "history_zone": [],  # 历史区
        "work_zone": []  # 工作区
    }
    
    # 提取系统消息作为状态区
    for msg in messages:
        if msg.get("role") == "system":
            regions["state_zone"].append(msg)
    
    # 识别对话轮次
    rounds = _identify_rounds(messages)
    
    if not rounds:
        # 如果没有识别到轮次，所有非系统消息放入工作区
        regions["work_zone"] = [m for m in messages if m.get("role") != "system"]
        return regions
    
    # 划分历史区和工作区
    if len(rounds) > keep_rounds:
        split_point = rounds[-keep_rounds][0]
        regions["history_zone"] = [m for m in messages[:split_point] if m.get("role") != "system"]
        regions["work_zone"] = [m for m in messages[split_point:] if m.get("role") != "system"]
    else:
        # 如果轮次较少，所有非系统消息放入工作区
        regions["work_zone"] = [m for m in messages if m.get("role") != "system"]
    
    return regions


async def compress_context(
    messages: list[dict],
    agent_state=None,
    session_memory=None,
    llm_interface=None,
) -> list[dict]:
    """L2 LLM智能压缩：调用LLM生成结构化摘要
    
    采用结构化上下文组织：
    - 状态区：完整保留（系统消息、关键状态）
    - 历史区：压缩为LLM摘要
    - 工作区：保留最近N轮对话
    
    Args:
        messages: 对话消息列表
        agent_state: AgentState 实例（用于提取关键状态）
        session_memory: SessionMemory 实例（可选）
        llm_interface: LLM 接口实例（用于生成智能摘要）
    
    Returns:
        压缩后的消息列表
    """
    # 组织上下文区域
    regions = _organize_context_regions(messages, keep_rounds=4)
    
    # 构建状态快照（状态区）
    state_snapshot = ""
    if agent_state is not None:
        state_snapshot = _build_state_snapshot(agent_state)
    elif session_memory is not None:
        state_snapshot = session_memory.to_summary()
    
    # 构建历史摘要（历史区）
    history_summary_parts = []
    
    # 提取工具调用摘要
    tool_call_summary = []
    for msg in regions["history_zone"]:
        role = msg.get("role", "")
        if role == "assistant" and "tool_calls" in msg:
            for tc in msg["tool_calls"]:
                if isinstance(tc, dict):
                    func = tc.get("function", {})
                    name = func.get("name", "")
                    args = func.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    if name == "opencli" and isinstance(args, dict):
                        cmd = args.get("command", "")
                        tool_call_summary.append(f"opencli: {cmd[:60]}")
                    elif name:
                        tool_call_summary.append(name)
    
    if tool_call_summary:
        history_summary_parts.append("已执行工具调用:\n" + "\n".join(f"  - {t}" for t in tool_call_summary[-15:]))
    
    # 提取错误摘要
    error_summary = []
    for msg in regions["history_zone"]:
        content = msg.get("content", "")
        if any(kw in content for kw in ["失败", "[错误]", "[X]", "Error"]):
            preview = content[:100].replace('\n', ' ')
            error_summary.append(preview)
    
    if error_summary:
        history_summary_parts.append("遇到的错误:\n" + "\n".join(f"  - {e}" for e in error_summary[-5:]))
    
    history_summary = "\n\n".join(history_summary_parts) if history_summary_parts else "无详细历史"
    
    # 尝试使用 LLM 生成智能摘要
    llm_summary = None
    if llm_interface is not None:
        prompt = _build_llm_summary_prompt(state_snapshot, history_summary, regions["work_zone"])
        llm_summary = await _generate_llm_summary(llm_interface, prompt)
    
    # 构建压缩后的上下文
    compressed = []
    
    # 保留状态区（系统消息）
    compressed.extend(regions["state_zone"])
    
    # 添加摘要消息
    if llm_summary:
        # 使用 LLM 生成的智能摘要
        summary_content = f"[LLM智能压缩摘要]\n\n{llm_summary}"
    else:
        # 回退到基础摘要
        summary_content = f"[对话历史摘要]\n\n{state_snapshot}\n\n{history_summary}" if state_snapshot else f"[对话历史摘要]\n\n{history_summary}"
    
    compressed.append({"role": "system", "content": summary_content})
    
    # 保留工作区（最近对话）
    compressed.extend(regions["work_zone"])
    
    return compressed


def emergency_compact(
    messages: list[dict],
    agent_state=None,
    session_memory=None,
) -> list[dict]:
    """L3 紧急压缩：仅保留摘要 + 最近2轮对话
    
    Args:
        messages: 对话消息列表
        agent_state: AgentState 实例
        session_memory: SessionMemory 实例（可选）
    
    Returns:
        压缩后的消息列表
    """
    state_snapshot = ""
    if agent_state is not None:
        state_snapshot = _build_state_snapshot(agent_state)
    elif session_memory is not None:
        state_snapshot = session_memory.to_summary()
    
    summary_content = f"[紧急上下文压缩 - 状态快照]\n\n{state_snapshot}" if state_snapshot else "[紧急上下文压缩 - 无状态快照]"
    
    compressed = [{"role": "system", "content": summary_content}]
    
    rounds = _identify_rounds(messages)
    if len(rounds) >= 2:
        last_two_start = rounds[-2][0]
        recent = messages[last_two_start:]
    else:
        recent = messages[-6:] if len(messages) > 6 else messages
    
    compressed.extend(recent)
    
    return compressed


def save_transcript(messages: list, session_id: str) -> Path:
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"transcript_{timestamp}_{session_id}.jsonl"
    filepath = TRANSCRIPT_DIR / filename
    with open(filepath, 'w', encoding='utf-8') as f:
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False) + '\n')
    return filepath


def load_transcript(path: Path) -> list:
    messages = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                messages.append(json.loads(line))
    return messages


@dataclass
class CompressionStats:
    """压缩统计信息"""
    original_tokens: int = 0
    final_tokens: int = 0
    compression_count: int = 0
    levels_used: List[str] = field(default_factory=list)
    transcript_path: Optional[str] = None
    
    @property
    def tokens_saved(self) -> int:
        """节省的 token 数"""
        return max(0, self.original_tokens - self.final_tokens)
    
    @property
    def compression_ratio(self) -> float:
        """压缩比率"""
        if self.original_tokens == 0:
            return 0.0
        return self.final_tokens / self.original_tokens


class ContextCompressor:
    """上下文压缩器 - 封装三级压缩策略的决策和执行逻辑
    
    三级渐进式压缩策略：
    - L1 compact_by_rounds: 按轮次保留最近N轮，更早消息替换为简短摘要（零额外成本）
    - L2 compress_context: LLM生成结构化摘要，保留关键状态（复用现有模型）
    - L3 emergency_compact: 紧急压缩，仅保留摘要+最近2轮对话（最后手段）
    """
    
    def __init__(
        self,
        compression_enabled: bool = COMPRESSION_ENABLED,
        compress_threshold: int = CONTEXT_COMPRESS_THRESHOLD,
        context_window_max: int = CONTEXT_WINDOW_MAX,
        keep_rounds: int = CONTEXT_KEEP_ROUNDS,
    ):
        """初始化压缩器
        
        Args:
            compression_enabled: 是否启用压缩
            compress_threshold: 触发压缩的 token 阈值
            context_window_max: 上下文窗口最大值
            keep_rounds: L1 压缩保留的轮次数
        """
        self.compression_enabled = compression_enabled
        self.compress_threshold = compress_threshold
        self.context_window_max = context_window_max
        self.keep_rounds = keep_rounds
        self._compression_count = 0
    
    async def compress_if_needed(
        self,
        context: List[dict],
        system_prompt: str,
        agent_state=None,
        session_memory=None,
        llm_interface=None,
        update_memory_callback: Optional[Callable] = None,
        iteration_id: Optional[str] = None,
    ) -> tuple[List[dict], CompressionStats]:
        """根据需要执行上下文压缩
        
        Args:
            context: 对话上下文
            system_prompt: 系统提示
            agent_state: AgentState 实例
            session_memory: SessionMemory 实例
            llm_interface: LLM 接口实例
            update_memory_callback: 更新会话内存的回调函数
            iteration_id: 迭代 ID（用于保存 transcript）
        
        Returns:
            (压缩后的上下文, 压缩统计信息)
        """
        stats = CompressionStats()
        
        if not self.compression_enabled:
            stats.original_tokens = estimate_context_tokens(context, system_prompt)
            stats.final_tokens = stats.original_tokens
            return context, stats
        
        current_tokens = estimate_context_tokens(context, system_prompt)
        stats.original_tokens = current_tokens
        
        if current_tokens <= self.compress_threshold:
            stats.final_tokens = current_tokens
            return context, stats
        
        logger.info(f"Context tokens {current_tokens} > {self.compress_threshold}, compressing...")
        
        if iteration_id:
            transcript_path = save_transcript(context, iteration_id)
            stats.transcript_path = str(transcript_path)
            logger.info(f"Transcript saved to: {transcript_path}")
        
        context = compact_by_rounds(
            context,
            keep_rounds=self.keep_rounds
        )
        after_l1 = estimate_context_tokens(context, system_prompt)
        stats.levels_used.append("L1")
        logger.info(f"L1 compact_by_rounds: {current_tokens} -> {after_l1} tokens")
        
        if after_l1 > self.compress_threshold:
            if update_memory_callback:
                update_memory_callback()
            
            context = await compress_context(
                context,
                agent_state=agent_state,
                session_memory=session_memory,
                llm_interface=llm_interface,
            )
            after_l2 = estimate_context_tokens(context, system_prompt)
            stats.levels_used.append("L2")
            logger.info(f"L2 compress_context: {after_l1} -> {after_l2} tokens")
            
            if after_l2 > self.context_window_max:
                context = emergency_compact(
                    context,
                    agent_state=agent_state,
                    session_memory=session_memory
                )
                after_l3 = estimate_context_tokens(context, system_prompt)
                stats.levels_used.append("L3")
                logger.info(f"L3 emergency_compact: {after_l2} -> {after_l3} tokens")
        
        self._compression_count += 1
        stats.compression_count = self._compression_count
        stats.final_tokens = estimate_context_tokens(context, system_prompt)
        
        logger.info(
            f"Context compressed: {stats.original_tokens} -> {stats.final_tokens} tokens "
            f"(compression #{stats.compression_count}, levels: {' -> '.join(stats.levels_used)})"
        )
        
        return context, stats

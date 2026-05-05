"""Agent配置常量"""
import os
from pathlib import Path

from .llm.config import LMStudioConfig, DeepSeekConfig


# ============================================================================
# 上下文压缩配置
# ============================================================================
# 三级压缩机制说明：
# - L1 压缩（轻量压缩）：当上下文超过 CONTEXT_COMPRESS_THRESHOLD 时触发
#   使用 compact_by_rounds 保留最近 N 轮对话
# - L2 压缩（智能摘要）：当 L1 压缩后仍超过 CONTEXT_COMPRESS_THRESHOLD 时触发
#   使用 LLM 生成结构化摘要，需要 COMPRESSION_ENABLED=True
# - L3 压缩（紧急压缩）：当 L2 压缩后仍超过 CONTEXT_WINDOW_MAX 时触发
#   仅保留摘要 + 最近 2 轮对话

# 上下文压缩触发阈值（字符数）
# 当上下文长度超过此阈值时，触发 L1 压缩机制
# L1 压缩后若仍超过此阈值，则继续触发 L2 压缩
# 默认值 60000 字符，约 15000-20000 tokens
CONTEXT_COMPRESS_THRESHOLD = 60000

# 压缩时保留的对话轮次数
# 在 L1/L3 压缩策略中，保留最近的 N 轮对话，防止关键信息丢失
# 默认值 10 轮，确保保留足够的上下文历史
CONTEXT_KEEP_ROUNDS = 10

# 上下文窗口最大容量（字符数）
# L3 紧急压缩的触发阈值
# 当 L2 压缩后上下文仍超过此值时，执行 L3 紧急压缩
# 默认值 40000 字符，约 10000-13000 tokens
CONTEXT_WINDOW_MAX = 40000

# 是否启用 L2 智能压缩功能
# 注意：此配置仅控制 L2 压缩（LLM 摘要），L1 和 L3 压缩始终可用
# 默认值 False，需要 LLM 支持才能启用
COMPRESSION_ENABLED = False


# ============================================================================
# 工具执行配置
# ============================================================================

# 单个工具调用结果的最大长度（字符数）
# 限制工具结果的显示长度，防止过长内容影响上下文
# 默认值 8000 字符，超出部分将被截断
MAX_RESULT_LENGTH = 8000

# Agent 最大执行迭代次数
# 防止 Agent 无限循环，作为主循环的终止条件
# 默认值 30 次迭代，适用于大多数任务场景
MAX_ITERATIONS = 30

# Subagent 最大执行迭代次数
# 防止 Subagent 无限循环，作为子Agent循环的终止条件
# 默认值 5 次迭代，适用于大多数子任务场景
# 可根据任务复杂度调整此值
SUBAGENT_MAX_ITERATIONS = 20


# ============================================================================
# 阶段转换配置
# ============================================================================

# 阶段转换时保留的对话轮次数
# 在阶段转换时的轻量级压缩中，保留最近的 N 轮对话
# 默认值 5 轮，比 CONTEXT_KEEP_ROUNDS 更激进，减少上下文负担
TRANSITION_KEEP_ROUNDS = 5

# 阶段转换时内容截断的最大长度（字符数）
# 在阶段转换时截断过长内容，保留关键信息
# 默认值 1000 字符，用于轻量级压缩场景
TRANSITION_CONTENT_TRUNCATE_LENGTH = 1000


# ============================================================================
# 网页内容获取配置
# ============================================================================

# 是否启用网页内容获取功能
# 控制是否允许 Agent 从网页获取内容
# 默认值 False，已关闭（CLI 命令已自带结构化结果，无需额外抓取）
WEB_CONTENT_FETCH_ENABLED = False

# 获取网页内容的最大长度（字符数）
# 限制从网页获取的内容长度，超出则截断
# 默认值 8000 字符，平衡信息完整性和上下文限制
WEB_CONTENT_MAX_LENGTH = 20000

# 网页内容获取的超时时间（秒）
# 防止网页请求无限期等待
# 默认值 30 秒，适用于大多数网页加载场景
WEB_CONTENT_FETCH_TIMEOUT = 30


# ============================================================================
# 工具结果保留配置
# ============================================================================

# 轻量压缩中保留最近工具结果的数量
# 在 _compact_long_content 函数中，控制保留完整工具结果的数量
# 默认值 3 个，确保最近的关键工具结果不被压缩
KEEP_RECENT_TOOL_RESULTS = 3



class LLMConfig:
    """LLM 提供商统一配置类"""

    _provider_env = os.getenv("LLM_PROVIDER", "").lower()
    PROVIDER = _provider_env if _provider_env else ("deepseek" if DeepSeekConfig.is_configured() else "lmstudio")
    CDP_SCREENSHOT_ENABLED = os.getenv("CDP_SCREENSHOT_ENABLED", "false").lower() == "true"

    @classmethod
    def get_provider_config(cls):
        if cls.PROVIDER == "deepseek":
            return DeepSeekConfig
        return LMStudioConfig

    @classmethod
    def is_deepseek(cls) -> bool:
        return cls.PROVIDER == "deepseek"

    @classmethod
    def is_lmstudio(cls) -> bool:
        return cls.PROVIDER == "lmstudio"


# ============================================================================
# 浏览器锁配置
# ============================================================================

# 是否启用浏览器锁
# 控制是否在执行浏览器命令时使用互斥锁
# 默认值 True，启用浏览器锁机制
BROWSER_LOCK_ENABLED = True

# 浏览器锁获取超时时间（秒）
# 当尝试获取浏览器锁时，超过此时间将抛出异常
# 默认值 120 秒，适用于大多数浏览器操作场景
BROWSER_LOCK_TIMEOUT = 120.0


# ============================================================================
# OpenCLI Live 模式配置
# ============================================================================

# 是否启用 OpenCLI Live 模式
# 启用后，OpenCLI 命令执行完成后不会关闭浏览器自动化窗口
# 这允许 Agent 在命令执行后通过 daemon API 获取页面内容
# 默认值 True，启用 Live 模式
OPENCLI_LIVE_ENABLED = True


# ============================================================================
# 容器配置
# ============================================================================

# 使用延迟导入避免循环依赖
# from .container.container_config import ContainerConfig

def get_container_config():
    """延迟加载 ContainerConfig 以避免循环导入"""
    from .container.container_config import ContainerConfig
    return ContainerConfig()

# 容器配置实例（延迟初始化）
_CONTAINER_CONFIG = None

def get_default_container_config():
    """获取默认容器配置实例"""
    global _CONTAINER_CONFIG
    if _CONTAINER_CONFIG is None:
        _CONTAINER_CONFIG = get_container_config()
    return _CONTAINER_CONFIG

# 为了向后兼容，保留 CONTAINER_CONFIG 变量
# 但使用 property 来延迟加载
class _ContainerConfigProxy:
    """ContainerConfig 代理类，支持延迟加载"""
    def __getattr__(self, name):
        return getattr(get_default_container_config(), name)

CONTAINER_CONFIG = _ContainerConfigProxy()

"""Browser Lock Module - 浏览器命令锁

提供全局浏览器锁，确保 OpenCLI 命令串行执行。
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class BrowserLockTimeoutError(Exception):
    """浏览器锁超时异常

    当获取浏览器锁超时时抛出此异常。

    Attributes:
        timeout: 超时时间（秒）
        message: 错误消息
    """

    def __init__(self, timeout: float, message: Optional[str] = None):
        self.timeout = timeout
        self.message = message or f"获取浏览器锁超时，超时时间: {timeout} 秒"
        super().__init__(self.message)


class BrowserLock:
    """浏览器命令锁

    提供浏览器级别的互斥锁，确保同一时刻只有一个协程可以执行浏览器操作。

    注意：此类使用单例模式，通过 __new__ 方法确保全局只有一个实例。
    锁会根据事件循环自动适配，支持 pytest-asyncio 等为每个测试创建新事件循环的场景。

    使用示例:
        # 方式一：使用上下文管理器
        async with get_browser_lock() as lock:
            await browser_operation()

        # 方式二：手动获取和释放
        lock = get_browser_lock()
        try:
            await lock.acquire(timeout=60.0)
            await browser_operation()
        finally:
            lock.release()
    """

    _instance: Optional["BrowserLock"] = None

    def __new__(cls) -> "BrowserLock":
        """单例模式：确保全局只有一个 BrowserLock 实例"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._lock = None
            cls._instance._current_loop_id = None
        return cls._instance

    def __init__(self):
        """初始化浏览器锁"""
        pass

    def _get_lock(self) -> asyncio.Lock:
        """获取当前事件循环的锁

        如果锁不存在或事件循环变化，则创建新锁。

        Returns:
            asyncio.Lock 实例
        """
        try:
            current_loop = asyncio.get_running_loop()
            current_loop_id = id(current_loop)
        except RuntimeError:
            current_loop = None
            current_loop_id = None

        if self._lock is None or self._current_loop_id != current_loop_id:
            self._lock = asyncio.Lock()
            self._current_loop_id = current_loop_id
            if current_loop_id is not None:
                logger.debug(f"[BrowserLock] 为事件循环 {current_loop_id} 创建新锁")
            else:
                logger.debug("[BrowserLock] 创建新锁（无运行中的事件循环）")

        return self._lock

    async def acquire(self, timeout: float = 120.0) -> bool:
        """获取浏览器锁

        Args:
            timeout: 获取锁的超时时间（秒）

        Returns:
            True 表示成功获取锁

        Raises:
            BrowserLockTimeoutError: 当获取锁超时时抛出
        """
        lock = self._get_lock()
        logger.debug(f"[BrowserLock] 尝试获取锁，超时: {timeout}s")

        try:
            await asyncio.wait_for(lock.acquire(), timeout=timeout)
            logger.debug("[BrowserLock] 锁获取成功")
            return True
        except asyncio.TimeoutError:
            logger.warning(f"[BrowserLock] 获取锁超时: {timeout}s")
            raise BrowserLockTimeoutError(timeout=timeout)

    def release(self) -> None:
        """释放浏览器锁"""
        if self._lock is None:
            logger.warning("[BrowserLock] 尝试释放未初始化的锁")
            return

        if self._lock.locked():
            self._lock.release()
            logger.debug("[BrowserLock] 锁已释放")
        else:
            logger.warning("[BrowserLock] 尝试释放未持有的锁")

    async def __aenter__(self) -> "BrowserLock":
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()

    @property
    def is_locked(self) -> bool:
        """检查锁是否被占用"""
        if self._lock is None:
            return False
        return self._lock.locked()

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例实例

        用于测试场景，重置单例实例。
        """
        global _browser_lock
        cls._instance = None
        _browser_lock = None
        logger.debug("[BrowserLock] 单例实例已重置")


_browser_lock: Optional[BrowserLock] = None


def get_browser_lock() -> BrowserLock:
    """获取全局浏览器锁实例

    Returns:
        BrowserLock 实例
    """
    global _browser_lock
    if _browser_lock is None:
        _browser_lock = BrowserLock()
    return _browser_lock


def reset_browser_lock() -> None:
    """重置浏览器锁

    用于测试场景，重置模块级单例。
    """
    BrowserLock.reset_instance()
    logger.debug("[BrowserLock] 模块级单例已重置")

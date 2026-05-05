"""命令执行器 - 处理 execute_command 工具调用"""

import logging
import os
import shlex
import subprocess

from ...execution_context import ExecutionContext
from ...content.fetcher import WebContentFetcher
from ...config import WEB_CONTENT_FETCH_ENABLED, BROWSER_LOCK_ENABLED, BROWSER_LOCK_TIMEOUT, OPENCLI_LIVE_ENABLED
from ...browser.opencli_client import OpenCLIClient, find_cli_path
from ...browser.browser_lock import get_browser_lock, BrowserLockTimeoutError
from ...errors import CommandExecutionError

logger = logging.getLogger(__name__)


class CommandExecutor:
    """命令执行器

    负责 execute_command 工具的完整执行流程：
    - OpenCLI 命令执行
    - 浏览器锁管理
    - 网页内容获取
    """

    def __init__(
        self,
        opencli_client: OpenCLIClient,
        opencli_path: str | None = None,
        browser_lock_enabled: bool | None = None,
    ):
        self.opencli_client = opencli_client
        self.opencli_path = opencli_path
        self.web_content_fetcher = WebContentFetcher(opencli_client) if WEB_CONTENT_FETCH_ENABLED else None
        self._cli_path_cache: dict[str, str] = {}
        self.browser_lock_enabled = browser_lock_enabled if browser_lock_enabled is not None else BROWSER_LOCK_ENABLED
        self.browser_lock_timeout = BROWSER_LOCK_TIMEOUT
        self.opencli_live_enabled = OPENCLI_LIVE_ENABLED

    async def execute_command(self, call: dict, context: ExecutionContext) -> dict:
        """执行execute_command工具调用

        使用context进行去重检查，返回should_record指令由Harness执行
        """
        command = call["arguments"].get("command", "")

        # 使用context进行去重检查
        duplicate_action = context.find_duplicate_action(command)
        duplicate_warning = ""
        if duplicate_action:
            duplicate_warning = (
                f"\n\n[重复操作警告] 命令 \"{command}\" 已在之前执行过"
                f"（结果: {duplicate_action.get('result_summary', '未知')}）。"
                f"如果你需要获取最新数据，请继续执行。如果不需要，请跳过此步骤。"
            )

        try:
            cmd_args = shlex.split(command)
        except ValueError:
            cmd_args = command.split()

        ref_errors = [arg for arg in cmd_args if "[REF_ERROR:" in arg]
        if ref_errors:
            error_details = "\n".join(ref_errors)
            return {
                "type": "error",
                "error": f"URL引用解析失败:\n{error_details}\n\n请检查引用ID是否正确，或先执行搜索命令获取有效的引用ID。"
            }

        # 处理 opencli 前缀的特殊情况
        # opencli 命令格式: opencli <subcommand> <args>
        # 其他 CLI 命令格式: <cli-name> <args>
        if cmd_args and cmd_args[0] == "opencli":
            # 移除 opencli 前缀，然后在 _execute_command 中添加回去
            # 这样 _execute_command 会正确查找 opencli CLI
            cmd_args = cmd_args[1:]
            # 在开头添加 opencli，让 _execute_command 知道要使用 opencli CLI
            cmd_args = ["opencli"] + cmd_args

        try:
            exec_result = await self._execute_command(cmd_args)
        except CommandExecutionError as e:
            if e.fatal:
                raise
            exec_result = {"success": False, "error": f"命令执行错误: {e}"}
            logger.warning(f"[WebContent] _execute_command non-fatal error: {e}")

        logger.info(f"[WebContent] _execute_command result: {exec_result}")

        if not isinstance(exec_result, dict):
            logger.error(f"[WebContent] _execute_command returned non-dict result: {type(exec_result).__name__}")
            exec_result = {"success": False, "error": f"Command returned non-dict result: {type(exec_result).__name__}"}

        is_browser_open = (
            len(cmd_args) >= 4
            and cmd_args[0] == "opencli"
            and cmd_args[1] == "browser"
            and cmd_args[2] == "open"
        )

        should_fetch_content = (
            self.web_content_fetcher is not None
            and len(cmd_args) >= 1
            and (exec_result.get("success") or is_browser_open)
        )

        logger.info(f"[WebContent] cmd_args: {cmd_args}")
        logger.info(f"[WebContent] exec_result.success: {exec_result.get('success')}")
        logger.info(f"[WebContent] should_fetch_content: {should_fetch_content}")
        logger.info(f"[WebContent] web_content_fetcher exists: {self.web_content_fetcher is not None}")

        web_content = None
        if should_fetch_content:
            if is_browser_open:
                url = cmd_args[3] if len(cmd_args) > 3 else " ".join(cmd_args[3:])
            else:
                url = "current_page"

            workspace = self._infer_workspace(cmd_args)

            logger.info(f"[WebContent] ========== 阶段分隔：开始内容获取 ==========")
            logger.info(f"[WebContent] 命令执行已完成，现在开始获取网页内容")
            logger.info(f"[WebContent] 目标地址: {url}")
            logger.info(f"[WebContent] 推断 workspace: {workspace}")

            try:
                fetch_result = await self.web_content_fetcher.fetch_page_content(url, workspace=workspace)

                if not isinstance(fetch_result, dict):
                    logger.warning(f"[WebContent] fetch_page_content returned non-dict result: {type(fetch_result).__name__}")
                    fetch_result = {"success": False, "error": f"Fetch returned non-dict result: {type(fetch_result).__name__}"}

                if fetch_result.get("success"):
                    logger.info(f"[WebContent] 内容获取成功 - 模式: {fetch_result.get('mode')}, 内容长度: {fetch_result.get('content_length')} 字符")
                    web_content = fetch_result
                else:
                    logger.warning(f"[WebContent] 内容获取失败 - 命令执行成功，但无法获取网页内容")
                    logger.warning(f"[WebContent] 失败原因: {fetch_result.get('error', '未知错误')}")
                    logger.warning(f"[WebContent] 建议: 请检查网页是否可访问，或尝试其他方式获取内容")
            except Exception as e:
                logger.warning(f"[WebContent] 内容获取过程中出现异常 - 命令执行成功，但内容获取失败")
                logger.warning(f"[WebContent] 异常详情: {e}")
                logger.warning(f"[WebContent] 建议: 请检查网络连接或稍后重试")

        result = {
            "type": "command_executed",
            "command": command,
            "result": exec_result
        }

        if web_content:
            result["web_content"] = web_content
            logger.info(f"[WebContent] Added web_content to result, length: {web_content.get('content_length')}")
        else:
            logger.info(f"[WebContent] No web_content added to result")

        # 注入重复操作警告
        if duplicate_warning and exec_result.get("success"):
            exec_result["output"] = exec_result.get("output", "") + duplicate_warning
        elif duplicate_warning and not exec_result.get("success"):
            exec_result["error"] = exec_result.get("error", "") + duplicate_warning

        # 构建result_summary，返回should_record指令由Harness执行
        result_summary = ""
        if exec_result.get("success"):
            result_summary = f"成功: {command[:80]}"
            if web_content and web_content.get("title"):
                result_summary += f" - {web_content['title']}"
        else:
            error_msg = exec_result.get("error", "")
            result_summary = f"失败: {error_msg[:2000]}"

        # 返回should_record指令，不直接修改状态
        result["should_record"] = True
        result["record_data"] = {
            "tool_name": "execute_command",
            "arguments": {"command": command},
            "result_summary": result_summary
        }

        return result

    def _get_cli_path(self, cmd_name: str) -> str | None:
        """获取 CLI 工具路径，使用缓存避免重复查找

        Args:
            cmd_name: CLI 工具名称

        Returns:
            CLI 工具的完整路径或 None
        """
        if cmd_name in self._cli_path_cache:
            return self._cli_path_cache[cmd_name]

        path = find_cli_path(cmd_name)
        self._cli_path_cache[cmd_name] = path
        return path

    @staticmethod
    def _infer_workspace(cmd_args: list[str]) -> str | None:
        """从命令参数推断 OpenCLI workspace

        OpenCLI CLI 使用 workspace: "site:<site>" 格式。
        对于 opencli <site> <command> 格式的命令，推断出对应的 workspace。
        "browser" 是浏览器控制命令，不是 site 命令，不推断 workspace。

        Args:
            cmd_args: 命令参数列表（已规范化为 ["opencli", ...]）

        Returns:
            推断的 workspace 字符串，如 "site:xiaohongshu"，
            如果无法推断则返回 None
        """
        NON_SITE_COMMANDS = {"browser", "list", "validate", "verify", "doctor", "daemon", "completion", "plugin", "adapter", "install", "register"}
        if len(cmd_args) >= 2 and cmd_args[0] == "opencli":
            site = cmd_args[1]
            if site not in NON_SITE_COMMANDS:
                return f"site:{site}"
        return None

    async def _execute_command(self, args: list[str]) -> dict:
        """Execute a command with args.

        Args:
            args: Command args like ["operate", "open", "https://example.com"]

        Returns:
            Result dict with success and output/error
        """
        if not args:
            return {"success": False, "error": "No command provided"}

        # 获取 CLI 工具名（第一个参数）
        cli_name = args[0]

        # 获取 CLI 路径
        cli_path = self._get_cli_path(cli_name)
        if not cli_path:
            return {"success": False, "error": f"{cli_name} not found in PATH"}

        # 判断是否需要获取浏览器锁
        # OpenCLI 命令需要获取锁，其他 CLI 命令不需要
        is_opencli_command = cli_name == "opencli"

        if is_opencli_command and self.browser_lock_enabled:
            # OpenCLI 命令：获取浏览器锁
            browser_lock = get_browser_lock()
            try:
                # 尝试获取锁
                await browser_lock.acquire(timeout=self.browser_lock_timeout)
                logger.debug(f"[BrowserLock] 成功获取浏览器锁，执行命令: {cli_name}")

                # 执行命令
                result = await self._run_subprocess(cli_path, args)
                return result
            except BrowserLockTimeoutError as e:
                logger.error(f"[BrowserLock] 获取浏览器锁超时: {e}")
                raise CommandExecutionError(
                    f"获取浏览器锁超时 ({e.timeout}s)，可能有其他浏览器操作正在进行",
                    tool_name="execute_command",
                    arguments={"cli_name": cli_name, "args": args[1:]},
                    fatal=True,
                ) from e
            finally:
                # 确保锁被释放
                browser_lock.release()
                logger.debug("[BrowserLock] 浏览器锁已释放")
        else:
            # 非 OpenCLI 命令或浏览器锁未启用：直接执行
            result = await self._run_subprocess(cli_path, args)
            return result

    async def _run_subprocess(self, cli_path: str, args: list[str]) -> dict:
        """运行子进程执行命令

        Args:
            cli_path: CLI 工具路径
            args: 命令参数列表

        Returns:
            Result dict with success and output/error
        """
        try:
            env = os.environ.copy()
            is_opencli = args[0] == "opencli"
            if is_opencli and self.opencli_live_enabled:
                env["OPENCLI_LIVE"] = "1"

            result = subprocess.run(
                [cli_path] + args[1:],
                capture_output=True,
                text=True,
                timeout=60,
                encoding='utf-8',
                errors='replace',
                env=env,
            )

            if result.returncode == 0:
                return {"success": True, "output": result.stdout.strip()}
            return {"success": False, "error": result.stderr.strip() or f"Exit code: {result.returncode}"}

        except subprocess.TimeoutExpired as e:
            raise CommandExecutionError(
                "命令执行超时 (60s)",
                tool_name="execute_command",
                arguments={"cli_path": cli_path, "args": args[1:]},
                fatal=True,
            ) from e
        except Exception as e:
            raise CommandExecutionError(
                f"命令执行异常: {e}",
                tool_name="execute_command",
                arguments={"cli_path": cli_path, "args": args[1:]},
                fatal=False,
            ) from e

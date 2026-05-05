"""OpenCLI HTTP Client - Python wrapper for OpenCLI daemon API."""

import os
import shutil
import sys
from typing import List, Optional


def _get_potential_paths(cmd_name: str) -> List[str]:
    """获取 CLI 工具的常见安装路径列表
    
    Args:
        cmd_name: CLI 工具名称
    
    Returns:
        可能的安装路径列表
    """
    paths = []
    
    if sys.platform == "win32":
        # Windows 常见路径
        appdata = os.environ.get("APPDATA", "")
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
        
        npm_paths = [
            os.path.join(appdata, "npm"),
            os.path.join(local_appdata, "npm"),
            os.path.join(program_files, "nodejs"),
        ]
        
        for npm_path in npm_paths:
            if npm_path:
                for ext in ['.cmd', '.ps1', '.bat', '.exe', '']:
                    paths.append(os.path.join(npm_path, f"{cmd_name}{ext}"))
    else:
        # Unix 常见路径
        home = os.path.expanduser("~")
        paths = [
            f"/usr/local/bin/{cmd_name}",
            f"/usr/bin/{cmd_name}",
            f"{home}/.npm-global/bin/{cmd_name}",
            f"{home}/.local/bin/{cmd_name}",
            f"/opt/homebrew/bin/{cmd_name}",  # macOS Apple Silicon
        ]
    
    return paths


def find_cli_path(cmd_name: str) -> Optional[str]:
    """查找 CLI 工具可执行文件路径
    
    Args:
        cmd_name: CLI 工具名称（如 'opencli', 'lark-cli', 'npm' 等）
    
    Returns:
        找到的完整路径或 None
    """
    # 1. 使用 shutil.which 查找
    path = shutil.which(cmd_name)
    if path:
        return path
    
    # 2. Windows 特有扩展名
    if sys.platform == "win32":
        for ext in ['.cmd', '.ps1', '.bat', '.exe']:
            path = shutil.which(f"{cmd_name}{ext}")
            if path:
                return path
    
    # 3. 常见安装路径回退
    potential_paths = _get_potential_paths(cmd_name)
    for path in potential_paths:
        if os.path.exists(path):
            return path
    
    return None


def find_opencli_path() -> Optional[str]:
    """查找 opencli 可执行文件路径（兼容性别名）"""
    return find_cli_path("opencli")

# 禁用代理，避免本地连接问题（必须在导入 httpx 之前）
for proxy_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    os.environ.pop(proxy_var, None)

import asyncio
import subprocess
import time
from typing import Any, Optional

import httpx
from pydantic import BaseModel


class DaemonStatus(BaseModel):
    """OpenCLI daemon status response."""
    ok: bool
    pid: Optional[int] = None
    uptime: Optional[float] = None
    extension_connected: bool = False
    extension_version: Optional[str] = None
    pending: int = 0
    last_cli_request_time: Optional[float] = None
    memory_mb: Optional[float] = None
    port: int = 19825


class DaemonCommand(BaseModel):
    """OpenCLI daemon command structure."""
    id: str
    action: str
    tabId: Optional[int] = None
    code: Optional[str] = None
    url: Optional[str] = None
    workspace: Optional[str] = None
    page: Optional[str] = None
    timeout: Optional[int] = None


class DaemonResult(BaseModel):
    """OpenCLI daemon result structure."""
    id: str
    ok: bool
    data: Optional[Any] = None
    error: Optional[str] = None


class OpenCLIError(Exception):
    """OpenCLI operation error."""
    pass


class OpenCLIClient:
    """HTTP client for OpenCLI daemon.
    
    OpenCLI daemon runs on port 19825 and provides browser automation
    capabilities through a Chrome extension.
    """
    
    DEFAULT_PORT = 19825
    DEFAULT_TIMEOUT = 30.0
    DEFAULT_BASE_URL = "http://localhost:19825"
    
    def __init__(self, port: int = DEFAULT_PORT, timeout: float = DEFAULT_TIMEOUT, workspace: str = "default"):
        self.port = port
        self.base_url = f"http://localhost:{port}"
        self.timeout = timeout
        self.workspace = workspace
        self._client: Optional[httpx.AsyncClient] = None
        self._command_counter = 0
        self._active_page: Optional[str] = None
    
    async def __aenter__(self) -> "OpenCLIClient":
        await self._ensure_client()
        return self
    
    async def __aexit__(self, *args) -> None:
        await self.close()
    
    async def _ensure_client(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers={"X-OpenCLI": "1"},
                proxy=None,
            )
            await self._client.__aenter__()
    
    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
    
    def _generate_id(self) -> str:
        self._command_counter += 1
        return f"cmd_{int(time.time() * 1000)}_{self._command_counter}"
    
    async def _request(
        self, 
        method: str, 
        path: str, 
        json: Optional[dict] = None,
    ) -> httpx.Response:
        await self._ensure_client()
        response = await self._client.request(method, path, json=json)
        response.raise_for_status()
        return response
    
    async def ping(self) -> bool:
        """Check if daemon is reachable."""
        try:
            response = await self._request("GET", "/ping")
            return response.json().get("ok", False)
        except Exception:
            return False
    
    async def status(self) -> Optional[DaemonStatus]:
        """Get daemon status."""
        try:
            await self._ensure_client()
            response = await self._client.get("/status")
            response.raise_for_status()
            data = response.json()
            return DaemonStatus(
                ok=data.get("ok", False),
                pid=data.get("pid"),
                uptime=data.get("uptime"),
                extension_connected=data.get("extensionConnected", False),
                extension_version=data.get("extensionVersion"),
                pending=data.get("pending", 0),
                last_cli_request_time=data.get("lastCliRequestTime"),
                memory_mb=data.get("memoryMB"),
                port=data.get("port", self.port),
            )
        except httpx.ConnectError as e:
            import logging
            logging.getLogger(__name__).debug(f"Daemon not running (connection refused): {e}")
            return None
        except httpx.TimeoutException as e:
            import logging
            logging.getLogger(__name__).debug(f"Daemon connection timeout: {e}")
            return None
        except httpx.ReadError as e:
            import logging
            logging.getLogger(__name__).debug(f"Daemon connection read error (may be starting): {e}")
            return None
        except httpx.WriteError as e:
            import logging
            logging.getLogger(__name__).debug(f"Daemon connection write error: {e}")
            return None
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Status check failed: {type(e).__name__}: {e}")
            return None
    
    async def send_command(
        self, 
        action: str, 
        **params: Any,
    ) -> Any:
        """Send a command to the daemon."""
        if "workspace" not in params:
            params["workspace"] = self.workspace
        if "page" not in params and self._active_page:
            params["page"] = self._active_page
        command = DaemonCommand(
            id=self._generate_id(),
            action=action,
            **params,
        )
        
        try:
            response = await self._request(
                "POST", 
                "/command", 
                json=command.model_dump(exclude_none=True),
            )
            result = DaemonResult(**response.json())
            
            if not result.ok:
                raise OpenCLIError(result.error or "Command failed")
            
            return result.data
        except httpx.HTTPStatusError as e:
            raise OpenCLIError(f"HTTP error: {e}") from e
        except Exception as e:
            raise OpenCLIError(f"Command error: {e}") from e
    
    async def navigate(self, url: str, workspace: Optional[str] = None) -> dict:
        """Navigate to URL."""
        params: dict[str, Any] = {"url": url}
        if workspace is not None:
            params["workspace"] = workspace
        result = await self.send_command("navigate", **params)
        if isinstance(result, dict) and "page" in result:
            self._active_page = result["page"]
        return result or {}
    
    async def evaluate(self, code: str, workspace: Optional[str] = None, page: Optional[str] = None) -> Any:
        """Execute JavaScript in the current page."""
        wrapped_code = f"(() => {{ return ({code}); }})()"
        params: dict[str, Any] = {"code": wrapped_code}
        if workspace is not None:
            params["workspace"] = workspace
        if page is not None:
            params["page"] = page
        return await self.send_command("exec", **params)
    
    async def get_title(self, workspace: Optional[str] = None) -> str:
        """Get page title."""
        result = await self.evaluate("document.title", workspace=workspace)
        return str(result) if result else ""

    async def get_url(self, workspace: Optional[str] = None) -> str:
        """Get current page URL."""
        result = await self.evaluate("window.location.href", workspace=workspace)
        return str(result) if result else ""

    async def get_state(self, workspace: Optional[str] = None) -> dict:
        """Get page state with interactive elements."""
        state_js = """
            (function() {
                var result = {
                    url: window.location.href,
                    title: document.title,
                    interactive: []
                };
                var selectors = ['a', 'button', 'input', 'select', 'textarea', '[onclick]', '[role="button"]'];
                var index = 0;
                selectors.forEach(function(sel) {
                    document.querySelectorAll(sel).forEach(function(el) {
                        if (el.offsetWidth === 0 && el.offsetHeight === 0) return;
                        var text = (el.textContent || el.value || el.placeholder || '').trim().slice(0, 50);
                        result.interactive.push({
                            index: ++index,
                            tag: el.tagName.toLowerCase(),
                            type: el.type || null,
                            text: text,
                            href: el.href || null
                        });
                        el.setAttribute('data-opencli-ref', String(index));
                    });
                });
                return result;
            })()
        """
        result = await self.evaluate(state_js, workspace=workspace)
        return result or {}
    
    def set_workspace(self, workspace: str) -> None:
        self.workspace = workspace
        self._active_page = None

    def get_active_page(self) -> Optional[str]:
        return self._active_page

    def set_active_page(self, page: Optional[str]) -> None:
        self._active_page = page
    
    async def screenshot(
        self, 
        path: Optional[str] = None,
        workspace: Optional[str] = None,
    ) -> bytes:
        """Take a screenshot."""
        params: dict[str, Any] = {"format": "png"}
        if workspace is not None:
            params["workspace"] = workspace
        result = await self.send_command("screenshot", **params)
        
        import base64
        if isinstance(result, str):
            data = base64.b64decode(result)
            if path:
                with open(path, "wb") as f:
                    f.write(data)
            return data
        
        raise OpenCLIError("Screenshot failed: invalid response")
    
    async def wait_for(
        self, 
        selector: Optional[str] = None,
        text: Optional[str] = None,
        time_seconds: Optional[float] = None,
        timeout: float = 10.0,
        workspace: Optional[str] = None,
    ) -> bool:
        """Wait for element, text, or time."""
        if time_seconds:
            await asyncio.sleep(time_seconds)
            return True
        
        if selector:
            wait_js = f"""
                (function() {{
                    var start = Date.now();
                    var timeout = {timeout * 1000};
                    while (Date.now() - start < timeout) {{
                        if (document.querySelector("{selector}")) return true;
                    }}
                    return false;
                }})()
            """
            return bool(await self.evaluate(wait_js, workspace=workspace))
        
        if text:
            escaped_text = text.replace("\\", "\\\\").replace('"', '\\"')
            wait_js = f"""
                (function() {{
                    var start = Date.now();
                    var timeout = {timeout * 1000};
                    while (Date.now() - start < timeout) {{
                        if (document.body.textContent.includes("{escaped_text}")) return true;
                    }}
                    return false;
                }})()
            """
            return bool(await self.evaluate(wait_js, workspace=workspace))
        
        return False
    
    async def ensure_daemon_running(self) -> bool:
        """Ensure OpenCLI daemon is running."""
        status = await self.status()
        if status and status.ok:
            return True
        
        opencli_path = find_opencli_path()
        if not opencli_path:
            import logging
            logging.getLogger(__name__).error("opencli command not found in PATH")
            return False
        
        try:
            subprocess.Popen(
                [opencli_path, "doctor"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            
            for _ in range(30):
                await asyncio.sleep(1)
                status = await self.status()
                if status and status.ok:
                    return True
            
            return False
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to start daemon: {e}")
            return False
    
    async def ensure_extension_connected(self, timeout: float = 30.0) -> bool:
        """Ensure Chrome extension is connected."""
        start = time.time()
        while time.time() - start < timeout:
            status = await self.status()
            if status and status.extension_connected:
                return True
            await asyncio.sleep(0.5)
        
        return False
    
    async def _run_cli_command(self, *args: str) -> dict:
        """Run OpenCLI command and return result."""
        opencli_path = find_opencli_path()
        if not opencli_path:
            return {"success": False, "error": "opencli command not found in PATH"}
        
        try:
            process = await asyncio.create_subprocess_exec(
                opencli_path,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout
            )
            
            if process.returncode == 0:
                return {"success": True, "output": stdout.decode("utf-8").strip()}
            else:
                return {"success": False, "error": stderr.decode("utf-8").strip() or "Unknown error"}
        except asyncio.TimeoutError:
            return {"success": False, "error": "Command timeout"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def bilibili_me(self) -> dict:
        """Get current Bilibili user information."""
        return await self._run_cli_command("bilibili", "me")
    
    async def bilibili_hot(self) -> dict:
        """Get Bilibili hot videos."""
        return await self._run_cli_command("bilibili", "hot")
    
    async def bilibili_search(self, query: str) -> dict:
        """Search on Bilibili."""
        return await self._run_cli_command("bilibili", "search", query)
    
    async def zhihu_hot(self) -> dict:
        """Get Zhihu hot topics."""
        return await self._run_cli_command("zhihu", "hot")
    
    async def hackernews_top(self) -> dict:
        """Get top Hacker News stories."""
        return await self._run_cli_command("hn", "top")

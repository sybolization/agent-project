import asyncio
import json
import logging
import os
import urllib.request
from typing import Optional

import websockets

logger = logging.getLogger(__name__)


class CDPError(Exception):
    pass


class CDPConnectionError(CDPError):
    pass


class CDPCommandError(CDPError):

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"CDP command error {code}: {message}")


class CDPClient:

    def __init__(self, host: str = "localhost", port: int = 9222, cookie_store_path: str = ".cdp_state/cookies.json"):
        self._host = host
        self._port = port
        self._cookie_store_path = cookie_store_path
        self._cookie_flush_task: Optional[asyncio.Task] = None
        self._msg_id: int = 0
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._session_id: Optional[str] = None
        self._target_id: Optional[str] = None
        self._document_node_id: Optional[int] = None

    async def __aenter__(self) -> "CDPClient":
        await self.connect()
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    def is_connected(self) -> bool:
        if self._ws is None:
            return False
        try:
            from websockets.protocol import State
            return self._ws.state == State.OPEN
        except Exception:
            return hasattr(self._ws, 'open') and self._ws.open

    async def connect(self) -> None:
        try:
            ws_url = await self._discover_ws_url()
            old_no_proxy = os.environ.get("NO_PROXY", "")
            old_no_proxy_lower = os.environ.get("no_proxy", "")
            try:
                os.environ["NO_PROXY"] = "localhost,127.0.0.1"
                os.environ["no_proxy"] = "localhost,127.0.0.1"
                self._ws = await websockets.connect(ws_url, max_size=2**24)
            finally:
                if old_no_proxy:
                    os.environ["NO_PROXY"] = old_no_proxy
                else:
                    os.environ.pop("NO_PROXY", None)
                if old_no_proxy_lower:
                    os.environ["no_proxy"] = old_no_proxy_lower
                else:
                    os.environ.pop("no_proxy", None)
            await self._attach_to_page()
            await self.execute("Page.enable")
            await self.execute("DOM.enable")
            try:
                await self.execute("Network.enable")
            except Exception:
                logger.warning("Failed to enable Network domain, cookie features will be unavailable")
            await self._refresh_document_node()
            await self._load_cookies()
            self._start_cookie_flush_timer()
        except CDPError:
            raise
        except Exception as e:
            raise CDPConnectionError(str(e)) from e

    async def close(self) -> None:
        if self._cookie_flush_task:
            self._cookie_flush_task.cancel()
            try:
                self._cookie_flush_task = None
            except Exception:
                pass
        await self._save_cookies()
        if self._ws:
            await self._ws.close()
            self._ws = None
            self._session_id = None
            self._target_id = None

    async def _refresh_document_node(self) -> None:
        try:
            result = await self.execute("DOM.getDocument", {"depth": 0})
            self._document_node_id = result.get("root", {}).get("nodeId", 1)
        except Exception:
            self._document_node_id = 1

    def get_document_node_id(self) -> int:
        return self._document_node_id or 1

    async def send(self, method: str, params: dict = None) -> dict:
        if not self.is_connected():
            raise CDPConnectionError("Not connected to Chrome")

        self._msg_id += 1
        msg_id = self._msg_id
        message: dict = {"id": msg_id, "method": method, "params": params or {}}

        await self._ws.send(json.dumps(message))

        while True:
            raw = await self._ws.recv()
            resp = json.loads(raw)

            if resp.get("id") == msg_id:
                if "error" in resp:
                    err = resp["error"]
                    raise CDPCommandError(
                        code=err.get("code", -1),
                        message=err.get("message", "Unknown error"),
                    )
                return resp.get("result", {})

    async def execute(self, method: str, params: dict = None) -> dict:
        if not self.is_connected():
            raise CDPConnectionError("Not connected to Chrome")

        self._msg_id += 1
        msg_id = self._msg_id
        message: dict = {
            "id": msg_id,
            "method": method,
            "params": params or {},
        }
        if self._session_id:
            message["sessionId"] = self._session_id

        await self._ws.send(json.dumps(message))

        while True:
            raw = await self._ws.recv()
            resp = json.loads(raw)

            if resp.get("id") == msg_id:
                if "error" in resp:
                    err = resp["error"]
                    raise CDPCommandError(
                        code=err.get("code", -1),
                        message=err.get("message", "Unknown error"),
                    )
                return resp.get("result", {})

    async def _discover_ws_url(self) -> str:
        try:
            url = f"http://{self._host}:{self._port}/json/version"
            proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(proxy_handler)
            with opener.open(url) as resp:
                info = json.loads(resp.read().decode())
            ws_url = info.get("webSocketDebuggerUrl")
            if not ws_url:
                raise CDPConnectionError("webSocketDebuggerUrl not found in /json/version response")
            return ws_url
        except CDPError:
            raise
        except Exception as e:
            raise CDPConnectionError(f"Failed to discover WebSocket URL: {e}") from e

    async def _attach_to_page(self) -> None:
        try:
            url = f"http://{self._host}:{self._port}/json/list"
            proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(proxy_handler)
            with opener.open(url) as resp:
                targets = json.loads(resp.read().decode())

            page_targets = [t for t in targets if t.get("type") == "page"]

            if page_targets:
                self._target_id = page_targets[0]["id"]
            else:
                result = await self.send("Target.createTarget", {"url": "about:blank"})
                self._target_id = result["targetId"]

            result = await self.send(
                "Target.attachToTarget",
                {"targetId": self._target_id, "flatten": True},
            )
            self._session_id = result["sessionId"]
        except CDPError:
            raise
        except Exception as e:
            raise CDPConnectionError(f"Failed to attach to page target: {e}") from e

    async def _load_cookies(self) -> None:
        try:
            cookie_path = self._cookie_store_path
            if not os.path.exists(cookie_path):
                return
            with open(cookie_path, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            if not isinstance(cookies, list):
                logger.warning("Invalid cookie store format, expected list")
                return
            loaded = 0
            for cookie in cookies:
                try:
                    await self.execute("Network.setCookie", cookie)
                    loaded += 1
                except Exception:
                    pass
            if loaded > 0:
                logger.info(f"Loaded {loaded} cookies from {cookie_path}")
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON in cookie store: {self._cookie_store_path}")
        except Exception as e:
            logger.warning(f"Failed to load cookies: {e}")

    async def _save_cookies(self) -> None:
        if not self.is_connected():
            return
        try:
            result = await self.execute("Network.getAllCookies")
            cookies = result.get("cookies", [])
            cookie_path = self._cookie_store_path
            os.makedirs(os.path.dirname(cookie_path) if os.path.dirname(cookie_path) else ".", exist_ok=True)
            with open(cookie_path, "w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved {len(cookies)} cookies to {cookie_path}")
        except Exception as e:
            logger.warning(f"Failed to save cookies: {e}")

    def _start_cookie_flush_timer(self) -> None:
        async def _flush_loop():
            try:
                while self.is_connected():
                    await asyncio.sleep(120)
                    if self.is_connected():
                        await self._save_cookies()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"Cookie flush loop error: {e}")
        self._cookie_flush_task = asyncio.create_task(_flush_loop())

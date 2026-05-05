import asyncio
import base64
import inspect
import re
from typing import Any, Callable, Optional

from .cdp_client import CDPClient, CDPError

_UNSAFE_PATTERNS = [
    r"\bsubprocess\b",
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\b__import__\b",
    r"\bos\.system\b",
    r"\bopen\s*\([^)]*[\"']w",
]


class CDPHelpers:

    def __init__(self, cdp_client: CDPClient):
        self._cdp = cdp_client
        self._functions: dict[str, Callable] = {}
        self._register_builtins()

    def register_function(self, name: str, func: Callable) -> None:
        self._functions[name] = func

    def get_function(self, name: str) -> Optional[Callable]:
        return self._functions.get(name)

    def list_functions(self) -> list[str]:
        return list(self._functions.keys())

    def has_function(self, name: str) -> bool:
        return name in self._functions

    async def call_function(self, name: str, **kwargs: Any) -> Any:
        func = self._functions.get(name)
        if func is None:
            raise CDPError(f"Function not found: {name}")
        result = func(**kwargs)
        if asyncio.iscoroutine(result):
            result = await result
        return result

    def add_function_from_code(self, name: str, code: str) -> bool:
        for pattern in _UNSAFE_PATTERNS:
            if re.search(pattern, code):
                return False

        try:
            compiled = compile(code, f"<cdp_helper_{name}>", "exec")
        except SyntaxError:
            return False

        namespace: dict[str, Any] = {"cdp_client": self._cdp, "CDPError": CDPError, "asyncio": asyncio}
        try:
            exec(compiled, namespace)
        except Exception:
            return False

        func = namespace.get(name)
        if func is None or not callable(func):
            return False

        self._functions[name] = func
        return True

    def get_helpers_source(self) -> str:
        parts: list[str] = []
        for name in self._functions:
            func = self._functions[name]
            try:
                source = inspect.getsource(func)
                parts.append(source)
            except (OSError, TypeError):
                parts.append(f"# {name}: source unavailable")
        return "\n\n".join(parts)

    def _register_builtins(self) -> None:
        cdp = self._cdp

        async def navigate(url: str) -> dict:
            await cdp.execute("Page.navigate", {"url": url})
            await asyncio.sleep(2.0)
            await cdp._refresh_document_node()
            try:
                await cdp.execute(
                    "Runtime.evaluate",
                    {"expression": "document.readyState", "returnByValue": True}
                )
            except Exception:
                pass
            return {"url": url, "status": "navigated"}

        async def get_url() -> str:
            result = await cdp.execute(
                "Runtime.evaluate",
                {"expression": "window.location.href", "returnByValue": True},
            )
            value = result.get("result", {}).get("value")
            return str(value) if value is not None else ""

        async def get_title() -> str:
            result = await cdp.execute(
                "Runtime.evaluate",
                {"expression": "document.title", "returnByValue": True},
            )
            value = result.get("result", {}).get("value")
            return str(value) if value is not None else ""

        async def evaluate(expression: str) -> Any:
            result = await cdp.execute(
                "Runtime.evaluate",
                {"expression": expression, "returnByValue": True},
            )
            if "exceptionDetails" in result:
                desc = result["exceptionDetails"].get("exception", {}).get("description", "Evaluation error")
                raise CDPError(desc)
            return result.get("result", {}).get("value")

        async def query_selector(selector: str) -> Optional[int]:
            result = await cdp.execute(
                "DOM.querySelector",
                {"nodeId": cdp.get_document_node_id(), "selector": selector},
            )
            node_id = result.get("nodeId", 0)
            return node_id if node_id else None

        async def query_selector_all(selector: str) -> list[int]:
            result = await cdp.execute(
                "DOM.querySelectorAll",
                {"nodeId": cdp.get_document_node_id(), "selector": selector},
            )
            return result.get("nodeIds", [])

        async def click(selector: str) -> bool:
            node_id = await query_selector(selector)
            if not node_id:
                return False

            box_result = await cdp.execute("DOM.getBoxModel", {"nodeId": node_id})
            model = box_result.get("model", {})
            borders = model.get("border", [])
            if len(borders) < 8:
                return False

            x = sum(borders[i] for i in range(0, 8, 2)) / 4
            y = sum(borders[i] for i in range(1, 8, 2)) / 4

            for event_type in ("mousePressed", "mouseReleased"):
                await cdp.execute(
                    "Input.dispatchMouseEvent",
                    {
                        "type": event_type,
                        "x": x,
                        "y": y,
                        "button": "left",
                        "clickCount": 1,
                    },
                )
            return True

        async def type_text(text: str) -> None:
            await cdp.execute("Input.insertText", {"text": text})

        async def press_key(key: str) -> None:
            key_definitions = {
                "Enter": {"key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13},
                "Tab": {"key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9},
                "Escape": {"key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27},
                "Backspace": {"key": "Backspace", "code": "Backspace", "windowsVirtualKeyCode": 8},
                "ArrowUp": {"key": "ArrowUp", "code": "ArrowUp", "windowsVirtualKeyCode": 38},
                "ArrowDown": {"key": "ArrowDown", "code": "ArrowDown", "windowsVirtualKeyCode": 40},
                "ArrowLeft": {"key": "ArrowLeft", "code": "ArrowLeft", "windowsVirtualKeyCode": 37},
                "ArrowRight": {"key": "ArrowRight", "code": "ArrowRight", "windowsVirtualKeyCode": 39},
                "Space": {"key": " ", "code": "Space", "windowsVirtualKeyCode": 32},
            }
            key_def = key_definitions.get(key, {"key": key, "code": key, "windowsVirtualKeyCode": ord(key[0]) if key else 0})

            for event_type in ("keyDown", "keyUp"):
                await cdp.execute(
                    "Input.dispatchKeyEvent",
                    {
                        "type": event_type,
                        "key": key_def["key"],
                        "code": key_def["code"],
                        "windowsVirtualKeyCode": key_def["windowsVirtualKeyCode"],
                    },
                )

        async def screenshot(path: str = None) -> bytes:
            result = await cdp.execute("Page.captureScreenshot", {"format": "png"})
            data_b64 = result.get("data", "")
            data = base64.b64decode(data_b64)
            if path:
                with open(path, "wb") as f:
                    f.write(data)
            return data

        async def scroll_down(amount: int = 300) -> None:
            await cdp.execute(
                "Runtime.evaluate",
                {"expression": f"window.scrollBy(0, {amount})", "returnByValue": True},
            )

        async def scroll_up(amount: int = 300) -> None:
            await cdp.execute(
                "Runtime.evaluate",
                {"expression": f"window.scrollBy(0, -{amount})", "returnByValue": True},
            )

        async def wait_for_selector(selector: str, timeout: float = 5.0) -> bool:
            js = f"""
            new Promise((resolve) => {{
                const deadline = Date.now() + {timeout * 1000};
                const check = () => {{
                    if (document.querySelector("{selector}")) {{
                        resolve(true);
                    }} else if (Date.now() < deadline) {{
                        requestAnimationFrame(check);
                    }} else {{
                        resolve(false);
                    }}
                }};
                check();
            }})
            """
            result = await cdp.execute(
                "Runtime.evaluate",
                {"expression": js, "returnByValue": True, "awaitPromise": True},
            )
            return bool(result.get("result", {}).get("value", False))

        async def get_interactive_elements() -> list[dict]:
            js = """
            (() => {
                const elements = [];
                const tags = ['a', 'button', 'input', 'select', 'textarea'];
                tags.forEach(tag => {
                    document.querySelectorAll(tag).forEach((el, i) => {
                        if (el.offsetWidth === 0 && el.offsetHeight === 0) return;
                        let selector = null;
                        if (el.id) {
                            selector = '#' + CSS.escape(el.id);
                        } else if (el.name) {
                            selector = el.tagName.toLowerCase() + '[name="' + el.name + '"]';
                        } else if (el.href && el.tagName.toLowerCase() === 'a') {
                            selector = 'a[href*="' + el.getAttribute('href').split('?')[0] + '"]';
                        } else {
                            selector = el.tagName.toLowerCase() + ':nth-of-type(' + (i + 1) + ')';
                        }
                        elements.push({
                            tag: el.tagName.toLowerCase(),
                            type: el.type || null,
                            text: (el.textContent || el.value || el.placeholder || '').trim().slice(0, 80),
                            href: el.href || null,
                            name: el.name || null,
                            id: el.id || null,
                            placeholder: el.placeholder || null,
                            selector: selector,
                            index: elements.length
                        });
                    });
                });
                return elements;
            })()
            """
            result = await cdp.execute(
                "Runtime.evaluate",
                {"expression": js, "returnByValue": True},
            )
            return result.get("result", {}).get("value", [])

        self._functions["navigate"] = navigate
        self._functions["get_url"] = get_url
        self._functions["get_title"] = get_title
        self._functions["evaluate"] = evaluate
        self._functions["query_selector"] = query_selector
        self._functions["query_selector_all"] = query_selector_all
        self._functions["click"] = click
        self._functions["type_text"] = type_text
        self._functions["press_key"] = press_key
        self._functions["screenshot"] = screenshot
        self._functions["scroll_down"] = scroll_down
        self._functions["scroll_up"] = scroll_up
        self._functions["wait_for_selector"] = wait_for_selector
        self._functions["get_interactive_elements"] = get_interactive_elements

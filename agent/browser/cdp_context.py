from typing import Optional


class CDPContextProvider:

    def __init__(self, cdp_client):
        self.cdp_client = cdp_client
        self.include_screenshot = False

    async def get_context(self) -> dict:
        try:
            page_info = await self.cdp_client.execute(
                "Runtime.evaluate",
                {"expression": "({url: window.location.href, title: document.title, readyState: document.readyState})", "returnByValue": True},
            )
            result = page_info.get("result", {}).get("value", {})
        except Exception:
            result = {}
        url = result.get("url", "")
        title = result.get("title", "")
        ready_state = result.get("readyState", "")

        try:
            viewport_info = await self.cdp_client.execute(
                "Runtime.evaluate",
                {"expression": "({width: window.innerWidth, height: window.innerHeight, scroll_x: window.pageXOffset, scroll_y: window.pageYOffset, scroll_height: document.documentElement.scrollHeight})", "returnByValue": True},
            )
            viewport = viewport_info.get("result", {}).get("value", {})
        except Exception:
            viewport = {}

        interactive_elements = await self._extract_interactive_elements()
        dom_summary = await self._extract_dom_summary()

        screenshot = ""
        if self.include_screenshot:
            screenshot = await self._take_screenshot()

        return {
            "url": url,
            "title": title,
            "ready_state": ready_state,
            "viewport": viewport,
            "interactive_elements": interactive_elements,
            "dom_summary": dom_summary,
            "screenshot": screenshot,
        }

    async def _take_screenshot(self) -> str:
        """Take a screenshot of the current page, return base64 encoded image"""
        try:
            result = await self.cdp_client.execute(
                "Page.captureScreenshot",
                {"format": "jpeg", "quality": 50}
            )
            return result.get("data", "")
        except Exception:
            return ""

    async def _extract_interactive_elements(self) -> list[dict]:
        js = """
        (() => {
            try {
                const selectors = ['a', 'button', 'input', 'select', 'textarea', '[onclick]', '[role="button"]'];
                const elements = [];
                let index = 0;
                for (const sel of selectors) {
                    for (const el of document.querySelectorAll(sel)) {
                        if (!el) continue;
                        if (el.offsetWidth <= 0 && el.offsetHeight <= 0) continue;
                        if (index >= 30) return elements;
                        elements.push({
                            index: index,
                            tag: el.tagName ? el.tagName.toLowerCase() : 'unknown',
                            type: el.type || null,
                            text: (el.textContent || '').trim().slice(0, 50),
                            id: el.id || null,
                            class: (el.className && typeof el.className === 'string') ? el.className.trim().slice(0, 30) : null,
                            href: el.href || null,
                            placeholder: el.placeholder || null,
                        });
                        index++;
                    }
                }
                return elements;
            } catch(e) {
                return [];
            }
        })()
        """
        result = await self.cdp_client.execute(
            "Runtime.evaluate",
            {"expression": js, "returnByValue": True},
        )
        return result.get("result", {}).get("value", [])

    async def _extract_dom_summary(self) -> str:
        js = """
        (() => {
            try {
                const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'META', 'LINK', 'NOSRIPT']);
                function walk(node, depth) {
                    if (!node) return '';
                    if (depth > 4) return '';
                    if (node.nodeType === Node.TEXT_NODE) {
                        const t = (node.textContent || '').trim();
                        return t ? t.slice(0, 50) + (t.length > 50 ? '...' : '') : '';
                    }
                    if (node.nodeType !== Node.ELEMENT_NODE) return '';
                    if (SKIP_TAGS.has(node.tagName)) return '';
                    const tag = node.tagName.toLowerCase();
                    let result = '  '.repeat(depth) + '<' + tag;
                    if (node.id) result += ' id="' + node.id + '"';
                    const cls = (node.className && typeof node.className === 'string') ? node.className.trim() : '';
                    if (cls) result += ' class="' + cls.slice(0, 30) + '"';
                    result += '>';
                    const text = (node.childNodes && node.childNodes.length === 1 && node.childNodes[0].nodeType === Node.TEXT_NODE)
                        ? (node.textContent || '').trim().slice(0, 50)
                        : '';
                    if (text) result += text + (node.textContent && node.textContent.trim().length > 50 ? '...' : '');
                    let childCount = 0;
                    if (node.childNodes) {
                        for (const child of node.childNodes) {
                            if (childCount >= 8) break;
                            const part = walk(child, depth + 1);
                            if (part) {
                                result += '\\n' + part;
                                childCount++;
                            }
                        }
                    }
                    if (childCount >= 8) result += '\\n' + '  '.repeat(depth + 1) + '...';
                    return result;
                }
                if (!document.body) return '(page body not loaded)';
                return walk(document.body, 0);
            } catch(e) {
                return '(DOM extraction error: ' + e.message + ')';
            }
        })()
        """
        result = await self.cdp_client.execute(
            "Runtime.evaluate",
            {"expression": js, "returnByValue": True},
        )
        return result.get("result", {}).get("value", "")

    def format_context_for_llm(self, context: dict) -> str:
        parts = []
        parts.append(f"## URL\n{context.get('url', '')}")
        parts.append(f"## Title\n{context.get('title', '')}")
        parts.append(f"## Ready State\n{context.get('ready_state', '')}")

        viewport = context.get("viewport", {})
        if viewport:
            parts.append(
                f"## Viewport\n"
                f"Width: {viewport.get('width', 0)}, Height: {viewport.get('height', 0)}\n"
                f"Scroll: x={viewport.get('scroll_x', 0)}, y={viewport.get('scroll_y', 0)}\n"
                f"Scroll Height: {viewport.get('scroll_height', 0)}"
            )

        elements = context.get("interactive_elements", [])
        if elements:
            lines = ["## Interactive Elements"]
            for el in elements:
                idx = el.get("index", 0)
                tag = el.get("tag", "")
                type_ = el.get("type")
                text = el.get("text", "")
                id_ = el.get("id")
                cls = el.get("class")
                href = el.get("href")
                placeholder = el.get("placeholder")
                desc = f"{idx}. <{tag}"
                if type_:
                    desc += f' type="{type_}"'
                if id_:
                    desc += f' id="{id_}"'
                if cls:
                    desc += f' class="{cls}"'
                if href:
                    desc += f' href="{href}"'
                if placeholder:
                    desc += f' placeholder="{placeholder}"'
                desc += ">"
                if text:
                    desc += f" {text}"
                lines.append(desc)
            parts.append("\n".join(lines))

        dom_summary = context.get("dom_summary", "")
        if dom_summary:
            parts.append(f"## DOM Summary\n{dom_summary}")

        return "\n\n".join(parts)

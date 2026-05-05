import asyncio
import io
import logging

from markitdown import MarkItDown

from ..browser.opencli_client import OpenCLIClient
from ..config import WEB_CONTENT_FETCH_ENABLED, WEB_CONTENT_FETCH_TIMEOUT, WEB_CONTENT_MAX_LENGTH

logger = logging.getLogger(__name__)


class WebContentFetcher:
    def __init__(self, opencli_client: OpenCLIClient):
        self.opencli_client = opencli_client
        self.markitdown = MarkItDown()

    async def fetch_page_content(self, url: str, workspace: str | None = None) -> dict:
        try:
            if not WEB_CONTENT_FETCH_ENABLED:
                return {
                    "success": False,
                    "content": "",
                    "title": "",
                    "content_length": 0,
                    "truncated": False,
                    "mode": "disabled",
                    "error": "web content fetch is disabled",
                }

            return await asyncio.wait_for(
                self._fetch_page_content_impl(url, workspace=workspace),
                timeout=WEB_CONTENT_FETCH_TIMEOUT,
            )
        except asyncio.TimeoutError:
            url_display = "current page (browser active page)" if url == "current_page" else url
            logger.warning(f"[Content Fetch] Timeout while fetching content from: {url_display}")
            return {
                "success": False,
                "content": "",
                "title": "",
                "content_length": 0,
                "truncated": False,
                "mode": "timeout",
                "error": f"fetch timeout after {WEB_CONTENT_FETCH_TIMEOUT}s",
            }
        except Exception as e:
            url_display = "current page (browser active page)" if url == "current_page" else url
            logger.error(f"[Content Fetch] Failed to fetch page content from {url_display}: {e}")
            return {
                "success": False,
                "content": "",
                "title": "",
                "content_length": 0,
                "truncated": False,
                "mode": "failed",
                "error": str(e),
            }

    async def _fetch_page_content_impl(self, url: str, workspace: str | None = None) -> dict:
        eval_kwargs = {}
        if workspace is not None:
            eval_kwargs["workspace"] = workspace

        try:
            page_title = await self.opencli_client.evaluate("document.title", **eval_kwargs)
            page_title = str(page_title) if page_title else ""
        except Exception as e:
            logger.error(f"[Content Fetch] Failed to execute JavaScript 'document.title': {e}")
            page_title = ""

        content = ""
        mode = "markitdown"
        truncated = False

        try:
            html_content = await self.opencli_client.evaluate("document.documentElement.outerHTML", **eval_kwargs)
            if html_content:
                html_bytes = html_content.encode("utf-8")
                conversion_result = self.markitdown.convert_stream(
                    io.BytesIO(html_bytes),
                    file_extension=".html"
                )
                content = conversion_result.text_content if conversion_result and conversion_result.text_content else ""
        except Exception as e:
            logger.warning(f"markitdown conversion failed, fallback to plaintext: {e}")
            mode = "plaintext"
            try:
                content = await self.opencli_client.evaluate("document.body.innerText", **eval_kwargs)
                content = str(content) if content else ""
            except Exception as inner_e:
                logger.error(f"[Content Fetch] Failed to execute JavaScript 'document.body.innerText' during plaintext fallback: {inner_e}")
                content = ""

        original_length = len(content)
        if original_length > WEB_CONTENT_MAX_LENGTH:
            content = content[:WEB_CONTENT_MAX_LENGTH]
            content += f"\n\n[内容已截断，原始长度: {original_length} 字符]"
            truncated = True

        return {
            "success": True,
            "content": content,
            "title": page_title,
            "content_length": len(content),
            "truncated": truncated,
            "mode": mode,
        }

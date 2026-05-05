"""
调试选择器问题 - 查看实际页面内容
"""
import asyncio
from playwright.async_api import async_playwright


async def debug_hackernews():
    print("\n" + "=" * 60)
    print("调试 Hacker News 选择器")
    print("=" * 60)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        await page.goto("https://news.ycombinator.com", wait_until="networkidle")
        await page.wait_for_timeout(3000)
        
        # 获取页面内容
        content = await page.content()
        print(f"\n页面内容长度: {len(content)}")
        
        # 检查常见的表格结构
        tables = await page.query_selector_all("table")
        print(f"\n找到 {len(tables)} 个 table 元素")
        
        rows = await page.query_selector_all("tr")
        print(f"找到 {len(rows)} 个 tr 元素")
        
        # 检查 class 包含 'item' 的元素
        items = await page.query_selector_all("[class*='item']")
        print(f"找到 {len(items)} 个 class 包含 'item' 的元素")
        
        # 检查 class 包含 'athing' 的元素
        athings = await page.query_selector_all("[class*='athing']")
        print(f"找到 {len(athings)} 个 class 包含 'athing' 的元素")
        
        # 尝试获取第一个链接
        links = await page.query_selector_all("a")
        print(f"\n找到 {len(links)} 个 a 元素")
        
        if links:
            for i, link in enumerate(links[:5]):
                text = await link.inner_text()
                href = await link.get_attribute("href")
                print(f"  [{i+1}] {text[:30]}... -> {href}")
        
        await browser.close()


async def debug_reddit():
    print("\n" + "=" * 60)
    print("调试 Reddit 选择器")
    print("=" * 60)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # 设置用户代理
        await page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        
        await page.goto("https://www.reddit.com", wait_until="networkidle")
        await page.wait_for_timeout(5000)
        
        # 获取页面内容
        content = await page.content()
        print(f"\n页面内容长度: {len(content)}")
        
        # 检查 shadow DOM 元素
        shreddit = await page.query_selector_all("shreddit-post")
        print(f"找到 {len(shreddit)} 个 shreddit-post 元素")
        
        # 检查其他可能的选择器
        selectors = [
            "div[data-testid='post-container']",
            "[data-testid='post-container']",
            "article",
            "[role='article']",
            "div[data-cy='post']",
            "div[data-click-id='body']",
        ]
        
        for sel in selectors:
            items = await page.query_selector_all(sel)
            print(f"  {sel}: {len(items)} 个元素")
        
        # 检查标题元素
        titles = await page.query_selector_all("h1, h2, h3")
        print(f"\n找到 {len(titles)} 个标题元素")
        for i, t in enumerate(titles[:3]):
            text = await t.inner_text()
            print(f"  [{i+1}] {text[:50]}...")
        
        await browser.close()


async def main():
    await debug_hackernews()
    await debug_reddit()


if __name__ == "__main__":
    asyncio.run(main())

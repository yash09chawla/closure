"""One shared headless Chrome for the whole server (launch once, ~1 s per page afterwards)."""
import asyncio

from playwright.async_api import async_playwright

_pw = None
_browser = None
_lock = asyncio.Lock()


async def browser():
    global _pw, _browser
    async with _lock:
        if _browser is None or not _browser.is_connected():
            _pw = await async_playwright().start()
            try:
                _browser = await _pw.chromium.launch(channel="chrome", headless=True)
            except Exception:
                _browser = await _pw.chromium.launch(headless=True)  # bundled chromium if installed
        return _browser


async def new_page(width=1366, height=900, scale=1):
    b = await browser()
    ctx = await b.new_context(viewport={"width": width, "height": height}, device_scale_factor=scale,
                              ignore_https_errors=True,
                              user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                                         "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
    return ctx, await ctx.new_page()


async def html_to_pdf(html: str, out_path: str, width_px: int | None = None, a4: bool = False) -> str:
    """width_px → single page exactly as tall as the content (nothing gets cut); a4 → paginated A4."""
    ctx, page = await new_page(width=width_px or 1000, height=800)
    try:
        await page.set_content(html, wait_until="load")
        await page.emulate_media(media="screen")
        if a4:
            await page.pdf(path=out_path, format="A4", print_background=True,
                           margin={"top": "14mm", "bottom": "14mm", "left": "12mm", "right": "12mm"})
        else:
            h = await page.evaluate("Math.ceil(document.documentElement.scrollHeight)")
            await page.pdf(path=out_path, width=f"{width_px}px", height=f"{h + 2}px", print_background=True,
                           margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
    finally:
        await ctx.close()
    return out_path


async def close():
    global _browser, _pw
    if _browser:
        await _browser.close()
    if _pw:
        await _pw.stop()
    _browser = _pw = None

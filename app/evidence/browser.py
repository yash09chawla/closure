"""One shared headless Chrome for the whole server (launch once, ~1 s per page afterwards)."""
import asyncio
import ctypes
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright

from .. import config

_pw = None
_browser = None
_lock = asyncio.Lock()


def _ensure_runtime_libs():
    """Playwright's Node driver needs libatomic.so.1. Some Linux/WSL images (e.g. Oracle Linux) lack it and the
    driver dies with 'Connection closed while reading from the driver'. Use a local copy if the system has none."""
    if sys.platform != "linux":
        return
    try:
        ctypes.CDLL("libatomic.so.1")
        return
    except OSError:
        pass
    for d in (config.ROOT / "vendor" / "lib", Path.home() / "hvlib" / "usr" / "lib64"):
        if (d / "libatomic.so.1").exists():
            cur = os.environ.get("LD_LIBRARY_PATH", "")
            if str(d) not in cur.split(":"):
                os.environ["LD_LIBRARY_PATH"] = f"{d}:{cur}" if cur else str(d)   # inherited by the driver process
            return


async def _reset():
    global _pw, _browser
    for obj, fn in ((_browser, "close"), (_pw, "stop")):
        try:
            if obj:
                await getattr(obj, fn)()
        except Exception:
            pass
    _pw = _browser = None


async def browser():
    global _pw, _browser
    async with _lock:
        if _browser is None or not _browser.is_connected():
            await _reset()                      # a failed/closed driver must not be reused ("handler is closed")
            _ensure_runtime_libs()
            try:
                _pw = await async_playwright().start()
            except Exception as e:
                await _reset()
                raise RuntimeError("Chrome driver could not start (on Linux/WSL install libatomic: "
                                   "'sudo dnf install libatomic' or 'sudo apt install libatomic1') — " + str(e)) from e
            try:
                _browser = await _pw.chromium.launch(channel="chrome", headless=True)
            except Exception:
                try:
                    _browser = await _pw.chromium.launch(headless=True)  # bundled chromium if installed
                except Exception:
                    await _reset()
                    raise
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

"""面板渲染管线：Jinja2 模板 → HTML → Playwright 截图 PNG。

- async API + 常驻浏览器实例（lazy 启动，进程内复用）
- 任何渲染失败返回 None，调用方必须回退纯文本（官方平台图片链路不稳）
- 输出 PNG 固定文件名（覆盖写），不堆积临时文件
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"

_env: Environment | None = None
_pw = None
_browser = None


def _jinja() -> Environment:
    global _env
    if _env is None:
        _env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=select_autoescape(["html"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
    return _env


async def _get_browser():
    global _pw, _browser
    if _browser is not None and _browser.is_connected():
        return _browser
    from playwright.async_api import async_playwright

    _pw = await async_playwright().start()
    _browser = await _pw.chromium.launch(args=["--no-sandbox", "--disable-gpu"])
    return _browser


async def render_png(html: str, out_path: Path, width: int = 520) -> Path | None:
    """截图 #panel 元素。失败返回 None（调用方回退纯文本）。"""
    try:
        browser = await _get_browser()
        page = await browser.new_page(viewport={"width": width, "height": 200})
        await page.set_content(html, wait_until="load")
        el = await page.query_selector("#panel")
        if el is None:
            await page.close()
            return None
        await el.screenshot(path=str(out_path))
        await page.close()
        return out_path if out_path.exists() else None
    except Exception:
        return None


async def render_panel(name: str, data: dict[str, Any], out_dir: Path) -> Path | None:
    """渲染具名面板。out_dir 为图片输出目录（会自动创建）。"""
    try:
        template = _jinja().get_template(f"{name}.html")
        html = template.render(**data)
    except Exception:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{name}.png"
    return await render_png(html, out)


async def shutdown() -> None:
    """插件卸载时释放浏览器。"""
    global _pw, _browser
    try:
        if _browser is not None:
            await _browser.close()
            _browser = None
        if _pw is not None:
            await _pw.stop()
            _pw = None
    except Exception:
        pass

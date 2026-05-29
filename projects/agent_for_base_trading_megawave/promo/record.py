from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path

from playwright.sync_api import Locator, Page, sync_playwright

from promo.demo_dashboard_server import TOKEN_ADDRESS, running_demo_server

ROOT = Path(__file__).resolve().parents[1]
PROMO_DIR = ROOT / "promo"
OUTPUT_DIR = PROMO_DIR / "output"
RAW_DIR = OUTPUT_DIR / "raw"
VIEWPORTS = {
    "16x9": {"width": 1920, "height": 1080, "output": "megawave-demo-16x9.webm"},
    "9x16": {"width": 1080, "height": 1920, "output": "megawave-demo-9x16.webm"},
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Record Megawave dashboard promo footage with Playwright.")
    parser.add_argument("--variant", choices=["16x9", "9x16", "all"], default="all")
    parser.add_argument("--port", type=int, default=8792)
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with running_demo_server(OUTPUT_DIR, port=args.port) as server:
        variants = ["16x9", "9x16"] if args.variant == "all" else [args.variant]
        for variant in variants:
            record_variant(server.base_url, variant)


def record_variant(base_url: str, variant: str) -> Path:
    viewport = VIEWPORTS[variant]
    scratch = RAW_DIR / f".{variant}-capture"
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": viewport["width"], "height": viewport["height"]},
            record_video_dir=str(scratch),
            record_video_size={"width": viewport["width"], "height": viewport["height"]},
            device_scale_factor=1,
        )
        page = context.new_page()
        page.goto(base_url, wait_until="networkidle")
        install_promo_overlays(page)
        page.wait_for_timeout(1600)
        perform_demo(page)
        page.wait_for_timeout(1200)
        page.screenshot(path=str(RAW_DIR / f"last-frame-{variant}.png"), full_page=False)
        context.close()
        browser.close()

    recorded = next(scratch.glob("*.webm"))
    output = RAW_DIR / viewport["output"]
    if output.exists():
        output.unlink()
    recorded.rename(output)
    shutil.rmtree(scratch)
    return output


def install_promo_overlays(page: Page) -> None:
    page.evaluate(
        """
        () => {
          const style = document.createElement('style');
          style.textContent = `
            #promo-cursor {
              position: fixed;
              z-index: 99999;
              width: 24px;
              height: 24px;
              pointer-events: none;
              transform: translate(-50%, -50%);
              transition: left 420ms ease, top 420ms ease;
            }
            #promo-cursor::before {
              content: "";
              position: absolute;
              left: 2px;
              top: 1px;
              width: 0;
              height: 0;
              border-left: 18px solid #111;
              border-top: 12px solid transparent;
              border-bottom: 12px solid transparent;
              filter: drop-shadow(0 2px 2px rgba(0,0,0,.25));
            }
            .promo-focus {
              outline: 4px solid #10b981 !important;
              outline-offset: 3px !important;
              box-shadow: 0 0 0 8px rgba(16,185,129,.16) !important;
            }
          `;
          document.head.appendChild(style);
          const cursor = document.createElement('div');
          cursor.id = 'promo-cursor';
          cursor.style.left = '320px';
          cursor.style.top = '160px';
          document.body.appendChild(cursor);
          window.__promoMask = setInterval(() => {
            const wallet = document.querySelector('#wallet-line');
            if (wallet) wallet.textContent = 'wallet: 0x8EF4...96F1 | db: demo/orders.sqlite';
          }, 120);
        }
        """
    )


def perform_demo(page: Page) -> None:
    page.wait_for_selector("#view-overview.active")
    pause(page, 4300)

    move_and_click(page, "nav button[data-view='trade']")
    page.wait_for_selector("#view-trade.active")
    move_and_click(page, "[data-tool-panel='market']")
    page.wait_for_selector("#market-form input[name='token']:visible")
    pause(page, 1200)

    focus_fill(page, "#market-form input[name='token']", TOKEN_ADDRESS)
    focus_fill(page, "#market-form input[name='amount']", "0.1")
    move_and_click(page, "#market-form button[type='submit']")
    page.wait_for_selector("text=市价单确认")
    pause(page, 3400)
    move_and_click(page, ".chat-actions button.primary")
    pause(page, 2400)
    pause(page, 3000)

    move_and_click(page, "[data-tool-panel='limit']")
    page.wait_for_selector("#limit-form input[name='token']:visible")
    focus_fill(page, "#limit-form input[name='token']", TOKEN_ADDRESS)
    focus_fill(page, "#limit-form input[name='amount']", "0.1")
    focus_fill(page, "#limit-form input[name='target_price']", "0.0001")
    move_and_click(page, "#limit-form button[type='submit']")
    page.wait_for_selector("text=限价单确认")
    pause(page, 3200)
    move_and_click(page, ".chat-item:last-child .chat-actions button.primary")
    page.wait_for_selector("text=限价单已启用")
    pause(page, 2400)

    focus_fill(page, "#command-input", f"用 0.1U 买入 {TOKEN_ADDRESS}")
    move_and_click(page, "#command-form button[type='submit']")
    page.wait_for_selector("[data-nl-send]")
    pause(page, 4600)
    move_and_click(page, "[data-nl-send]")
    page.wait_for_selector("text=市价单确认")
    pause(page, 2600)

    move_and_click(page, "nav button[data-view='orders']")
    page.wait_for_selector("#view-orders.active")
    page.wait_for_selector("#orders-table:visible")
    pause(page, 5200)

    move_and_click(page, "nav button[data-view='copy']")
    page.wait_for_selector("#view-copy.active")
    page.wait_for_selector("#copy-command-form:visible")
    pause(page, 4400)


def focus_fill(page: Page, selector: str, value: str) -> None:
    locator = page.locator(selector)
    focus(page, locator)
    locator.fill(value)
    pause(page, 650)


def move_and_click(page: Page, selector: str) -> None:
    locator = page.locator(selector).first
    focus(page, locator)
    locator.click()
    pause(page, 650)


def focus(page: Page, locator: Locator) -> None:
    locator.scroll_into_view_if_needed()
    box = locator.bounding_box()
    if box:
        x = box["x"] + box["width"] / 2
        y = box["y"] + min(box["height"] / 2, 30)
        page.evaluate("(pos) => { const c = document.querySelector('#promo-cursor'); if (c) { c.style.left = pos.x + 'px'; c.style.top = pos.y + 'px'; } }", {"x": x, "y": y})
    locator.evaluate("el => el.classList.add('promo-focus')")
    pause(page, 480)
    locator.evaluate("el => setTimeout(() => el.classList.remove('promo-focus'), 900)")


def pause(page: Page, ms: int) -> None:
    page.wait_for_timeout(ms)


if __name__ == "__main__":
    start = time.time()
    main()
    print(f"recording complete in {time.time() - start:.1f}s")

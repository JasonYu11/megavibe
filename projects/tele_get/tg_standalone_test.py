#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml
from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def visible_text(page: Page, selector: str) -> list[str]:
    return page.locator(selector).evaluate_all(
        """els => els
          .filter(el => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0 &&
                   r.top < innerHeight && r.left < innerWidth;
          })
          .map(el => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim())
          .filter(Boolean)
        """
    )


def extract_messages(page: Page) -> list[dict[str, Any]]:
    return page.locator(".bubble").evaluate_all(
        """els => {
          const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
          const visible = el => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0 &&
                   r.top < innerHeight && r.left < innerWidth;
          };
          return els
            .filter(el => !el.classList.contains('service'))
            .filter(visible)
            .map((el, index) => {
              const msgEl = el.querySelector('.message');
              const timeEl = el.querySelector('.time-inner, .time');
              const senderEl = el.querySelector('.name, .peer-title, .reply-title');
              const text = clean(msgEl?.innerText || '');
              const raw = clean(el.innerText || '');
              return {
                index: index + 1,
                sender_hint: clean(senderEl?.innerText || '').slice(0, 120),
                message_time: clean(timeEl?.innerText || '').replace(/^edited\\s+/i, '').trim(),
                media_hint: el.className.includes('photo') ? 'photo'
                  : el.querySelector('video') ? 'video'
                  : el.querySelector('img, canvas') ? 'media'
                  : '',
                has_reply: !!el.querySelector('.reply'),
                text,
                raw_text: raw,
              };
            });
        }"""
    )


def page_summary(page: Page) -> dict[str, Any]:
    headers = visible_text(page, ".chat-info, .person")
    body_text = page.locator("body").evaluate(
        "el => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 1000)"
    )
    return {
        "url": page.url,
        "title": page.title(),
        "logged_in": not bool(re.search(r"log in to telegram|please enter your phone|phone number", body_text, re.I)),
        "current_chat": headers[0] if headers else "",
        "messages": extract_messages(page),
    }


def open_target(page: Page, target: dict[str, Any]) -> dict[str, Any]:
    aliases = [target["topic_title"], *target.get("aliases", [])]
    wanted = [normalize(alias) for alias in aliases]

    candidates = page.locator(".chatlist-chat").evaluate_all(
        """(els, wanted) => {
          const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
          const norm = s => clean(s).toLowerCase().replace(/[^a-z0-9]+/g, '');
          const visible = el => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0 &&
                   r.top < innerHeight && r.left < innerWidth;
          };
          return els
            .map((el, index) => ({
              index,
              text: clean(el.innerText || ''),
              normalized: norm(el.innerText || ''),
              peer_id: el.getAttribute('data-peer-id') ||
                el.querySelector('[data-peer-id]')?.getAttribute('data-peer-id') || '',
              active: typeof el.className === 'string' && /active/.test(el.className),
              visible: visible(el),
            }))
            .filter(row => row.visible && wanted.some(w => row.normalized.includes(w)));
        }""",
        wanted,
    )

    result: dict[str, Any] = {
        "target": target["name"],
        "topic_title": target["topic_title"],
        "matched_rows": candidates,
    }
    if not candidates:
        result["opened"] = False
        result["error"] = "target row not visible"
        return result

    row = candidates[0]
    page.locator(".chatlist-chat").nth(row["index"]).click()
    page.wait_for_timeout(2500)
    summary = page_summary(page)
    result["opened"] = normalize(target["topic_title"]) in normalize(summary["current_chat"])
    result["summary"] = summary
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone Telegram Web target parser test.")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--profile", default=str(ROOT / "profiles" / "telegram-web"))
    parser.add_argument("--cdp", default="", help="Connect to an existing Chrome CDP URL, e.g. http://127.0.0.1:9222")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--keep-open", action="store_true", help="Keep Chrome open for first-time manual Telegram login.")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    with sync_playwright() as p:
        if args.cdp:
            browser = p.chromium.connect_over_cdp(args.cdp)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()
            close_context = False
        else:
            context = p.chromium.launch_persistent_context(
                user_data_dir=args.profile,
                executable_path=CHROME,
                headless=args.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = context.pages[0] if context.pages else context.new_page()
            close_context = True

        page.goto(config["telegram_url"], wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        output = {
            "mode": "standalone_playwright",
            "telegram_url": config["telegram_url"],
            "initial": page_summary(page),
            "targets": [],
        }

        for target in config["targets"]:
            output["targets"].append(open_target(page, target))

        print(json.dumps(output, ensure_ascii=False, indent=2))

        if args.keep_open and close_context:
            print("Chrome is staying open. Log in to Telegram there, then rerun without --keep-open.")
            page.wait_for_timeout(10 * 60 * 1000)
        elif close_context:
            context.close()
        else:
            browser.close()


if __name__ == "__main__":
    main()

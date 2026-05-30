from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from playwright.sync_api import Page

from .fingerprint import make_fingerprint


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def wait_for_telegram(page: Page, timeout_ms: int = 15000) -> None:
    page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    page.wait_for_timeout(5000)


def is_logged_in(page: Page) -> bool:
    body_text = page.locator("body").evaluate(
        "el => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 1500)"
    )
    return not bool(re.search(r"log in to telegram|please enter your phone|phone number", body_text, re.I))


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


def current_chat(page: Page) -> str:
    headers = visible_text(page, ".chat-info, .person")
    return headers[0] if headers else ""


def find_target_rows(page: Page, target: dict[str, Any]) -> list[dict[str, Any]]:
    aliases = [target["topic_title"], *target.get("aliases", [])]
    wanted = [normalize(alias) for alias in aliases]
    expected_peer_id = str(target.get("peer_id", "") or "")
    return page.locator(".chatlist-chat").evaluate_all(
        """(els, args) => {
          const wanted = args.wanted;
          const expectedPeerId = args.expectedPeerId;
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
            .filter(row => row.visible)
            .filter(row => !expectedPeerId || row.peer_id === expectedPeerId)
            .filter(row => wanted.some(w => row.normalized.includes(w)));
        }""",
        {"wanted": wanted, "expectedPeerId": expected_peer_id},
    )


def open_target(page: Page, target: dict[str, Any]) -> dict[str, Any]:
    current = current_chat(page)
    if normalize(target["topic_title"]) in normalize(current):
        return {"opened": True, "matched_rows": [], "current_chat": current, "already_open": True}

    candidates = find_target_rows(page, target)
    if not candidates:
        return {"opened": False, "matched_rows": [], "error": "target row not visible"}

    row = candidates[0]
    locator = page.locator(".chatlist-chat").nth(row["index"])
    try:
        locator.click(force=True, timeout=8000)
    except Exception:
        locator.evaluate("el => el.click()")
    page.wait_for_timeout(2500)
    opened = normalize(target["topic_title"]) in normalize(current_chat(page))
    return {"opened": opened, "matched_rows": candidates, "current_chat": current_chat(page)}


def _extract_visible_message_rows(page: Page) -> list[dict[str, Any]]:
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


def scroll_to_latest(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """async () => {
          const visible = el => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0 &&
                   r.top < innerHeight && r.left < innerWidth;
          };
          const getScroller = () => Array.from(document.querySelectorAll('.scrollable.scrollable-y'))
            .filter(el => {
              const r = el.getBoundingClientRect();
              return r.x > 250 && r.width > 300 && el.scrollHeight > el.clientHeight + 50;
            })
            .sort((a, b) => b.scrollHeight - a.scrollHeight)[0];
          const scroller = getScroller();
          if (!scroller) return { ok: false, error: 'message scroller not found' };
          const before = {
            scrollTop: Math.round(scroller.scrollTop),
            scrollHeight: Math.round(scroller.scrollHeight),
            clientHeight: Math.round(scroller.clientHeight)
          };
          scroller.scrollTo(0, scroller.scrollHeight);
          await new Promise(resolve => setTimeout(resolve, 1200));
          const after = {
            scrollTop: Math.round(scroller.scrollTop),
            scrollHeight: Math.round(scroller.scrollHeight),
            clientHeight: Math.round(scroller.clientHeight),
            visibleBubbles: Array.from(document.querySelectorAll('.bubble')).filter(el => !el.classList.contains('service')).filter(visible).length
          };
          return { ok: true, before, after };
        }"""
    )


def scroll_up_one_page(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """async () => {
          const visible = el => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0 &&
                   r.top < innerHeight && r.left < innerWidth;
          };
          const getScroller = () => Array.from(document.querySelectorAll('.scrollable.scrollable-y'))
            .filter(el => {
              const r = el.getBoundingClientRect();
              return r.x > 250 && r.width > 300 && el.scrollHeight > el.clientHeight + 50;
            })
            .sort((a, b) => b.scrollHeight - a.scrollHeight)[0];
          const scroller = getScroller();
          if (!scroller) return { ok: false, error: 'message scroller not found' };
          const before = {
            scrollTop: Math.round(scroller.scrollTop),
            scrollHeight: Math.round(scroller.scrollHeight),
            clientHeight: Math.round(scroller.clientHeight)
          };
          const nextTop = Math.max(0, scroller.scrollTop - Math.max(500, scroller.clientHeight * 0.85));
          scroller.scrollTo(0, nextTop);
          await new Promise(resolve => setTimeout(resolve, 900));
          const after = {
            scrollTop: Math.round(scroller.scrollTop),
            scrollHeight: Math.round(scroller.scrollHeight),
            clientHeight: Math.round(scroller.clientHeight),
            visibleBubbles: Array.from(document.querySelectorAll('.bubble')).filter(el => !el.classList.contains('service')).filter(visible).length
          };
          return { ok: true, before, after };
        }"""
    )


def scroll_recent_history(page: Page, pages: int) -> dict[str, Any]:
    return page.evaluate(
        """async pages => {
          const visible = el => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0 &&
                   r.top < innerHeight && r.left < innerWidth;
          };
          const getScroller = () => Array.from(document.querySelectorAll('.scrollable.scrollable-y'))
            .filter(el => {
              const r = el.getBoundingClientRect();
              return r.x > 250 && r.width > 300 && el.scrollHeight > el.clientHeight + 50;
            })
            .sort((a, b) => b.scrollHeight - a.scrollHeight)[0];
          const scroller = getScroller();
          if (!scroller) return { ok: false, error: 'message scroller not found' };
          const before = {
            scrollTop: Math.round(scroller.scrollTop),
            scrollHeight: Math.round(scroller.scrollHeight),
            clientHeight: Math.round(scroller.clientHeight)
          };
          scroller.scrollTo(0, scroller.scrollHeight);
          await new Promise(resolve => setTimeout(resolve, 1200));
          const latest = {
            scrollTop: Math.round(scroller.scrollTop),
            scrollHeight: Math.round(scroller.scrollHeight),
            clientHeight: Math.round(scroller.clientHeight),
            visibleBubbles: Array.from(document.querySelectorAll('.bubble')).filter(el => !el.classList.contains('service')).filter(visible).length
          };
          for (let i = 0; i < pages; i++) {
            const nextTop = Math.max(0, scroller.scrollTop - Math.max(500, scroller.clientHeight * 0.85));
            scroller.scrollTo(0, nextTop);
            await new Promise(resolve => setTimeout(resolve, 900));
          }
          const after = {
            scrollTop: Math.round(scroller.scrollTop),
            scrollHeight: Math.round(scroller.scrollHeight),
            clientHeight: Math.round(scroller.clientHeight),
            visibleBubbles: Array.from(document.querySelectorAll('.bubble')).filter(el => !el.classList.contains('service')).filter(visible).length
          };
          return { ok: true, before, latest, after };
        }""",
        pages,
    )


def build_messages(rows: list[dict[str, Any]], target: dict[str, Any], chat_title: str) -> list[dict[str, Any]]:
    scraped_at = datetime.now(timezone.utc).isoformat()
    messages: list[dict[str, Any]] = []
    for row in rows:
        message = {
            **row,
            "target_name": target["name"],
            "chat_title": target.get("chat_title", ""),
            "topic_title": target.get("topic_title", ""),
            "peer_id": target.get("peer_id", ""),
            "current_chat": chat_title,
            "scraped_at": scraped_at,
        }
        message["fingerprint"] = make_fingerprint(message)
        messages.append(message)
    return messages


def extract_messages(page: Page, target: dict[str, Any], chat_title: str) -> list[dict[str, Any]]:
    return build_messages(_extract_visible_message_rows(page), target, chat_title)


def collect_recent_messages(page: Page, target: dict[str, Any], pages: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scroll_events: list[dict[str, Any]] = []
    rows_by_key: dict[str, dict[str, Any]] = {}

    latest = scroll_to_latest(page)
    scroll_events.append({"phase": "latest", **latest})
    chat_title = current_chat(page)
    latest_rows = _extract_visible_message_rows(page)
    for row in latest_rows:
        message = build_messages([row], target, chat_title)[0]
        rows_by_key[message["fingerprint"]] = message

    for index in range(pages):
        event = scroll_up_one_page(page)
        scroll_events.append({"phase": f"history_{index + 1}", **event})
        chat_title = current_chat(page)
        for row in _extract_visible_message_rows(page):
            message = build_messages([row], target, chat_title)[0]
            rows_by_key.setdefault(message["fingerprint"], message)

    return list(rows_by_key.values()), {"ok": True, "events": scroll_events}

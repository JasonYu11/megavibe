"""Web search tools — DuckDuckGo Lite-backed, no API keys required."""

from __future__ import annotations

import re
import urllib.parse

import httpx

from .base import JsonObject, Tool

_SEARCH_URL = "https://lite.duckduckgo.com/lite/"

# Known official docs domains
_OFFICIAL_DOCS: dict[str, str] = {
    "python": "docs.python.org",
    "react": "react.dev",
    "vite": "vitejs.dev",
    "node": "nodejs.org",
    "npm": "docs.npmjs.com",
    "typescript": "www.typescriptlang.org",
    "fastapi": "fastapi.tiangolo.com",
    "pydantic": "docs.pydantic.dev",
    "openai": "platform.openai.com",
    "deepseek": "api-docs.deepseek.com",
    "swift": "developer.apple.com",
    "macos": "developer.apple.com",
    "rust": "doc.rust-lang.org",
    "go": "pkg.go.dev",
    "tailwindcss": "tailwindcss.com",
    "nextjs": "nextjs.org",
    "vue": "vuejs.org",
    "docker": "docs.docker.com",
    "kubernetes": "kubernetes.io",
}


def _resolve_domain(product: str) -> str:
    lowered = product.lower().strip()
    for key, domain in _OFFICIAL_DOCS.items():
        if key in lowered:
            return domain
    if "." in lowered and not lowered.startswith((".", "/")):
        return lowered
    return f"{lowered}.org"


def _extract_url(href: str) -> str:
    match = re.search(r"uddg=([^&]+)", href)
    if match:
        return urllib.parse.unquote(match.group(1))
    if href.startswith("http"):
        return href
    return href


def _search(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """Execute a DuckDuckGo Lite search and extract results via regex."""
    url = _SEARCH_URL + "?" + urllib.parse.urlencode({"q": query})
    try:
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            resp = client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
    except Exception as exc:
        return [{"title": "搜索失败", "snippet": str(exc), "url": ""}]

    html = resp.text
    # Extract result-link <a> tags: href uses double quotes, class uses single quotes
    link_matches = re.findall(
        r'''<a[^>]*href="([^"]*)"[^>]*class='result-link'[^>]*>([^<]+)</a>''', html
    )
    # Extract snippets
    snippet_matches = re.findall(
        r"<td[^>]*class='result-snippet'[^>]*>(.*?)</td>", html, re.DOTALL
    )

    results: list[dict[str, str]] = []
    for i, (href, title) in enumerate(link_matches[:max_results]):
        snippet = ""
        if i < len(snippet_matches):
            snippet = re.sub(r"<[^>]+>", "", snippet_matches[i]).strip()
        results.append({
            "title": title.strip(),
            "snippet": snippet,
            "url": _extract_url(href),
        })
    return results


def _format(results: list[dict[str, str]], query: str) -> str:
    if not results:
        return f'搜索 "{query}" 未找到结果。'
    if results[0].get("title") == "搜索失败":
        return f"搜索失败：{results[0]['snippet']}"

    lines = [f"## Search: {query}\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        snippet = r.get("snippet", "")
        url = r.get("url", "")
        lines.append(f"{i}. **{title}**")
        if snippet:
            lines.append(f"   {snippet}")
        if url:
            lines.append(f"   {url}")
        lines.append("")
    return "\n".join(lines).strip()


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Search the web via DuckDuckGo. Returns title, snippet, and URL for each result. "
        "Use for facts, API references, version info, and current events."
    )

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "Max results (1-10, default 5)"},
            },
            "required": ["query"],
        }

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, arguments: JsonObject) -> str:
        query = str(arguments.get("query", "")).strip()
        if not query:
            return "Error: query is required"
        max_results = min(max(int(arguments.get("max_results", 5) or 5), 1), 10)
        return _format(_search(query, max_results), query)


class OfficialDocsSearchTool(Tool):
    name = "official_docs_search"
    description = (
        "Search official documentation by product name or domain. "
        f"Known products: {', '.join(sorted(_OFFICIAL_DOCS.keys()))}. "
        "Use for API references, parameter formats, and version-specific docs."
    )

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "product": {
                    "type": "string",
                    "description": "Product name (e.g. python, react, vite) or domain",
                },
                "query": {"type": "string", "description": "What to search in documentation"},
                "max_results": {"type": "integer", "description": "Max results (1-10, default 5)"},
            },
            "required": ["product", "query"],
        }

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, arguments: JsonObject) -> str:
        product = str(arguments.get("product", "")).strip()
        query = str(arguments.get("query", "")).strip()
        if not product or not query:
            return "Error: product and query are required"

        domain = _resolve_domain(product)
        max_results = min(max(int(arguments.get("max_results", 5) or 5), 1), 10)
        full_query = f"site:{domain} {query}"
        return _format(_search(full_query, max_results), full_query)

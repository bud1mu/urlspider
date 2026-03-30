#!/usr/bin/env python3

import argparse
import asyncio
import ipaddress
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

from curl_cffi.requests import AsyncSession, RequestsError


BANNER = """\
         _         _   _
 _ _ ___| |___ ___|_|_| |___ ___
| | |  _| |_ -| . | | . | -_|  _|
|___|_| |_|___|  _|_|___|___|_|
              |_|
                    @bud1mu
              """
HREF_SRC_RE = re.compile(r"""(?is)\b(?:href|src)\s*=\s*(['"])(.*?)\1""")
ABSOLUTE_URL_RE = re.compile(r"""(?i)\bhttps?://[^\s"'<>\\)]+""")
ROOT_RELATIVE_RE = re.compile(r"""(?i)(?:"|')((?:/|\.?/)[^"'<>\\\s]+)(?:"|')""")
PATH_LIKE_RE = re.compile(
    r"""(?i)(?:"|')([a-z0-9][^"'<>\\\s]*\.(?:php|aspx?|jsp|json|js|css|xml|txt|map|svg|png|jpe?g|gif|webp|woff2?|ttf|eot)(?:\?[^"'<>\\\s]*)?)(?:"|')"""
)
SKIP_SCHEMES = ("javascript:", "mailto:", "tel:", "data:", "blob:", "#")
TEXTUAL_HINTS = (
    "text/",
    "application/javascript",
    "application/x-javascript",
    "text/javascript",
    "application/json",
    "application/ld+json",
    "application/xml",
    "text/xml",
    "text/css",
    "application/xhtml+xml",
)
COMMON_SECOND_LEVEL_SUFFIXES = {
    "ac.id",
    "ac.jp",
    "ac.uk",
    "co.id",
    "co.jp",
    "co.nz",
    "co.uk",
    "com.au",
    "com.br",
    "com.tr",
    "go.id",
    "gov.uk",
    "net.au",
    "or.id",
    "org.au",
    "org.uk",
    "sch.id",
}
DEFAULT_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "User-Agent": "URLSpider/1.0",
}
DEFAULT_MAX_DEPTH = 3
DEFAULT_MAX_PAGES = 5000
DEFAULT_CONCURRENCY = 40
DEFAULT_TIMEOUT = 15
AGENT_FILE = "agent.txt"
INTERESTING_SUFFIX = " <- interesting, u should look at this bro"
INTERESTING_URL_PATTERNS = (
    re.compile(r"/(?:api|apis)(?:/|$|\?)"),
    re.compile(r"/(?:graphql|graphiql)(?:/|$|\?)"),
    re.compile(r"/(?:rest|soap|rpc|jsonrpc)(?:/|$|\?)"),
    re.compile(r"/(?:swagger|openapi|redoc|api-docs?|docs)(?:/|$|\?)"),
    re.compile(r"/(?:auth|oauth|sso|token|jwt|session)(?:/|$|\?)"),
    re.compile(r"/(?:callback|callbacks|webhook|webhooks)(?:/|$|\?)"),
    re.compile(r"/(?:admin/api|internal|private|public-api|gateway|backend|service|services)(?:/|$|\?)"),
    re.compile(r"/(?:query|queries|mutation|mutations)(?:/|$|\?)"),
    re.compile(r"/v\d+(?:/|$|\?)"),
    re.compile(r"[?&](?:api[_-]?key|access[_-]?token|auth[_-]?token|bearer|jwt|sessionid|client[_-]?id)="),
)
INTERESTING_CONTENT_PATTERNS = (
    re.compile(r"(?<![a-z0-9_])/(?:api|apis)(?:/|['\"?])"),
    re.compile(r"(?<![a-z0-9_])/(?:graphql|graphiql)(?:/|['\"?])"),
    re.compile(r"(?<![a-z0-9_])/(?:rest|soap|rpc|jsonrpc)(?:/|['\"?])"),
    re.compile(r"(?<![a-z0-9_])/(?:swagger|openapi|redoc|api-docs?|docs)(?:/|['\"?])"),
    re.compile(r"(?<![a-z0-9_])/(?:auth|oauth|sso|token|jwt|session)(?:/|['\"?])"),
    re.compile(r"(?<![a-z0-9_])/(?:callback|callbacks|webhook|webhooks)(?:/|['\"?])"),
    re.compile(r"(?<![a-z0-9_])/(?:query|queries|mutation|mutations)(?:/|['\"?])"),
    re.compile(r"(?<![a-z0-9_])/v\d+(?:/|['\"?])"),
    re.compile(r"(?<![a-z0-9_])(?:api[_-]?key|access[_-]?token|auth[_-]?token|bearer|jwt|sessionid|client[_-]?id)(?![a-z0-9_])"),
)
INTERESTING_CONTENT_EXTENSIONS = (
    ".js",
    ".json",
    ".xml",
    ".txt"
)


@dataclass(slots=True)
class CrawlJob:
    url: str
    depth: int


@dataclass(slots=True)
class FetchResult:
    final_url: str
    text: str | None


def parse_json_object(raw: str | None, label: str) -> dict[str, str]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"{label} must be a JSON object.")
    return {str(key): str(item) for key, item in value.items()}


def parse_keywords(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    parts = [item.strip().lower() for item in raw.split(",")]
    return tuple(item for item in parts if item)


def is_interesting_url(url: str) -> bool:
    lowered = url.lower()
    return any(pattern.search(lowered) for pattern in INTERESTING_URL_PATTERNS)


def has_interesting_content(content: str) -> bool:
    lowered = content.lower()
    return any(pattern.search(lowered) for pattern in INTERESTING_CONTENT_PATTERNS)


def url_supports_content_label(url: str) -> bool:
    return urlparse(url.lower()).path.endswith(INTERESTING_CONTENT_EXTENSIONS)


def load_user_agents(path: str) -> list[str]:
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    return [line.strip() for line in lines if line.strip()]


def normalize_url(candidate: str, base_url: str) -> str | None:
    candidate = candidate.strip()
    if not candidate or candidate.startswith(SKIP_SCHEMES):
        return None
    absolute = urljoin(base_url, candidate)
    absolute, _ = urldefrag(absolute)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return absolute


def iter_candidates(content: str) -> Iterable[str]:
    seen: set[str] = set()
    for regex in (HREF_SRC_RE, ABSOLUTE_URL_RE, ROOT_RELATIVE_RE, PATH_LIKE_RE):
        for match in regex.finditer(content):
            if regex is HREF_SRC_RE:
                value = match.group(2)
            elif regex is ABSOLUTE_URL_RE:
                value = match.group(0)
            else:
                value = match.group(1)
            if value and value not in seen:
                seen.add(value)
                yield value


def is_textual(content_type: str, data: bytes) -> bool:
    lowered = (content_type or "").lower()
    if any(hint in lowered for hint in TEXTUAL_HINTS):
        return True
    if not lowered and data:
        return b"\x00" not in data[:1024]
    return False


def host_in_scope(candidate_host: str, root_host: str) -> bool:
    candidate_host = candidate_host.lower().strip(".")
    root_host = root_host.lower().strip(".")
    return candidate_host == root_host or candidate_host.endswith(f".{root_host}")


def registrable_host(host: str) -> str:
    host = host.lower().strip(".")
    if not host:
        return host
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass

    labels = host.split(".")
    if len(labels) <= 2:
        return host

    suffix = ".".join(labels[-2:])
    if suffix in COMMON_SECOND_LEVEL_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return suffix


class UrlSpider:
    def __init__(
        self,
        start_url: str,
        headers: dict[str, str],
        cookies: dict[str, str],
        max_depth: int,
        max_pages: int,
        concurrency: int,
        timeout: float,
        match_keywords: tuple[str, ...],
        exclude_keywords: tuple[str, ...],
        quiet_interesting: bool,
    ) -> None:
        self.start_url = start_url
        self.scope_host = registrable_host(urlparse(start_url).hostname or "")
        self.headers = {**DEFAULT_HEADERS, **headers}
        self.cookies = cookies
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.concurrency = concurrency
        self.timeout = timeout
        self.match_keywords = match_keywords
        self.exclude_keywords = exclude_keywords
        self.quiet_interesting = quiet_interesting
        self.user_agents = load_user_agents(AGENT_FILE)
        self.visited: set[str] = set()
        self.enqueued: set[str] = set()
        self.printed: set[str] = set()
        self.queue: asyncio.Queue[CrawlJob | None] = asyncio.Queue()
        self.print_lock = asyncio.Lock()
        self.ua_index = 0
        self.ua_lock = asyncio.Lock()

    def in_scope(self, url: str) -> bool:
        host = urlparse(url).hostname
        return bool(host and host_in_scope(host, self.scope_host))

    async def enqueue(self, url: str, depth: int) -> None:
        if depth > self.max_depth:
            return
        if len(self.visited) + len(self.enqueued) >= self.max_pages:
            return
        if url in self.visited or url in self.enqueued:
            return
        self.enqueued.add(url)
        await self.queue.put(CrawlJob(url=url, depth=depth))

    async def emit(self, url: str, interesting: bool | None = None) -> None:
        lowered = url.lower()
        if self.match_keywords and not any(keyword in lowered for keyword in self.match_keywords):
            return
        if self.exclude_keywords and any(keyword in lowered for keyword in self.exclude_keywords):
            return
        async with self.print_lock:
            if url in self.printed:
                return
            self.printed.add(url)
            if interesting is None:
                interesting = is_interesting_url(url)
            label = INTERESTING_SUFFIX if interesting and not self.quiet_interesting else ""
            print(f"{url}{label}", flush=True)

    async def next_headers(self) -> dict[str, str]:
        headers = dict(self.headers)
        if not self.user_agents:
            return headers
        async with self.ua_lock:
            headers["User-Agent"] = self.user_agents[self.ua_index]
            self.ua_index = (self.ua_index + 1) % len(self.user_agents)
        return headers

    async def fetch_text(self, session: AsyncSession, url: str) -> FetchResult | None:
        try:
            response = await session.get(
                url,
                allow_redirects=True,
                impersonate="chrome",
                headers=await self.next_headers(),
            )
        except RequestsError:
            return None

        final_url = str(response.url)
        if not self.in_scope(final_url):
            return None
        if response.status_code >= 400:
            return None

        data = response.content or b""
        if not is_textual(response.headers.get("Content-Type", ""), data):
            await self.emit(final_url)
            return FetchResult(final_url=final_url, text=None)
        text = data.decode(response.charset or "utf-8", errors="ignore")
        interesting = is_interesting_url(final_url)
        if not interesting and url_supports_content_label(final_url):
            interesting = has_interesting_content(text)
        await self.emit(final_url, interesting=interesting)
        return FetchResult(final_url=final_url, text=text)

    async def worker(self, session: AsyncSession) -> None:
        while True:
            try:
                job = await self.queue.get()
            except asyncio.CancelledError:
                return

            if job is None:
                self.queue.task_done()
                return

            try:
                if job.url in self.visited:
                    continue

                self.visited.add(job.url)
                result = await self.fetch_text(session, job.url)
                if not result or not result.text or job.depth >= self.max_depth:
                    continue

                for candidate in iter_candidates(result.text):
                    normalized = normalize_url(candidate, result.final_url)
                    if not normalized or not self.in_scope(normalized):
                        continue
                    await self.enqueue(normalized, job.depth + 1)
            except asyncio.CancelledError:
                raise
            finally:
                self.queue.task_done()

    async def run(self) -> None:
        session = AsyncSession(
            headers=self.headers,
            cookies=self.cookies,
            max_clients=self.concurrency,
            timeout=self.timeout,
            verify=False,
        )
        workers = []
        try:
            await self.enqueue(self.start_url, 0)
            workers = [asyncio.create_task(self.worker(session)) for _ in range(self.concurrency)]
            await self.queue.join()
        finally:
            for worker in workers:
                if not worker.done():
                    worker.cancel()
            if workers:
                await asyncio.gather(*workers, return_exceptions=True)
            await session.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fast recursive endpoint crawler for one base domain and its subdomains."
    )
    parser.add_argument("url", help="Starting URL, e.g. https://target.tld")
    parser.add_argument(
        "--cookie",
        default="",
        help='Cookies in JSON object format, e.g. \'{"session":"value"}\'',
    )
    parser.add_argument(
        "--header",
        default="",
        help='Headers in JSON object format, e.g. \'{"Authorization":"Bearer x"}\'',
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=DEFAULT_MAX_DEPTH,
        help="Maximum crawl depth from the starting URL.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help="Maximum number of URLs/resources to process.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help="Number of concurrent worker requests.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="Per-request timeout in seconds.",
    )
    parser.add_argument(
        "--match",
        default="",
        help='Only print URLs containing these keywords. Comma-separated, e.g. "graphql,api".',
    )
    parser.add_argument(
        "--exclude",
        default="",
        help='Do not print URLs containing these keywords. Comma-separated, e.g. ".jpg,.css,.pdf".',
    )
    parser.add_argument("-s", action="store_true", help="Hide the interesting suffix in output.")
    return parser


async def async_main(args: argparse.Namespace) -> int:
    start_url = normalize_url(args.url, args.url)
    if not start_url:
        raise SystemExit("Invalid start URL.")

    spider = UrlSpider(
        start_url=start_url,
        headers=parse_json_object(args.header, "header"),
        cookies=parse_json_object(args.cookie, "cookie"),
        max_depth=max(0, args.max_depth),
        max_pages=max(1, args.max_pages),
        concurrency=max(1, args.concurrency),
        timeout=max(1.0, args.timeout),
        match_keywords=parse_keywords(args.match),
        exclude_keywords=parse_keywords(args.exclude),
        quiet_interesting=args.s,
    )
    await spider.run()
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        print(BANNER, flush=True)
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

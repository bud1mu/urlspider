# urlspider

Fast recursive endpoint crawler for a target URL, scoped to the same base domain and its subdomains.

`urlspider` requests a starting URL, extracts URL candidates from `href` and `src`, normalizes relative paths to absolute URLs, and keeps crawling deeper while staying inside scope. It also scans textual responses such as HTML, JS, CSS, JSON, and XML for more URLs.

## Features

- Built on `curl_cffi`
- Simple CLI with only the core crawl controls
- Fast concurrent crawling with internal worker pool
- Recursive crawling for same base domain and subdomains
- Rotates `User-Agent` per request using `agent.txt`
- Prints valid in-scope URLs to stdout immediately
- Deduplicates URLs to avoid loops
- Scans HTML, JS, CSS, JSON, XML, and other text-like responses
- Marks potentially interesting URLs such as API or GraphQL paths in the output

## Requirements

- Python 3.10+
- `curl_cffi`

Install dependency:

```bash
pip install curl_cffi
```

## Installation

Clone the repository:

```bash
git clone https://github.com/your-username/urlspider.git
cd urlspider
```

Install the dependency:

```bash
pip install curl_cffi
```

Make the script executable:

```bash
chmod +x urlspider.py
```

Create a symlink so it can be called globally from the terminal:

```bash
sudo ln -sf "$(pwd)/urlspider.py" /usr/local/bin/urlspider
```

Verify the command:

```bash
urlspider --help
```

After that, you can run it directly from anywhere:

```bash
urlspider https://target.com
```

## Usage

Basic:

```bash
urlspider https://target.com
```

With cookies:

```bash
urlspider https://target.com --cookie '{"session":"value"}'
```

With custom headers:

```bash
urlspider https://target.com --header '{"Authorization":"Bearer token"}'
```

With both:

```bash
urlspider https://target.com --cookie '{"session":"value"}' --header '{"Authorization":"Bearer token"}'
```

User-Agent rotation is loaded automatically from `agent.txt` in the current directory. If `agent.txt` is missing or empty, the default header inside the script is used.

With crawl tuning:

```bash
urlspider https://target.com --max-depth 4 --max-pages 8000 --concurrency 80 --timeout 20
```

Only show URLs containing specific keywords:

```bash
urlspider https://target.com --match "graphql,api"
```

Hide URLs containing specific keywords:

```bash
urlspider https://target.com --exclude ".jpg,.css,.pdf"
```

Use both filters together:

```bash
urlspider https://target.com --match "graphql,api" --exclude ".jpg,.css,.pdf"
```

Hide the interesting suffix:

```bash
urlspider https://target.com -s
```

## CLI

```text
usage: urlspider.py [-h] [--cookie COOKIE] [--header HEADER]
                    [--max-depth MAX_DEPTH] [--max-pages MAX_PAGES]
                    [--concurrency CONCURRENCY] [--timeout TIMEOUT]
                    [--match MATCH] [--exclude EXCLUDE] [-s]
                    url
```

- `url`
  Starting target URL. This is the first page or resource requested by the crawler.
- `--cookie`
  Optional cookies in JSON object format. Example: `{"session":"value"}`.
- `--header`
  Optional headers in JSON object format. Example: `{"Authorization":"Bearer token"}`.
- `--max-depth`
  Maximum crawl depth from the starting URL.
  `0` means only the input URL.
  `1` means the input URL plus URLs found directly inside it.
  Higher values allow deeper recursive crawling.
- `--max-pages`
  Maximum total number of URLs or resources the crawler is allowed to process.
  This prevents the crawl from growing indefinitely on very large sites.
- `--concurrency`
  Number of requests that can run in parallel.
  Higher values increase crawl speed, but also increase load on the target and local resource usage.
- `--timeout`
  Per-request timeout in seconds.
  If a request takes longer than this value, it is treated as failed and the crawler continues with other targets.
- `--match`
  Only print URLs containing one or more of the given keywords.
  Use a comma-separated list such as `"graphql,api"`.
- `--exclude`
  Do not print URLs containing one or more of the given keywords.
  Use a comma-separated list such as `".jpg,.css,.pdf"`.
- `-s`
  Hide the `interesting` suffix in output.

## Output

The script prints only valid discovered URLs to stdout, one per line, as soon as they are found.
If a URL looks interesting, the script appends:

```text
 <- interesting, u should look at this bro
```

Example:

```text
https://target.com/
https://target.com/assets/app.js
https://api.target.com/v1/users <- interesting, u should look at this bro
```

## Defaults

- max depth: `3`
- max pages: `5000`
- concurrency: `40`
- timeout: `15` seconds
- user-agent source: `agent.txt`
- output match filter: disabled by default
- output exclude filter: disabled by default
- interesting suffix: enabled by default

## Scope Rules

- In-scope: the same base domain and its subdomains
- Out-of-scope: external domains
- Relative paths are resolved against the current response URL
- Fragment-only links such as `#section` are ignored
- Non-HTTP schemes such as `javascript:`, `mailto:`, `tel:`, `data:`, and `blob:` are ignored

## Notes

- The crawler uses regex-based extraction, not a headless browser.
- URLs generated only at runtime in the browser may not be discovered.
- The script only prints URLs that return a successful response.
- `--match` and `--exclude` filter printed output only. Crawling still continues in scope.
- Interesting URL labeling is based on tighter endpoint-oriented patterns such as API, GraphQL, auth, docs, webhook, RPC, and versioned paths.

## Disclaimer

Use this tool only on systems and targets you are authorized to test.

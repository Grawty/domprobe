# domprobe

DOM locator ranker, XHR/Fetch/GraphQL sniffer, `curl` exporter, and Selenium `PageObject` / `requests` client generator.

## Features

- **Resilience-Scored Locators (`0–100`)**: Ranks interactive elements using `data-testid`, static `#id`, `name`, `aria-label`, semantic XPath, and filters out obfuscated CSS hashes (`css-*`, `sc-*`, `e-*`).
- **CDP & JS Network Hook**: Intercepts `window.fetch`, `XMLHttpRequest`, and Chrome DevTools `Network.requestWillBeSent` events (including request headers and POST payloads).
- **HAR Parser & `curl` Exporter**: Parses exported `.har` files into clean API definitions and ready-to-run `curl` commands.
- **Code Generation**: Emits a Python module (`*_client.py`) containing a `PageLocators` class, `PageObject` wrapper, and `DiscoveredAPIClient` session class.

## CLI Usage

```bash
pip install -r requirements.txt

# Fast static HTML locator extraction
python main.py https://github.com/login

# Live Chrome CDP inspection (DOM + background XHR/Fetch/GraphQL APIs)
python main.py https://open.spotify.com --live

# Interactive mode: click around in Chrome, press Enter to dump locators + APIs
python main.py https://open.spotify.com --interactive

# Extract APIs and cURL commands from a .har capture
python main.py --har network_traffic.har
```

## Library Usage

```python
from core import analyze_static_html, parse_har_file, to_curl

locators = analyze_static_html("https://example.com")
for loc in locators[:5]:
    print(loc["score"], loc["ident"], loc["primary_css"])

apis = parse_har_file("capture.har")
for api in apis:
    print(to_curl(api))
```

## Disclaimer

For educational, E2E/QA testing, and authorized security research only. Provided "AS IS" under the [MIT License](LICENSE); the author assumes no liability for misuse or third-party ToS violations.


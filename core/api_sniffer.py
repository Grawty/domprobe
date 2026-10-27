import json

IGNORE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".woff", ".woff2", ".ttf", ".css", ".ico", ".webp")
IGNORE_HOSTS = ("google-analytics.com", "doubleclick.net", "googletagmanager.com", "facebook.net", "hotjar.com", "sentry.io")


def install_network_hook(driver):
    js = """
    window.__wx_calls = [];
    const origFetch = window.fetch;
    window.fetch = function(input, init) {
        try {
            const url = typeof input === 'string' ? input : (input && input.url) || '';
            const method = ((init && init.method) || 'GET').toUpperCase();
            const body = (init && typeof init.body === 'string') ? init.body.slice(0, 500) : null;
            let headers = {};
            if (init && init.headers) {
                if (typeof init.headers.forEach === 'function') {
                    init.headers.forEach((v, k) => { headers[k] = v; });
                } else if (typeof init.headers === 'object') {
                    headers = Object.assign({}, init.headers);
                }
            }
            window.__wx_calls.push({ source: 'fetch', method, url, headers, body });
        } catch (e) {}
        return origFetch.apply(this, arguments);
    };
    const origOpen = XMLHttpRequest.prototype.open;
    const origSend = XMLHttpRequest.prototype.send;
    const origHeader = XMLHttpRequest.prototype.setRequestHeader;
    XMLHttpRequest.prototype.open = function(method, url) {
        this.__wx = { source: 'xhr', method: (method || 'GET').toUpperCase(), url: String(url || ''), headers: {} };
        return origOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.setRequestHeader = function(k, v) {
        if (this.__wx) this.__wx.headers[k] = v;
        return origHeader.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function(body) {
        if (this.__wx) {
            if (typeof body === 'string') this.__wx.body = body.slice(0, 500);
            window.__wx_calls.push(this.__wx);
        }
        return origSend.apply(this, arguments);
    };
    """
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": js})
    except Exception:
        pass


def collect_live_apis(driver):
    endpoints = {}

    try:
        hooked = driver.execute_script("return window.__wx_calls || [];") or []
        for item in hooked:
            url = item.get("url", "")
            if not _is_api_candidate(url, item.get("method", "GET")):
                continue
            key = f"{item.get('method', 'GET')} {url.split('?')[0]}"
            endpoints[key] = _normalize_entry(
                item.get("method", "GET"),
                url,
                item.get("headers") or {},
                item.get("body"),
            )
    except Exception:
        pass

    try:
        for entry in driver.get_log("performance"):
            msg = json.loads(entry["message"])["message"]
            if msg.get("method") != "Network.requestWillBeSent":
                continue
            params = msg.get("params", {})
            rtype = params.get("type", "")
            req = params.get("request", {})
            url = req.get("url", "")
            method = req.get("method", "GET")
            if rtype in ("XHR", "Fetch") or _is_api_candidate(url, method):
                if _is_ignored(url):
                    continue
                key = f"{method} {url.split('?')[0]}"
                if key not in endpoints:
                    endpoints[key] = _normalize_entry(
                        method,
                        url,
                        req.get("headers") or {},
                        req.get("postData"),
                    )
    except Exception:
        pass

    return list(endpoints.values())


def parse_har_file(har_path):
    with open(har_path, "r", encoding="utf-8", errors="ignore") as f:
        data = json.load(f)

    endpoints = {}
    for entry in data.get("log", {}).get("entries", []):
        req = entry.get("request", {})
        url = req.get("url", "")
        method = req.get("method", "GET")
        if _is_ignored(url):
            continue
        if not _is_api_candidate(url, method) and method not in ("POST", "PUT", "PATCH", "DELETE"):
            continue
        headers = {h["name"]: h["value"] for h in req.get("headers", []) if "name" in h and "value" in h}
        post_data = (req.get("postData") or {}).get("text")
        key = f"{method} {url.split('?')[0]}"
        endpoints[key] = _normalize_entry(method, url, headers, post_data)
    return list(endpoints.values())


def to_curl(entry):
    parts = [f"curl -X {entry['method']} '{entry['url']}'"]
    for k, v in (entry.get("headers") or {}).items():
        if k.lower() in ("authorization", "content-type", "accept", "x-csrf-token", "client-token"):
            parts.append(f"-H '{k}: {v}'")
    if entry.get("body"):
        escaped = entry["body"].replace("'", "'\\''")
        parts.append(f"--data-raw '{escaped}'")
    return " \\\n  ".join(parts)


def _normalize_entry(method, url, headers, body):
    kind = "GraphQL" if ("graphql" in url.lower() or "pathfinder" in url.lower() or "query" in url.lower()) else "REST"
    filtered_headers = {
        k: v for k, v in headers.items()
        if k.lower() in ("authorization", "content-type", "accept", "x-csrf-token", "client-token", "app-platform")
    }
    return {
        "kind": kind,
        "method": method,
        "url": url,
        "headers": filtered_headers,
        "body": body[:500] if isinstance(body, str) else None,
    }


def _is_ignored(url):
    u = url.lower().split("?")[0]
    return any(u.endswith(ext) for ext in IGNORE_EXT) or any(h in u for h in IGNORE_HOSTS)


def _is_api_candidate(url, method="GET"):
    if _is_ignored(url):
        return False
    u = url.lower()
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        return True
    tokens = ("/api/", "/v1/", "/v2/", "/v3/", "graphql", "pathfinder", ".json", "token", "auth", "login", "signup", "query")
    return any(t in u for t in tokens)

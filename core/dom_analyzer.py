from html.parser import HTMLParser
import re
import requests

DYNAMIC_CLASS_RE = re.compile(r"^(?:css|sc|emotion|e|jsx|svelte|tw)-[a-zA-Z0-9_-]+$|^[a-zA-Z]{1,3}[0-9]{3,}$")
INTERACTIVE_TAGS = ("button", "input", "select", "textarea", "a", "form")
TEXT_TAGS = ("button", "a", "label", "span", "li", "option", "h1", "h2", "h3")
SEMANTIC_ATTRS = ("data-testid", "data-qa", "data-cy", "data-test", "role", "aria-label", "placeholder", "name", "id")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/134.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class _DOMParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.nodes = []
        self._stack = []

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t in ("script", "style", "meta", "link", "head", "svg", "path", "noscript"):
            return
        attr_map = {k.lower(): (v or "") for k, v in attrs if k}
        has_semantic = any(attr_map.get(a, "").strip() for a in SEMANTIC_ATTRS)
        if t not in INTERACTIVE_TAGS and not has_semantic:
            return

        node = {
            "tag": t,
            "id": attr_map.get("id", ""),
            "name": attr_map.get("name", ""),
            "type": attr_map.get("type", ""),
            "testid": (
                attr_map.get("data-testid")
                or attr_map.get("data-qa")
                or attr_map.get("data-cy")
                or attr_map.get("data-test")
                or ""
            ),
            "aria_label": attr_map.get("aria-label", ""),
            "placeholder": attr_map.get("placeholder", ""),
            "role": attr_map.get("role", ""),
            "href": attr_map.get("href", "") or attr_map.get("action", ""),
            "class_name": attr_map.get("class", ""),
            "text": attr_map.get("value", "").strip()[:60],
            "_collect_text": t in TEXT_TAGS or bool(attr_map.get("role") or attr_map.get("data-testid")),
        }
        self.nodes.append(node)
        if t not in ("input", "img", "br", "hr"):
            self._stack.append(node)

    def handle_data(self, data):
        if not self._stack:
            return
        chunk = data.strip()
        if not chunk:
            return
        for node in reversed(self._stack):
            if node.get("_collect_text"):
                cur = node["text"]
                node["text"] = (f"{cur} {chunk}".strip() if cur else chunk)[:60]
                break

    def handle_endtag(self, tag):
        t = tag.lower()
        for idx in range(len(self._stack) - 1, -1, -1):
            if self._stack[idx]["tag"] == t:
                self._stack.pop(idx)
                break


def _stable_classes(class_str):
    if not class_str:
        return []
    out = []
    for c in class_str.split():
        c = c.strip()
        if len(c) > 2 and not DYNAMIC_CLASS_RE.match(c) and not re.search(r"\d{4,}", c):
            out.append(c)
    return out[:2]


def rank_element(el):
    tag = el.get("tag", "div")
    el_id = el.get("id", "").strip()
    testid = el.get("testid", "").strip()
    name = el.get("name", "").strip()
    aria = el.get("aria_label", "").strip()
    placeholder = el.get("placeholder", "").strip()
    el_type = el.get("type", "").strip()
    role = el.get("role", "").strip()
    href = el.get("href", "").strip()
    text = el.get("text", "").strip()
    stable_cls = _stable_classes(el.get("class_name", ""))

    css_list = []
    score = 50
    strategy = "tag"

    if testid:
        css_list.append(f"{tag}[data-testid='{testid}']")
        score = 98
        strategy = "data-testid"

    if el_id and not re.search(r"\d{4,}", el_id):
        css_list.append(f"{tag}#{el_id}")
        if score < 95:
            score = 95
            strategy = "id"

    if name:
        css_list.append(f"{tag}[name='{name}']")
        if score < 90:
            score = 90
            strategy = "name"

    if aria:
        escaped = aria.replace("'", "\\'")[:45]
        css_list.append(f"{tag}[aria-label*='{escaped}']")
        if score < 86:
            score = 86
            strategy = "aria-label"

    if placeholder:
        escaped = placeholder.replace("'", "\\'")[:40]
        css_list.append(f"{tag}[placeholder*='{escaped}']")
        if score < 82:
            score = 82
            strategy = "placeholder"

    if role:
        css_list.append(f"{tag}[role='{role}']")
        if score < 76:
            score = 76
            strategy = "role"

    if href and not href.startswith(("javascript:", "#")):
        clean_href = href.split("?")[0].replace("'", "\\'")[:60]
        if clean_href:
            attr_name = "action" if tag == "form" else "href"
            css_list.append(f"{tag}[{attr_name}*='{clean_href}']")
            if score < 75:
                score = 75
                strategy = attr_name

    if stable_cls:
        css_list.append(f"{tag}.{'.'.join(stable_cls)}")
        if score < 74:
            score = 74
            strategy = "stable-class"

    if el_type and tag in ("input", "button"):
        css_list.append(f"{tag}[type='{el_type}']")
        if score < 70:
            score = 70
            strategy = "type"

    if testid:
        xpath = f"//{tag}[@data-testid='{testid}']"
    elif el_id and not re.search(r"\d{4,}", el_id):
        xpath = f"//{tag}[@id='{el_id}']"
    elif text and len(text) <= 45 and "'" not in text:
        xpath = f"//{tag}[normalize-space()='{text}']"
        if score < 78:
            score = 78
            strategy = "text-xpath"
    elif aria and "'" not in aria:
        xpath = f"//{tag}[contains(@aria-label, '{aria[:30]}')]"
    elif name:
        xpath = f"//{tag}[@name='{name}']"
    elif href and not href.startswith(("javascript:", "#")) and "'" not in href:
        xpath = f"//{tag}[contains(@href, '{href.split('?')[0][:45]}')]"
    elif role:
        xpath = f"//{tag}[@role='{role}']"
    else:
        xpath = f"//{tag}"

    primary = css_list[0] if css_list else xpath
    fallback = css_list[1] if len(css_list) > 1 else xpath

    raw_label = testid or el_id or name or aria or placeholder or text or role or href.strip("/").split("/")[-1] or f"{tag}_el"
    ident = re.sub(r"[^a-zA-Z0-9_]", "_", raw_label.lower()).strip("_")[:32] or tag
    if ident[0].isdigit():
        ident = f"el_{ident}"

    return {
        "ident": ident,
        "tag": tag,
        "label": text or aria or placeholder or name or el_id or testid or role or tag,
        "primary_css": primary,
        "fallback": fallback,
        "xpath": xpath,
        "score": score,
        "strategy": strategy,
    }


def analyze_live_dom(driver):
    js = """
    const out = [];
    const q = [
        'button', 'input', 'select', 'textarea', 'a[href]', 'form',
        '[data-testid]', '[data-qa]', '[data-cy]', '[data-test]',
        '[role="button"]', '[role="link"]', '[role="tab"]', '[role="searchbox"]', '[role="menuitem"]',
        '[aria-label]'
    ].join(', ');
    document.querySelectorAll(q).forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return;
        out.push({
            tag: el.tagName.toLowerCase(),
            id: el.id || '',
            name: el.getAttribute('name') || '',
            type: el.getAttribute('type') || '',
            testid: el.getAttribute('data-testid') || el.getAttribute('data-qa') || el.getAttribute('data-cy') || el.getAttribute('data-test') || '',
            aria_label: el.getAttribute('aria-label') || '',
            placeholder: el.getAttribute('placeholder') || '',
            role: el.getAttribute('role') || '',
            href: el.getAttribute('href') || el.getAttribute('action') || '',
            class_name: (typeof el.className === 'string' ? el.className : ''),
            text: (el.innerText || el.value || '').trim().slice(0, 60)
        });
    });
    return out;
    """
    raw = driver.execute_script(js) or []
    ranked = [rank_element(e) for e in raw]
    ranked = [r for r in ranked if r["score"] >= 65]
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return _deduplicate(ranked)


def fetch_static_page(url, timeout=12):
    r = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    return r.text, r.url


def analyze_static_html(url, timeout=12, html=None):
    if html is None:
        html, _ = fetch_static_page(url, timeout=timeout)
    parser = _DOMParser()
    parser.feed(html)
    ranked = [rank_element(e) for e in parser.nodes]
    ranked = [x for x in ranked if x["score"] >= 65]
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return _deduplicate(ranked)


def _deduplicate(items):
    seen = set()
    unique = []
    for item in items:
        key = (item["primary_css"], item["xpath"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique

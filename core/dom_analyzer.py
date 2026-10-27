from html.parser import HTMLParser
import re
import requests

DYNAMIC_CLASS_RE = re.compile(r"^(?:css|sc|emotion|e|jsx|svelte|tw)-[a-zA-Z0-9_-]+$|^[a-zA-Z]{1,3}[0-9]{3,}$")


class _DOMParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.nodes = []
        self._tag = None
        self._attrs = {}
        self._text = []

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        if t in ("button", "input", "select", "textarea", "a", "form"):
            self._tag = t
            self._attrs = attr_map
            self._text = []
            if t == "input":
                self._flush()

    def handle_data(self, data):
        if self._tag:
            self._text.append(data.strip())

    def handle_endtag(self, tag):
        if self._tag and tag.lower() == self._tag:
            if self._tag != "input":
                self._flush()
            self._tag = None

    def _flush(self):
        text = " ".join(x for x in self._text if x).strip()[:60]
        self.nodes.append({
            "tag": self._tag,
            "id": self._attrs.get("id", ""),
            "name": self._attrs.get("name", ""),
            "type": self._attrs.get("type", ""),
            "testid": (
                self._attrs.get("data-testid")
                or self._attrs.get("data-qa")
                or self._attrs.get("data-cy")
                or self._attrs.get("data-test")
                or ""
            ),
            "aria_label": self._attrs.get("aria-label", ""),
            "placeholder": self._attrs.get("placeholder", ""),
            "role": self._attrs.get("role", ""),
            "href": self._attrs.get("href", ""),
            "class_name": self._attrs.get("class", ""),
            "text": text,
        })
        self._tag = None


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
    elif el_id:
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
    else:
        xpath = f"//{tag}"

    primary = css_list[0] if css_list else tag
    fallback = css_list[1] if len(css_list) > 1 else xpath

    raw_label = testid or el_id or name or aria or placeholder or text or f"{tag}_el"
    ident = re.sub(r"[^a-zA-Z0-9_]", "_", raw_label.lower()).strip("_")[:32] or tag
    if ident[0].isdigit():
        ident = f"el_{ident}"

    return {
        "ident": ident,
        "tag": tag,
        "label": text or aria or placeholder or name or el_id or testid or tag,
        "primary_css": primary,
        "fallback": fallback,
        "xpath": xpath,
        "score": score,
        "strategy": strategy,
    }


def analyze_live_dom(driver):
    js = """
    const out = [];
    const q = 'button, input, select, textarea, a[role="button"], a[href*="login"], a[href*="signup"], form';
    document.querySelectorAll(q).forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return;
        out.push({
            tag: el.tagName.toLowerCase(),
            id: el.id || '',
            name: el.getAttribute('name') || '',
            type: el.getAttribute('type') || '',
            testid: el.getAttribute('data-testid') || el.getAttribute('data-qa') || el.getAttribute('data-cy') || '',
            aria_label: el.getAttribute('aria-label') || '',
            placeholder: el.getAttribute('placeholder') || '',
            role: el.getAttribute('role') || '',
            href: el.getAttribute('href') || '',
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


def analyze_static_html(url, timeout=12):
    r = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/134.0.0.0"},
        timeout=timeout,
    )
    parser = _DOMParser()
    parser.feed(r.text)
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

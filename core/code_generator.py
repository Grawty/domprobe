import json
import os
import re
from urllib.parse import urlparse

from core.api_sniffer import to_curl

DEFAULT_OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")


def _slug(url):
    host = urlparse(url).netloc or "target"
    return re.sub(r"[^a-zA-Z0-9_-]", "_", host)


def export_artifacts(url, selectors, apis, out_dir=DEFAULT_OUT_DIR):
    os.makedirs(out_dir, exist_ok=True)
    name = _slug(url)

    json_path = os.path.join(out_dir, f"{name}_schema.json")
    md_path = os.path.join(out_dir, f"{name}_report.md")
    py_path = os.path.join(out_dir, f"{name}_client.py")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "url": url,
                "selectors": selectors,
                "apis": apis,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# domprobe Report: `{url}`\n\n")
        f.write(f"## Ranked Locators ({len(selectors)})\n\n")
        f.write("| Score | Strategy | Tag | Identifier | Primary CSS | XPath |\n")
        f.write("| :--- | :--- | :--- | :--- | :--- | :--- |\n")
        for s in selectors[:50]:
            f.write(
                f"| {s['score']} | `{s['strategy']}` | `{s['tag']}` | `{s['ident']}` | "
                f"`{s['primary_css']}` | `{s['xpath']}` |\n"
            )

        f.write(f"\n## Captured API Endpoints ({len(apis)})\n\n")
        for a in apis[:30]:
            f.write(f"### `{a['method']}` `{a['url'][:100]}` ({a['kind']})\n\n")
            f.write(f"```bash\n{to_curl(a)}\n```\n\n")

    _write_python_module(py_path, url, selectors, apis)

    return {
        "json": json_path,
        "md": md_path,
        "py": py_path,
    }


def _write_python_module(py_path, url, selectors, apis):
    used_names = set()
    locator_lines = []
    for s in selectors[:35]:
        ident = s["ident"].upper()
        base = ident
        idx = 2
        while ident in used_names:
            ident = f"{base}_{idx}"
            idx += 1
        used_names.add(ident)
        css = s["primary_css"].replace('"', '\\"')
        locator_lines.append(f'    {ident} = (By.CSS_SELECTOR, "{css}")')

    with open(py_path, "w", encoding="utf-8") as f:
        f.write("import requests\n")
        f.write("from selenium.webdriver.common.by import By\n")
        f.write("from selenium.webdriver.support.ui import WebDriverWait\n")
        f.write("from selenium.webdriver.support import expected_conditions as EC\n\n\n")
        f.write("class PageLocators:\n")
        f.write(f'    URL = "{url}"\n')
        if locator_lines:
            f.write("\n".join(locator_lines) + "\n")
        else:
            f.write("    pass\n")

        f.write("\n\nclass PageObject:\n")
        f.write("    def __init__(self, driver, timeout=15):\n")
        f.write("        self.driver = driver\n")
        f.write("        self.wait = WebDriverWait(driver, timeout)\n\n")
        f.write("    def open(self):\n")
        f.write("        self.driver.get(PageLocators.URL)\n\n")
        f.write("    def click(self, locator):\n")
        f.write("        el = self.wait.until(EC.element_to_be_clickable(locator))\n")
        f.write("        el.click()\n")
        f.write("        return el\n\n")
        f.write("    def fill(self, locator, text):\n")
        f.write("        el = self.wait.until(EC.element_to_be_clickable(locator))\n")
        f.write("        el.clear()\n")
        f.write("        el.send_keys(text)\n")
        f.write("        return el\n")

        if apis:
            f.write("\n\nclass DiscoveredAPIClient:\n")
            f.write("    def __init__(self, headers=None, proxies=None):\n")
            f.write("        self.session = requests.Session()\n")
            f.write("        if headers:\n")
            f.write("            self.session.headers.update(headers)\n")
            f.write("        if proxies:\n")
            f.write("            self.session.proxies.update(proxies)\n\n")
            for idx, a in enumerate(apis[:15], 1):
                m = a["method"].lower()
                u = a["url"].replace('"', '\\"')
                f.write(f"    def call_endpoint_{idx}(self, **kwargs):\n")
                f.write(f'        return self.session.request("{m.upper()}", "{u}", **kwargs)\n\n')

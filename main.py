import argparse
import os
import sys
import time

from core.api_sniffer import collect_live_apis, extract_static_apis, install_network_hook, parse_har_file
from core.browser_engine import launch_browser
from core.code_generator import export_artifacts
from core.dom_analyzer import analyze_live_dom, analyze_static_html, fetch_static_page


def _normalize_url(url):
    url = (url or "").strip()
    if url and not url.startswith("http"):
        return "https://" + url
    return url


def _merge_apis(existing, new_items):
    by_key = {f"{a['method']} {a['url'].split('?')[0]}": a for a in existing}
    for item in new_items:
        key = f"{item['method']} {item['url'].split('?')[0]}"
        if key not in by_key:
            by_key[key] = item
    return list(by_key.values())


def _capture_with_chrome(url, wait_sec=5.0, interactive=False):
    driver = launch_browser(headless=not interactive)
    try:
        install_network_hook(driver)
        print(f"[*] Loading {url} via Chrome CDP...")
        driver.get(url)
        time.sleep(wait_sec)
        if interactive:
            input("[*] Interact with the page in Chrome, then press Enter to capture...")
        selectors = analyze_live_dom(driver)
        apis = collect_live_apis(driver)
        return selectors, apis
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def build_parser():
    p = argparse.ArgumentParser(
        prog="domprobe",
        description="DOM locator ranker, XHR/Fetch/GraphQL sniffer, and PageObject/API code generator.",
        epilog="Disclaimer: For educational and authorized E2E/QA testing only. Provided AS-IS.",
    )
    p.add_argument("url", nargs="?", help="Target URL to inspect")
    p.add_argument("--live", action="store_true", help="Use real Chrome + CDP network hooks instead of static HTTP")
    p.add_argument("--interactive", action="store_true", help="Keep browser open until Enter is pressed to capture manual actions")
    p.add_argument("--no-fallback", action="store_true", help="Disable automatic Chrome fallback when a client-side SPA shell is detected")
    p.add_argument("--wait", type=float, default=5.0, help="Seconds to wait after page load in live mode")
    p.add_argument("--har", help="Parse an exported .har file for API endpoints")
    p.add_argument("-o", "--out-dir", default=None, help="Output directory for generated code and reports")
    return p


def run_cli(args):
    selectors = []
    apis = []
    target_label = args.url or "https://har-capture.local"

    if args.har:
        if not os.path.exists(args.har):
            print(f"[-] HAR file not found: {args.har}")
            return 1
        apis = _merge_apis(apis, parse_har_file(args.har))
        print(f"[*] Extracted {len(apis)} API endpoints from {args.har}")

    if args.url:
        url = _normalize_url(args.url)
        target_label = url
        if args.live or args.interactive:
            live_sel, live_apis = _capture_with_chrome(url, wait_sec=args.wait, interactive=args.interactive)
            selectors = live_sel
            apis = _merge_apis(apis, live_apis)
        else:
            print(f"[*] Fetching static DOM from {url}...")
            html, final_url = fetch_static_page(url)
            target_label = final_url or url
            selectors = analyze_static_html(target_label, html=html)
            apis = _merge_apis(apis, extract_static_apis(html, base_url=target_label))

            if len(selectors) <= 2 and not args.no_fallback:
                print(f"[!] Client-side SPA detected ({len(selectors)} static DOM element(s) in raw HTML).")
                print("[*] Auto-falling back to Live Chrome CDP to render JS DOM & capture live APIs...")
                try:
                    live_sel, live_apis = _capture_with_chrome(target_label, wait_sec=args.wait, interactive=False)
                    if live_sel:
                        selectors = live_sel
                    apis = _merge_apis(apis, live_apis)
                except Exception as exc:
                    print(f"[!] Chrome fallback skipped: {exc}")

    out = export_artifacts(target_label, selectors, apis, out_dir=args.out_dir) if args.out_dir else export_artifacts(target_label, selectors, apis)

    print(f"\n[+] Locators ranked : {len(selectors)}")
    for s in selectors[:10]:
        print(f"    [{s['score']:>2}] {s['ident']:<24} -> {s['primary_css']}")

    print(f"[+] APIs captured   : {len(apis)}")
    for a in apis[:8]:
        print(f"    [{a['kind']:<7}] {a['method']:<5} {a['url'][:72]}")

    print("\n[+] Generated artifacts:")
    for k, v in out.items():
        print(f"    {k:<4} -> {v}")
    return 0


def interactive_prompt():
    print("domprobe — Locator Ranker, API Sniffer & Codegen")
    print("  [1] Live Chrome CDP Inspection (DOM + XHR/Fetch/GraphQL)")
    print("  [2] Fast Static HTTP DOM Inspection")
    print("  [3] Parse .HAR Network File")
    choice = input("\nSelect [1-3] (default 1): ").strip() or "1"

    parser = build_parser()
    if choice == "3":
        har_path = input("HAR file path: ").strip().strip('"')
        args = parser.parse_args(["--har", har_path])
    elif choice == "2":
        url = input("Target URL: ").strip()
        args = parser.parse_args([url])
    else:
        url = input("Target URL: ").strip()
        args = parser.parse_args([url, "--live"])

    run_cli(args)


if __name__ == "__main__":
    parser = build_parser()
    if len(sys.argv) > 1:
        sys.exit(run_cli(parser.parse_args()))
    interactive_prompt()

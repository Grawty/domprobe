import argparse
import os
import sys
import time

from core.api_sniffer import collect_live_apis, install_network_hook, parse_har_file
from core.browser_engine import launch_browser
from core.code_generator import export_artifacts
from core.dom_analyzer import analyze_live_dom, analyze_static_html


def _normalize_url(url):
    url = (url or "").strip()
    if url and not url.startswith("http"):
        return "https://" + url
    return url


def build_parser():
    p = argparse.ArgumentParser(
        prog="domprobe",
        description="DOM locator ranker, XHR/Fetch/GraphQL sniffer, and PageObject/API code generator.",
        epilog="Disclaimer: For educational and authorized E2E/QA testing only. Provided AS-IS.",
    )
    p.add_argument("url", nargs="?", help="Target URL to inspect")
    p.add_argument("--live", action="store_true", help="Use real Chrome + CDP network hooks instead of static HTTP")
    p.add_argument("--interactive", action="store_true", help="Keep browser open until Enter is pressed to capture manual actions")
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
        apis.extend(parse_har_file(args.har))
        print(f"[*] Extracted {len(apis)} API endpoints from {args.har}")

    if args.url:
        url = _normalize_url(args.url)
        target_label = url
        if args.live or args.interactive:
            driver = launch_browser(headless=not args.interactive)
            try:
                install_network_hook(driver)
                print(f"[*] Loading {url} via Chrome CDP...")
                driver.get(url)
                time.sleep(args.wait)
                if args.interactive:
                    input("[*] Interact with the page in Chrome, then press Enter to capture...")
                selectors = analyze_live_dom(driver)
                apis.extend(collect_live_apis(driver))
            finally:
                try:
                    driver.quit()
                except Exception:
                    pass
        else:
            print(f"[*] Fetching static DOM from {url}...")
            selectors = analyze_static_html(url)

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

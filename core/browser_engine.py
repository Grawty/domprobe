import os
import re
import subprocess
import sys
import types


def _ensure_distutils():
    try:
        import distutils.version  # noqa: F401
    except ModuleNotFoundError:
        d_mod = types.ModuleType("distutils")
        v_mod = types.ModuleType("distutils.version")

        class LooseVersion:
            def __init__(self, vstring=None):
                self.vstring = str(vstring or "")
                self.version = [
                    int(x) if x.isdigit() else x
                    for x in re.findall(r"\d+|[a-zA-Z]+", self.vstring)
                ]

            def __str__(self):
                return self.vstring

            def _cmp(self, other):
                if isinstance(other, str):
                    other = LooseVersion(other)
                a = [int(x) for x in re.findall(r"\d+", self.vstring)]
                b = [int(x) for x in re.findall(r"\d+", other.vstring)]
                return (a > b) - (a < b)

            def __eq__(self, other):
                return self._cmp(other) == 0

            def __lt__(self, other):
                return self._cmp(other) < 0

            def __le__(self, other):
                return self._cmp(other) <= 0

            def __gt__(self, other):
                return self._cmp(other) > 0

            def __ge__(self, other):
                return self._cmp(other) >= 0

        v_mod.LooseVersion = LooseVersion
        d_mod.version = v_mod
        sys.modules["distutils"] = d_mod
        sys.modules["distutils.version"] = v_mod


_ensure_distutils()


def detect_chrome_major():
    paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                for entry in os.listdir(os.path.dirname(p)):
                    m = re.match(r"^(\d+)\.\d+\.\d+\.\d+$", entry)
                    if m:
                        return int(m.group(1))
            except Exception:
                pass
    try:
        out = subprocess.check_output(
            ["reg", "query", r"HKEY_CURRENT_USER\Software\Google\Chrome\BLBeacon", "/v", "version"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        m = re.search(r"(\d+)\.\d+\.\d+\.\d+", out)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None


def launch_browser(headless=False):
    import undetected_chromedriver as uc

    opts = uc.ChromeOptions()
    if headless:
        opts.add_argument("--window-position=-3200,-3200")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    driver = uc.Chrome(options=opts, version_main=detect_chrome_major(), enable_cdp_events=True)
    driver.set_window_size(1440, 900)
    if headless:
        try:
            driver.set_window_position(-3200, -3200)
        except Exception:
            pass
    return driver

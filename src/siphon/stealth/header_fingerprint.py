from __future__ import annotations

import os
import re
import sys

BEARER_TOKEN = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

# Default Chrome version — updated by sync_chrome_version() at runtime
_DEFAULT_CHROME_VERSION = "133"
_chrome_version: str = _DEFAULT_CHROME_VERSION


def best_chrome_target() -> str:
    """Detect the best available Chrome impersonation target at runtime."""
    try:
        from curl_cffi.requests import BrowserType
        available = {e.value for e in BrowserType}
    except ImportError:
        available = set()

    for target in ("chrome133", "chrome133a", "chrome136", "chrome131", "chrome130"):
        if target in available:
            return target
    chrome_targets = sorted(
        [v for v in available if v.startswith("chrome") and v.replace("chrome", "").isdigit()],
        key=lambda x: int(x.replace("chrome", "")),
        reverse=True,
    )
    return chrome_targets[0] if chrome_targets else "chrome131"


def sync_chrome_version(impersonate: str = "chrome133") -> None:
    global _chrome_version
    match = re.search(r"(\d+)", impersonate)
    if match:
        _chrome_version = match.group(1)


def get_user_agent() -> str:
    if sys.platform == "darwin":
        plat = "Macintosh; Intel Mac OS X 10_15_7"
    elif sys.platform.startswith("win"):
        plat = "Windows NT 10.0; Win64; x64"
    else:
        plat = "X11; Linux x86_64"
    return (
        f"Mozilla/5.0 ({plat}) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{_chrome_version}.0.0.0 Safari/537.36"
    )


def get_sec_ch_ua() -> str:
    return (
        f'"Chromium";v="{_chrome_version}", '
        f'"Not(A:Brand";v="99", '
        f'"Google Chrome";v="{_chrome_version}"'
    )


def get_sec_ch_ua_full_version() -> str:
    return f'"{_chrome_version}.0.0.0"'


def get_sec_ch_ua_full_version_list() -> str:
    return (
        f'"Google Chrome";v="{_chrome_version}.0.0.0", '
        f'"Chromium";v="{_chrome_version}.0.0.0", '
        f'"Not.A/Brand";v="99.0.0.0"'
    )


def _get_locale_tag() -> str:
    raw = (
        os.environ.get("LC_ALL")
        or os.environ.get("LC_MESSAGES")
        or os.environ.get("LANG")
        or "en_US.UTF-8"
    )
    tag = raw.split(".", 1)[0].replace("_", "-")
    return tag or "en-US"


def get_accept_language() -> str:
    tag = _get_locale_tag()
    language = tag.split("-", 1)[0] or "en"
    return f"{tag},{language};q=0.9,en;q=0.8"


def get_twitter_client_language() -> str:
    return _get_locale_tag().split("-", 1)[0] or "en"


def get_sec_ch_ua_platform() -> str:
    if sys.platform == "darwin":
        return '"macOS"'
    if sys.platform.startswith("win"):
        return '"Windows"'
    return '"Linux"'


def get_sec_ch_ua_arch() -> str:
    machine = (os.uname().machine if hasattr(os, "uname") else "").lower()
    if "arm" in machine or "aarch" in machine:
        return '"arm"'
    if "86" in machine or "amd64" in machine or "x64" in machine:
        return '"x86"'
    return '""'


def get_sec_ch_ua_platform_version() -> str:
    if sys.platform == "darwin":
        return '"15.0.0"'
    if sys.platform.startswith("win"):
        return '"10.0.0"'
    return '""'


# Static Client Hints
SEC_CH_UA_MOBILE = "?0"
SEC_CH_UA_BITNESS = '"64"'
SEC_CH_UA_MODEL = '""'


def build_headers(ct0: str, url: str = "", method: str = "GET") -> dict[str, str]:
    headers: dict[str, str] = {
        "Authorization": f"Bearer {BEARER_TOKEN}",
        "X-Csrf-Token": ct0,
        "X-Twitter-Active-User": "yes",
        "X-Twitter-Client-Language": get_twitter_client_language(),
        "User-Agent": get_user_agent(),
        "Origin": "https://x.com",
        "Referer": "https://x.com/",
        "Accept": "*/*",
        "Accept-Language": get_accept_language(),
        "sec-ch-ua": get_sec_ch_ua(),
        "sec-ch-ua-mobile": SEC_CH_UA_MOBILE,
        "sec-ch-ua-platform": get_sec_ch_ua_platform(),
        "sec-ch-ua-arch": get_sec_ch_ua_arch(),
        "sec-ch-ua-bitness": SEC_CH_UA_BITNESS,
        "sec-ch-ua-full-version": get_sec_ch_ua_full_version(),
        "sec-ch-ua-full-version-list": get_sec_ch_ua_full_version_list(),
        "sec-ch-ua-model": SEC_CH_UA_MODEL,
        "sec-ch-ua-platform-version": get_sec_ch_ua_platform_version(),
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    if method == "POST":
        headers["Content-Type"] = "application/json"
        headers["Referer"] = "https://x.com/compose/post"
        headers["Priority"] = "u=1, i"
    return headers

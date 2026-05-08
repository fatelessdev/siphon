from __future__ import annotations

from dataclasses import dataclass

from siphon.config import get_settings


@dataclass(frozen=True)
class TwitterCookies:
    auth_token: str
    ct0: str
    cookie_string: str = ""

    def as_dict(self) -> dict[str, str]:
        cookies = {"auth_token": self.auth_token, "ct0": self.ct0}
        if self.cookie_string:
            cookies["cookie_string"] = self.cookie_string
        return cookies

    @property
    def header_value(self) -> str:
        return self.cookie_string or f"auth_token={self.auth_token}; ct0={self.ct0}"


def load_cookies() -> TwitterCookies:
    s = get_settings()
    if not s.twitter_auth_token or not s.twitter_ct0:
        raise ValueError("TWITTER_AUTH_TOKEN and TWITTER_CT0 must be set")
    return TwitterCookies(
        auth_token=s.twitter_auth_token,
        ct0=s.twitter_ct0,
        cookie_string=s.twitter_cookie_string.strip(),
    )

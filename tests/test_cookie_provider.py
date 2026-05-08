import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def test_load_cookies_preserves_full_cookie_string(monkeypatch):
    from siphon import config
    from siphon.auth.cookie_provider import load_cookies

    monkeypatch.setenv("TWITTER_AUTH_TOKEN", "auth")
    monkeypatch.setenv("TWITTER_CT0", "csrf")
    monkeypatch.setenv(
        "TWITTER_COOKIE_STRING",
        "auth_token=auth; ct0=csrf; twid=u%3D123; personalization_id=v1_demo",
    )
    config._settings = None

    cookies = load_cookies()

    assert cookies.cookie_string == (
        "auth_token=auth; ct0=csrf; twid=u%3D123; personalization_id=v1_demo"
    )
    assert cookies.as_dict()["cookie_string"] == cookies.cookie_string


def test_graphql_headers_prefer_full_cookie_string():
    from siphon.extract.graphql_engine import GraphQLSession

    full_cookie = "auth_token=auth; ct0=csrf; twid=u%3D123; personalization_id=v1_demo"
    engine = GraphQLSession(
        session=object(),
        ct0="csrf",
        transaction_id_mgr=None,
        auth_token="auth",
        cookie_string=full_cookie,
    )

    headers = engine._build_request_headers(url="https://x.com/i/api/graphql/demo/HomeLatestTimeline")

    assert headers["Cookie"] == full_cookie

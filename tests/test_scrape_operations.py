import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def test_scheduled_scrape_runs_for_you_then_following():
    from siphon.jobs.scrape_timeline import resolve_scrape_operations

    assert resolve_scrape_operations("scheduled") == ("home", "following")
    assert resolve_scrape_operations("both") == ("home", "following")
    assert resolve_scrape_operations("all") == ("home", "following")


def test_for_you_alias_resolves_to_home_operation():
    from siphon.jobs.scrape_timeline import resolve_scrape_operations

    assert resolve_scrape_operations("for-you") == ("home",)
    assert resolve_scrape_operations("home") == ("home",)
    assert resolve_scrape_operations("following") == ("following",)

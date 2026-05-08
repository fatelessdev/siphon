"""Smoke tests for the parser layer."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from siphon.parse.timeline_parser import parse_timeline_response
from siphon.parse.article_parser import parse_article_content
from siphon.parse.parse_stats import ParseStats

FIXTURES = Path(__file__).parent.parent.parent / "twitter-cli" / "tests" / "fixtures"


def _minimal_tweet_entry(tweet_id: int, handle: str, text: str, source: str = "Twitter Web App"):
    return {
        "entryId": f"tweet-{tweet_id}",
        "content": {
            "entryType": "TimelineTimelineItem",
            "itemContent": {
                "tweet_results": {
                    "result": {
                        "__typename": "Tweet",
                        "rest_id": str(tweet_id),
                        "legacy": {
                            "created_at": "Fri May 08 00:00:00 +0000 2026",
                            "full_text": text,
                            "source": source,
                            "favorite_count": 0,
                            "retweet_count": 0,
                            "reply_count": 0,
                            "quote_count": 0,
                            "lang": "en",
                        },
                        "core": {
                            "user_results": {
                                "result": {
                                    "rest_id": str(tweet_id + 1000),
                                    "legacy": {"screen_name": handle, "name": handle},
                                }
                            }
                        },
                    }
                }
            },
        },
    }


def test_home_timeline():
    with open(FIXTURES / "home_timeline.json") as f:
        data = json.load(f)

    stats = ParseStats()
    tweets, cursor = parse_timeline_response(data, stats)

    assert len(tweets) == 2, f"Expected 2 tweets, got {len(tweets)}"
    assert cursor == "cursor-bottom-1", f"Expected cursor, got {cursor}"

    t1 = tweets[0]
    assert t1.id == 1
    assert t1.author_handle == "alice"
    assert t1.tweet_type == "tweet"
    # note_tweet text preferred over legacy.full_text
    assert "full text of a long tweet" in t1.text_raw
    assert len(t1.media) == 1
    assert t1.media[0].type == "photo"
    assert t1.views == 1234
    assert t1.urls == ["https://example.com/post"]

    t2 = tweets[1]
    assert t2.id == 20  # Retweet resolves to original tweet's rest_id
    assert t2.is_retweet is True
    assert t2.tweet_type == "retweet"
    # Retweet resolves to the original author
    assert t2.author_handle == "carol"
    assert t2.text_raw == "original retweeted post"
    assert t2.is_quote is True  # Has a nested quote

    assert stats.raw == 2
    assert stats.parsed == 2
    assert stats.drop_rate == 0.0


def test_search_timeline():
    with open(FIXTURES / "search_timeline.json") as f:
        data = json.load(f)

    stats = ParseStats()
    tweets, cursor = parse_timeline_response(data, stats)

    assert len(tweets) == 1
    assert cursor == "search-cursor"
    t = tweets[0]
    assert t.id == 500
    assert t.author_handle == "searcher"
    assert len(t.media) == 1
    assert t.media[0].type == "video"
    # Highest bitrate MP4 variant is selected
    assert "video-high" in t.media[0].url


def test_empty_response():
    stats = ParseStats()
    tweets, cursor = parse_timeline_response({}, stats)
    assert tweets == []
    assert cursor is None


def test_advertiser_source_entries_are_preserved_to_match_twitter_cli():
    data = {
        "data": {
            "home": {
                "home_timeline_urt": {
                    "instructions": [
                        {
                            "entries": [
                                _minimal_tweet_entry(
                                    100,
                                    "normal_author",
                                    "fresh timeline tweet",
                                ),
                                _minimal_tweet_entry(
                                    200,
                                    "ad_author",
                                    "old injected ad",
                                    '<a href="https://twitter.com" rel="nofollow">Twitter for Advertisers</a>',
                                ),
                            ]
                        }
                    ]
                }
            }
        }
    }

    stats = ParseStats()
    tweets, cursor = parse_timeline_response(data, stats)

    assert [t.id for t in tweets] == [100, 200]
    assert cursor is None
    assert stats.raw == 2
    assert stats.parsed == 2


def test_snowflake_ids_are_parsed_without_precision_loss():
    tweet_id = 2052550869581766809
    data = {
        "data": {
            "home": {
                "home_timeline_urt": {
                    "instructions": [
                        {
                            "entries": [
                                _minimal_tweet_entry(
                                    tweet_id,
                                    "snowflake_author",
                                    "large id tweet",
                                ),
                            ]
                        }
                    ]
                }
            }
        }
    }

    stats = ParseStats()
    tweets, _ = parse_timeline_response(data, stats)

    assert len(tweets) == 1
    assert tweets[0].id == tweet_id
    assert tweets[0].author_id == tweet_id + 1000


def test_article_parsing():
    data = {
        "article": {
            "article_results": {
                "result": {
                    "title": "My Article",
                    "content_state": {
                        "blocks": [
                            {"type": "header-one", "text": "Introduction"},
                            {"type": "unstyled", "text": "A paragraph."},
                            {"type": "blockquote", "text": "A wise quote"},
                            {"type": "unordered-list-item", "text": "Item 1"},
                            {"type": "unordered-list-item", "text": "Item 2"},
                            {"type": "ordered-list-item", "text": "First"},
                            {"type": "ordered-list-item", "text": "Second"},
                            {"type": "code-block", "text": "print(1)"},
                            {"type": "atomic", "text": "should be skipped"},
                        ]
                    },
                }
            }
        }
    }
    result = parse_article_content(data)
    assert result["title"] == "My Article"
    text = result["text"]
    assert "# Introduction" in text
    assert "A paragraph." in text
    assert "> A wise quote" in text
    assert "- Item 1" in text
    assert "- Item 2" in text
    assert "1. First" in text
    assert "2. Second" in text
    assert "print(1)" in text
    assert "should be skipped" not in text


def test_no_article():
    result = parse_article_content({"legacy": {}})
    assert result["title"] == ""
    assert result["text"] == ""


def test_malformed_entry_never_crashes():
    stats = ParseStats()
    # These should all return None without raising
    from siphon.parse.timeline_parser import parse_tweet_entry

    assert parse_tweet_entry({}, stats) is None
    assert parse_tweet_entry({"content": "not a dict"}, stats) is None
    assert parse_tweet_entry({"content": {"itemContent": "bad"}}, stats) is None
    assert stats.raw == 3
    assert stats.parsed == 0


if __name__ == "__main__":
    test_home_timeline()
    print("PASS: home_timeline")
    test_search_timeline()
    print("PASS: search_timeline")
    test_empty_response()
    print("PASS: empty_response")
    test_article_parsing()
    print("PASS: article_parsing")
    test_no_article()
    print("PASS: no_article")
    test_malformed_entry_never_crashes()
    print("PASS: malformed_entry_never_crashes")
    print("\nAll smoke tests passed!")

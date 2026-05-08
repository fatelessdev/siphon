from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TweetMedia(BaseModel):
    type: str  # photo, video, animated_gif
    url: str
    width: int | None = None
    height: int | None = None


class Tweet(BaseModel):
    id: int
    author_id: int
    author_handle: str
    author_name: str = ""
    created_at: datetime
    lang: str | None = None
    text_raw: str
    text_normalized: str
    tweet_type: str = "tweet"  # tweet, retweet, reply, quote
    is_retweet: bool = False
    is_reply: bool = False
    is_quote: bool = False
    parent_tweet_id: int | None = None
    conversation_id: int | None = None
    likes: int = 0
    retweets: int = 0
    replies: int = 0
    quotes: int = 0
    views: int = 0
    bookmarks: int = 0
    urls: list[str] = Field(default_factory=list)
    media: list[TweetMedia] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    cashtags: list[str] = Field(default_factory=list)
    source_operation: str = ""
    pinned: bool = False
    raw_json: dict = Field(default_factory=dict)


class UserProfile(BaseModel):
    id: int
    screen_name: str
    name: str = ""
    bio: str = ""
    followers_count: int = 0
    following_count: int = 0
    tweets_count: int = 0
    verified: bool = False
    profile_image_url: str = ""

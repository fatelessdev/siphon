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
    text: str
    reply_to_tweet_id: int | None = None
    reply_to_author_handle: str | None = None
    reply_to_text: str | None = None
    quoted_tweet_id: int | None = None
    quoted_author_handle: str | None = None
    quoted_text: str | None = None
    urls: list[str] = Field(default_factory=list)
    media: list[TweetMedia] = Field(default_factory=list)
    source_operation: str = ""


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

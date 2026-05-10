"""Константы проекта."""

from __future__ import annotations

DEFAULT_API_BASE_URL = "https://api.duckmyduck.com"

MOBILE_FINGERPRINT_HEADERS = {
    "sec-ch-ua-platform": '"Android"',
    "sec-ch-ua-mobile": "?1",
    "user-agent": (
        "Mozilla/5.0 (Linux; Android 12; Pixel 6 Build/SQ3A.220705.004; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        "Chrome/143.0.0.0 Mobile Safari/537.36"
    ),
}

DEFAULT_HTTP_HEADERS = {
    "accept": "application/json",
    "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "content-type": "application/json",
    "origin": "https://webapp.duckmyduck.com",
    "referer": "https://webapp.duckmyduck.com/",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "sec-fetch-storage-access": "active",
    "x-app-version": "1.57.231",
    "x-platform": "WEB",
}

IMMUTABLE_FINGERPRINT_HEADER_KEYS = frozenset(MOBILE_FINGERPRINT_HEADERS)

DEFAULT_FEED_LIMITS = {
    "COMMON": 30,
    "UNCOMMON": 80,
    "RARE": 120,
    "EPIC": 200,
    "LEGENDARY": 1000,
}

DEFAULT_EGG_MERGE_LIMITS = {
    "DUCK": 12,
    "HEART": 12,
    "REGULAR_TOURNAMENT_EGG": 5,
    "REGULAR_TOURNAMENT_POINTS_EGG": 5,
    "REGULAR_TOUR_REPEATABLE_EGG": 5,
}

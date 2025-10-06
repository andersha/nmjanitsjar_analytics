"""Utilities for discovering streaming links for NM Janitsjar performances.

This module provides helper classes that talk to Spotify and Apple Music
and attempts to map competition pieces to their corresponding album tracks.

Usage example:

```
poetry run python -m src.nmjanitsjar_scraper.streaming_search \
    --positions apps/band-positions/public/data/band_positions.json \
    --output data/processed/piece_streaming_links.json
```

Spotify credentials are read from the ``SPOTIFY_CLIENT_ID`` and
``SPOTIFY_CLIENT_SECRET`` environment variables unless explicitly
provided via command-line options.
"""

from __future__ import annotations

import base64
import json
import os
import time
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests
from requests import Response, Session
try:
    from tenacity import retry, stop_after_attempt, wait_fixed  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback when tenacity is unavailable
    def retry(*_args, **_kwargs):  # type: ignore
        def decorator(func):
            return func

        return decorator

    def stop_after_attempt(_attempts):  # type: ignore
        return None

    def wait_fixed(_seconds):  # type: ignore
        return None


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def _strip_parenthetical(value: str) -> str:
    result = []
    depth = 0
    for char in value:
        if char == "(":
            depth += 1
        elif char == ")":
            if depth > 0:
                depth -= 1
            continue
        elif depth > 0:
            continue
        result.append(char)
    return "".join(result)


def normalize_title(value: str, *, remove_parentheticals: bool = True) -> str:
    """Normalize a piece or track title for fuzzy comparison."""

    if not value:
        return ""

    cleaned = (
        value.replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )
    if remove_parentheticals:
        cleaned = _strip_parenthetical(cleaned)
    cleaned = unicodedata.normalize("NFKD", cleaned)
    cleaned = "".join(ch for ch in cleaned if not unicodedata.combining(ch))
    cleaned = cleaned.lower()
    tokens = []
    current = []
    for ch in cleaned:
        if ch.isalnum():
            current.append(ch)
        else:
            if current:
                tokens.append("".join(current))
                current = []
    if current:
        tokens.append("".join(current))
    return "-".join(tokens)


def get_title_variants(value: str) -> List[str]:
    """Get title variants including main title and subtitle parts.
    
    For example, 'Myth Forest - Hestefallstjønn' would return:
    - 'myth-forest-hestefallstjonn' (full)
    - 'myth-forest' (before dash)
    """
    if not value:
        return []
    
    variants = [normalize_title(value)]
    
    # Split on common subtitle separators and add the main part
    for separator in [' - ', ' – ', ' — ']:
        if separator in value:
            main_part = value.split(separator)[0].strip()
            if main_part:
                normalized_main = normalize_title(main_part)
                if normalized_main and normalized_main not in variants:
                    variants.append(normalized_main)
            break
    
    return variants


def similarity_score(piece_slug: str, track_slug: str) -> float:
    if not piece_slug or not track_slug:
        return 0.0
    if piece_slug == track_slug:
        return 1.0
    matcher = SequenceMatcher(None, piece_slug, track_slug)
    ratio = matcher.ratio()
    tokens_piece = set(piece_slug.split("-"))
    tokens_track = set(track_slug.split("-"))
    if not tokens_piece or not tokens_track:
        token_overlap = 0.0
    else:
        token_overlap = len(tokens_piece & tokens_track) / max(len(tokens_piece), len(tokens_track))
    if piece_slug in track_slug or track_slug in piece_slug:
        ratio = max(ratio, 0.9)
    return max(ratio, token_overlap)


def get_division_tokens(division: str) -> set[str]:
    """Get normalized division tokens for album matching."""
    # Normalize the input division
    normalized = division.lower().strip()
    
    # Build token set
    tokens = set()
    
    if "elite" in normalized:
        tokens.update(["elite", "elitedivisjon", "elite-divisjon", "elite divisjon"])
    
    # Extract division number if present
    for num in ["1", "2", "3", "4", "5", "6", "7"]:
        if num in normalized:
            tokens.update([
                f"{num}. div",
                f"{num} div",
                f"{num}. divisjon",
                f"{num}-divisjon",
                f"{num}.div",
                f"{num}div",
            ])
            break
    
    return tokens


def score_album_relevance(album: Dict, year: int, division: str) -> float:
    """Score an album's relevance for a given year and division.
    
    Higher scores indicate more relevant albums that should be prioritized.
    """
    score = 0.0
    album_name = (album.get("name") or album.get("collectionName") or "").lower()
    release_date = album.get("release_date") or album.get("releaseDate") or ""
    
    # Extract release year
    release_year = None
    if isinstance(release_date, str) and len(release_date) >= 4:
        try:
            release_year = int(release_date[:4])
        except ValueError:
            pass
    
    # Year matching (HIGHEST priority - dramatically increased)
    if release_year == year:
        score += 200  # Increased from 50
    if str(year) in album_name:
        score += 100  # Increased from 30
    
    # Division matching (VERY high priority - dramatically increased)
    division_tokens = get_division_tokens(division)
    for token in division_tokens:
        if token in album_name:
            score += 150  # Increased from 40
            break
    
    # Contest tokens
    contest_tokens = ["nm brass", "nm janitsjar", "norgesmesterskap"]
    for token in contest_tokens:
        if token in album_name:
            score += 20
            break
    
    # Live recording
    if "live" in album_name or "(live)" in album_name:
        score += 5
    
    # Album type preference (Spotify specific)
    album_type = album.get("album_type") or album.get("type") or ""
    if album_type == "album":
        score += 2
    elif album_type == "single":
        score -= 10
    
    return score


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


def _sanitize_token(value: str) -> str:
    return (
        value.lower()
        .replace(" ", "")
        .replace(".", "")
        .replace("-", "")
        .replace("–", "")
        .replace("—", "")
    )


def infer_band_type_from_name(name: str) -> Optional[str]:
    sanitised = _sanitize_token(name)
    if "nmbrass" in sanitised:
        return "brass"
    if "nmjanitsjar" in sanitised:
        return "wind"
    return None


def infer_division_hints_from_name(name: str) -> List[str]:
    sanitised = _sanitize_token(name)
    hints: List[str] = []
    for canonical, variants in DIVISION_SYNONYMS.items():
        for variant in variants:
            if _sanitize_token(variant) in sanitised:
                hints.append(canonical)
                break
    return hints


def is_winners_album_name(name: str) -> bool:
    lower = name.lower()
    for token in ("winner", "winners", "vinner", "vinnere", "vinnarar"):
        if token in lower:
            return True
    return False


def performance_key(performance: Performance) -> Tuple[int, str, str, str]:
    return (
        performance.year,
        performance.division,
        performance.band,
        performance.piece,
    )


@dataclass
class AlbumMetadata:
    platform: str
    album_id: str
    name: str
    release_date: Optional[str] = None
    release_year: Optional[int] = None
    album_type: Optional[str] = None
    band_type: Optional[str] = None
    division_hints: List[str] = field(default_factory=list)
    is_winners_album: bool = False
    fetched_at: Optional[float] = None
    extra: Dict[str, object] = field(default_factory=dict)

    def to_cache_dict(self) -> Dict[str, object]:
        return {
            "album_id": self.album_id,
            "name": self.name,
            "release_date": self.release_date,
            "release_year": self.release_year,
            "album_type": self.album_type,
            "band_type": self.band_type,
            "division_hints": list(self.division_hints),
            "is_winners_album": self.is_winners_album,
            "fetched_at": self.fetched_at,
            "extra": self.extra,
        }

    def to_score_dict(self) -> Dict[str, object]:
        data: Dict[str, object] = {
            "name": self.name,
        }
        if self.release_date:
            data["release_date"] = self.release_date
            data["releaseDate"] = self.release_date
        if self.album_type:
            data["album_type"] = self.album_type
            data.setdefault("type", self.album_type)
        data.update(self.extra)
        return data

    @classmethod
    def from_cache(cls, platform: str, album_id: str, payload: Dict[str, object]) -> "AlbumMetadata":
        name = str(payload.get("name") or "")
        release_date = payload.get("release_date")
        release_year = payload.get("release_year")
        album_type = payload.get("album_type")
        band_type = payload.get("band_type")
        division_hints_raw = payload.get("division_hints") or []
        if isinstance(division_hints_raw, list):
            division_hints = [str(item) for item in division_hints_raw if item]
        else:
            division_hints = []
        extra_raw = payload.get("extra")
        extra = dict(extra_raw) if isinstance(extra_raw, dict) else {}
        fetched_at_value = payload.get("fetched_at")
        fetched_at = float(fetched_at_value) if isinstance(fetched_at_value, (int, float)) else None
        release_year_value = None
        if isinstance(release_year, int):
            release_year_value = release_year
        elif isinstance(release_year, str) and release_year.isdigit():
            release_year_value = int(release_year)
        return cls(
            platform=platform,
            album_id=album_id,
            name=name,
            release_date=str(release_date) if release_date else None,
            release_year=release_year_value,
            album_type=str(album_type) if album_type else None,
            band_type=str(band_type) if band_type else None,
            division_hints=division_hints,
            is_winners_album=bool(payload.get("is_winners_album")),
            fetched_at=fetched_at,
            extra=extra,
        )


@dataclass(frozen=True)
class Performance:
    year: int
    division: str
    band: str
    piece: str
    rank: Optional[int] = None
    is_test_piece: bool = False


@dataclass
class Track:
    platform: str
    title: str
    slug: str
    slug_variants: List[str]
    url: str
    album: str
    album_id: str
    artist: str = ""  # Artist/band name from the streaming service
    match_score: float = 0.0


@dataclass
class StreamingMatch:
    performance: Performance
    spotify: Optional[Track] = None
    apple_music: Optional[Track] = None

    def to_dict(self) -> Dict[str, Optional[str]]:
        track = self.spotify or self.apple_music
        return {
            "year": self.performance.year,
            "division": self.performance.division,
            "band": self.performance.band,
            "result_piece": self.performance.piece,
            "recording_title": track.title if track else None,
            "album": track.album if track else None,
            "spotify": self.spotify.url if self.spotify else None,
            "apple_music": self.apple_music.url if self.apple_music else None,
        }


# ---------------------------------------------------------------------------
# Spotify client
# ---------------------------------------------------------------------------


class StreamingCache:
    def __init__(self, path: Optional[Path]):
        self.path = path.expanduser() if path else None
        self._data: Dict[str, Dict[str, object]] = {
            "spotify": {},
            "apple": {},
        }
        self._dirty = False
        if self.path and self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    for key in ("spotify", "apple"):
                        if key in loaded and isinstance(loaded[key], dict):
                            self._data[key].update(loaded[key])
            except json.JSONDecodeError:
                pass

        # Ensure expected platform sections exist (backwards compatible with older cache formats)
        for platform in ("spotify", "apple"):
            platform_section = self._data.setdefault(platform, {})
            platform_section.setdefault("album_tracks", {})
            platform_section.setdefault("album_searches", {})
            platform_section.setdefault("albums", {})

    def _platform_section(self, platform: str) -> Dict[str, object]:
        if platform not in self._data:
            self._data[platform] = {
                "album_tracks": {},
                "album_searches": {},
                "albums": {},
            }
        else:
            section = self._data[platform]
            section.setdefault("album_tracks", {})
            section.setdefault("album_searches", {})
            section.setdefault("albums", {})
        return self._data[platform]

    def get_spotify_album_tracks(self, album_id: str) -> Optional[List[Dict]]:
        return self._platform_section("spotify").get("album_tracks", {}).get(album_id, {}).get("tracks")

    def set_spotify_album_tracks(self, album_id: str, tracks: List[Dict]) -> None:
        self._platform_section("spotify").setdefault("album_tracks", {})[album_id] = {
            "tracks": tracks,
            "fetched_at": time.time(),
        }
        self._dirty = True

    def get_spotify_album_search(self, year: int, division: str) -> Optional[List[Dict]]:
        """Get cached Spotify album search results for a year/division."""
        spotify = self._platform_section("spotify")
        searches = spotify.get("album_searches", {})
        key = f"{year}|{division}"
        entry = searches.get(key)
        if not entry:
            return None
        albums = entry.get("albums") or []
        return albums if albums else None

    def set_spotify_album_search(self, year: int, division: str, albums: List[Dict]) -> None:
        """Cache Spotify album search results for a year/division."""
        if not albums:
            return
        spotify = self._platform_section("spotify")
        searches = spotify.setdefault("album_searches", {})
        key = f"{year}|{division}"
        searches[key] = {
            "albums": albums,
            "fetched_at": time.time(),
        }
        self._dirty = True

    def get_apple_album_tracks(self, collection_id: str) -> Optional[List[Dict]]:
        return self._platform_section("apple").get("album_tracks", {}).get(collection_id, {}).get("tracks")

    def set_apple_album_tracks(self, collection_id: str, tracks: List[Dict]) -> None:
        self._platform_section("apple").setdefault("album_tracks", {})[collection_id] = {
            "tracks": tracks,
            "fetched_at": time.time(),
        }
        self._dirty = True

    def get_apple_album_search(self, year: int, division: str) -> Optional[List[Dict]]:
        """Get cached Apple Music album search results for a year/division."""
        apple = self._platform_section("apple")
        searches = apple.get("album_searches", {})
        key = f"{year}|{division}"
        entry = searches.get(key)
        if not entry:
            return None
        albums = entry.get("albums") or []
        return albums if albums else None

    def set_apple_album_search(self, year: int, division: str, albums: List[Dict]) -> None:
        """Cache Apple Music album search results for a year/division."""
        if not albums:
            return
        apple = self._platform_section("apple")
        searches = apple.setdefault("album_searches", {})
        key = f"{year}|{division}"
        searches[key] = {
            "albums": albums,
            "fetched_at": time.time(),
        }
        self._dirty = True

    def get_platform_albums(self, platform: str) -> Dict[str, Dict[str, object]]:
        """Return stored album metadata for the given platform."""
        section = self._platform_section(platform)
        albums = section.get("albums", {})
        if isinstance(albums, dict):
            return albums  # type: ignore[return-value]
        return {}

    def upsert_platform_album(self, platform: str, album_id: str, metadata: Dict[str, object]) -> None:
        """Insert or update cached album metadata for a platform."""
        section = self._platform_section(platform)
        albums = section.setdefault("albums", {})
        if not isinstance(albums, dict):  # defensive for legacy formats
            section["albums"] = {}
            albums = section["albums"]
        albums[album_id] = metadata
        self._dirty = True

    def set_platform_albums(self, platform: str, albums: Dict[str, Dict[str, object]]) -> None:
        section = self._platform_section(platform)
        section["albums"] = dict(albums)
        self._dirty = True

    def save(self) -> None:
        if not self._dirty or not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
        self._dirty = False


class SpotifyClient:
    TOKEN_URL = "https://accounts.spotify.com/api/token"
    API_URL = "https://api.spotify.com/v1"

    def __init__(self, client_id: str, client_secret: str, *, session: Optional[Session] = None, market: str = "NO", cache: Optional[StreamingCache] = None):
        if not client_id or not client_secret:
            raise ValueError("Spotify client id and secret must be provided")
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = session or requests.Session()
        self.market = market
        self._access_token: Optional[str] = None
        self._token_expiry: float = 0.0
        self.cache = cache

    def _auth_header(self) -> Dict[str, str]:
        self._ensure_token()
        return {"Authorization": f"Bearer {self._access_token}"}

    def _ensure_token(self) -> None:
        now = time.time()
        if self._access_token and now < self._token_expiry - 60:
            return

        auth = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode("utf-8")).decode("ascii")
        response = self.session.post(
            self.TOKEN_URL,
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {auth}"},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        self._access_token = payload["access_token"]
        expires_in = int(payload.get("expires_in", 3600))
        self._token_expiry = now + expires_in

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
    def _get(self, path: str, *, params: Optional[Dict[str, str]] = None) -> Response:
        url = f"{self.API_URL}{path}"
        headers = self._auth_header()
        response = self.session.get(url, headers=headers, params=params, timeout=15)
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            delay = float(retry_after) if retry_after is not None else 2.0
            print(f"[spotify] 429 rate limit on {path} – waiting {delay:.1f}s before retry")
            time.sleep(max(delay, 1.0))
            response = self.session.get(url, headers=headers, params=params, timeout=15)
        if response.status_code >= 500:
            response.raise_for_status()
        if response.status_code == 401:
            self._access_token = None
            self._token_expiry = 0.0
            headers = self._auth_header()
            response = self.session.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        return response

    def search_albums(self, query: str, *, limit: int = 5) -> List[Dict]:
        params = {
            "q": query,
            "type": "album",
            "limit": limit,
        }
        if self.market:
            params["market"] = self.market
        data = self._get("/search", params=params).json()
        return data.get("albums", {}).get("items", [])

    def search_all_albums(self, query: str, *, limit: int = 50, max_pages: int = 5) -> List[Dict]:
        params = {
            "q": query,
            "type": "album",
            "limit": limit,
        }
        if self.market:
            params["market"] = self.market

        results: List[Dict] = []
        seen_ids: set[str] = set()
        offset = 0

        for _ in range(max_pages):
            params["offset"] = offset
            data = self._get("/search", params=params).json()
            items = data.get("albums", {}).get("items", []) or []
            if not items:
                break
            for item in items:
                album_id = item.get("id")
                if not album_id or album_id in seen_ids:
                    continue
                seen_ids.add(album_id)
                results.append(item)
            if len(items) < limit:
                break
            offset += limit

        return results

    def get_album_tracks(self, album_id: str) -> List[Dict]:
        items: List[Dict] = []
        params = {"limit": 50}
        while True:
            data = self._get(f"/albums/{album_id}/tracks", params=params).json()
            items.extend(data.get("items", []))
            next_url = data.get("next")
            if not next_url:
                break
            params = {"offset": len(items), "limit": 50}
        return items


# ---------------------------------------------------------------------------
# Apple Music (iTunes) client
# ---------------------------------------------------------------------------


class AppleMusicClient:
    SEARCH_URL = "https://itunes.apple.com/search"
    LOOKUP_URL = "https://itunes.apple.com/lookup"

    def __init__(self, *, country: str = "us", session: Optional[Session] = None, cache: Optional[StreamingCache] = None, user_agent: Optional[str] = None):
        self.country = country
        self.session = session or requests.Session()
        if user_agent:
            self.session.headers.update({"User-Agent": user_agent})
        elif "User-Agent" not in self.session.headers:
            # Set a default user agent to avoid 403 Forbidden errors from some servers
            self.session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36"})
        self.cache = cache

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
    def search_album(self, term: str, limit: int = 5) -> List[Dict]:
        params = {
            "term": term,
            "entity": "album",
            "limit": limit,
            "country": self.country,
        }
        response = self.session.get(self.SEARCH_URL, params=params, timeout=15)
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            delay = float(retry_after) if retry_after is not None else 2.0
            print(f"[apple] 429 rate limit on search('{term}') – waiting {delay:.1f}s before retry")
            time.sleep(max(delay, 1.0))
            response = self.session.get(self.SEARCH_URL, params=params, timeout=15)
        if response.status_code == 404:
            return []
        if response.status_code == 403:
            print(f"[apple] 403 forbidden on search('{term}') – rate limited, skipping Apple Music")
            return []
        response.raise_for_status()
        data = response.json()
        return data.get("results", [])

    def search_all_albums(self, term: str, *, limit: int = 200, max_pages: int = 5) -> List[Dict]:
        results: List[Dict] = []
        seen_ids: set[int] = set()
        offset = 0

        for _ in range(max_pages):
            params = {
                "term": term,
                "entity": "album",
                "limit": limit,
                "country": self.country,
                "offset": offset,
            }
            response = self.session.get(self.SEARCH_URL, params=params, timeout=15)
            if response.status_code in (403, 404):
                break
            response.raise_for_status()
            data = response.json()
            items = data.get("results", []) or []
            if not items:
                break
            for item in items:
                collection_id = item.get("collectionId")
                if not isinstance(collection_id, int) or collection_id in seen_ids:
                    continue
                seen_ids.add(collection_id)
                results.append(item)
            if len(items) < limit:
                break
            offset += limit

        return results

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
    def lookup_album_tracks(self, collection_id: int) -> List[Dict]:
        params = {"id": collection_id, "entity": "song", "country": self.country}
        response = self.session.get(self.LOOKUP_URL, params=params, timeout=15)
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            delay = float(retry_after) if retry_after is not None else 2.0
            print(f"[apple] 429 rate limit on lookup('{collection_id}') – waiting {delay:.1f}s before retry")
            time.sleep(max(delay, 1.0))
            response = self.session.get(self.LOOKUP_URL, params=params, timeout=15)
        if response.status_code == 404:
            return []
        if response.status_code == 403:
            print(f"[apple] 403 forbidden on lookup('{collection_id}') – rate limited, skipping")
            return []
        response.raise_for_status()
        data = response.json()
        return [item for item in data.get("results", []) if item.get("wrapperType") == "track"]


# ---------------------------------------------------------------------------
# Album catalogue
# ---------------------------------------------------------------------------


class AlbumCatalog:
    def __init__(
        self,
        *,
        spotify: Optional[SpotifyClient],
        apple_music: Optional[AppleMusicClient],
        cache: Optional[StreamingCache],
        band_type: str,
    ) -> None:
        self.spotify = spotify
        self.apple_music = apple_music
        self.cache = cache
        self.band_type = band_type
        self._albums: Dict[str, Dict[str, AlbumMetadata]] = {"spotify": {}, "apple": {}}
        self._platform_loaded: set[str] = set()
        self._load_from_cache()

    # -------------------------- cache coordination -------------------------

    def _load_from_cache(self) -> None:
        if not self.cache:
            return
        for platform in ("spotify", "apple"):
            cached = self.cache.get_platform_albums(platform)
            for album_id, payload in cached.items():
                if not isinstance(payload, dict):
                    continue
                try:
                    metadata = AlbumMetadata.from_cache(platform, album_id, payload)
                except Exception:
                    continue
                self._register_album(metadata, persist=False)

    def _register_album(self, metadata: AlbumMetadata, *, persist: bool = True) -> None:
        platform_albums = self._albums.setdefault(metadata.platform, {})
        existing = platform_albums.get(metadata.album_id)
        if existing:
            # Merge metadata, preferring existing non-empty values but extending hints.
            if not existing.band_type and metadata.band_type:
                existing.band_type = metadata.band_type
            if metadata.release_date and not existing.release_date:
                existing.release_date = metadata.release_date
            if metadata.release_year and not existing.release_year:
                existing.release_year = metadata.release_year
            if metadata.album_type and not existing.album_type:
                existing.album_type = metadata.album_type
            if metadata.fetched_at:
                existing.fetched_at = metadata.fetched_at
            if metadata.extra:
                merged_extra = dict(existing.extra)
                merged_extra.update(metadata.extra)
                existing.extra = merged_extra
            # Combine division hints without duplicates
            if metadata.division_hints:
                combined = {hint for hint in existing.division_hints}
                combined.update(metadata.division_hints)
                existing.division_hints = sorted(combined)
            existing.is_winners_album = existing.is_winners_album or metadata.is_winners_album
            if persist and self.cache:
                self.cache.upsert_platform_album(metadata.platform, metadata.album_id, existing.to_cache_dict())
            return

        platform_albums[metadata.album_id] = metadata
        if persist and self.cache:
            self.cache.upsert_platform_album(metadata.platform, metadata.album_id, metadata.to_cache_dict())

    # --------------------------- API collection ---------------------------

    def _ensure_platform_loaded(self, platform: str) -> None:
        if platform in self._platform_loaded:
            return
        if platform == "spotify":
            self._fetch_spotify_albums()
        elif platform == "apple":
            self._fetch_apple_albums()
        self._platform_loaded.add(platform)

    def _fetch_spotify_albums(self) -> None:
        if not self.spotify:
            return
        queries = ["NM Brass"] if self.band_type == "brass" else ["NM Janitsjar"]
        # Query both with and without quotes to catch typographical variants
        base_term = queries[0]
        queries.append(f'"{base_term}"')

        for query in queries:
            try:
                items = self.spotify.search_all_albums(query, limit=50, max_pages=6)
            except Exception as exc:
                print(f"[spotify] Failed to search albums with '{query}': {exc}")
                continue

            for album in items:
                album_id = album.get("id")
                name = album.get("name") or ""
                if not album_id or not name:
                    continue
                band_type = infer_band_type_from_name(name)
                if band_type != self.band_type:
                    continue
                release_date = album.get("release_date") or album.get("releaseDate")
                release_year = None
                if isinstance(release_date, str) and len(release_date) >= 4:
                    try:
                        release_year = int(release_date[:4])
                    except ValueError:
                        release_year = None
                division_hints = infer_division_hints_from_name(name)
                metadata = AlbumMetadata(
                    platform="spotify",
                    album_id=album_id,
                    name=name,
                    release_date=release_date,
                    release_year=release_year,
                    album_type=album.get("album_type") or album.get("type"),
                    band_type=band_type,
                    division_hints=division_hints,
                    is_winners_album=is_winners_album_name(name),
                    fetched_at=time.time(),
                    extra={"type": album.get("type") or "album"},
                )
                self._register_album(metadata)

    def _fetch_apple_albums(self) -> None:
        if not self.apple_music:
            return
        queries = ["NM Brass"] if self.band_type == "brass" else ["NM Janitsjar"]
        queries.append(f'"{queries[0]}"')

        for query in queries:
            try:
                items = self.apple_music.search_all_albums(query, limit=200, max_pages=5)
            except Exception as exc:
                print(f"[apple] Failed to search albums with '{query}': {exc}")
                continue

            for album in items:
                collection_id = album.get("collectionId")
                collection_name = album.get("collectionName") or ""
                if not collection_id or not collection_name:
                    continue
                band_type = infer_band_type_from_name(collection_name)
                if band_type != self.band_type:
                    continue
                release_date = album.get("releaseDate")
                release_year = None
                if isinstance(release_date, str) and len(release_date) >= 4:
                    try:
                        release_year = int(release_date[:4])
                    except ValueError:
                        release_year = None
                metadata = AlbumMetadata(
                    platform="apple",
                    album_id=str(collection_id),
                    name=collection_name,
                    release_date=release_date,
                    release_year=release_year,
                    album_type=album.get("collectionType"),
                    band_type=band_type,
                    division_hints=infer_division_hints_from_name(collection_name),
                    is_winners_album=is_winners_album_name(collection_name),
                    fetched_at=time.time(),
                    extra={
                        "collectionName": collection_name,
                        "releaseDate": release_date,
                        "collectionType": album.get("collectionType"),
                    },
                )
                self._register_album(metadata)

    # ----------------------------- public API -----------------------------

    def get_album_candidates(self, platform: str, year: int, division: str) -> List[Tuple[float, AlbumMetadata]]:
        self._ensure_platform_loaded(platform)
        candidates: List[Tuple[float, AlbumMetadata]] = []
        for metadata in self._albums.get(platform, {}).values():
            if platform == "apple" and metadata.release_year and metadata.release_year < 2017:
                continue
            if metadata.band_type and metadata.band_type != self.band_type:
                continue
            if not self._album_matches_year(metadata, year):
                continue
            score = score_album_relevance(metadata.to_score_dict(), year, division)
            if division and metadata.division_hints and division in metadata.division_hints:
                score += 150
            if metadata.is_winners_album:
                # Give winners albums a small base score boost so they remain as fallback
                score += 25
            candidates.append((score, metadata))

        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates

    def get_winners_albums(self, platform: str, year: int) -> List[AlbumMetadata]:
        self._ensure_platform_loaded(platform)
        winners: List[Tuple[float, AlbumMetadata]] = []
        for metadata in self._albums.get(platform, {}).values():
            if not metadata.is_winners_album:
                continue
            if platform == "apple" and metadata.release_year and metadata.release_year < 2017:
                continue
            if metadata.band_type and metadata.band_type != self.band_type:
                continue
            if not self._album_matches_year(metadata, year):
                continue
            score = score_album_relevance(metadata.to_score_dict(), year, "") + 25
            winners.append((score, metadata))
        winners.sort(key=lambda item: item[0], reverse=True)
        return [meta for _, meta in winners]

    def _album_matches_year(self, metadata: AlbumMetadata, year: int) -> bool:
        if metadata.release_year == year:
            return True
        year_str = str(year)
        potential_fields = [metadata.name]
        if metadata.release_date and year_str in metadata.release_date:
            return True
        for field_name in ("collectionName", "name"):
            value = metadata.extra.get(field_name)
            if isinstance(value, str):
                potential_fields.append(value)
        for value in potential_fields:
            if isinstance(value, str) and year_str in value:
                return True
        return False

# ---------------------------------------------------------------------------
# Streaming discovery logic
# ---------------------------------------------------------------------------


DIVISION_CODE_MAP = {
    "E": "Elite",
    "1": "1. divisjon",
    "2": "2. divisjon",
    "3": "3. divisjon",
    "4": "4. divisjon",
    "5": "5. divisjon",
    "6": "6. divisjon",
    "7": "7. divisjon",
}

DIVISION_ALBUM_LABELS = {
    "Elite": "Elitedivisjon",
    "Elitedivisjon": "Elitedivisjon",
    "1. divisjon": "1. divisjon",
    "2. divisjon": "2. divisjon",
    "3. divisjon": "3. divisjon",
    "4. divisjon": "4. divisjon",
    "5. divisjon": "5. divisjon",
    "6. divisjon": "6. divisjon",
    "7. divisjon": "7. divisjon",
}

DIVISION_SYNONYMS = {
    "Elitedivisjon": ["Elitedivisjon", "Elite"],
    "1. divisjon": ["1. divisjon", "1. div", "1.div", "1 div"],
    "2. divisjon": ["2. divisjon", "2. div", "2.div", "2 div"],
    "3. divisjon": ["3. divisjon", "3. div", "3.div", "3 div"],
    "4. divisjon": ["4. divisjon", "4. div", "4.div", "4 div"],
    "5. divisjon": ["5. divisjon", "5. div", "5.div", "5 div"],
    "6. divisjon": ["6. divisjon", "6. div", "6.div", "6 div"],
    "7. divisjon": ["7. divisjon", "7. div", "7.div", "7 div"],
}


def load_performances(path: Path, *, min_year: int = 2017, elite_test_pieces_path: Optional[Path] = None, band_type: str = "wind") -> List[Performance]:
    """Load performances from band positions dataset.
    
    For brass bands with Elite division, also includes test pieces from elite_test_pieces.json
    if the path is provided.
    """
    dataset = json.loads(path.read_text(encoding="utf-8"))
    performances: List[Performance] = []
    
    # Load elite test pieces if available (for brass bands only)
    elite_test_pieces = {}
    if band_type == "brass" and elite_test_pieces_path and elite_test_pieces_path.exists():
        try:
            test_pieces_data = json.loads(elite_test_pieces_path.read_text(encoding="utf-8"))
            elite_test_pieces = test_pieces_data.get("test_pieces", {})
        except (json.JSONDecodeError, IOError):
            pass  # Silently ignore if file doesn't exist or is invalid
    
    for band in dataset.get("bands", []):
        name = band.get("name")
        for entry in band.get("entries", []):
            year = entry.get("year")
            division = entry.get("division")
            pieces = entry.get("pieces") or []
            rank = entry.get("rank")
            if not isinstance(pieces, list):
                pieces = [str(pieces)]
            if not isinstance(year, int) or year < min_year:
                continue
            
            # Add own-choice pieces
            for raw_piece in pieces:
                piece = (raw_piece or "").strip()
                if not piece:
                    continue
                performances.append(
                    Performance(
                        year=year,
                        division=division,
                        band=name,
                        piece=piece,
                        rank=rank if isinstance(rank, int) else None,
                    )
                )
            
            # For Elite brass bands, also add the test piece
            if band_type == "brass" and division and division.lower() == "elite":
                year_str = str(year)
                if year_str in elite_test_pieces:
                    test_piece_name = elite_test_pieces[year_str].get("piece")
                    if test_piece_name and test_piece_name.strip():
                        performances.append(
                            Performance(
                                year=year,
                                division=division,
                                band=name,
                                piece=test_piece_name.strip(),
                                rank=rank if isinstance(rank, int) else None,
                                is_test_piece=True,
                            )
                        )
    
    return performances


class StreamingLinkFinder:
    def __init__(
        self,
        *,
        spotify: Optional[SpotifyClient],
        apple_music: Optional[AppleMusicClient],
        cache: Optional[StreamingCache],
        band_type: str = "wind",
    ) -> None:
        self.spotify = spotify
        self.apple_music = apple_music
        self.band_type = band_type
        self.cache = cache
        self.album_catalog = AlbumCatalog(
            spotify=spotify,
            apple_music=apple_music,
            cache=cache,
            band_type=band_type,
        )
        self._track_cache: Dict[str, Dict[str, List[Track]]] = {"spotify": {}, "apple": {}}

    def build_links(self, performances: Iterable[Performance]) -> List[StreamingMatch]:
        grouped: Dict[Tuple[int, str], List[Performance]] = defaultdict(list)
        for performance in performances:
            division = performance.division or ""
            grouped[(performance.year, division)].append(performance)

        results: Dict[Tuple[int, str, str, str], StreamingMatch] = {}
        for (year, division), items in grouped.items():
            normalized_division = DIVISION_ALBUM_LABELS.get(division, division)
            spotify_assignments = self._match_platform_group("spotify", year, normalized_division, items)
            apple_assignments = self._match_platform_group("apple", year, normalized_division, items)

            for performance in items:
                key = performance_key(performance)
                match = results.get(key)
                if not match:
                    match = StreamingMatch(performance=performance)
                    results[key] = match
                spotify_track = spotify_assignments.get(key)
                if spotify_track:
                    match.spotify = spotify_track
                apple_track = apple_assignments.get(key)
                if apple_track:
                    match.apple_music = apple_track

        return list(results.values())

    def _match_platform_group(
        self,
        platform: str,
        year: int,
        division: str,
        performances: List[Performance],
    ) -> Dict[Tuple[int, str, str, str], Track]:
        if not performances:
            return {}

        if platform == "spotify" and not self.spotify:
            return {}
        if platform == "apple" and not self.apple_music:
            return {}

        candidates = self.album_catalog.get_album_candidates(platform, year, division)
        division_albums = [metadata for _, metadata in candidates if not metadata.is_winners_album]
        winner_albums = [metadata for _, metadata in candidates if metadata.is_winners_album]

        assignments: Dict[Tuple[int, str, str, str], Track] = {}
        remaining: List[Performance] = list(performances)

        for metadata in division_albums:
            album_assignments = self._assign_album_tracks(platform, metadata, remaining)
            if not album_assignments:
                continue
            for performance, track in album_assignments.items():
                assignments[performance_key(performance)] = track
            remaining = [perf for perf in remaining if performance_key(perf) not in assignments]
            if not remaining:
                break

        if remaining:
            if not winner_albums:
                winner_albums = self.album_catalog.get_winners_albums(platform, year)
            for metadata in winner_albums:
                candidate_performances = [perf for perf in remaining if perf.rank == 1]
                if not candidate_performances:
                    if len(remaining) == 1:
                        candidate_performances = remaining
                    else:
                        continue
                album_assignments = self._assign_album_tracks(platform, metadata, candidate_performances)
                if not album_assignments:
                    continue
                for performance, track in album_assignments.items():
                    assignments[performance_key(performance)] = track
                remaining = [perf for perf in remaining if performance_key(perf) not in assignments]
                if not remaining:
                    break

        return assignments

    def _assign_album_tracks(
        self,
        platform: str,
        metadata: AlbumMetadata,
        performances: List[Performance],
    ) -> Dict[Performance, Track]:
        if not performances:
            return {}

        tracks = self._get_tracks_for_album(platform, metadata)
        if not tracks:
            return {}

        score_table = self._build_score_table(performances, tracks)
        if not score_table:
            return {}

        primary_threshold = 0.6
        if metadata.is_winners_album or any(perf.is_test_piece for perf in performances):
            primary_threshold = 0.5

        assignments_idx = self._resolve_assignments(
            score_table,
            len(performances),
            len(tracks),
            primary_threshold,
        )

        if len(assignments_idx) < min(len(performances), len(tracks)):
            assignments_idx.update(
                self._resolve_assignments(
                    score_table,
                    len(performances),
                    len(tracks),
                    0.4,
                )
            )

        assignments: Dict[Performance, Track] = {}
        for perf_idx, track_idx in assignments_idx.items():
            score = score_table.get((perf_idx, track_idx), 0.0)
            if score < 0.35:
                continue
            base_track = tracks[track_idx]
            track_with_score = replace(base_track, match_score=score)
            assignments[performances[perf_idx]] = track_with_score
        return assignments

    def _get_tracks_for_album(self, platform: str, metadata: AlbumMetadata) -> List[Track]:
        platform_cache = self._track_cache.setdefault(platform, {})
        cached_tracks = platform_cache.get(metadata.album_id)
        if cached_tracks is None:
            if platform == "spotify":
                cached_tracks = self._load_spotify_tracks(metadata)
            else:
                cached_tracks = self._load_apple_tracks(metadata)
            platform_cache[metadata.album_id] = cached_tracks
        return [replace(track, match_score=0.0) for track in (cached_tracks or [])]

    def _load_spotify_tracks(self, metadata: AlbumMetadata) -> List[Track]:
        if not self.spotify:
            return []
        raw_tracks = None
        if self.cache:
            raw_tracks = self.cache.get_spotify_album_tracks(metadata.album_id)
        if raw_tracks is None:
            try:
                raw_tracks = self.spotify.get_album_tracks(metadata.album_id)
            except Exception as exc:
                print(f"[spotify] Kunne ikke hente spor for {metadata.name}: {exc}")
                return []
            if self.cache and raw_tracks is not None:
                self.cache.set_spotify_album_tracks(metadata.album_id, raw_tracks)

        tracks: List[Track] = []
        seen_ids: set[str] = set()
        for item in raw_tracks or []:
            track_id = item.get("id")
            if track_id and track_id in seen_ids:
                continue
            if track_id:
                seen_ids.add(track_id)
            title = item.get("name")
            external_urls = item.get("external_urls") or {}
            url = external_urls.get("spotify")
            if not title or not url:
                continue
            artists = item.get("artists") or []
            artist_names = [a.get("name") for a in artists if a.get("name")]
            artist = ", ".join(artist_names) if artist_names else ""
            slug_primary = normalize_title(title)
            slug_full = normalize_title(title, remove_parentheticals=False)
            slug_variants: List[str] = []
            for candidate in (slug_primary, slug_full):
                if candidate and candidate not in slug_variants:
                    slug_variants.append(candidate)
            tracks.append(
                Track(
                    platform="spotify",
                    title=title,
                    slug=slug_variants[0] if slug_variants else slug_primary,
                    slug_variants=slug_variants or [slug_primary],
                    url=url,
                    album=metadata.name,
                    album_id=metadata.album_id,
                    artist=artist,
                )
            )
        return tracks

    def _load_apple_tracks(self, metadata: AlbumMetadata) -> List[Track]:
        if not self.apple_music:
            return []
        raw_tracks = None
        if self.cache:
            raw_tracks = self.cache.get_apple_album_tracks(metadata.album_id)
        if raw_tracks is None:
            try:
                lookup_id = int(metadata.album_id)
            except (TypeError, ValueError):
                lookup_id = metadata.album_id
            try:
                raw_tracks = self.apple_music.lookup_album_tracks(lookup_id)
            except Exception as exc:
                print(f"[apple] Kunne ikke hente spor for {metadata.name}: {exc}")
                return []
            if self.cache and raw_tracks is not None:
                self.cache.set_apple_album_tracks(metadata.album_id, raw_tracks)

        tracks: List[Track] = []
        seen_ids: set[int] = set()
        for song in raw_tracks or []:
            track_id = song.get("trackId")
            if isinstance(track_id, int) and track_id in seen_ids:
                continue
            if isinstance(track_id, int):
                seen_ids.add(track_id)
            title = song.get("trackName")
            url = song.get("trackViewUrl")
            if not title or not url:
                continue
            if song.get("isStreamable") is False:
                print(f"[apple] Track '{title}' is not streamable – skipping")
                continue
            artist_raw = song.get("artistName") or ""
            artist = artist_raw if artist_raw.strip().lower() not in {"", "na", "n/a", "unknown"} else ""
            slug_primary = normalize_title(title)
            slug_full = normalize_title(title, remove_parentheticals=False)
            slug_variants: List[str] = []
            for candidate in (slug_primary, slug_full):
                if candidate and candidate not in slug_variants:
                    slug_variants.append(candidate)
            tracks.append(
                Track(
                    platform="apple_music",
                    title=title,
                    slug=slug_variants[0] if slug_variants else slug_primary,
                    slug_variants=slug_variants or [slug_primary],
                    url=url,
                    album=metadata.name,
                    album_id=metadata.album_id,
                    artist=artist,
                )
            )
        return tracks

    def _build_score_table(
        self,
        performances: List[Performance],
        tracks: List[Track],
    ) -> Dict[Tuple[int, int], float]:
        table: Dict[Tuple[int, int], float] = {}
        piece_variants_cache = [get_title_variants(perf.piece) for perf in performances]
        band_slug_cache = [normalize_title(perf.band) if perf.band else "" for perf in performances]

        for perf_idx, performance in enumerate(performances):
            piece_variants = piece_variants_cache[perf_idx] or []
            band_slug = band_slug_cache[perf_idx]
            for track_idx, track in enumerate(tracks):
                piece_score = 0.0
                for piece_variant in piece_variants or []:
                    for slug_variant in track.slug_variants:
                        piece_score = max(piece_score, similarity_score(piece_variant, slug_variant))
                if not piece_variants:
                    piece_score = similarity_score(normalize_title(performance.piece), track.slug)

                band_score = self._band_similarity(band_slug, track)
                combined = self._combine_scores(performance, piece_score, band_score)
                if combined <= 0:
                    continue
                table[(perf_idx, track_idx)] = combined

        return table

    def _band_similarity(self, band_slug: str, track: Track) -> float:
        if not band_slug:
            return 0.0
        best = 0.0
        if track.artist:
            artist_parts = [part.strip() for part in track.artist.split(',')]
            for artist_part in artist_parts:
                if not artist_part:
                    continue
                artist_slug = normalize_title(artist_part)
                if not artist_slug:
                    continue
                best = max(best, similarity_score(band_slug, artist_slug))
        title_slug = normalize_title(track.title)
        if band_slug in title_slug:
            best = max(best, 0.95)
        else:
            best = max(best, similarity_score(band_slug, title_slug))
        return best

    def _combine_scores(self, performance: Performance, piece_score: float, band_score: float) -> float:
        if performance.is_test_piece:
            if band_score > 0.85:
                return band_score * 0.9 + piece_score * 0.1
            if band_score > 0.6:
                return band_score * 0.8 + piece_score * 0.2
            if band_score > 0.4:
                return band_score * 0.7 + piece_score * 0.2
            return band_score * 0.5

        if band_score > 0.85:
            return piece_score * 0.5 + band_score * 0.5
        if band_score > 0.7:
            return piece_score * 0.6 + band_score * 0.4
        if band_score > 0.5:
            return piece_score * 0.75 + band_score * 0.25
        if band_score > 0.3:
            return piece_score * 0.6 + band_score * 0.1
        if piece_score >= 0.9:
            return piece_score * 0.55
        return piece_score * 0.35

    def _resolve_assignments(
        self,
        score_table: Dict[Tuple[int, int], float],
        num_performances: int,
        num_tracks: int,
        threshold: float,
    ) -> Dict[int, int]:
        unmatched_performances = set(range(num_performances))
        unmatched_tracks = set(range(num_tracks))
        assignments: Dict[int, int] = {}

        while unmatched_performances and unmatched_tracks:
            perf_best: Dict[int, Tuple[int, float]] = {}
            for perf_idx in unmatched_performances:
                best_track = None
                best_score = 0.0
                for track_idx in unmatched_tracks:
                    score = score_table.get((perf_idx, track_idx), 0.0)
                    if score > best_score:
                        best_track = track_idx
                        best_score = score
                if best_track is not None and best_score >= threshold:
                    perf_best[perf_idx] = (best_track, best_score)

            track_best: Dict[int, Tuple[int, float]] = {}
            for track_idx in unmatched_tracks:
                best_perf = None
                best_score = 0.0
                for perf_idx in unmatched_performances:
                    score = score_table.get((perf_idx, track_idx), 0.0)
                    if score > best_score:
                        best_perf = perf_idx
                        best_score = score
                if best_perf is not None and best_score >= threshold:
                    track_best[track_idx] = (best_perf, best_score)

            mutual_matches: List[Tuple[float, int, int]] = []
            for perf_idx, (track_idx, perf_score) in perf_best.items():
                track_choice = track_best.get(track_idx)
                if track_choice and track_choice[0] == perf_idx:
                    mutual_matches.append((max(perf_score, track_choice[1]), perf_idx, track_idx))

            if mutual_matches:
                mutual_matches.sort(reverse=True)
                for _, perf_idx, track_idx in mutual_matches:
                    assignments[perf_idx] = track_idx
                    unmatched_performances.discard(perf_idx)
                    unmatched_tracks.discard(track_idx)
                continue

            best_pair = None
            best_score = threshold
            for perf_idx in unmatched_performances:
                for track_idx in unmatched_tracks:
                    score = score_table.get((perf_idx, track_idx), 0.0)
                    if score > best_score:
                        best_score = score
                        best_pair = (perf_idx, track_idx)
            if not best_pair:
                break
            perf_idx, track_idx = best_pair
            assignments[perf_idx] = track_idx
            unmatched_performances.discard(perf_idx)
            unmatched_tracks.discard(track_idx)

        return assignments

# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def make_lookup_slug(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = normalize_title(value)
    if normalized:
        return normalized
    return value.strip().lower()


def build_override_key(year: int, division_slug: Optional[str], band_slug: Optional[str], piece_slug: Optional[str]) -> Optional[str]:
    if division_slug is None or band_slug is None or piece_slug is None:
        return None
    return f"{year}|{division_slug}|{band_slug}|{piece_slug}"


class StreamingOverrideResolver:
    ALLOWED_FIELDS = {
        "spotify",
        "apple_music",
        "album",
        "recording_title",
        "alternate_result_piece_slugs",
        "result_piece",
        "notes",
        "allow_album_mismatch",
        "band_type",
    }

    def __init__(self, overrides: Dict[str, Dict[str, object]], band_type: str):
        self._overrides = overrides
        self._applied_keys: set[str] = set()
        self._band_type = band_type

    @classmethod
    def from_file(cls, path: Optional[Path], console, *, band_type: str) -> "StreamingOverrideResolver":
        if not path:
            return cls({}, band_type)
        path = path.expanduser()
        if not path.exists():
            return cls({}, band_type)

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            console.print(f"[red]Kunne ikke lese streaming-overrides fra {path}: {exc}[/red]")
            return cls({}, band_type)

        if isinstance(payload, dict) and "overrides" in payload:
            raw_entries = payload.get("overrides", [])
        elif isinstance(payload, list):
            raw_entries = payload
        else:
            console.print(f"[yellow]Ukjent format på {path}; forventer liste eller objekt med 'overrides'.[/yellow]")
            raw_entries = []

        overrides: Dict[str, Dict[str, object]] = {}
        for entry in raw_entries:
            if not isinstance(entry, dict):
                continue
            year = entry.get("year")
            division = entry.get("division")
            band = entry.get("band")
            piece = entry.get("piece") or entry.get("result_piece")
            division_slug = entry.get("division_slug") or make_lookup_slug(division)
            band_slug = entry.get("band_slug") or make_lookup_slug(band)
            piece_slug = entry.get("piece_slug") or entry.get("result_piece_slug") or make_lookup_slug(piece)

            if year is None or division_slug is None or band_slug is None or piece_slug is None:
                console.print(f"[yellow]Ignorerer override med manglende nøkler: {entry}[/yellow]")
                continue

            key = build_override_key(int(year), division_slug, band_slug, piece_slug)
            if not key:
                continue

            fields = {
                field: entry[field]
                for field in cls.ALLOWED_FIELDS
                if field in entry
            }

            if not fields:
                continue

            entry_band_type = (entry.get("band_type") or entry.get("type") or "").strip().lower()
            if entry_band_type and entry_band_type not in {"wind", "brass"}:
                console.print(f"[yellow]Ignorerer override med ukjent band_type: {entry_band_type} ({entry})[/yellow]")
                continue

            overrides[key] = {
                "fields": fields,
                "meta": {
                    "year": int(year),
                    "division": division,
                    "band": band,
                    "piece": piece,
                    "division_slug": division_slug,
                    "band_slug": band_slug,
                    "piece_slug": piece_slug,
                    "band_type": entry_band_type or None,
                },
            }

        if overrides:
            console.print(f"[green]Lest {len(overrides)} streaming-overrides fra {path}[/green]")
        return cls(overrides, band_type)

    def lookup(self, performance: Performance) -> Optional[Dict[str, object]]:
        division_slug = make_lookup_slug(performance.division)
        band_slug = make_lookup_slug(performance.band)
        piece_slug = make_lookup_slug(performance.piece)
        key = build_override_key(performance.year, division_slug, band_slug, piece_slug)
        if key and key in self._overrides:
            entry = self._overrides[key]
            meta = entry.get("meta", {})
            entry_band_type = meta.get("band_type")
            if entry_band_type and entry_band_type != self._band_type:
                return None
            self._applied_keys.add(key)
            return entry["fields"]
        return None

    def remaining_entries(self, *, year: Optional[int] = None) -> List[Dict[str, object]]:
        remaining: List[Dict[str, object]] = []
        for key, entry in self._overrides.items():
            if key in self._applied_keys:
                continue
            entry_band_type = entry.get("meta", {}).get("band_type")
            if entry_band_type and entry_band_type != self._band_type:
                continue
            if year is not None and entry.get("meta", {}).get("year") != year:
                continue
            remaining.append(entry)
        return remaining


# ---------------------------------------------------------------------------
# CLI helper
# ---------------------------------------------------------------------------


def build_year_streaming_entries(
    year: int,
    performances: List[Performance],
    finder: StreamingLinkFinder,
    override_resolver: StreamingOverrideResolver,
) -> List[Dict[str, object]]:
    matches = finder.build_links(performances)
    match_lookup: Dict[Tuple[int, str, str, str], StreamingMatch] = {
        performance_key(match.performance): match for match in matches
    }

    serialised: List[Dict[str, object]] = []
    for performance in performances:
        key = performance_key(performance)
        match = match_lookup.get(key, StreamingMatch(performance=performance))
        entry_dict: Dict[str, object] = match.to_dict()
        override = override_resolver.lookup(match.performance)
        allow_mismatch = False
        if override:
            allow_mismatch = bool(override.get("allow_album_mismatch"))
            for key, value in override.items():
                if key == "allow_album_mismatch":
                    continue
                entry_dict[key] = value

        if not (entry_dict.get("spotify") or entry_dict.get("apple_music")) and not override:
            continue

        album_value = entry_dict.get("album")
        if not allow_mismatch:
            album_text = str(album_value or "")
            if not album_text or str(year) not in album_text:
                continue
        serialised.append(entry_dict)

    for leftover in override_resolver.remaining_entries(year=year):
        fields = leftover.get("fields", {})
        meta = leftover.get("meta", {})
        if not (fields.get("spotify") or fields.get("apple_music")):
            continue
        album_value = fields.get("album")
        allow_mismatch = bool(fields.get("allow_album_mismatch"))
        if not allow_mismatch:
            album_text = str(album_value or "")
            if not album_text or str(year) not in album_text:
                continue
        entry_dict = {
            "year": meta.get("year", year),
            "division": meta.get("division"),
            "band": meta.get("band"),
            "result_piece": meta.get("piece"),
            "recording_title": fields.get("recording_title"),
            "album": album_value,
            "spotify": fields.get("spotify"),
            "apple_music": fields.get("apple_music"),
        }
        if "alternate_result_piece_slugs" in fields:
            entry_dict["alternate_result_piece_slugs"] = fields["alternate_result_piece_slugs"]
        serialised.append(entry_dict)

    serialised.sort(
        key=lambda entry: (
            entry.get("year", 0),
            str(entry.get("division", "")),
            str(entry.get("band", "")),
            str(entry.get("result_piece", "")),
        )
    )

    return serialised


def load_existing_entries(
    output_dir: Path,
    band_type: str,
    year: int,
) -> List[Dict[str, object]]:
    """Load existing entries from a year file if it exists."""
    year_dir = output_dir.expanduser() / band_type
    year_path = year_dir / f"{year}.json"
    
    if not year_path.exists():
        return []
    
    try:
        existing_data = json.loads(year_path.read_text(encoding="utf-8"))
        if isinstance(existing_data, dict):
            return existing_data.get("entries", [])
        elif isinstance(existing_data, list):
            return existing_data
    except (json.JSONDecodeError, IOError):
        pass
    
    return []


def write_year_file(
    output_dir: Path, 
    band_type: str, 
    year: int, 
    entries: List[Dict[str, object]], 
    divisions_filter: Optional[List[str]] = None
) -> Path:
    """Write year file, merging with existing entries when using division filter.
    
    When divisions_filter is provided, preserves entries from other divisions.
    """
    year_dir = output_dir.expanduser() / band_type
    year_dir.mkdir(parents=True, exist_ok=True)
    year_path = year_dir / f"{year}.json"
    
    # If using division filter, merge with existing entries from other divisions
    if divisions_filter:
        existing_entries = load_existing_entries(output_dir, band_type, year)
        # Keep entries from divisions NOT in the filter
        preserved_entries = [
            entry for entry in existing_entries
            if entry.get("division") not in divisions_filter
        ]
        
        # Combine preserved entries with new entries
        all_entries = preserved_entries + entries
        
        # Sort combined entries
        all_entries.sort(
            key=lambda entry: (
                entry.get("year", 0),
                str(entry.get("division", "")),
                str(entry.get("band", "")),
                str(entry.get("result_piece", "")),
            )
        )
        entries = all_entries
    
    payload = {
        "band_type": band_type,
        "year": year,
        "entries": entries,
    }
    year_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return year_path


def combine_year_files(output_dir: Path, aggregate_path: Path, band_type: str) -> None:
    aggregate_data = {"wind": [], "brass": []}
    aggregate_path = aggregate_path.expanduser()
    if aggregate_path.exists():
        try:
            existing = json.loads(aggregate_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                aggregate_data.update(existing)
        except json.JSONDecodeError:
            pass

    combined: List[Dict[str, object]] = []
    year_dir = output_dir.expanduser() / band_type
    if year_dir.exists():
        for year_file in sorted(year_dir.glob("*.json")):
            try:
                payload = json.loads(year_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            entries = []
            if isinstance(payload, dict):
                entries = payload.get("entries") or []
            elif isinstance(payload, list):
                entries = payload
            if isinstance(entries, list):
                combined.extend(entries)

    combined.sort(
        key=lambda entry: (
            entry.get("year", 0),
            str(entry.get("division", "")),
            str(entry.get("band", "")),
            str(entry.get("result_piece", "")),
        )
    )

    aggregate_data[band_type] = combined
    aggregate_path.parent.mkdir(parents=True, exist_ok=True)
    aggregate_path.write_text(json.dumps(aggregate_data, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_credentials(credentials_path: Optional[Path], console) -> Tuple[Optional[str], Optional[str]]:
    if not credentials_path:
        return None, None
    credentials_path = credentials_path.expanduser()
    if not credentials_path.exists():
        return None, None
    try:
        data = json.loads(credentials_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        console.print(f"[red]Kunne ikke tolke Spotify-nøkler fra {credentials_path}: {exc}[/red]")
        return None, None
    client_id = (data.get("spotify_client_id") or "").strip() or None
    client_secret = (data.get("spotify_client_secret") or "").strip() or None
    return client_id, client_secret


def parse_divisions_argument(codes: Optional[List[str]]) -> Optional[List[str]]:
    """Parse division codes (E, 1, 2, etc.) into full division names.
    
    Args:
        codes: List of division codes (e.g., ['E', '1', '2']) or full names
    
    Returns:
        List of full division names, or None if codes is None/empty
    
    Raises:
        ValueError: If an invalid division code is provided
    """
    if not codes:
        return None
    expanded = []
    for raw in codes:
        code = str(raw).strip()
        # Accept exact full names too
        if code in DIVISION_CODE_MAP:
            expanded.append(DIVISION_CODE_MAP[code])
        elif code in DIVISION_CODE_MAP.values():
            expanded.append(code)
        else:
            valid_codes = ', '.join(list(DIVISION_CODE_MAP.keys()))
            raise ValueError(
                f"Invalid division '{raw}'. Use one of: {valid_codes}"
            )
    # De-duplicate while preserving order
    seen = set()
    result = []
    for name in expanded:
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result


def generate_streaming_links(
    *,
    positions: Path,
    output_dir: Path,
    aggregate: Optional[Path] = None,
    min_year: int = 2017,
    years: Optional[List[int]] = None,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    divisions_filter: Optional[List[str]] = None,
    spotify_client_id: Optional[str] = None,
    spotify_client_secret: Optional[str] = None,
    apple_country: str = "us",
    skip_spotify: bool = False,
    skip_apple: bool = False,
    overrides_path: Optional[Path] = None,
    credentials_path: Optional[Path] = None,
    cache_path: Optional[Path] = None,
    console=None,
    band_type: str = "wind",
    preserve_existing: bool = False,
) -> int:
    from rich.console import Console
    from rich.progress import track

    console = console or Console()

    if not positions.exists():
        console.print(f"[red]Positions file not found:[/red] {positions}")
        raise FileNotFoundError(positions)

    cache = StreamingCache(cache_path) if cache_path else None

    spotify_client: Optional[SpotifyClient] = None
    apple_client: Optional[AppleMusicClient] = None
    user_agent = f"nmjanitsjar_scraper/1.0 (https://github.com/frefrik/nmjanitsjar; andreas@famileik.no)"

    if not skip_spotify:
        if not spotify_client_id or not spotify_client_secret:
            default_credentials_path = credentials_path or Path("config/streaming_credentials.json")
            file_client_id, file_client_secret = _load_credentials(default_credentials_path, console)
            spotify_client_id = spotify_client_id or file_client_id
            spotify_client_secret = spotify_client_secret or file_client_secret
            if file_client_id and file_client_secret:
                console.print(f"[green]Henter Spotify-nøkler fra {default_credentials_path}[/green]")

        if not spotify_client_id or not spotify_client_secret:
            console.print("[yellow]Spotify-nøkler mangler – hopper over Spotify-søk[/yellow]")
        else:
            spotify_client = SpotifyClient(client_id=spotify_client_id, client_secret=spotify_client_secret, cache=cache)

    if not skip_apple:
        apple_client = AppleMusicClient(country=apple_country, cache=cache, user_agent=user_agent)

    override_resolver = StreamingOverrideResolver.from_file(overrides_path, console, band_type=band_type)

    # Determine path to elite test pieces file for brass bands
    elite_test_pieces_path = None
    if band_type == "brass":
        # Assume elite_test_pieces.json is in the same directory as the positions file
        elite_test_pieces_path = positions.parent / "elite_test_pieces.json"
    
    performances = load_performances(positions, min_year=min_year, elite_test_pieces_path=elite_test_pieces_path, band_type=band_type)
    if not performances:
        console.print("[yellow]No performances found for the given criteria[/yellow]")
        if aggregate:
            combine_year_files(output_dir, aggregate, band_type)
        if cache:
            cache.save()
        return 0

    finder = StreamingLinkFinder(
        spotify=spotify_client,
        apple_music=apple_client,
        cache=cache,
        band_type=band_type,
    )

    available_years = sorted({performance.year for performance in performances})
    target_years = {year for year in available_years if year >= min_year}

    if years:
        target_years &= set(years)
    if start_year is not None:
        target_years = {year for year in target_years if year >= start_year}
    if end_year is not None:
        target_years = {year for year in target_years if year <= end_year}

    if not target_years:
        console.print("[yellow]Ingen år samsvarte med filtrene – ingen data generert.[/yellow]")
        if cache:
            cache.save()
        return 0

    if len(target_years) != 1:
        console.print(
            "[yellow]Denne kommandoen er nå begrenset til ett år om gangen. "
            "Angi for eksempel --years 2025 for å kjøre et spesifikt år.[/yellow]"
        )
        if cache:
            cache.save()
        return 0

    year_map: Dict[int, List[Performance]] = {}
    for performance in performances:
        if performance.year in target_years:
            # Apply division filter if specified
            if divisions_filter is None or performance.division in divisions_filter:
                year_map.setdefault(performance.year, []).append(performance)
    
    # Log division filtering
    if divisions_filter:
        divisions_being_processed = set()
        for perfs in year_map.values():
            divisions_being_processed.update(p.division for p in perfs)
        console.print(f"[cyan]Processing divisions: {', '.join(sorted(divisions_being_processed))}[/cyan]")
    
    required_fields: List[str] = []
    if finder.spotify:
        required_fields.append("spotify")
    if finder.apple_music:
        required_fields.append("apple_music")

    total_entries = 0
    for year in track(sorted(year_map.keys()), description="Matching streaming links"):
        year_performances = year_map[year]
        
        # If preserve_existing is True, filter out performances that already have links
        if preserve_existing:
            existing_entries = load_existing_entries(output_dir, band_type, year)
            
            # Build a set of performance keys that already have all required links
            existing_with_links: set[str] = set()
            for entry in existing_entries:
                if required_fields and not all(entry.get(field) for field in required_fields):
                    continue
                if not required_fields and not (entry.get("spotify") or entry.get("apple_music")):
                    continue
                key = f"{entry.get('year')}|{entry.get('division')}|{entry.get('band')}|{entry.get('result_piece')}"
                existing_with_links.add(key)
            
            # Filter performances to only those that need linking
            performances_to_process = []
            for perf in year_performances:
                perf_key = f"{perf.year}|{perf.division}|{perf.band}|{perf.piece}"
                if perf_key not in existing_with_links:
                    performances_to_process.append(perf)
            
            # Build entries for performances that need linking
            new_entries = build_year_streaming_entries(year, performances_to_process, finder, override_resolver)
            
            # Combine with existing entries that have links
            all_entries = []
            for entry in existing_entries:
                entry_key = f"{entry.get('year')}|{entry.get('division')}|{entry.get('band')}|{entry.get('result_piece')}"
                # Keep existing entries with links, or those from other divisions if filter is active
                if entry_key in existing_with_links:
                    if divisions_filter is None or entry.get("division") in divisions_filter:
                        all_entries.append(entry)
                    elif entry.get("division") not in divisions_filter:
                        # Keep entries from other divisions
                        all_entries.append(entry)
            
            # Add newly processed entries
            all_entries.extend(new_entries)
            
            # Sort combined entries
            all_entries.sort(
                key=lambda entry: (
                    entry.get("year", 0),
                    str(entry.get("division", "")),
                    str(entry.get("band", "")),
                    str(entry.get("result_piece", "")),
                )
            )
            
            entries = all_entries
        else:
            # Force overwrite mode - process all performances
            entries = build_year_streaming_entries(year, year_performances, finder, override_resolver)
        
        write_year_file(output_dir, band_type, year, entries, divisions_filter)
        total_entries += len(entries)

    if aggregate:
        combine_year_files(output_dir, aggregate, band_type)

    if cache:
        cache.save()

    console.print(f"[green]Skrev {total_entries} streaming-oppføringer for {band_type} til {output_dir}[/green]")
    return total_entries


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Fetch streaming links for NM Janitsjar performances")
    parser.add_argument("--positions", type=Path, required=True, help="Path to band positions dataset (JSON)")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory where per-year streaming data will be written")
    parser.add_argument("--aggregate", type=Path, required=True, help="Combined JSON output consumed by the app")
    parser.add_argument("--min-year", type=int, default=2017, help="First year to include (default: 2017)")
    parser.add_argument("--years", nargs="+", type=int, help="Specific years to process")
    parser.add_argument("--start-year", type=int, help="Optional starting year filter")
    parser.add_argument("--end-year", type=int, help="Optional ending year filter")
    parser.add_argument("--credentials", type=Path, default=Path("config/streaming_credentials.json"))
    parser.add_argument("--overrides", type=Path, default=Path("config/streaming_overrides.json"))
    parser.add_argument("--cache", type=Path, default=Path("config/streaming_cache.json"))
    parser.add_argument("--band-type", type=str, default="wind", choices=("wind", "brass"))
    parser.add_argument(
        "--divisions",
        nargs="+",
        metavar="DIV",
        help="Division codes to process (E=Elite, 1-7 for divisions). If omitted, all divisions are processed. Example: --divisions E 1 2"
    )
    parser.add_argument("--spotify-client-id", type=str, default=os.getenv("SPOTIFY_CLIENT_ID"))
    parser.add_argument("--spotify-client-secret", type=str, default=os.getenv("SPOTIFY_CLIENT_SECRET"))
    parser.add_argument("--apple-country", type=str, default="us", help="Apple Music store country code (default: us)")
    parser.add_argument("--skip-spotify", action="store_true", help="Skip Spotify lookup")
    parser.add_argument("--skip-apple", action="store_true", help="Skip Apple Music lookup")
    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        help="Force overwrite existing streaming links. By default, existing links are preserved."
    )

    args = parser.parse_args()
    
    # Parse division codes
    divisions_filter = None
    if args.divisions:
        try:
            divisions_filter = parse_divisions_argument(args.divisions)
        except ValueError as e:
            parser.error(str(e))

    generate_streaming_links(
        positions=args.positions,
        output_dir=args.output_dir,
        aggregate=args.aggregate,
        min_year=args.min_year,
        years=args.years,
        start_year=args.start_year,
        end_year=args.end_year,
        divisions_filter=divisions_filter,
        preserve_existing=not args.force_overwrite,
        spotify_client_id=args.spotify_client_id,
        spotify_client_secret=args.spotify_client_secret,
        apple_country=args.apple_country,
        skip_spotify=args.skip_spotify,
        skip_apple=args.skip_apple,
        overrides_path=args.overrides,
        credentials_path=args.credentials,
        cache_path=args.cache,
        band_type=args.band_type,
    )


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()

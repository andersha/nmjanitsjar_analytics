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
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Performance:
    year: int
    division: str
    band: str
    piece: str


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
        self._data = {
            "spotify": {"album_tracks": {}, "album_searches": {}},
            "apple": {"album_tracks": {}, "album_searches": {}},
        }
        self._dirty = False
        if self.path and self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    for key in ("spotify", "apple"):
                        if key in loaded and isinstance(loaded[key], dict):
                            self._data[key].update(loaded[key])
                    # Ensure album_searches exists for backward compatibility
                    self._data.setdefault("spotify", {}).setdefault("album_searches", {})
                    self._data.setdefault("apple", {}).setdefault("album_searches", {})
            except json.JSONDecodeError:
                pass

    def get_spotify_album_tracks(self, album_id: str) -> Optional[List[Dict]]:
        return self._data.get("spotify", {}).get("album_tracks", {}).get(album_id, {}).get("tracks")

    def set_spotify_album_tracks(self, album_id: str, tracks: List[Dict]) -> None:
        self._data.setdefault("spotify", {}).setdefault("album_tracks", {})[album_id] = {
            "tracks": tracks,
            "fetched_at": time.time(),
        }
        self._dirty = True

    def get_spotify_album_search(self, year: int, division: str) -> Optional[List[Dict]]:
        """Get cached Spotify album search results for a year/division."""
        spotify = self._data.get("spotify", {})
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
        spotify = self._data.setdefault("spotify", {})
        searches = spotify.setdefault("album_searches", {})
        key = f"{year}|{division}"
        searches[key] = {
            "albums": albums,
            "fetched_at": time.time(),
        }
        self._dirty = True

    def get_apple_album_tracks(self, collection_id: str) -> Optional[List[Dict]]:
        return self._data.get("apple", {}).get("album_tracks", {}).get(collection_id, {}).get("tracks")

    def set_apple_album_tracks(self, collection_id: str, tracks: List[Dict]) -> None:
        self._data.setdefault("apple", {}).setdefault("album_tracks", {})[collection_id] = {
            "tracks": tracks,
            "fetched_at": time.time(),
        }
        self._dirty = True

    def get_apple_album_search(self, year: int, division: str) -> Optional[List[Dict]]:
        """Get cached Apple Music album search results for a year/division."""
        apple = self._data.get("apple", {})
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
        apple = self._data.setdefault("apple", {})
        searches = apple.setdefault("album_searches", {})
        key = f"{year}|{division}"
        searches[key] = {
            "albums": albums,
            "fetched_at": time.time(),
        }
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

ALBUM_PREFIXES = {
    "wind": "NM Janitsjar",
    "brass": "NM Brass",
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


def resolve_album_search_terms(year: int, division: str, band_type: str) -> List[str]:
    prefix = ALBUM_PREFIXES.get(band_type, "NM Janitsjar")
    normalized_division = DIVISION_ALBUM_LABELS.get(division, division)
    division_variants = DIVISION_SYNONYMS.get(normalized_division, [normalized_division])

    variants = {f"{prefix} {year}"}
    for div_variant in division_variants:
        base = f"{prefix} {year} {div_variant}".strip()
        variants.update({
            base,
            f"{base} (Live)",
            f"{prefix} {year} – {div_variant} (Live)",
            f"{prefix} {year} - {div_variant}",
        })
    return [variant for variant in variants if variant]


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
            if not isinstance(pieces, list):
                pieces = [str(pieces)]
            if not isinstance(year, int) or year < min_year:
                continue
            
            # Add own-choice pieces
            for raw_piece in pieces:
                piece = (raw_piece or "").strip()
                if not piece:
                    continue
                performances.append(Performance(year=year, division=division, band=name, piece=piece))
            
            # For Elite brass bands, also add the test piece
            if band_type == "brass" and division and division.lower() == "elite":
                year_str = str(year)
                if year_str in elite_test_pieces:
                    test_piece_name = elite_test_pieces[year_str].get("piece")
                    if test_piece_name and test_piece_name.strip():
                        performances.append(Performance(year=year, division=division, band=name, piece=test_piece_name.strip()))
    
    return performances


class StreamingLinkFinder:
    def __init__(
        self,
        *,
        spotify: Optional[SpotifyClient],
        apple_music: Optional[AppleMusicClient],
        band_type: str = "wind",
    ) -> None:
        self.spotify = spotify
        self.apple_music = apple_music
        self._spotify_album_cache: Dict[Tuple[int, str], List[Track]] = {}
        self._apple_album_cache: Dict[Tuple[int, str], List[Track]] = {}
        # Cache discovered album names per year to avoid redundant searches
        self._discovered_album_names: Dict[Tuple[int, str], set[str]] = {}  # (year, platform) -> set of album names
        self.band_type = band_type

    def build_links(self, performances: Iterable[Performance]) -> List[StreamingMatch]:
        matches: List[StreamingMatch] = []
        for performance in performances:
            spotify_track = self.match_spotify(performance)
            apple_track = self.match_apple(performance)
            match = StreamingMatch(performance=performance, spotify=spotify_track, apple_music=apple_track)
            matches.append(match)
        return matches

    # ----------------------- Spotify -----------------------

    def _get_spotify_tracks_for_division(self, year: int, division: str) -> List[Track]:
        key = (year, division)
        if key in self._spotify_album_cache:
            return self._spotify_album_cache[key]
        if not self.spotify:
            self._spotify_album_cache[key] = []
            return []

        # Check if we should use album search caching (years >= 2012)
        use_album_cache = year >= 2012 and self.spotify.cache is not None
        
        # Try to get cached album search results
        all_albums_from_searches: List[Dict] = []
        if use_album_cache:
            cached_albums = self.spotify.cache.get_spotify_album_search(year, division)
            if cached_albums:
                print(f"[spotify] Album search cache HIT for {year}|{division} ({len(cached_albums)} albums)")
                all_albums_from_searches = cached_albums
        
        # If no cache hit, perform album searches
        if not all_albums_from_searches:
            seen_albums: set[str] = set()
            for term in resolve_album_search_terms(year, division, self.band_type):
                albums = self.spotify.search_albums(term)
                for album in albums:
                    album_id = album.get("id")
                    if not album_id or album_id in seen_albums:
                        continue
                    seen_albums.add(album_id)
                    all_albums_from_searches.append(album)
                
                # Stop early if we have enough candidates
                if len(all_albums_from_searches) >= 15:
                    break
            
            # Cache the album search results if we got any
            if use_album_cache and all_albums_from_searches:
                self.spotify.cache.set_spotify_album_search(year, division, all_albums_from_searches)
                print(f"[spotify] Album search cache WRITE for {year}|{division} ({len(all_albums_from_searches)} albums)")
        
        # Now score and filter the albums
        candidate_albums: List[Tuple[float, Dict]] = []  # (score, album)
        for album in all_albums_from_searches:
            score = score_album_relevance(album, year, division)
            candidate_albums.append((score, album))
        
        # Sort by score descending (best matches first)
        candidate_albums.sort(key=lambda x: x[0], reverse=True)
        
        # Filter: ONLY use albums from the target year
        # Check both release date and album name for the year
        filtered_albums = []
        for score, album in candidate_albums:
            release_date = album.get("release_date") or ""
            album_name = album.get("name") or ""
            album_name_lower = album_name.lower()
            
            # Extract release year
            release_year = None
            if isinstance(release_date, str) and len(release_date) >= 4:
                try:
                    release_year = int(release_date[:4])
                except ValueError:
                    pass
            
            # Only include albums from the target year
            if release_year == year or str(year) in album_name_lower:
                filtered_albums.append((score, album))
                # Remember this album name for future searches
                if album_name:
                    self._discovered_album_names.setdefault((year, "spotify"), set()).add(album_name)
        
        # Collect tracks from filtered albums, deduplicating by track ID
        tracks: List[Track] = []
        seen_track_ids: set[str] = set()
        
        for score, album in filtered_albums:
            album_id = album.get("id")
            album_name = album.get("name")
            
            # Skip albums with very low relevance scores
            if score < 10:
                continue
            
            # Fetch tracks from this album
            cached_tracks = self.spotify.cache.get_spotify_album_tracks(album_id) if self.spotify and self.spotify.cache else None
            if cached_tracks is not None:
                track_items = cached_tracks
            else:
                track_items = self.spotify.get_album_tracks(album_id)
                if self.spotify and self.spotify.cache and track_items is not None:
                    self.spotify.cache.set_spotify_album_tracks(album_id, track_items)
            
            for item in track_items:
                track_id = item.get("id")
                if track_id and track_id in seen_track_ids:
                    continue
                if track_id:
                    seen_track_ids.add(track_id)
                
                title = item.get("name")
                external_urls = item.get("external_urls") or {}
                url = external_urls.get("spotify")
                if not title or not url:
                    continue
                
                # Extract artist name(s), filtering out placeholder values
                artists = item.get("artists") or []
                artist_names = [
                    a.get("name") for a in artists 
                    if a.get("name") and a.get("name").strip().lower() not in ["", "na", "n/a", "unknown"]
                ]
                # Store all artist names for better matching - we'll check against all of them
                artist = ", ".join(artist_names) if artist_names else ""
                
                slug_primary = normalize_title(title)
                slug_full = normalize_title(title, remove_parentheticals=False)
                slug_variants = []
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
                        album=album_name or "",
                        album_id=album_id,
                        artist=artist,
                    )
                )

        self._spotify_album_cache[key] = tracks
        return tracks

    def match_spotify(self, performance: Performance) -> Optional[Track]:
        tracks = self._get_spotify_tracks_for_division(performance.year, performance.division)
        if not tracks:
            return None
        piece_variants = get_title_variants(performance.piece)
        band_slug = normalize_title(performance.band)
        
        best_match: Optional[Track] = None
        best_score = 0.0
        
        for track in tracks:
            # Calculate piece similarity using all variants
            piece_match_score = 0.0
            for piece_variant in piece_variants:
                for slug_variant in track.slug_variants:
                    score = similarity_score(piece_variant, slug_variant)
                    if score > piece_match_score:
                        piece_match_score = score
            
            # Calculate band/artist similarity if artist info is available
            # Check against all individual artists in the track, not just the combined string
            band_match_score = 0.0
            if track.artist and band_slug:
                # Split on comma to check each artist separately
                # (since tracks can have composer, "Na", band, conductor)
                artist_parts = [part.strip() for part in track.artist.split(',')]
                for artist_part in artist_parts:
                    if artist_part:
                        artist_slug = normalize_title(artist_part)
                        score = similarity_score(band_slug, artist_slug)
                        if score > band_match_score:
                            band_match_score = score
            
            # Combined score: piece matching is primary, band matching is crucial for disambiguation
            # For test pieces where multiple bands perform the same piece, band matching is essential
            if band_match_score > 0.85:
                # Excellent band match: very likely the correct track
                combined_score = piece_match_score * 0.5 + band_match_score * 0.5
            elif band_match_score > 0.7:
                # Good band match: piece score + significant band bonus
                combined_score = piece_match_score * 0.6 + band_match_score * 0.4
            elif band_match_score > 0.5:
                # Moderate band match: piece score + moderate band bonus  
                combined_score = piece_match_score * 0.75 + band_match_score * 0.25
            elif band_match_score > 0.3:
                # Weak band match: heavily penalize to avoid wrong matches
                combined_score = piece_match_score * 0.5 + band_match_score * 0.1
            else:
                # Very weak or no band match: significant penalty
                combined_score = piece_match_score * 0.4
            
            if combined_score > best_score:
                best_score = combined_score
                best_match = track
        
        if best_match and best_score >= 0.65:
            best_match.match_score = best_score
            return best_match
        return None

    # ----------------------- Apple Music -----------------------

    def _get_apple_tracks_for_division(self, year: int, division: str) -> List[Track]:
        key = (year, division)
        if key in self._apple_album_cache:
            return self._apple_album_cache[key]
        if not self.apple_music:
            self._apple_album_cache[key] = []
            return []

        # Check if we should use album search caching (years >= 2012)
        use_album_cache = year >= 2012 and self.apple_music.cache is not None
        
        # Try to get cached album search results
        all_albums_from_searches: List[Dict] = []
        if use_album_cache:
            cached_albums = self.apple_music.cache.get_apple_album_search(year, division)
            if cached_albums:
                print(f"[apple] Album search cache HIT for {year}|{division} ({len(cached_albums)} albums)")
                all_albums_from_searches = cached_albums
        
        # If no cache hit, perform album searches
        if not all_albums_from_searches:
            seen_collections: set[int] = set()
            for term in resolve_album_search_terms(year, division, self.band_type):
                try:
                    albums = self.apple_music.search_album(term)
                    for album in albums:
                        collection_id = album.get("collectionId")
                        if not collection_id or collection_id in seen_collections:
                            continue
                        seen_collections.add(collection_id)
                        all_albums_from_searches.append(album)
                    
                    # Stop early if we have enough candidates
                    if len(all_albums_from_searches) >= 15:
                        break
                except Exception as e:
                    # Handle 403/404 gracefully
                    if "403" in str(e) or "404" in str(e):
                        print(f"[apple] Search failed for '{term}' (rate limited or not found), continuing...")
                        continue
                    raise
            
            # Cache the album search results if we got any
            if use_album_cache and all_albums_from_searches:
                self.apple_music.cache.set_apple_album_search(year, division, all_albums_from_searches)
                print(f"[apple] Album search cache WRITE for {year}|{division} ({len(all_albums_from_searches)} albums)")
        
        # Now score and filter the albums
        candidate_albums: List[Tuple[float, Dict]] = []  # (score, album)
        for album in all_albums_from_searches:
            score = score_album_relevance(album, year, division)
            candidate_albums.append((score, album))
        
        # Sort by score descending (best matches first)
        candidate_albums.sort(key=lambda x: x[0], reverse=True)
        
        # Filter: ONLY use albums from the target year
        # Check both release date and album name for the year
        filtered_albums = []
        for score, album in candidate_albums:
            release_date = album.get("releaseDate") or ""
            collection_name = album.get("collectionName") or ""
            album_name_lower = collection_name.lower()
            
            # Extract release year
            release_year = None
            if isinstance(release_date, str) and len(release_date) >= 4:
                try:
                    release_year = int(release_date[:4])
                except ValueError:
                    pass
            
            # Only include albums from the target year
            if release_year == year or str(year) in album_name_lower:
                filtered_albums.append((score, album))
                # Remember this album name for future searches
                if collection_name:
                    self._discovered_album_names.setdefault((year, "apple"), set()).add(collection_name)
        
        # Collect tracks from filtered albums, deduplicating by track ID
        tracks: List[Track] = []
        seen_track_ids: set[int] = set()
        
        for score, album in filtered_albums:
            collection_id = album.get("collectionId")
            collection_name = album.get("collectionName")
            
            # Skip albums with very low relevance scores
            if score < 10:
                continue
            
            # Fetch tracks from this album
            cache_key = str(collection_id)
            cached_tracks = self.apple_music.cache.get_apple_album_tracks(cache_key) if self.apple_music and self.apple_music.cache else None
            if cached_tracks is not None:
                songs = cached_tracks
            else:
                songs = self.apple_music.lookup_album_tracks(collection_id)
                if self.apple_music and self.apple_music.cache and songs is not None:
                    self.apple_music.cache.set_apple_album_tracks(cache_key, songs)
            
            for song in songs:
                track_id = song.get("trackId")
                if track_id and track_id in seen_track_ids:
                    continue
                if track_id:
                    seen_track_ids.add(track_id)
                
                title = song.get("trackName")
                url = song.get("trackViewUrl")
                if not title or not url:
                    continue
                
                # Extract artist name, filtering out placeholder values
                artist_raw = song.get("artistName") or ""
                artist = artist_raw if artist_raw.strip().lower() not in ["", "na", "n/a", "unknown"] else ""
                
                slug_primary = normalize_title(title)
                slug_full = normalize_title(title, remove_parentheticals=False)
                slug_variants = []
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
                        album=collection_name or "",
                        album_id=str(collection_id),
                        artist=artist,
                    )
                )

        self._apple_album_cache[key] = tracks
        return tracks

    def match_apple(self, performance: Performance) -> Optional[Track]:
        tracks = self._get_apple_tracks_for_division(performance.year, performance.division)
        if not tracks:
            return None
        piece_variants = get_title_variants(performance.piece)
        band_slug = normalize_title(performance.band)
        
        best_match: Optional[Track] = None
        best_score = 0.0
        
        for track in tracks:
            # Calculate piece similarity using all variants
            piece_match_score = 0.0
            for piece_variant in piece_variants:
                for slug_variant in track.slug_variants:
                    score = similarity_score(piece_variant, slug_variant)
                    if score > piece_match_score:
                        piece_match_score = score
            
            # Calculate band/artist similarity if artist info is available
            # Check against all individual artists in the track, not just the combined string
            band_match_score = 0.0
            if track.artist and band_slug:
                # Split on comma to check each artist separately
                # (since tracks can have composer, "Na", band, conductor)
                artist_parts = [part.strip() for part in track.artist.split(',')]
                for artist_part in artist_parts:
                    if artist_part:
                        artist_slug = normalize_title(artist_part)
                        score = similarity_score(band_slug, artist_slug)
                        if score > band_match_score:
                            band_match_score = score
            
            # Combined score: piece matching is primary, band matching is crucial for disambiguation
            # For test pieces where multiple bands perform the same piece, band matching is essential
            if band_match_score > 0.85:
                # Excellent band match: very likely the correct track
                combined_score = piece_match_score * 0.5 + band_match_score * 0.5
            elif band_match_score > 0.7:
                # Good band match: piece score + significant band bonus
                combined_score = piece_match_score * 0.6 + band_match_score * 0.4
            elif band_match_score > 0.5:
                # Moderate band match: piece score + moderate band bonus  
                combined_score = piece_match_score * 0.75 + band_match_score * 0.25
            elif band_match_score > 0.3:
                # Weak band match: heavily penalize to avoid wrong matches
                combined_score = piece_match_score * 0.5 + band_match_score * 0.1
            else:
                # Very weak or no band match: significant penalty
                combined_score = piece_match_score * 0.4
            
            if combined_score > best_score:
                best_score = combined_score
                best_match = track
        
        if best_match and best_score >= 0.65:
            best_match.match_score = best_score
            return best_match
        return None


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
    matches: List[StreamingMatch] = []
    for performance in performances:
        matches.append(
            StreamingMatch(
                performance=performance,
                spotify=finder.match_spotify(performance) if finder.spotify else None,
                apple_music=finder.match_apple(performance) if finder.apple_music else None,
            )
        )

    serialised: List[Dict[str, object]] = []
    for match in matches:
        if not (match.spotify or match.apple_music):
            continue
        entry_dict: Dict[str, object] = match.to_dict()
        override = override_resolver.lookup(match.performance)
        allow_mismatch = False
        if override:
            allow_mismatch = bool(override.get("allow_album_mismatch"))
            for key, value in override.items():
                if key == "allow_album_mismatch":
                    continue
                entry_dict[key] = value

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
    
    # If using division filter, merge with existing entries
    if divisions_filter:
        existing_entries: List[Dict[str, object]] = []
        if year_path.exists():
            try:
                existing_data = json.loads(year_path.read_text(encoding="utf-8"))
                if isinstance(existing_data, dict):
                    existing_entries = existing_data.get("entries", [])
                elif isinstance(existing_data, list):
                    existing_entries = existing_data
            except (json.JSONDecodeError, IOError):
                pass
        
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

    finder = StreamingLinkFinder(spotify=spotify_client, apple_music=apple_client, band_type=band_type)

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
    
    total_entries = 0
    for year in track(sorted(year_map.keys()), description="Matching streaming links"):
        year_performances = year_map[year]
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

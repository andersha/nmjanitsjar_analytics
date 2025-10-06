import math
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nmjanitsjar_scraper.streaming_search import (
    AlbumMetadata,
    Performance,
    StreamingLinkFinder,
    Track,
    normalize_title,
    performance_key,
)


class StubAlbumCatalog:
    def __init__(self, candidates, winners=None):
        self._candidates = candidates
        self._winners = winners or []

    def get_album_candidates(self, platform, year, division):
        return self._candidates

    def get_winners_albums(self, platform, year):
        return self._winners


def _make_track(title: str, artist: str, album_id: str, album_name: str) -> Track:
    slug_primary = normalize_title(title)
    slug_full = normalize_title(title, remove_parentheticals=False)
    variants = [slug_primary]
    if slug_full and slug_full not in variants:
        variants.append(slug_full)
    return Track(
        platform="spotify",
        title=title,
        slug=variants[0],
        slug_variants=variants,
        url=f"https://example.com/{album_id}/{slug_primary}",
        album=album_name,
        album_id=album_id,
        artist=artist,
    )


def _setup_finder(album_metadata, tracks_per_album):
    finder = StreamingLinkFinder(spotify=object(), apple_music=None, cache=None, band_type="brass")
    finder.album_catalog = StubAlbumCatalog(candidates=[(150.0, album_metadata)])

    def fake_fetch(platform: str, metadata: AlbumMetadata):
        base_tracks = tracks_per_album[metadata.album_id]
        return [replace(track, match_score=0.0) for track in base_tracks]

    finder._get_tracks_for_album = fake_fetch  # type: ignore[assignment]
    return finder


def test_album_matching_assigns_unique_tracks():
    album = AlbumMetadata(
        platform="spotify",
        album_id="album-2024-1",
        name="NM Brass 2024 – 1. div",
        release_year=2024,
        band_type="brass",
    )
    tracks = [
        _make_track("Fenring Dances - Live", "Band A", album.album_id, album.name),
        _make_track("Sinfonietta No. 3 - Live", "Band B", album.album_id, album.name),
    ]
    finder = _setup_finder(album, {album.album_id: tracks})

    performances = [
        Performance(year=2024, division="1. divisjon", band="Band A", piece="Fenring Dances"),
        Performance(year=2024, division="1. divisjon", band="Band B", piece="Sinfonietta No. 3"),
    ]

    matches = finder.build_links(performances)
    match_map = {performance_key(match.performance): match for match in matches}

    assert match_map[performance_key(performances[0])].spotify.title == "Fenring Dances - Live"
    assert match_map[performance_key(performances[1])].spotify.title == "Sinfonietta No. 3 - Live"
    assert match_map[performance_key(performances[0])].spotify.match_score >= 0.95


def test_album_matching_uses_band_for_test_pieces():
    album = AlbumMetadata(
        platform="spotify",
        album_id="album-elite",
        name="NM Brass 2025 – Elitedivisjon",
        release_year=2025,
        band_type="brass",
    )
    tracks = [
        _make_track("CATHARSIS: Band A - Live", "Band A", album.album_id, album.name),
        _make_track("CATHARSIS: Band B - Live", "Band B", album.album_id, album.name),
    ]
    finder = _setup_finder(album, {album.album_id: tracks})

    performances = [
        Performance(year=2025, division="Elite", band="Band A", piece="CATHARSIS", is_test_piece=True),
        Performance(year=2025, division="Elite", band="Band B", piece="CATHARSIS", is_test_piece=True),
    ]

    matches = finder.build_links(performances)
    match_map = {performance_key(match.performance): match for match in matches}

    assert match_map[performance_key(performances[0])].spotify.title == "CATHARSIS: Band A - Live"
    assert match_map[performance_key(performances[1])].spotify.title == "CATHARSIS: Band B - Live"
    assert match_map[performance_key(performances[0])].spotify.match_score > 0.7


def test_winners_album_only_matches_rank_one():
    album = AlbumMetadata(
        platform="spotify",
        album_id="album-2011-winners",
        name="NM Brass 2011 – Vinnere",
        release_year=2011,
        band_type="brass",
        is_winners_album=True,
    )
    tracks = [
        _make_track("Journey of the Lone Wolf", "Winner Band", album.album_id, album.name),
    ]
    finder = StreamingLinkFinder(spotify=object(), apple_music=None, cache=None, band_type="brass")
    finder.album_catalog = StubAlbumCatalog(candidates=[], winners=[album])

    def fake_fetch(platform: str, metadata: AlbumMetadata):
        return [replace(track, match_score=0.0) for track in tracks]

    finder._get_tracks_for_album = fake_fetch  # type: ignore[assignment]

    winner = Performance(year=2011, division="1. divisjon", band="Winner Band", piece="Journey of the Lone Wolf", rank=1)
    runner_up = Performance(year=2011, division="1. divisjon", band="Runner Band", piece="Another Piece", rank=2)

    matches = finder.build_links([winner, runner_up])
    match_map = {performance_key(match.performance): match for match in matches}

    assert match_map[performance_key(winner)].spotify.title == "Journey of the Lone Wolf"
    assert match_map[performance_key(runner_up)].spotify is None

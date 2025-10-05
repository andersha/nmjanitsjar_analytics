#!/usr/bin/env python3
"""Fetch tracks from a specific Spotify album and optionally add to cache."""

import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from nmjanitsjar_scraper.streaming_search import SpotifyClient, StreamingCache

def main():
    import sys
    album_id = sys.argv[1] if len(sys.argv) > 1 else "0ppXmxegupzbOa7ALzy6VO"
    
    # Load credentials
    creds_path = Path("config/streaming_credentials.json")
    if not creds_path.exists():
        print(f"❌ Credentials file not found: {creds_path}")
        return
    
    creds = json.loads(creds_path.read_text())
    client_id = creds.get("spotify_client_id")
    client_secret = creds.get("spotify_client_secret")
    
    if not client_id or not client_secret:
        print("❌ Missing Spotify credentials in config file")
        return
    
    # Initialize cache
    cache_path = Path("config/streaming_cache.json")
    cache = StreamingCache(cache_path)
    
    # Initialize Spotify client
    print(f"🔑 Authenticating with Spotify...")
    spotify = SpotifyClient(client_id, client_secret, cache=cache)
    
    # Fetch album info first
    print(f"📀 Fetching album: https://open.spotify.com/album/{album_id}")
    try:
        album_response = spotify._get(f"/albums/{album_id}")
        album_data = album_response.json()
        album_name = album_data.get("name", "Unknown Album")
        release_date = album_data.get("release_date", "Unknown")
        print(f"   Album: {album_name}")
        print(f"   Release Date: {release_date}")
    except Exception as e:
        print(f"❌ Error fetching album info: {e}")
        return
    
    # Fetch tracks
    print(f"\n🎵 Fetching tracks...")
    try:
        tracks = spotify.get_album_tracks(album_id)
        print(f"   Found {len(tracks)} tracks\n")
        
        # Display tracks
        print("Tracks:")
        print("-" * 80)
        for i, track in enumerate(tracks, 1):
            track_name = track.get("name", "Unknown")
            artists = track.get("artists", [])
            artist_names = [a.get("name") for a in artists if a.get("name")]
            artist_str = ", ".join(artist_names) if artist_names else "Unknown Artist"
            track_url = track.get("external_urls", {}).get("spotify", "")
            print(f"{i:2}. {track_name}")
            print(f"    Artist: {artist_str}")
            print(f"    URL: {track_url}")
            print()
        
        # Add to cache
        print(f"💾 Adding {len(tracks)} tracks to cache...")
        cache.set_spotify_album_tracks(album_id, tracks)
        cache.save()
        print(f"✅ Cache updated: {cache_path}")
        
    except Exception as e:
        print(f"❌ Error fetching tracks: {e}")
        import traceback
        traceback.print_exc()
        return

if __name__ == "__main__":
    main()

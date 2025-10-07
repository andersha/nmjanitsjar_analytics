#!/usr/bin/env python3
"""
Export WindRep cache data to JSON format for the band-positions app.
"""

import json
import re
from pathlib import Path
from collections import defaultdict

CACHE_FILE = Path("data/windrep_year_cache.json")
OUTPUT_FILE = Path("apps/band-positions/public/data/repertoire.json")

def parse_duration_to_minutes(duration_str):
    """Parse duration string to minutes (float)."""
    if not duration_str or duration_str == "Unknown":
        return None
    
    # Format: "MM:SS" or just "MM"
    if ':' in duration_str:
        parts = duration_str.split(':')
        if len(parts) == 2:
            try:
                minutes = int(parts[0])
                seconds = int(parts[1])
                return minutes + (seconds / 60.0)
            except ValueError:
                return None
    else:
        # Just minutes
        try:
            return float(duration_str)
        except ValueError:
            return None
    return None

def parse_difficulty(difficulty_str):
    """Parse difficulty Roman numeral to integer (1-7)."""
    if not difficulty_str:
        return None
    
    # Map Roman numerals to integers
    roman_map = {
        'I': 1,
        'II': 2,
        'III': 3,
        'IV': 4,
        'V': 5,
        'VI': 6,
        'VII': 7
    }
    
    difficulty_upper = difficulty_str.strip().upper()
    return roman_map.get(difficulty_upper)

def extract_year_from_url(url):
    """Extract year from WindRep URL if it's from a category page."""
    if not url:
        return None
    
    # Try to extract year from URL patterns
    # URLs like "https://www.windrep.org/Some_Piece" don't have year
    # We'll need to get year from the cache key instead
    return None

def main():
    """Export repertoire data to JSON."""
    print("🎵 Exporting WindRep repertoire data...")
    
    # Load cache
    if not CACHE_FILE.exists():
        print(f"❌ Cache file not found: {CACHE_FILE}")
        return
    
    with open(CACHE_FILE, 'r', encoding='utf-8') as f:
        cache = json.load(f)
    
    # Build year index from category entries
    piece_years = defaultdict(set)
    for key, value in cache.items():
        if key.startswith('category:'):
            year = key.split(':')[1]
            if value and isinstance(value, list):
                for piece_url in value:
                    piece_years[piece_url].add(int(year))
    
    # Extract pieces
    pieces = []
    for key, value in cache.items():
        if not key.startswith('piece:') or not value:
            continue
        
        piece_url = key.replace('piece:', '')
        
        # Get years this piece appears in
        years = sorted(list(piece_years.get(piece_url, [])))
        
        # Parse duration
        duration_minutes = parse_duration_to_minutes(value.get('duration'))
        
        # Parse difficulty
        difficulty = parse_difficulty(value.get('difficulty'))
        
        piece_data = {
            'title': value.get('title', 'Unknown'),
            'composer': value.get('composer'),
            'duration': value.get('duration'),  # Original string format
            'duration_minutes': round(duration_minutes, 2) if duration_minutes else None,
            'difficulty': difficulty,
            'difficulty_roman': value.get('difficulty'),
            'url': value.get('url'),
            'years': years,
            'min_year': min(years) if years else None,
            'max_year': max(years) if years else None
        }
        
        pieces.append(piece_data)
    
    # Sort by title
    pieces.sort(key=lambda p: (p['title'].lower(), p.get('min_year', 9999)))
    
    # Create output structure
    output = {
        'pieces': pieces,
        'metadata': {
            'total_pieces': len(pieces),
            'generated_at': '2025-01-07T07:55:00Z',
            'source': 'windrep.org',
            'year_range': {
                'min': min((p['min_year'] for p in pieces if p['min_year']), default=None),
                'max': max((p['max_year'] for p in pieces if p['max_year']), default=None)
            },
            'difficulty_range': {
                'min': 1,
                'max': 7
            }
        }
    }
    
    # Save to file
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Exported {len(pieces)} pieces to {OUTPUT_FILE}")
    print(f"   Year range: {output['metadata']['year_range']['min']} - {output['metadata']['year_range']['max']}")
    print(f"   Pieces with duration: {sum(1 for p in pieces if p['duration_minutes'])}")
    print(f"   Pieces with difficulty: {sum(1 for p in pieces if p['difficulty'])}")
    print(f"   Pieces with years: {sum(1 for p in pieces if p['years'])}")

if __name__ == "__main__":
    main()

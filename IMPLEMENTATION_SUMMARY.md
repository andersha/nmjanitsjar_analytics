# Implementation Summary: Division Filtering & Apple Music Album Search Caching

## Overview
This implementation adds two major features to the streaming search script:
1. **Division Filtering**: Filter processing to specific divisions using simplified codes (E, 1-7)
2. **Apple Music Album Search Caching**: Cache album search results to reduce API rate limiting

## Changes Made

### 1. Division Filtering

#### New Constant: `DIVISION_CODE_MAP`
```python
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
```

#### New Function: `parse_divisions_argument()`
- Location: `src/nmjanitsjar_scraper/streaming_search.py` (around line 1299)
- Validates and converts division codes to full division names
- Accepts both codes (E, 1-7) and full names ("Elite", "1. divisjon", etc.)
- Deduplicates while preserving order
- Raises `ValueError` for invalid codes

#### CLI Argument: `--divisions`
- Accepts one or more division codes
- Example: `--divisions E 1 2` processes Elite, 1. divisjon, and 2. divisjon only
- If omitted, all divisions are processed (backward compatible)

#### Filtering Logic
- Added to `generate_streaming_links()` function
- Filters performances during year_map construction
- Logs which divisions are being processed when filter is active
- **Incremental updates**: When using `--divisions`, existing entries from other divisions are preserved
  - The script merges new entries with existing ones
  - Only entries for the specified divisions are replaced
  - Example: `--divisions 2` updates only "2. divisjon" while keeping Elite, 1, 3-7 intact

### 2. Apple Music Album Search Caching

#### StreamingCache Enhancements
**Data Structure** (line ~278):
```python
{
  "apple": {
    "album_tracks": { ... },  # existing
    "album_searches": {        # NEW
      "2023|2. divisjon": {
        "albums": [...],
        "fetched_at": 1690000000.0
      }
    }
  }
}
```

**New Methods**:
- `get_apple_album_search(year, division)` - Retrieve cached album search results
- `set_apple_album_search(year, division, albums)` - Store album search results

#### Caching Logic in `_get_apple_tracks_for_division()`
1. **Cache Check** (year >= 2012 only):
   - Checks cache before making any API calls
   - Logs cache HIT with album count

2. **Cache Miss Flow**:
   - Performs normal album searches
   - Handles 403/404 errors gracefully (rate limiting)
   - Deduplicates albums by collectionId

3. **Cache Write**:
   - Stores results only for years >= 2012
   - Only caches non-empty results
   - Logs cache WRITE with album count

#### Why Years >= 2012?
- Albums from 2012 onwards are division-specific
- Earlier albums are "collection albums" with mixed content
- Prevents cache pollution with irrelevant data

### 3. Logging Improvements
- `[apple] Album search cache HIT for {year}|{division} ({count} albums)`
- `[apple] Album search cache WRITE for {year}|{division} ({count} albums)`
- `[apple] Search failed for '{term}' (rate limited or not found), continuing...`
- `[cyan]Processing divisions: {division_list}[/cyan]`

## Usage Examples

### Process a Single Division
```bash
python -m src.nmjanitsjar_scraper.streaming_search \
  --positions apps/band-positions/public/data/band_positions.json \
  --output-dir apps/band-positions/public/data/streaming \
  --aggregate apps/band-positions/public/data/piece_streaming_links.json \
  --years 2023 \
  --divisions 2 \
  --min-year 2012 \
  --band-type wind \
  --credentials config/streaming_credentials.json \
  --overrides config/streaming_overrides.json \
  --cache config/streaming_cache.json
```

### Process Multiple Divisions
```bash
python -m src.nmjanitsjar_scraper.streaming_search \
  --positions apps/band-positions/public/data/band_positions.json \
  --output-dir apps/band-positions/public/data/streaming \
  --aggregate apps/band-positions/public/data/piece_streaming_links.json \
  --years 2023 \
  --divisions E 1 2 3 \
  --min-year 2012 \
  --band-type wind \
  --credentials config/streaming_credentials.json \
  --overrides config/streaming_overrides.json \
  --cache config/streaming_cache.json
```

### Process All Divisions (Default Behavior)
```bash
python -m src.nmjanitsjar_scraper.streaming_search \
  --positions apps/band-positions/public/data/band_positions.json \
  --output-dir apps/band-positions/public/data/streaming \
  --aggregate apps/band-positions/public/data/piece_streaming_links.json \
  --years 2023 \
  --min-year 2012 \
  --band-type wind \
  --credentials config/streaming_credentials.json \
  --overrides config/streaming_overrides.json \
  --cache config/streaming_cache.json
```

## Important: Division Filter Behavior

⚠️ **Incremental Updates (Fixed)**

When using `--divisions`, the script now **merges** entries instead of overwriting:

**Before the fix** (❌ Bug):
```bash
# Running this would DELETE all other divisions!
--divisions 2  # Would remove Elite, 1, 3-7 from 2023.json
```

**After the fix** (✅ Correct):
```bash
# Running this preserves other divisions
--divisions 2  # Only updates 2. divisjon, keeps all others
```

**How it works:**
1. Loads existing year file (e.g., `2023.json`)
2. Removes entries for filtered divisions (e.g., "2. divisjon")
3. Adds new entries for those divisions
4. Merges and sorts all entries
5. Saves back to file

**Use cases:**
- Fix a single missing link: `--divisions 3`
- Update multiple divisions: `--divisions 1 2 3`
- Complete refresh: Omit `--divisions` (processes all)

## Benefits

### 1. Reduced API Traffic
- **Before**: Every run searches Apple Music for all albums across all search terms
- **After**: Subsequent runs for the same year/division use cached results
- **Impact**: Dramatically reduces 403 Forbidden rate limit errors

### 2. Faster Processing
- Cache hits are instant (no network latency)
- Especially beneficial when re-running after errors or for fixes

### 3. Targeted Processing
- Fix a single missing link without processing all 8 divisions
- Test changes on a subset of divisions
- Reduces load on both Spotify and Apple Music APIs

### 4. Backward Compatible
- Omitting `--divisions` processes all divisions as before
- Existing cache files work seamlessly (backward compatible structure)
- No breaking changes to existing workflows

## Cache Management

### Viewing Cache Contents
```bash
cat config/streaming_cache.json | jq '.apple.album_searches'
```

### Clearing Cache for a Specific Year/Division
Edit `config/streaming_cache.json` and remove the specific key:
```json
{
  "apple": {
    "album_searches": {
      "2023|2. divisjon": { ... }  // Remove this entry
    }
  }
}
```

### Full Cache Reset
Delete or backup the cache file:
```bash
mv config/streaming_cache.json config/streaming_cache.json.bak
```

## Testing Recommendations

1. **Test Single Division**:
   - Run with `--divisions 2` for 2023
   - Verify only "2. divisjon" is processed
   - Check for cache WRITE messages

2. **Test Cache Hit**:
   - Re-run the same command
   - Verify cache HIT messages appear
   - Confirm no Apple Music API calls are made

3. **Test Invalid Code**:
   - Run with `--divisions 9`
   - Verify helpful error message

4. **Test Pre-2012 Year**:
   - Run with `--years 2011`
   - Verify cache is NOT used (no HIT/WRITE messages)

5. **Test Backward Compatibility**:
   - Run without `--divisions` argument
   - Verify all divisions are processed

## Known Limitations

1. **Year Restriction**: Script still requires single year processing (`len(target_years) == 1`)
2. **Cache Invalidation**: No automatic cache expiration (manual management required)
3. **Spotify**: Album search caching not yet implemented for Spotify (only Apple Music)

## Future Enhancements

1. Consider adding Spotify album search caching
2. Add cache expiration/TTL mechanism
3. Add `--clear-cache` CLI option
4. Support multi-year processing with division filter
5. Add cache statistics (`--cache-stats`)

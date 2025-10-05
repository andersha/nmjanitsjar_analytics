# Cache File Management

## Overview

The streaming search feature uses a cache file (`config/streaming_cache.json`) to store:
- Album track listings from Spotify and Apple Music
- Album search results from Apple Music (for years ≥ 2012)

This dramatically reduces API calls and prevents rate limiting issues.

## Why the Cache File is NOT in Git

### Problem
The cache file has several characteristics that make it unsuitable for version control:

1. **Size**: Can grow to 8+ MB (272,504 lines in some cases)
2. **Frequency**: Changes on every run
3. **Machine-specific**: Contains local API response data
4. **No collaborative value**: Each developer/machine should maintain their own cache
5. **Noise**: Would create massive, meaningless diffs in pull requests

### Solution
The cache file is now:
- ✅ Ignored by git (via `.gitignore`)
- ✅ Created automatically on first run
- ✅ Maintained locally per machine
- ✅ Documented with an example template

## File Locations

```
config/
├── streaming_cache.json          # Local only (ignored by git)
├── streaming_cache.json.example  # Tracked template
└── streaming_credentials.json    # Local only (ignored by git)
```

## Setup for New Developers

When cloning the repository, the cache file won't exist. It will be created automatically on first run of the streaming search script.

**Optional manual creation:**
```bash
cp config/streaming_cache.json.example config/streaming_cache.json
```

## Cache Structure

```json
{
  "spotify": {
    "album_tracks": {
      "album_id_123": {
        "tracks": [...],
        "fetched_at": 1690000000.0
      }
    }
  },
  "apple": {
    "album_tracks": {
      "collection_id_456": {
        "tracks": [...],
        "fetched_at": 1690000000.0
      }
    },
    "album_searches": {
      "2023|2. divisjon": {
        "albums": [...],
        "fetched_at": 1690000000.0
      }
    }
  }
}
```

## Cache Management

### View Cache Contents
```bash
# View entire cache
cat config/streaming_cache.json | jq '.'

# View Apple Music album searches only
cat config/streaming_cache.json | jq '.apple.album_searches'

# View Spotify album tracks only
cat config/streaming_cache.json | jq '.spotify.album_tracks'

# Check cache file size
ls -lh config/streaming_cache.json
```

### Clear Specific Cache Entries

**Option 1: Manual editing**
1. Open `config/streaming_cache.json` in an editor
2. Remove specific keys (e.g., `"2023|2. divisjon"` under `apple.album_searches`)
3. Save the file

**Option 2: Using jq**
```bash
# Remove a specific album search cache entry
jq 'del(.apple.album_searches["2023|2. divisjon"])' \
  config/streaming_cache.json > config/streaming_cache.json.tmp
mv config/streaming_cache.json.tmp config/streaming_cache.json
```

### Full Cache Reset
```bash
# Backup current cache (optional)
cp config/streaming_cache.json config/streaming_cache.json.backup

# Delete cache (will be recreated on next run)
rm config/streaming_cache.json

# Or reset to empty template
cp config/streaming_cache.json.example config/streaming_cache.json
```

## Cache Benefits

### Before Caching
- Every run makes full API calls to Apple Music and Spotify
- Rate limits hit quickly (especially Apple Music)
- 403 Forbidden errors common
- Slow processing times

### After Caching
- Subsequent runs use cached data
- Minimal API calls (only for new data)
- Dramatically reduced rate limiting
- Fast processing (instant cache hits)

## Cache Invalidation Strategy

**Current approach: Manual**
- No automatic expiration
- Cache entries persist indefinitely
- Manual cleanup as needed

**Why manual?**
- Competition data doesn't change frequently
- Albums and tracks are relatively stable
- Prevents unnecessary re-fetching
- Developer has full control

**When to clear cache:**
- Albums/tracks updated on streaming services
- Switching between different competition years
- Testing cache implementation
- Disk space concerns

## Git Configuration

**.gitignore entry:**
```gitignore
# Local credentials and cache files
config/streaming_credentials.json
config/streaming_cache.json
```

**What IS tracked:**
```
config/streaming_cache.json.example    ✅ Template file
config/streaming_overrides.json       ✅ Manual overrides (shared)
```

**What is NOT tracked:**
```
config/streaming_cache.json            ❌ Machine-specific cache
config/streaming_credentials.json      ❌ API credentials
```

## Migration from Tracked to Untracked

If you had the cache file tracked before:

```bash
# Remove from git tracking (keeps local file)
git rm --cached config/streaming_cache.json

# Add to .gitignore
echo "config/streaming_cache.json" >> .gitignore

# Commit the change
git add .gitignore
git commit -m "chore: Move streaming_cache.json to gitignore"
```

## Best Practices

1. **Never commit the cache file**
   - It's already in `.gitignore`
   - If accidentally staged, unstage it immediately

2. **Keep credentials separate**
   - `streaming_credentials.json` is also ignored
   - Never commit API keys

3. **Share overrides, not cache**
   - `streaming_overrides.json` is tracked (manual corrections)
   - Cache is generated locally

4. **Backup before major changes**
   - Cache can take time to rebuild
   - Keep a backup during testing

5. **Monitor cache size**
   - Check occasionally: `ls -lh config/streaming_cache.json`
   - Consider clearing old entries if >10MB

## Troubleshooting

### Cache file doesn't exist
**Normal**: It's created automatically on first run. No action needed.

### Cache file is huge (>20MB)
**Solution**: Clear old entries or reset:
```bash
rm config/streaming_cache.json
```

### Git wants to commit cache file
**Check**: Is it in `.gitignore`?
```bash
grep "streaming_cache.json" .gitignore
```

If missing, add it:
```bash
echo "config/streaming_cache.json" >> .gitignore
```

### Cache seems corrupted
**Solution**: Delete and let it regenerate:
```bash
rm config/streaming_cache.json
# Run streaming search - cache will be recreated
```

## Performance Impact

**Cache file size vs. performance:**
- 1-5 MB: Normal, good performance
- 5-10 MB: Still fine, consider occasional cleanup
- 10-20 MB: Large but functional, cleanup recommended
- 20+ MB: Clean up old entries to improve load time

**JSON parsing time:**
- Small (1 MB): <0.1 seconds
- Medium (5 MB): ~0.2-0.5 seconds
- Large (10 MB): ~0.5-1 second
- Very large (20+ MB): >1 second

For most use cases, even a 10MB cache loads quickly and saves minutes of API calls.

---

*Last updated: October 2025*

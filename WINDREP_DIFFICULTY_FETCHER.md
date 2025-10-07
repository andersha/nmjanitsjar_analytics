# WindRep Difficulty Fetcher

A command-line tool to fetch and filter wind band repertoire pieces from [WindRep.org](https://www.windrep.org) by year and difficulty rating.

## Overview

This script scrapes piece information from WindRep.org's year-based category pages and filters pieces by their difficulty rating (Grade I-VI). It extracts:

- **Title**: The name of the piece
- **Composer**: The composer/arranger
- **Duration**: Performance duration (in MM:SS format)
- **Difficulty**: Grade level (Roman numerals I-VI)
- **URL**: Link to the piece's WindRep.org page

## Features

✨ **Smart Pagination**: Automatically handles multi-page categories (e.g., 443 pieces across 3 pages for 2024)

📦 **Intelligent Caching**: Caches fetched data to avoid redundant requests

🎨 **Rich Terminal Output**: Beautiful formatted tables with color-coded information

💾 **CSV Export**: Optional export to CSV for further analysis

⚡ **Rate Limiting**: Respectful 0.7s delay between requests

🔄 **Cache Management**: `--clear-cache` flag to refresh stale data

## Installation

No additional installation required beyond the project's existing dependencies:

```bash
# All dependencies are already in pyproject.toml
poetry install
```

Required packages:
- `click` - CLI interface
- `requests` - HTTP requests
- `beautifulsoup4` - HTML parsing
- `rich` - Terminal formatting

## Usage

### Basic Usage

Fetch all Grade III pieces from 2024:

```bash
python fetch_windrep_by_difficulty.py --year 2024 --difficulty 3
```

### With CSV Export

Export results to a CSV file:

```bash
python fetch_windrep_by_difficulty.py --year 2024 --difficulty 3 --export grade3_2024.csv
```

### Clear Cache

Force refresh of cached data (useful when WindRep.org is updated):

```bash
python fetch_windrep_by_difficulty.py --year 2024 --difficulty 1 --clear-cache
```

### All Options

```bash
python fetch_windrep_by_difficulty.py --help
```

## Command-Line Options

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| `--year` | integer | ✓ | Year to fetch pieces from (e.g., 2024) |
| `--difficulty` | 1-6 | ✓ | Difficulty level (1=I, 2=II, 3=III, 4=IV, 5=V, 6=VI) |
| `--export` | path | ✗ | Export results to CSV file |
| `--clear-cache` | flag | ✗ | Clear cached data before fetching |

## Output Format

### Terminal Output

```
🎵 WindRep Difficulty Fetcher
Year: 2024, Difficulty: 3 (III)

🌐 Fetching category page for year 2024...
  Fetching page 1...
    Found 200 pieces on page 1
  Fetching page 2...
    Found 200 pieces on page 2
  Fetching page 3...
    Found 43 pieces on page 3
✓ Found 443 pieces in category 2024 (3 page(s))

📖 Fetching metadata for 443 pieces...
Fetching pieces... ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 0:05:12
✓ Successfully fetched metadata for 443 pieces

🔍 Filtering by difficulty III...

┏━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Title                    ┃ Composer         ┃ Duration ┃ URL                         ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Balatro                  │ Minoo Dixon      │     3:55 │ https://www.windrep.org/... │
│ ...                      │ ...              │      ... │ ...                         │
└──────────────────────────┴──────────────────┴──────────┴─────────────────────────────┘

Total: 22 piece(s)

✓ Found 22 piece(s) with difficulty level 3
```

### CSV Output

The CSV file contains the following columns:

```csv
title,composer,duration,difficulty,url
Balatro,Minoo Dixon,3:55,III,https://www.windrep.org/Balatro
Amaranthus,Satoshi Yagisawa,4:40,III,https://www.windrep.org/Amaranthus
...
```

## How It Works

1. **Category Fetching**: Fetches the WindRep.org category page for the specified year (e.g., `/Category:2024`)
2. **Pagination Handling**: Automatically follows "next page" links to retrieve all pieces (200 per page)
3. **Metadata Extraction**: Visits each piece's individual page to extract:
   - Title from page header
   - Composer from meta description
   - Duration from "General Info" section (supports formats like "c. 3:55" or "10 minutes")
   - Difficulty from "Difficulty: III" field
4. **Filtering**: Filters pieces by the requested difficulty level (Roman numeral I-VI)
5. **Display**: Shows results in a formatted table
6. **Export** (optional): Writes filtered results to CSV

## Caching Strategy

### Cache Location

```
data/windrep_year_cache.json
```

### Cache Structure

```json
{
  "category:2024": ["/Balatro", "/Amaranthus", ...],
  "piece:/Balatro": {
    "title": "Balatro",
    "composer": "Minoo Dixon",
    "duration": "3:55",
    "difficulty": "III",
    "url": "https://www.windrep.org/Balatro"
  },
  ...
}
```

### Cache Benefits

- **Speed**: Subsequent runs with the same year use cached data (< 1 second vs. 5+ minutes)
- **Politeness**: Reduces load on WindRep.org servers
- **Reliability**: Works even if WindRep.org is temporarily unavailable

### When to Clear Cache

Use `--clear-cache` when:
- WindRep.org has been updated with new pieces for the year
- You suspect cached data is stale or incorrect
- You want to re-fetch all metadata

## Examples

### Example 1: Find Easy Pieces (Grade I)

```bash
python fetch_windrep_by_difficulty.py --year 2024 --difficulty 1
```

### Example 2: Find Advanced Pieces with Export

```bash
python fetch_windrep_by_difficulty.py --year 2023 --difficulty 6 --export grade6_2023.csv
```

### Example 3: Refresh 2024 Data

```bash
python fetch_windrep_by_difficulty.py --year 2024 --difficulty 3 --clear-cache
```

### Example 4: Survey Multiple Difficulties

```bash
# Create exports for each difficulty level
for i in {1..6}; do
  python fetch_windrep_by_difficulty.py --year 2024 --difficulty $i --export grade${i}_2024.csv
done
```

## Performance

### First Run (No Cache)
- **Time**: ~5-10 minutes for 443 pieces
  - Category fetching: ~3-5 seconds (with pagination)
  - Metadata extraction: ~0.7s per piece × 443 = ~5 minutes
- **Requests**: 1 + 3 (pagination) + 443 (pieces) = 447 total requests

### Subsequent Runs (Cached)
- **Time**: < 1 second
- **Requests**: 0 (all data from cache)

## Rate Limiting

The script includes respectful rate limiting:
- **0.7 seconds** between piece metadata requests
- **0.7 seconds** between pagination requests
- Proper User-Agent header: `Norwegian Band Competition Analyzer/1.0 (Research Project)`

## Error Handling

The script gracefully handles:
- **Network errors**: Logs warning and continues with next piece
- **Parsing errors**: Logs warning and skips malformed pages
- **Missing data**: Shows "Unknown" for missing fields
- **Empty results**: Exits with status 1 if no pieces match criteria

## Exit Codes

- **0**: Success (found matching pieces)
- **1**: Warning (no pieces found matching criteria)
- **2**: Error (exception occurred)

## Integration with Existing Project

This script is designed to work alongside the existing `nmjanitsjar` project:

- **Separate cache file**: Uses `data/windrep_year_cache.json` (separate from `data/windrep_cache.json`)
- **Reuses dependencies**: Uses same packages (requests, beautifulsoup4, rich)
- **Similar patterns**: Follows same coding style and structure as `piece_analysis.py`
- **Runnable from root**: Can be executed from project root without additional setup

## Limitations

1. **Difficulty data quality**: Not all pieces on WindRep.org have difficulty ratings
2. **Duration formats**: Some pieces may have unconventional duration formats
3. **Composer extraction**: Relies on meta description which may not always be present
4. **MediaWiki structure**: Changes to WindRep.org's HTML structure may require updates

## Future Enhancements

Potential improvements:
- [ ] Multi-year batch processing
- [ ] Filtering by duration range
- [ ] Filtering by composer
- [ ] JSON export format
- [ ] Integration with main CLI (`cli.py`)
- [ ] Difficulty range filtering (e.g., grades 3-5)
- [ ] Publisher information extraction

## Related Files

- `fetch_windrep_by_difficulty.py` - Main CLI script
- `src/nmjanitsjar_scraper/difficulty_fetcher.py` - Core fetcher class
- `src/nmjanitsjar_scraper/piece_analysis.py` - Original WindRepScraper (for competition data)
- `data/windrep_year_cache.json` - Cache file

## Troubleshooting

### "No pieces found with difficulty X"

- Check that pieces from that year actually have difficulty ratings on WindRep.org
- Try a different difficulty level (3-5 are most common)
- Use `--clear-cache` to refresh data

### "Failed to fetch category page"

- Check internet connection
- Verify WindRep.org is accessible
- Check if site structure has changed

### Slow performance

- First run is always slow (5-10 minutes for 443 pieces)
- Subsequent runs should be instant (using cache)
- Use `--export` to save results for later analysis

### Cache is stale

- Use `--clear-cache` to force refresh
- Manually delete `data/windrep_year_cache.json`

## License

Part of the nmjanitsjar project - Norwegian Wind Band Orchestra Competition Data Scraper.

## Author

Created for analyzing wind band repertoire from WindRep.org (https://www.windrep.org).

---

For questions or issues, refer to the main project documentation or contact the maintainer.

# Repertoire Explorer Feature

A new page added to the band-positions app for browsing and filtering wind band repertoire from WindRep.org.

## Overview

The Repertoire Explorer displays **3,470 pieces** collected from WindRep.org spanning years 2016-2025, with comprehensive filtering and sorting capabilities.

## Features

### ✨ Search & Filter
- **Text Search**: Type-ahead search on title or composer
- **Duration Filter**: Min/max duration in minutes (e.g., 5-15 minutes)
- **Difficulty Filter**: Grade 1-7 (Roman numerals I-VII)
- **Year Filter**: Filter by year range (2016-2025)

### 📊 Table View
- **Sortable Columns**: Click any column header to sort
  - Title
  - Composer
  - Duration (MM:SS format)
  - Difficulty (Roman numerals)
  - Year range
- **Pagination**: Adjustable page sizes (20, 50, or 100 rows)
- **Links**: Direct links to WindRep.org for each piece

### 🎨 UI Features
- **Dark/Light Theme**: Respects app theme settings
- **Responsive Design**: Works on desktop and mobile
- **Sticky Header**: Table header remains visible when scrolling
- **Hover Effects**: Interactive row highlighting

## Data Coverage

From the 3,470 pieces in the database:
- **3,222 pieces** (93%) have duration information
- **1,985 pieces** (57%) have difficulty ratings
- **All pieces** have year information

## Usage

### Basic Search
1. Navigate to **Repertoar** tab (after Resultat)
2. Type in the search box to filter by title or composer
3. Switch between Title/Komponist using the dropdown

### Advanced Filtering
```
Example: Find intermediate pieces (Grade 3-4) that are 8-12 minutes long from recent years

1. Set Vanskelighetsgrad: Min=3, Maks=4
2. Set Varighet: Min=8, Maks=12
3. Set År: Fra=2020, Til=2025
4. Results automatically update
```

### Sorting
- Click column headers to sort
- Click again to reverse sort direction
- Current sort shown with ▲ (ascending) or ▼ (descending)

## Files Created

### Python Scripts
- `export_repertoire_data.py` - Exports WindRep cache to JSON format
- `fetch_windrep_by_difficulty.py` - Fetches pieces from WindRep.org by year/difficulty

### App Files
- `apps/band-positions/src/lib/RepertoireExplorer.svelte` - Main component (616 lines)
- `apps/band-positions/public/data/repertoire.json` - Data file (1.1 MB, 3,470 pieces)

### Updates
- `apps/band-positions/src/App.svelte` - Added repertoire view integration

## Data Structure

```json
{
  "pieces": [
    {
      "title": "Balatro",
      "composer": "Minoo Dixon",
      "duration": "3:55",
      "duration_minutes": 3.92,
      "difficulty": 3,
      "difficulty_roman": "III",
      "url": "https://www.windrep.org/Balatro",
      "years": [2024],
      "min_year": 2024,
      "max_year": 2024
    },
    ...
  ],
  "metadata": {
    "total_pieces": 3470,
    "year_range": { "min": 2016, "max": 2025 },
    "difficulty_range": { "min": 1, "max": 7 }
  }
}
```

## Workflow for Updating Data

When new pieces are added to WindRep.org:

```bash
# 1. Fetch new year data
python fetch_windrep_by_difficulty.py --year 2026 --difficulty 1
python fetch_windrep_by_difficulty.py --year 2026 --difficulty 2
# ... repeat for each difficulty level

# 2. Re-export to JSON
python export_repertoire_data.py

# 3. Rebuild app (data is automatically included)
cd apps/band-positions
npm run build
```

## Performance

- **Initial Load**: ~1-2 seconds (1.1 MB JSON file)
- **Filtering**: Instant (client-side)
- **Sorting**: Instant (client-side)
- **Pagination**: Instant (client-side)

All filtering and sorting happens in the browser, providing a responsive user experience.

## Example Queries

### Find easy pieces for beginners
- Vanskelighetsgrad: Min=1, Maks=2
- Varighet: Maks=5

### Find substantial works for advanced bands
- Vanskelighetsgrad: Min=5, Maks=7
- Varighet: Min=12

### Find pieces by specific composer
- Search field: Komponist
- Type: "Sparke" or "Ticheli" etc.

### Find recently added pieces
- År: Fra=2024, Til=2025

## Technical Details

### Component Architecture
- Built with **Svelte 5** (runes syntax)
- **Reactive state management** with `$state` and `$derived`
- **TypeScript** for type safety
- **Scoped CSS** for styling

### Filtering Logic
- All filters are combined with AND logic
- Empty filters are ignored
- Filters on missing data exclude those pieces

### Sorting Logic
- Default: Title (ascending)
- Secondary sort by year when titles match
- Pieces without data sort to the end

### Accessibility
- Semantic HTML
- ARIA labels where appropriate
- Keyboard navigation support
- Focus indicators

## Browser Compatibility

Tested and working on:
- ✅ Chrome/Edge (latest)
- ✅ Firefox (latest)
- ✅ Safari (latest)
- ✅ Mobile browsers (iOS Safari, Chrome Mobile)

## Future Enhancements

Potential improvements:
- [ ] Export filtered results to CSV
- [ ] Save filter presets
- [ ] Multi-select filtering (e.g., multiple composers)
- [ ] Advanced search (composer AND title)
- [ ] Piece comparison view
- [ ] Performance statistics integration
- [ ] Favorite/bookmark pieces
- [ ] Share filter URLs

## Known Limitations

1. **Duration Data**: 7% of pieces lack duration information
2. **Difficulty Data**: 43% of pieces lack difficulty ratings  
3. **Year Coverage**: Only 2016-2025 (limited by data collection)
4. **Composer Normalization**: Some composer names may have variations

## Troubleshooting

### "No pieces found"
- Check if filters are too restrictive
- Click "Nullstill" to reset all filters

### "Laster repertoar..." stuck
- Check browser console for errors
- Verify `repertoire.json` exists and is valid
- Clear browser cache and reload

### Incorrect data
- Re-run `export_repertoire_data.py` to regenerate from cache
- Check if WindRep.org cache is up to date

## Credits

- Data source: [WindRep.org](https://www.windrep.org)
- Integration: nmjanitsjar project
- UI Framework: Svelte 5 + TypeScript

---

For questions or issues, check the main project documentation or the WindRep Difficulty Fetcher docs (`WINDREP_DIFFICULTY_FETCHER.md`).

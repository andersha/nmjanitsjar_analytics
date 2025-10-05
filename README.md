# Norwegian Wind Band Orchestra Competition Data Scraper

🎺 A comprehensive data scraping and analytics application for Norwegian Wind Band Orchestra competition results from 1981-2025.

## Overview

This application scrapes, processes, and analyzes competition data from [nmjanitsjar.no](https://www.nmjanitsjar.no/), providing structured access to 40+ years of Norwegian wind band orchestra competition results. The data includes orchestra placements, conductor information, musical pieces performed, and scoring details across multiple divisions.

## Features

- **Automated Data Discovery**: Discovers and verifies URLs for all yearly competition results
- **JSON API Integration**: Efficiently extracts data from the site's JSON APIs instead of HTML parsing
- **Data Validation**: Uses Pydantic models for robust data validation and type safety
- **Multiple Export Formats**: Outputs to CSV and JSON formats for easy analysis and database integration
- **Built-in Analytics**: Provides statistical analysis and rich terminal-based reporting
- **Caching & Rate Limiting**: Respectful scraping with intelligent caching and rate limiting
- **Comprehensive CLI**: Full-featured command-line interface for all operations

## Data Coverage

- **Time Period**: 1981-2025 (41 years of data)
- **Total Competitions**: 1000+ orchestra placements across all years
- **Divisions**: Elite through 7th division (structure evolved over time)
- **Data Points**: Orchestra names, conductors, musical pieces, scores, rankings, and images

## Installation

### Prerequisites
- Python 3.10+
- Poetry (recommended) or pip

### Setup
```bash
# Clone or create project directory
cd nmjanitsjar

# Install Poetry (if not already installed)
curl -sSL https://install.python-poetry.org | python3 -

# Install dependencies
poetry install

# Or with pip
pip install -r requirements.txt
```

## Configuration

### Streaming Link Discovery (Optional)

If you want to use the streaming link discovery feature for Spotify and Apple Music:

1. **Create credentials file** (required for Spotify):
   ```bash
   cp config/streaming_credentials.json.example config/streaming_credentials.json
   ```
   Then edit `config/streaming_credentials.json` with your Spotify API credentials.

2. **Cache file setup** (automatic):
   - The cache file `config/streaming_cache.json` is created automatically on first run
   - This file is **not tracked in git** (machine-specific, can grow to 8+ MB)
   - If needed, you can create it manually:
     ```bash
     cp config/streaming_cache.json.example config/streaming_cache.json
     ```

3. **Cache management**:
   - View cache contents: `cat config/streaming_cache.json | jq '.apple.album_searches'`
   - Clear specific entries: Edit the JSON file and remove unwanted keys
   - Full reset: `rm config/streaming_cache.json` (will be recreated on next run)

**Note**: The cache significantly reduces API rate limiting by storing:
- Album track listings (Spotify & Apple Music)
- Album search results (Apple Music only, for years ≥ 2012)

## Quick Start

### Run Complete Pipeline
```bash
# Process all available years
poetry run python -m src.nmjanitsjar_scraper.cli pipeline

# Process specific years only
poetry run python -m src.nmjanitsjar_scraper.cli pipeline --years 2024 2025
```

### Individual Commands
```bash
# Discover available data URLs
poetry run python -m src.nmjanitsjar_scraper.cli urls

# Parse competition data
poetry run python -m src.nmjanitsjar_scraper.cli parse --all-years

# Export to CSV/JSON
poetry run python -m src.nmjanitsjar_scraper.cli export --all

# View analytics
poetry run python -m src.nmjanitsjar_scraper.cli stats --summary --top-orchestras 10
```

## CLI Commands

### `pipeline`
Runs the complete data processing pipeline:
```bash
poetry run python -m src.nmjanitsjar_scraper.cli pipeline [--years YEAR...] [--force-refresh]
```

### `urls`
Manage competition result URLs:
```bash
poetry run python -m src.nmjanitsjar_scraper.cli urls [--show] [--force-refresh]
```

### `parse` 
Parse competition data from JSON APIs:
```bash
poetry run python -m src.nmjanitsjar_scraper.cli parse [--year YEAR] [--all-years]
```

### `export`
Export processed data to files:
```bash
poetry run python -m src.nmjanitsjar_scraper.cli export [--all] [--years YEAR...] [--stats]
```

### `stats`
View analytics and statistics:
```bash
poetry run python -m src.nmjanitsjar_scraper.cli stats [--summary] [--top-orchestras N] [--conductors N] [--divisions] [--years]
```

## Data Schema

### Placements CSV Structure
- `id`: Unique placement identifier
- `year`: Competition year
- `division`: Division name (Elite, 1. divisjon, etc.)
- `rank`: Placement rank within division
- `orchestra`: Orchestra name
- `conductor`: Conductor name
- `pieces`: Musical pieces performed (semicolon-separated)
- `composers`: Composers (extracted from pieces, semicolon-separated)
- `points`: Score achieved
- `max_points`: Maximum possible score (100.0)
- `image_url`: Orchestra image URL (if available)

### Awards CSV Structure
- `id`: Unique award identifier
- `year`: Competition year
- `division`: Division name
- `award_type`: Type of award (soloist/group)
- `recipient`: Award recipient name
- `orchestra`: Associated orchestra (if applicable)

## Project Structure

```
nmjanitsjar/
├── src/nmjanitsjar_scraper/    # Main package
│   ├── __init__.py
│   ├── models.py               # Pydantic data models
│   ├── url_discovery.py        # URL discovery and management
│   ├── fetcher.py              # HTML fetching (legacy)
│   ├── parser.py               # JSON data parsing
│   ├── exporter.py             # Data export to CSV/JSON
│   ├── analytics.py            # Statistical analysis
│   └── cli.py                  # Main CLI interface
├── data/
│   ├── raw/                    # Cached HTML files
│   ├── json/                   # Cached JSON data
│   └── processed/              # Exported CSV/JSON files
├── meta/                       # Metadata (URLs, etc.)
├── tests/                      # Unit tests
├── notebooks/                  # Analysis notebooks
├── pyproject.toml              # Project configuration
└── README.md
```

## Example Analytics Output

```
Top 5 Orchestras by Wins
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━━━┓
┃ Orchestra                   ┃ Wins ┃ Last Win ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━━━┩
│ Christiania Blåseensemble   │ 15   │ 2025     │
│ Eikanger-Bjørsvik           │ 12   │ 2019     │
│ Stavanger Brass Band        │ 8    │ 2018     │
└─────────────────────────────┴──────┴──────────┘
```

## Technical Details

### Data Source
The application primarily uses JSON APIs from nmjanitsjar.no:
- `konkurranser.json`: Competition results
- `korps.json`: Orchestra information  
- `dirigenter.json`: Conductor information
- `musikkstykker.json`: Musical pieces

### Architecture
- **Pydantic**: Data validation and serialization
- **Rich**: Beautiful terminal output and progress bars  
- **Pandas**: Data manipulation and CSV export
- **Tenacity**: Robust retry logic for HTTP requests
- **Requests**: HTTP client with session management

### Respectful Scraping
- Checks `robots.txt` compliance
- Implements rate limiting (1 second between requests)
- Uses intelligent caching to avoid redundant requests
- Provides proper User-Agent identification

## Future Development

### Phase 2: Database Integration
- PostgreSQL/DuckDB schema design
- SQLAlchemy ORM models
- Database migration tools
- REST/GraphQL API

### Phase 3: Advanced Analytics
- Time series analysis
- Orchestra performance trends
- Conductor success patterns
- Musical piece popularity analysis
- Geographic distribution analysis

### Phase 4: Web Interface
- Interactive dashboard
- Data visualization
- Search and filtering
- Export capabilities

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Submit a pull request

## License

This project is intended for educational and research purposes. Please respect the original data source and their terms of service.

## Data Quality

The application includes data validation and normalization:
- Orchestra and conductor name standardization
- Point score validation (0-100 range)
- Division name normalization
- Missing data handling
- Duplicate detection and removal

## Performance

- Processes 40+ years of data in under 2 minutes
- Exports 1000+ records to CSV in seconds  
- Memory efficient streaming for large datasets
- Incremental updates for new competition data

---

*For questions, issues, or contributions, please refer to the project's issue tracker.*

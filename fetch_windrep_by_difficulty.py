#!/usr/bin/env python3
"""
Fetch wind repertoire pieces from WindRep.org filtered by year and difficulty rating.

Usage:
    python fetch_windrep_by_difficulty.py --year 2024 --difficulty 3
    python fetch_windrep_by_difficulty.py --year 2023 --difficulty 5 --export grade5_2023.csv
    python fetch_windrep_by_difficulty.py --year 2024 --difficulty 1 --clear-cache
"""

import sys
from pathlib import Path

import click
from rich.console import Console

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from nmjanitsjar_scraper.difficulty_fetcher import WindRepDifficultyFetcher

console = Console()


@click.command()
@click.option(
    '--year',
    type=int,
    required=True,
    help='Year to fetch pieces from (e.g., 2024)'
)
@click.option(
    '--difficulty',
    type=click.IntRange(1, 6),
    required=True,
    help='Difficulty level to filter by (1-6, corresponding to Roman numerals I-VI)'
)
@click.option(
    '--export',
    type=click.Path(),
    default=None,
    help='Export results to CSV file (optional)'
)
@click.option(
    '--clear-cache',
    is_flag=True,
    help='Clear cached data before fetching'
)
def main(year: int, difficulty: int, export: str, clear_cache: bool):
    """
    Fetch wind repertoire pieces from WindRep.org filtered by year and difficulty.
    
    This script will:
    1. Fetch all pieces from the specified year's category page
    2. Extract metadata (title, composer, duration, difficulty) from each piece
    3. Filter pieces by the specified difficulty level
    4. Display results in a formatted table
    5. Optionally export to CSV
    """
    try:
        # Initialize fetcher
        fetcher = WindRepDifficultyFetcher(
            year=year,
            difficulty=difficulty,
            export_path=Path(export) if export else None,
            clear_cache=clear_cache
        )
        
        # Run the fetch and filter process
        pieces = fetcher.run()
        
        # Exit with appropriate status
        if pieces:
            console.print(f"\n[bold green]✓ Found {len(pieces)} piece(s) with difficulty level {difficulty}[/bold green]")
            sys.exit(0)
        else:
            console.print(f"\n[yellow]⚠ No pieces found with difficulty level {difficulty} for year {year}[/yellow]")
            sys.exit(1)
            
    except Exception as e:
        console.print(f"\n[bold red]✗ Error: {e}[/bold red]")
        import traceback
        console.print(traceback.format_exc())
        sys.exit(2)


if __name__ == "__main__":
    main()

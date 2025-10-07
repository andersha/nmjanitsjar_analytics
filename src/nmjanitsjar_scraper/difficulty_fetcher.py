"""
Fetch and filter WindRep.org pieces by year and difficulty rating.

This module provides functionality to scrape piece metadata from WindRep.org's
year-based category pages and filter by difficulty level.
"""

import csv
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup
from rich.console import Console
from rich.table import Table
from rich.progress import track

console = Console()


class WindRepDifficultyFetcher:
    """Fetches and filters WindRep.org pieces by year and difficulty."""
    
    BASE_URL = "https://www.windrep.org"
    CACHE_FILE = Path("data/windrep_year_cache.json")
    
    # Roman numeral mapping
    DIFFICULTY_MAP = {
        1: 'I',
        2: 'II',
        3: 'III',
        4: 'IV',
        5: 'V',
        6: 'VI'
    }
    
    def __init__(
        self,
        year: int,
        difficulty: int,
        export_path: Optional[Path] = None,
        clear_cache: bool = False
    ):
        """
        Initialize the difficulty fetcher.
        
        Args:
            year: Year to fetch pieces from
            difficulty: Difficulty level (1-6)
            export_path: Optional path to export CSV
            clear_cache: Whether to clear cache before fetching
        """
        self.year = year
        self.difficulty = difficulty
        self.difficulty_roman = self.DIFFICULTY_MAP[difficulty]
        self.export_path = export_path
        
        # Setup session with proper headers
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Norwegian Band Competition Analyzer/1.0 (Research Project)'
        })
        
        # Handle cache clearing
        if clear_cache and self.CACHE_FILE.exists():
            console.print(f"[yellow]🗑️  Clearing cache: {self.CACHE_FILE}[/yellow]")
            self.CACHE_FILE.unlink()
        
        # Load cache
        self.cache = self._load_cache()
    
    def _load_cache(self) -> Dict:
        """Load cache from file."""
        if self.CACHE_FILE.exists():
            try:
                with open(self.CACHE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                console.print(f"[yellow]⚠️  Failed to load cache: {e}[/yellow]")
        return {}
    
    def _save_cache(self):
        """Save cache to file."""
        try:
            self.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(self.CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, indent=2, ensure_ascii=False)
        except Exception as e:
            console.print(f"[yellow]⚠️  Failed to save cache: {e}[/yellow]")
    
    def fetch_category_pieces(self) -> List[str]:
        """
        Fetch all piece URLs from the year's category page.
        Handles pagination to retrieve all pieces across multiple pages.
        
        Returns:
            List of piece URLs (relative paths)
        """
        cache_key = f"category:{self.year}"
        
        # Check cache first
        if cache_key in self.cache:
            console.print(f"[dim]📦 Using cached category data for {self.year}[/dim]")
            return self.cache[cache_key]
        
        console.print(f"[blue]🌐 Fetching category page for year {self.year}...[/blue]")
        
        all_piece_urls = []
        current_url = f"{self.BASE_URL}/Category:{self.year}"
        page_num = 1
        
        try:
            while current_url:
                console.print(f"[dim]  Fetching page {page_num}...[/dim]")
                
                response = self.session.get(current_url, timeout=15)
                response.raise_for_status()
                
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Find all piece links in the category
                category_groups = soup.find_all('div', class_='mw-category-group')
                page_pieces = 0
                
                for group in category_groups:
                    links = group.find_all('a')
                    for link in links:
                        href = link.get('href')
                        if href and href.startswith('/') and not href.startswith('/index.php'):
                            # Filter out special pages
                            if not any(x in href for x in ['/Category:', '/Special:', '/File:']):
                                all_piece_urls.append(href)
                                page_pieces += 1
                
                console.print(f"[dim]    Found {page_pieces} pieces on page {page_num}[/dim]")
                
                # Look for "next page" link
                next_link = None
                for link in soup.find_all('a'):
                    if link.get_text().strip() == 'next page':
                        href = link.get('href')
                        if href:
                            # Convert relative URL to absolute
                            if href.startswith('/'):
                                next_link = f"{self.BASE_URL}{href}"
                            else:
                                next_link = f"{self.BASE_URL}/{href}"
                        break
                
                # Move to next page or stop
                if next_link:
                    current_url = next_link
                    page_num += 1
                    time.sleep(0.7)  # Rate limiting between pages
                else:
                    current_url = None
            
            console.print(f"[green]✓ Found {len(all_piece_urls)} pieces in category {self.year} ({page_num} page(s))[/green]")
            
            # Cache the results
            self.cache[cache_key] = all_piece_urls
            self._save_cache()
            
            return all_piece_urls
            
        except requests.RequestException as e:
            console.print(f"[red]✗ Failed to fetch category page: {e}[/red]")
            return all_piece_urls if all_piece_urls else []
    
    def get_piece_metadata(self, piece_url: str) -> Optional[Dict]:
        """
        Fetch metadata for a single piece.
        
        Args:
            piece_url: Relative URL to piece page (e.g., '/Balatro')
        
        Returns:
            Dictionary with title, composer, duration, difficulty, url
            or None if extraction fails
        """
        cache_key = f"piece:{piece_url}"
        
        # Check cache first
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        full_url = f"{self.BASE_URL}{piece_url}"
        
        try:
            # Rate limiting
            time.sleep(0.7)
            
            response = self.session.get(full_url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract title from page title or h1
            title = None
            title_tag = soup.find('h1', class_='firstHeading')
            if title_tag:
                title = title_tag.get_text().strip()
            else:
                # Fallback: extract from URL
                title = piece_url.strip('/').replace('_', ' ')
            
            # Extract metadata from the page
            metadata = {
                'title': title,
                'composer': None,
                'duration': None,
                'difficulty': None,
                'url': full_url
            }
            
            # Look for "General Info" section with structured data
            content_text = soup.get_text()
            
            # Extract composer from meta description (most reliable)
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            if meta_desc and meta_desc.get('content'):
                composer_name = meta_desc['content'].strip()
                if composer_name and len(composer_name) > 3 and len(composer_name) < 100:
                    metadata['composer'] = composer_name
            
            # Extract difficulty (Roman numeral format)
            difficulty_pattern = r'Difficulty:\s*(VI|V|IV|III|II|I)\s'
            difficulty_match = re.search(difficulty_pattern, content_text, re.IGNORECASE)
            if difficulty_match:
                metadata['difficulty'] = difficulty_match.group(1).upper()
            
            # Extract duration (multiple formats supported)
            duration_patterns = [
                r'Duration:\s*c?\.\s*(\d{1,2}):(\d{2})',  # "Duration: c. 3:55"
                r'Duration:\s*c?\.\s*(\d+)\s*(?:min|minutes?)',  # "Duration: 10 minutes"
            ]
            
            for pattern in duration_patterns:
                match = re.search(pattern, content_text, re.IGNORECASE)
                if match:
                    if len(match.groups()) == 2:  # MM:SS format
                        minutes = int(match.group(1))
                        seconds = int(match.group(2))
                        metadata['duration'] = f"{minutes}:{seconds:02d}"
                    elif len(match.groups()) == 1:  # Just minutes
                        metadata['duration'] = f"{match.group(1)}:00"
                    break
            
            # Cache the result
            self.cache[cache_key] = metadata
            self._save_cache()
            
            return metadata
            
        except requests.RequestException as e:
            console.print(f"[dim yellow]⚠️  Failed to fetch {piece_url}: {e}[/dim yellow]")
            # Cache the failure to avoid repeated requests
            self.cache[cache_key] = None
            self._save_cache()
            return None
        except Exception as e:
            console.print(f"[dim yellow]⚠️  Error parsing {piece_url}: {e}[/dim yellow]")
            return None
    
    def filter_by_difficulty(self, pieces: List[Dict]) -> List[Dict]:
        """
        Filter pieces by difficulty level.
        
        Args:
            pieces: List of piece metadata dictionaries
        
        Returns:
            Filtered list containing only pieces with matching difficulty
        """
        filtered = []
        
        for piece in pieces:
            if piece and piece.get('difficulty') == self.difficulty_roman:
                filtered.append(piece)
        
        return filtered
    
    def display_results(self, pieces: List[Dict]):
        """
        Display results in a formatted Rich table.
        
        Args:
            pieces: List of piece metadata to display
        """
        if not pieces:
            console.print(f"\n[yellow]No pieces found with difficulty {self.difficulty_roman}[/yellow]")
            return
        
        # Create table
        table = Table(title=f"WindRep.org Pieces - Year {self.year}, Difficulty {self.difficulty_roman}")
        
        table.add_column("Title", style="cyan", no_wrap=False)
        table.add_column("Composer", style="magenta")
        table.add_column("Duration", style="green", justify="right")
        table.add_column("URL", style="blue", no_wrap=False)
        
        # Add rows
        for piece in pieces:
            table.add_row(
                piece.get('title', 'Unknown'),
                piece.get('composer', 'Unknown'),
                piece.get('duration', 'Unknown'),
                piece.get('url', '')
            )
        
        console.print("\n")
        console.print(table)
        console.print(f"\n[bold]Total: {len(pieces)} piece(s)[/bold]")
    
    def export_to_csv(self, pieces: List[Dict]):
        """
        Export pieces to CSV file.
        
        Args:
            pieces: List of piece metadata to export
        """
        if not self.export_path:
            return
        
        try:
            with open(self.export_path, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['title', 'composer', 'duration', 'difficulty', 'url']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                writer.writeheader()
                for piece in pieces:
                    writer.writerow({
                        'title': piece.get('title', ''),
                        'composer': piece.get('composer', ''),
                        'duration': piece.get('duration', ''),
                        'difficulty': piece.get('difficulty', ''),
                        'url': piece.get('url', '')
                    })
            
            console.print(f"\n[green]✓ Exported {len(pieces)} piece(s) to {self.export_path}[/green]")
            
        except Exception as e:
            console.print(f"[red]✗ Failed to export CSV: {e}[/red]")
    
    def run(self) -> List[Dict]:
        """
        Run the complete fetch, filter, and display workflow.
        
        Returns:
            List of filtered pieces
        """
        console.print(f"\n[bold blue]🎵 WindRep Difficulty Fetcher[/bold blue]")
        console.print(f"[dim]Year: {self.year}, Difficulty: {self.difficulty} ({self.difficulty_roman})[/dim]\n")
        
        # Step 1: Fetch all piece URLs from category page
        piece_urls = self.fetch_category_pieces()
        
        if not piece_urls:
            console.print("[red]✗ No pieces found in category[/red]")
            return []
        
        # Step 2: Fetch metadata for each piece
        console.print(f"\n[blue]📖 Fetching metadata for {len(piece_urls)} pieces...[/blue]")
        all_pieces = []
        
        for url in track(piece_urls, description="Fetching pieces..."):
            metadata = self.get_piece_metadata(url)
            if metadata:
                all_pieces.append(metadata)
        
        console.print(f"[green]✓ Successfully fetched metadata for {len(all_pieces)} pieces[/green]")
        
        # Step 3: Filter by difficulty
        console.print(f"\n[blue]🔍 Filtering by difficulty {self.difficulty_roman}...[/blue]")
        filtered_pieces = self.filter_by_difficulty(all_pieces)
        
        # Step 4: Display results
        self.display_results(filtered_pieces)
        
        # Step 5: Export if requested
        if self.export_path and filtered_pieces:
            self.export_to_csv(filtered_pieces)
        
        return filtered_pieces

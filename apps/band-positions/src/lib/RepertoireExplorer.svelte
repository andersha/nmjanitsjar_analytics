<script lang="ts">
  import { onMount } from 'svelte';

  interface RepertoirePiece {
    title: string;
    composer: string | null;
    duration: string | null;
    duration_minutes: number | null;
    difficulty: number | null;
    difficulty_roman: string | null;
    url: string;
    years: number[];
    min_year: number | null;
    max_year: number | null;
  }

  interface RepertoireData {
    pieces: RepertoirePiece[];
    metadata: {
      total_pieces: number;
      year_range: { min: number; max: number };
      difficulty_range: { min: number; max: number };
    };
  }

  let data = $state<RepertoireData | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);

  // Filter states
  let searchTerm = $state('');
  let searchField = $state<'title' | 'composer'>('title');
  let minDuration = $state<number | null>(null);
  let maxDuration = $state<number | null>(null);
  let minDifficulty = $state<number | null>(null);
  let maxDifficulty = $state<number | null>(null);
  let minYear = $state<number | null>(null);
  let maxYear = $state<number | null>(null);
  let pageSize = $state(50);
  let currentPage = $state(1);
  let sortColumn = $state<'year' | 'title' | 'composer' | 'duration' | 'difficulty'>('title');
  let sortDirection = $state<'asc' | 'desc'>('asc');

  // Filtered and sorted pieces
  let filteredPieces = $derived.by(() => {
    if (!data) return [];

    let result = data.pieces.filter(piece => {
      // Search filter
      if (searchTerm.trim()) {
        const term = searchTerm.toLowerCase();
        if (searchField === 'title') {
          if (!piece.title.toLowerCase().includes(term)) return false;
        } else {
          if (!piece.composer?.toLowerCase().includes(term)) return false;
        }
      }

      // Duration filter
      if (minDuration !== null && (piece.duration_minutes === null || piece.duration_minutes < minDuration)) return false;
      if (maxDuration !== null && (piece.duration_minutes === null || piece.duration_minutes > maxDuration)) return false;

      // Difficulty filter
      if (minDifficulty !== null && (piece.difficulty === null || piece.difficulty < minDifficulty)) return false;
      if (maxDifficulty !== null && (piece.difficulty === null || piece.difficulty > maxDifficulty)) return false;

      // Year filter
      if (minYear !== null && (piece.max_year === null || piece.max_year < minYear)) return false;
      if (maxYear !== null && (piece.min_year === null || piece.min_year > maxYear)) return false;

      return true;
    });

    // Sort
    result.sort((a, b) => {
      let aVal, bVal;

      switch (sortColumn) {
        case 'title':
          aVal = a.title.toLowerCase();
          bVal = b.title.toLowerCase();
          break;
        case 'composer':
          aVal = (a.composer || '').toLowerCase();
          bVal = (b.composer || '').toLowerCase();
          break;
        case 'duration':
          aVal = a.duration_minutes ?? -1;
          bVal = b.duration_minutes ?? -1;
          break;
        case 'difficulty':
          aVal = a.difficulty ?? -1;
          bVal = b.difficulty ?? -1;
          break;
        case 'year':
          aVal = a.min_year ?? -1;
          bVal = b.min_year ?? -1;
          break;
        default:
          return 0;
      }

      if (aVal < bVal) return sortDirection === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortDirection === 'asc' ? 1 : -1;
      return 0;
    });

    return result;
  });

  let paginatedPieces = $derived.by(() => {
    const start = (currentPage - 1) * pageSize;
    const end = start + pageSize;
    return filteredPieces.slice(start, end);
  });

  let totalPages = $derived(Math.ceil(filteredPieces.length / pageSize));

  function handleSort(column: typeof sortColumn) {
    if (sortColumn === column) {
      sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
    } else {
      sortColumn = column;
      sortDirection = 'asc';
    }
    currentPage = 1; // Reset to first page when sorting
  }

  function handlePageSizeChange() {
    currentPage = 1; // Reset to first page
  }

  function resetFilters() {
    searchTerm = '';
    minDuration = null;
    maxDuration = null;
    minDifficulty = null;
    maxDifficulty = null;
    minYear = null;
    maxYear = null;
    currentPage = 1;
  }

  function formatDuration(minutes: number | null): string {
    if (minutes === null) return '—';
    const wholeMinutes = Math.floor(minutes);
    const seconds = Math.round((minutes - wholeMinutes) * 60);
    return `${wholeMinutes}:${seconds.toString().padStart(2, '0')}`;
  }

  function formatYears(years: number[]): string {
    if (!years || years.length === 0) return '—';
    if (years.length === 1) return years[0].toString();
    return `${years[0]}–${years[years.length - 1]}`;
  }

  onMount(async () => {
    // Only run in browser (not during SSR build)
    if (typeof window === 'undefined') {
      loading = false;
      return;
    }

    try {
      const response = await fetch('data/repertoire.json');
      if (!response.ok) {
        throw new Error(`Failed to load repertoire data: ${response.statusText}`);
      }
      data = await response.json();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Unknown error';
      console.error('Failed to load repertoire:', err);
    } finally {
      loading = false;
    }
  });
</script>

<div class="repertoire-explorer">
  {#if loading}
    <div class="loading">Laster repertoar...</div>
  {:else if error}
    <div class="error">Feil ved lasting av data: {error}</div>
  {:else if data}
    <div class="filters-container">
      <div class="search-row">
        <div class="search-group">
          <input
            type="text"
            placeholder="Søk..."
            bind:value={searchTerm}
            class="search-input"
          />
          <select bind:value={searchField} class="search-field-select">
            <option value="title">Tittel</option>
            <option value="composer">Komponist</option>
          </select>
        </div>
      </div>

      <div class="filter-row">
        <div class="filter-group">
          <label for="duration-min">Varighet (min)</label>
          <div class="range-inputs">
            <input id="duration-min" type="number" placeholder="Min" bind:value={minDuration} min="0" max="60" />
            <span>—</span>
            <input id="duration-max" type="number" placeholder="Maks" bind:value={maxDuration} min="0" max="60" />
          </div>
        </div>

        <div class="filter-group">
          <label for="difficulty-min">Vanskelighetsgrad</label>
          <div class="range-inputs">
            <input id="difficulty-min" type="number" placeholder="Min" bind:value={minDifficulty} min="1" max="7" />
            <span>—</span>
            <input id="difficulty-max" type="number" placeholder="Maks" bind:value={maxDifficulty} min="1" max="7" />
          </div>
        </div>

        <div class="filter-group">
          <label for="year-min">År</label>
          <div class="range-inputs">
            <input id="year-min" type="number" placeholder="Fra" bind:value={minYear} min="2016" max="2025" />
            <span>—</span>
            <input id="year-max" type="number" placeholder="Til" bind:value={maxYear} min="2016" max="2025" />
          </div>
        </div>

        <button class="reset-button" onclick={resetFilters}>
          Nullstill
        </button>
      </div>

      <div class="results-info">
        <span>{filteredPieces.length} stykker</span>
        <div class="page-size-selector">
          <label for="page-size-select">Vis:</label>
          <select id="page-size-select" bind:value={pageSize} onchange={handlePageSizeChange}>
            <option value={20}>20</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
          </select>
        </div>
      </div>
    </div>

    <div class="table-container">
      <table class="repertoire-table">
        <thead>
          <tr>
            <th onclick={() => handleSort('title')} class:sorted={sortColumn === 'title'}>
              Tittel {sortColumn === 'title' ? (sortDirection === 'asc' ? '▲' : '▼') : ''}
            </th>
            <th onclick={() => handleSort('composer')} class:sorted={sortColumn === 'composer'}>
              Komponist {sortColumn === 'composer' ? (sortDirection === 'asc' ? '▲' : '▼') : ''}
            </th>
            <th onclick={() => handleSort('duration')} class:sorted={sortColumn === 'duration'}>
              Varighet {sortColumn === 'duration' ? (sortDirection === 'asc' ? '▲' : '▼') : ''}
            </th>
            <th onclick={() => handleSort('difficulty')} class:sorted={sortColumn === 'difficulty'}>
              Grad {sortColumn === 'difficulty' ? (sortDirection === 'asc' ? '▲' : '▼') : ''}
            </th>
            <th onclick={() => handleSort('year')} class:sorted={sortColumn === 'year'}>
              År {sortColumn === 'year' ? (sortDirection === 'asc' ? '▲' : '▼') : ''}
            </th>
            <th>Link</th>
          </tr>
        </thead>
        <tbody>
          {#each paginatedPieces as piece (piece.url)}
            <tr>
              <td class="title-cell">{piece.title}</td>
              <td class="composer-cell">{piece.composer || '—'}</td>
              <td class="duration-cell">{formatDuration(piece.duration_minutes)}</td>
              <td class="difficulty-cell">{piece.difficulty_roman || '—'}</td>
              <td class="year-cell">{formatYears(piece.years)}</td>
              <td class="link-cell">
                <a href={piece.url} target="_blank" rel="noopener noreferrer">
                  WindRep
                </a>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    {#if totalPages > 1}
      <div class="pagination">
        <button
          onclick={() => currentPage = Math.max(1, currentPage - 1)}
          disabled={currentPage === 1}
        >
          ‹ Forrige
        </button>
        
        <span class="page-info">
          Side {currentPage} av {totalPages}
        </span>
        
        <button
          onclick={() => currentPage = Math.min(totalPages, currentPage + 1)}
          disabled={currentPage === totalPages}
        >
          Neste ›
        </button>
      </div>
    {/if}
  {/if}
</div>

<style>
  .repertoire-explorer {
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
  }

  .loading, .error {
    margin: 0.5rem 0;
    color: var(--color-text-secondary);
    font-size: 0.95rem;
  }

  .error {
    color: #ef4444;
  }

  .filters-container {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .search-row {
    display: flex;
    gap: 1rem;
    flex-wrap: wrap;
  }

  .search-group {
    display: flex;
    gap: 0.5rem;
    flex: 1;
    min-width: 300px;
  }

  .search-input {
    flex: 1;
    padding: 0.5rem 0.75rem;
    border-radius: 0.6rem;
    border: 1px solid var(--color-border);
    background: var(--color-surface-card);
    color: var(--color-text-primary);
    font-size: 0.95rem;
  }

  .search-input::placeholder {
    color: var(--color-text-secondary);
    opacity: 0.6;
  }

  .search-field-select {
    padding: 0.5rem 0.75rem;
    border-radius: 0.6rem;
    border: 1px solid var(--color-border);
    background: var(--color-surface-card);
    color: var(--color-text-primary);
    font-size: 0.95rem;
    cursor: pointer;
  }

  .filter-row {
    display: flex;
    gap: 1rem;
    flex-wrap: wrap;
    align-items: flex-end;
  }

  .filter-group {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }

  .filter-group label {
    font-size: 0.95rem;
    font-weight: 600;
    color: var(--color-text-primary);
  }

  .range-inputs {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .range-inputs input {
    width: 5rem;
    padding: 0.45rem 0.75rem;
    border-radius: 0.6rem;
    border: 1px solid var(--color-border);
    background: var(--color-surface-card);
    color: var(--color-text-primary);
    font-size: 0.95rem;
  }

  .range-inputs input::placeholder {
    color: var(--color-text-secondary);
    opacity: 0.6;
  }

  .range-inputs span {
    color: var(--color-text-secondary);
  }

  .reset-button {
    padding: 0.45rem 1rem;
    background: var(--color-accent);
    color: white;
    border: none;
    border-radius: 0.6rem;
    cursor: pointer;
    font-size: 0.95rem;
    font-weight: 500;
    transition: opacity 0.18s ease, transform 0.18s ease;
  }

  .reset-button:hover {
    opacity: 0.9;
    transform: translateY(-1px);
  }

  .reset-button:active {
    transform: translateY(0);
  }

  .results-info {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-top: 1rem;
    border-top: 1px solid var(--color-border);
    font-size: 0.95rem;
    color: var(--color-text-secondary);
  }

  .page-size-selector {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .page-size-selector label {
    font-weight: 500;
    color: var(--color-text-secondary);
  }

  .page-size-selector select {
    padding: 0.35rem 0.6rem;
    border-radius: 0.6rem;
    border: 1px solid var(--color-border);
    background: var(--color-surface-card);
    color: var(--color-text-primary);
    font-size: 0.95rem;
    cursor: pointer;
  }

  .table-container {
    overflow-x: auto;
    border-radius: 1rem;
    border: 1px solid var(--color-border);
    background: var(--color-surface-card);
    box-shadow: 0 18px 40px rgba(15, 23, 42, 0.25);
  }

  .repertoire-table {
    width: 100%;
    border-collapse: collapse;
    min-width: 600px;
  }

  .repertoire-table thead {
    background: var(--color-mode-toggle-bg);
  }

  .repertoire-table th {
    padding: 0.75rem 1rem;
    text-align: left;
    font-size: 0.85rem;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
    cursor: pointer;
    user-select: none;
    transition: background 0.15s ease;
  }

  .repertoire-table th:hover {
    background: rgba(255, 255, 255, 0.05);
  }

  .repertoire-table th.sorted {
    color: var(--color-accent);
  }

  .repertoire-table tbody tr:nth-child(even) {
    background: rgba(255, 255, 255, 0.02);
  }

  .repertoire-table tbody td {
    padding: 0.75rem 1rem;
    border-top: 1px solid var(--color-border);
    color: var(--color-text-primary);
    font-size: 0.95rem;
  }

  .title-cell {
    font-weight: 500;
  }

  .composer-cell {
    color: var(--color-text-secondary);
  }

  .duration-cell, .difficulty-cell, .year-cell {
    text-align: center;
    font-variant-numeric: tabular-nums;
  }

  .link-cell {
    text-align: center;
  }

  .link-cell a {
    color: var(--color-accent);
    text-decoration: none;
    font-size: 0.9rem;
    padding: 0.25rem 0.5rem;
    border-radius: 0.4rem;
    transition: background 0.15s ease;
  }

  .link-cell a:hover {
    background: rgba(var(--color-accent-rgb, 147, 51, 234), 0.1);
  }

  .pagination {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 1rem;
    padding: 1rem 0;
  }

  .pagination button {
    padding: 0.45rem 1rem;
    background: var(--color-accent);
    color: white;
    border: none;
    border-radius: 0.6rem;
    cursor: pointer;
    font-size: 0.95rem;
    font-weight: 500;
    transition: opacity 0.18s ease, transform 0.18s ease;
  }

  .pagination button:hover:not(:disabled) {
    opacity: 0.9;
    transform: translateY(-1px);
  }

  .pagination button:active:not(:disabled) {
    transform: translateY(0);
  }

  .pagination button:disabled {
    background: var(--color-border);
    cursor: not-allowed;
    opacity: 0.4;
  }

  .page-info {
    font-size: 0.95rem;
    color: var(--color-text-secondary);
    font-weight: 500;
  }

  /* Responsive */

  @media (max-width: 768px) {
    .search-group {
      min-width: 100%;
    }

    .filter-row {
      flex-direction: column;
      align-items: stretch;
    }

    .range-inputs input {
      flex: 1;
    }

    .results-info {
      flex-direction: column;
      gap: 0.75rem;
      align-items: flex-start;
    }

    .repertoire-table th,
    .repertoire-table td {
      padding: 0.5rem 0.75rem;
      font-size: 0.9rem;
    }
  }
</style>

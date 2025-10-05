<script lang="ts">
  import type { BandRecord, BandEntry, BandType, StreamingLink, EliteTestPiecesData } from './types';
  import { slugify } from './slugify';

  interface Props {
    bands?: BandRecord[];
    bandType?: BandType;
    streamingResolver?: (entry: BandEntry, bandName: string, pieceName: string) => StreamingLink | null;
    eliteTestPieces?: EliteTestPiecesData | null;
  }

  let { bands = [], bandType = 'wind', streamingResolver, eliteTestPieces = null }: Props = $props();

  const pointsFormatter = new Intl.NumberFormat('nb-NO', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1
  });

  function sortEntries(entries: BandEntry[]): BandEntry[] {
    return [...entries].sort((a, b) => {
      const yearDiff = a.year - b.year;
      if (yearDiff !== 0) return yearDiff;
      const rankA = a.rank ?? Number.POSITIVE_INFINITY;
      const rankB = b.rank ?? Number.POSITIVE_INFINITY;
      if (rankA !== rankB) return rankA - rankB;
      return (a.absolute_position ?? Number.POSITIVE_INFINITY) - (b.absolute_position ?? Number.POSITIVE_INFINITY);
    });
  }

  function formatPoints(points: number | null): string {
    if (points == null) return '–';
    return pointsFormatter.format(points);
  }

  function formatRank(rank: number | null): string {
    return rank != null ? `${rank}` : '–';
  }

  function hasStreamingLinks(streaming?: StreamingLink | null): boolean {
    return Boolean(streaming?.spotify || streaming?.apple_music);
  }

  function toAppleMusicHref(url: string | null | undefined): string | null {
    if (!url) return null;
    const trimmed = url.trim();
    if (!trimmed) return null;
    if (!/^https?:\/\//i.test(trimmed)) {
      return trimmed;
    }
    try {
      const parsed = new URL(trimmed);
      const path = `${parsed.host}${parsed.pathname}${parsed.search}${parsed.hash}`;
      return `music://${path}`;
    } catch (err) {
      console.warn('Kunne ikke konvertere Apple Music-lenke', err);
      return trimmed;
    }
  }

  function buildStreamingTitle(
    pieceName: string,
    streaming: StreamingLink | null | undefined,
    platform: 'spotify' | 'apple'
  ): string {
    if (!streaming) return pieceName;
    const trackName = streaming.recording_title?.trim();
    const albumName = streaming.album?.trim();
    const platformLabel = platform === 'spotify' ? 'Spotify' : 'Apple Music';
    const base = trackName && trackName.length > 0 ? trackName : pieceName;
    if (albumName && albumName.length > 0) {
      return `${base} • ${albumName} (${platformLabel})`;
    }
    return `${base} (${platformLabel})`;
  }

  function resolveStreaming(entry: BandEntry, bandName: string, pieceName: string): StreamingLink | null {
    if (!streamingResolver) return null;
    return streamingResolver(entry, bandName, pieceName) ?? null;
  }

  function testPieceForYear(year: string | number): { composer: string; piece: string } | null {
    const y = String(year);
    const tp = eliteTestPieces?.test_pieces?.[y];
    return tp ? { composer: tp.composer, piece: tp.piece } : null;
  }

  function isEliteDivision(division: string | undefined): boolean {
    return (division || '').toLowerCase() === 'elite';
  }

  let normalizedBands = $derived(
    bands.map((band) => ({
      ...band,
      entries: sortEntries(band.entries)
    }))
  );
</script>

<section class="band-performances">
  {#each normalizedBands as band}
    <article class="band-card">
      <header class="band-header">
        <div>
          <h2>{band.name}</h2>
          <p class="band-count">{band.entries.length} fremføringer</p>
        </div>
      </header>

      <div class="table-wrapper" role="region" aria-label={`Fremføringer av ${band.name}`}>
        <table>
          <thead>
            <tr>
              <th scope="col">År</th>
              <th scope="col" class="division-column">Divisjon</th>
              <th scope="col">Stykke</th>
              <th scope="col">Plass</th>
              <th scope="col">Poeng</th>
              <th scope="col">Dirigent</th>
              <th scope="col" class="streaming-column">Opptak</th>
            </tr>
          </thead>
          <tbody>
            {#each band.entries as entry}
              {@const rawPieces = Array.isArray(entry.pieces) ? entry.pieces : []}
              {@const pieces = rawPieces.filter((piece) => piece && piece.trim().length > 0)}
              {@const testPiece = bandType === 'brass' && isEliteDivision(entry.division) ? testPieceForYear(entry.year) : null}
              {@const conductorName = entry.conductor?.trim() ?? ''}
              {@const hasConductor = conductorName.length > 0}
              {@const conductorSlug = hasConductor ? slugify(conductorName) : ''}
              {@const ownChoicePieceEntries = pieces.map((piece) => {
                const pieceName = piece.trim();
                const pieceSlug = pieceName ? slugify(pieceName) : '';
                const streaming = pieceName ? resolveStreaming(entry, band.name, pieceName) : null;
                return { pieceName, pieceSlug, streaming, isTestPiece: false };
              })}
              {@const testPieceEntry = testPiece ? [{
                pieceName: testPiece.piece,
                pieceSlug: slugify(testPiece.piece),
                streaming: resolveStreaming(entry, band.name, testPiece.piece),
                isTestPiece: true
              }] : []}
              {@const pieceEntries = [...testPieceEntry, ...ownChoicePieceEntries]}
              {@const streamingEntries = pieceEntries.filter((item) => hasStreamingLinks(item.streaming))}
              <tr>
                <td data-label="År">{entry.year}</td>
                <td data-label="Divisjon" class="division-cell">{entry.division}</td>
                <td data-label="Stykke" class="piece-cell">
                  {#if pieceEntries.length > 0}
                    <ul class="piece-list">
                      {#each pieceEntries as pieceEntry}
                        <li>
                          {#if pieceEntry.isTestPiece}
                            <span class="test-piece-label" title="Pliktstykke (fredag)">P:</span>
                          {:else if bandType === 'brass' && isEliteDivision(entry.division)}
                            <span class="own-choice-label" title="Selvvalgt (lørdag)">S:</span>
                          {/if}
                          {#if pieceEntry.pieceSlug}
                            <a
                              href={`?type=${bandType}&view=pieces&piece=${encodeURIComponent(pieceEntry.pieceSlug)}`}
                              class="entity-link"
                              class:test-piece-link={pieceEntry.isTestPiece}
                            >
                              {pieceEntry.pieceName}
                            </a>
                          {:else if pieceEntry.pieceName}
                            <span>{pieceEntry.pieceName}</span>
                          {:else}
                            <span>Ukjent</span>
                          {/if}
                        </li>
                      {/each}
                    </ul>
                  {:else}
                    <span>Ukjent</span>
                  {/if}
                </td>
                <td data-label="Plass">{formatRank(entry.rank)}</td>
                <td data-label="Poeng">{formatPoints(entry.points)}</td>
                <td data-label="Dirigent">
                  {#if hasConductor}
                    <a
                      href={`?type=${bandType}&view=conductors&conductor=${encodeURIComponent(conductorSlug)}`}
                      class="entity-link"
                    >
                      {conductorName}
                    </a>
                  {:else}
                    <span>Ukjent</span>
                  {/if}
                </td>
                <td data-label="Opptak" class="streaming-cell">
                  {#if streamingEntries.length > 0}
                    <div class="streaming-list">
                      {#each streamingEntries as streamingEntry}
                        {@const streaming = streamingEntry.streaming}
                        {#if hasStreamingLinks(streaming)}
                          <div class="streaming-piece-row">
                            <span class="streaming-links">
                              {#if streaming?.spotify}
                                <a
                                  href={streaming.spotify}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  class="streaming-link spotify"
                                  title={buildStreamingTitle(streamingEntry.pieceName, streaming, 'spotify')}
                                >
                                  <span class="sr-only">Hør {streamingEntry.pieceName} på Spotify</span>
                                  <svg class="streaming-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                                    <circle cx="12" cy="12" r="10.5" opacity="0.15" fill="currentColor" />
                                    <path
                                      d="M16.88 16.13a.75.75 0 0 0-1.03-.26c-2.36 1.43-5.48 1.8-9.09 1.04a.75.75 0 1 0-.3 1.47c3.96.81 7.47.39 10.05-1.12a.75.75 0 0 0 .37-.37.75.75 0 0 0 0-.76z"
                                      fill="currentColor"
                                    />
                                    <path
                                      d="M16.1 13.69c-2.01 1.2-4.92 1.55-8.16.9a.75.75 0 0 0-.29 1.47c3.56.71 6.91.31 9.27-1.08a.75.75 0 0 0-.77-1.29h-.05z"
                                      fill="currentColor"
                                      opacity="0.8"
                                    />
                                    <path
                                      d="M15.24 11.12c-1.76 1.04-4.31 1.34-7.15.79a.75.75 0 0 0-.29 1.47c3.15.6 6.02.27 8.07-.96a.75.75 0 0 0-.77-1.3h-.04z"
                                      fill="currentColor"
                                      opacity="0.6"
                                    />
                                  </svg>
                                </a>
                              {/if}
                              {#if streaming?.apple_music}
                                {@const appleHref = toAppleMusicHref(streaming.apple_music)}
                                {#if appleHref}
                                  <a
                                    href={appleHref}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    class="streaming-link apple"
                                    title={buildStreamingTitle(streamingEntry.pieceName, streaming, 'apple')}
                                  >
                                    <span class="sr-only">Hør {streamingEntry.pieceName} på Apple Music</span>
                                    <svg class="streaming-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                                      <circle cx="12" cy="12" r="10.5" opacity="0.15" fill="currentColor" />
                                      <path
                                        d="M14.75 6.75a.75.75 0 0 1 .75.75v6.33a2.92 2.92 0 1 1-1.5-2.54V9.25h-1.5A.75.75 0 0 1 12 8.5v-1a.75.75 0 0 1 .75-.75z"
                                        fill="currentColor"
                                      />
                                      <path
                                        d="M9.75 13.75a.75.75 0 0 1 .75.75c0 .69.56 1.25 1.25 1.25s1.25-.56 1.25-1.25a.75.75 0 0 1 1.5 0 2.75 2.75 0 1 1-5.5 0 .75.75 0 0 1 .75-.75z"
                                        fill="currentColor"
                                        opacity="0.8"
                                      />
                                    </svg>
                                  </a>
                                {/if}
                              {/if}
                            </span>
                          </div>
                        {/if}
                      {/each}
                    </div>
                  {:else}
                    <span class="streaming-missing" aria-hidden="true">–</span>
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </article>
  {/each}
</section>

<style>
  .band-performances {
    display: flex;
    flex-direction: column;
    gap: 1.75rem;
    margin-top: 1.5rem;
  }

  .band-card {
    padding: 1.5rem;
    background: var(--color-surface-card);
    border-radius: 1rem;
    border: 1px solid var(--color-border);
    box-shadow: 0 18px 40px rgba(15, 23, 42, 0.25);
  }

  .band-header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 1rem;
  }

  .band-header h2 {
    margin: 0;
    color: var(--color-accent);
  }

  .band-header p {
    margin: 0.25rem 0 0;
    color: var(--color-text-secondary);
    font-size: 0.9rem;
  }

  .band-count {
    font-size: 0.85rem;
  }

  .table-wrapper {
    overflow-x: auto;
    border-radius: 0.85rem;
    border: 1px solid var(--color-border);
  }

  table {
    width: 100%;
    border-collapse: collapse;
    min-width: 560px;
  }

  th,
  td {
    padding: 0.7rem 1rem;
    text-align: left;
  }

  thead {
    background: var(--color-mode-toggle-bg);
  }

  th {
    font-size: 0.85rem;
    text-transform: uppercase;
    letter-spacing: 0.02em;
    color: var(--color-text-secondary);
  }

  tbody tr:nth-child(even) {
    background: rgba(255, 255, 255, 0.02);
  }

  tbody td {
    border-top: 1px solid var(--color-border);
    color: var(--color-text-primary);
    font-size: 0.95rem;
  }

  .division-column,
  .division-cell {
    white-space: nowrap;
  }

  .piece-cell {
    min-width: 200px;
  }

  .piece-list {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
    padding: 0;
    margin: 0;
    list-style: none;
  }

  .piece-list li {
    display: flex;
    align-items: center;
    gap: 0.35rem;
  }

  .entity-link {
    color: var(--color-accent);
    text-decoration: none;
  }

  .entity-link:hover,
  .entity-link:focus-visible {
    text-decoration: underline;
  }

  .streaming-column,
  .streaming-cell {
    text-align: center;
  }

  .streaming-cell {
    white-space: nowrap;
  }

  .streaming-list {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }

  .streaming-piece-row {
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .streaming-links {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
  }

  .streaming-link {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.75rem;
    height: 1.75rem;
    border-radius: 999px;
    color: var(--color-text-secondary);
    transition: transform 0.15s ease, color 0.15s ease, box-shadow 0.15s ease;
  }

  .streaming-link.spotify {
    color: #1db954;
  }

  .streaming-link.apple {
    color: #fa2d48;
  }

  .streaming-link:hover,
  .streaming-link:focus-visible {
    transform: translateY(-1px) scale(1.05);
    box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.2);
  }

  .streaming-link:focus-visible {
    outline: 2px solid var(--color-accent);
    outline-offset: 2px;
  }

  .streaming-icon {
    width: 1.25rem;
    height: 1.25rem;
    fill: currentColor;
  }

  .streaming-missing {
    color: var(--color-text-secondary);
  }

  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }

  .test-piece-label,
  .own-choice-label {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.7rem;
    font-weight: 700;
    border-radius: 0.25rem;
    padding: 0.1rem 0.3rem;
    margin-right: 0.35rem;
    text-transform: uppercase;
    letter-spacing: 0.02em;
  }

  .test-piece-label {
    color: var(--color-accent);
    background: rgba(var(--color-accent-rgb, 147, 51, 234), 0.1);
    border: 1px solid var(--color-accent);
  }

  .own-choice-label {
    color: #10b981;
    background: rgba(16, 185, 129, 0.1);
    border: 1px solid #10b981;
  }

  .test-piece-link {
    font-weight: 600;
  }
</style>

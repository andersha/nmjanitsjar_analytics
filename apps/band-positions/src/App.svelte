<script lang="ts">
  import { preventDefault } from 'svelte/legacy';

  import { onMount } from 'svelte';
  import BandTrajectoryChart from './lib/BandTrajectoryChart.svelte';
  import BandPerformances from './lib/BandPerformances.svelte';
  import ConductorPerformances from './lib/ConductorPerformances.svelte';
  import DataExplorer from './lib/DataExplorer.svelte';
  import PiecePerformances from './lib/PiecePerformances.svelte';
  import ComposerPieces from './lib/ComposerPieces.svelte';
  import RepertoireExplorer from './lib/RepertoireExplorer.svelte';
  import { slugify } from './lib/slugify';
  import { extractComposerNames, normalizeComposerName } from './lib/composerUtils';
import type {
  BandDataset,
  BandRecord,
  BandEntry,
  PieceRecord,
  ComposerRecord,
  BandType,
  StreamingLink,
  EliteTestPiecesData
} from './lib/types';

  type ViewType = 'bands' | 'conductors' | 'pieces' | 'composers' | 'data' | 'repertoire';
  type Theme = 'light' | 'dark';

  const URL_PARAM_KEYS = { bands: 'band', conductors: 'conductor', pieces: 'piece', composers: 'composer' } as const;
  const URL_MODE_KEY = 'mode';
  const URL_YAXIS_KEY = 'yaxis';
  const URL_VIEW_KEY = 'view';
  const URL_BAND_TYPE_KEY = 'type';
  const URL_YEAR_KEY = 'year';
  const URL_DIVISION_KEY = 'division';
  const URL_SEPARATOR = ',';
  const DEFAULT_MODE: 'absolute' | 'relative' = 'relative';
  const DEFAULT_YAXIS_SCALE: 'fitted' | 'full' = 'fitted';
  const DEFAULT_VIEW: ViewType = 'bands';
  const DEFAULT_BAND_TYPE: BandType = 'wind';
  const THEME_STORAGE_KEY = 'nmkorps-theme';
  const BAND_TYPE_STORAGE_KEY = 'nmkorps-band-type';

  const viewLabels: Record<ViewType, string> = {
    bands: 'Korps',
    conductors: 'Dirigent',
    pieces: 'Stykke',
    composers: 'Komponist',
    data: 'Resultat',
    repertoire: 'Repertoar'
  };
  const viewOrder: ViewType[] = ['bands', 'conductors', 'pieces', 'composers', 'data', 'repertoire'];

  let dataset = $state<BandDataset | null>(null);
  let conductorRecords = $state<BandRecord[]>([]);
  let pieceRecords = $state<PieceRecord[]>([]);
  let composerRecords = $state<ComposerRecord[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let searchTerm = $state('');
  let selectedBands = $state<BandRecord[]>([]);
  let selectedConductors = $state<BandRecord[]>([]);
  let selectedPieces = $state<PieceRecord[]>([]);
  let selectedComposers = $state<ComposerRecord[]>([]);
  let focusedIndex = $state(-1);
  let initialUrlSyncDone = false;
  let lastSyncedSignature = '';
  let yAxisMode = $state<'absolute' | 'relative'>(DEFAULT_MODE);
  let yAxisScale = $state<'fitted' | 'full'>('fitted'); // Default to fitted (new dynamic behavior)
  let activeView = $state<ViewType>(DEFAULT_VIEW);
  let theme = $state<Theme>('dark');
  let bandType = $state<BandType>('wind');
  let menuOpen = $state(false);
  let modeMenuOpen = $state(false);
  let bandTypeMenuOpen = $state(false);

  type ConductorPlacement = BandEntry & { band_name?: string };
  type PiecePerformance = BandEntry & { band_name: string };

  interface PieceMetadataEntry {
    title: string;
    slug: string;
    composer: string | null;
  }

  interface PieceMetadataDataset {
    pieces?: PieceMetadataEntry[];
  }

  interface PieceStreamingEntry {
    year: number;
    division: string;
    band: string;
    result_piece: string;
    result_piece_slug?: string;
    alternate_result_piece_slugs?: string[];
    spotify?: string | null;
    apple_music?: string | null;
    album?: string | null;
    recording_title?: string | null;
    division_slug?: string;
    band_slug?: string;
  }

  interface PieceStreamingDataset {
    wind?: PieceStreamingEntry[];
    brass?: PieceStreamingEntry[];
  }

  let pieceComposerIndex = new Map<string, PieceMetadataEntry[]>();
  let pieceStreamingIndex = new Map<string, StreamingLink>();
  let composerPieceIndex = new Map<string, ComposerRecord>();
  let eliteTestPieces = $state<EliteTestPiecesData | null>(null);

  function buildPieceComposerIndex(metadata: PieceMetadataEntry[]): Map<string, PieceMetadataEntry[]> {
    const index = new Map<string, PieceMetadataEntry[]>();
    for (const entry of metadata) {
      if (!entry || !entry.slug) continue;
      const slug = entry.slug.trim();
      if (!slug) continue;
      const bucket = index.get(slug);
      if (bucket) {
        bucket.push(entry);
      } else {
        index.set(slug, [entry]);
      }
    }
    return index;
  }

  function buildPieceStreamingIndex(entries: PieceStreamingEntry[]): Map<string, StreamingLink> {
    const index = new Map<string, StreamingLink>();

    for (const entry of entries) {
      if (!entry) continue;

      const yearValue = Number(entry.year);
      if (!Number.isFinite(yearValue)) continue;

      const divisionSource = entry.division_slug ?? entry.division;
      const bandSource = entry.band_slug ?? entry.band;
      const resultPieceSource = entry.result_piece_slug ?? entry.result_piece;

      if (!divisionSource || !bandSource || !resultPieceSource) continue;

      const divisionSlug = slugify(divisionSource);
      const bandSlug = slugify(bandSource);
      if (!divisionSlug || divisionSlug === 'uidentifisert' || !bandSlug || bandSlug === 'uidentifisert') {
        continue;
      }

      const pieceSlugs = new Set<string>();

      const primaryPieceSlug = slugify(resultPieceSource);
      if (primaryPieceSlug && primaryPieceSlug !== 'uidentifisert') {
        pieceSlugs.add(primaryPieceSlug);
      }

      if (entry.alternate_result_piece_slugs && Array.isArray(entry.alternate_result_piece_slugs)) {
        for (const rawSlug of entry.alternate_result_piece_slugs) {
          const normalized = rawSlug ? slugify(rawSlug) : '';
          if (normalized && normalized !== 'uidentifisert') {
            pieceSlugs.add(normalized);
          }
        }
      }

      if (entry.result_piece && entry.result_piece.trim()) {
        const derivedSlug = slugify(entry.result_piece);
        if (derivedSlug && derivedSlug !== 'uidentifisert') {
          pieceSlugs.add(derivedSlug);
        }
      }

      if (!pieceSlugs.size) continue;

      const spotifyUrl = typeof entry.spotify === 'string' && entry.spotify.trim().length > 0 ? entry.spotify.trim() : null;
      const appleUrl = typeof entry.apple_music === 'string' && entry.apple_music.trim().length > 0
        ? entry.apple_music.trim()
        : null;

      if (!spotifyUrl && !appleUrl) continue;

      const link: StreamingLink = {
        spotify: spotifyUrl,
        apple_music: appleUrl,
        album: entry.album?.trim() ?? null,
        recording_title: entry.recording_title?.trim() ?? null
      };

      for (const pieceSlug of pieceSlugs) {
        const key = `${yearValue}|${divisionSlug}|${bandSlug}|${pieceSlug}`;
        index.set(key, link);
      }
    }

    return index;
  }

  function findStreamingLinkForPiece(entry: BandEntry, bandName: string, pieceName: string): StreamingLink | null {
    if (!pieceStreamingIndex.size) return null;

    const divisionSlug = slugify(entry.division);
    const bandSlug = slugify(bandName);
    if (!divisionSlug || divisionSlug === 'uidentifisert' || !bandSlug || bandSlug === 'uidentifisert') {
      return null;
    }

    const keyPrefix = `${entry.year}|${divisionSlug}|${bandSlug}`;
    let candidateSlugs = getCandidateSlugs(pieceName, bandName);

    if (!candidateSlugs.length) {
      const fallbackSlug = slugify(pieceName);
      candidateSlugs = fallbackSlug && fallbackSlug !== 'uidentifisert' ? [fallbackSlug] : [];
    }

    for (const pieceSlug of candidateSlugs) {
      const key = `${keyPrefix}|${pieceSlug}`;
      const link = pieceStreamingIndex.get(key);
      if (link) {
        return link;
      }
    }

    return null;
  }

  const QUOTE_CHARS = /["'«»“”„‟]/g;
  const PARENTHESIS_CONTENT = /\([^)]*\)/g;

  function stripParenthetical(value: string): string {
    return value.replace(PARENTHESIS_CONTENT, ' ');
  }

  function normalizePieceTitle(value: string): string {
    return value.replace(QUOTE_CHARS, '').replace(/\s+/g, ' ').trim().toLowerCase();
  }

  function getCandidateSlugs(name: string, bandName?: string): string[] {
    const trimmed = name.trim();
    if (!trimmed) return [];

    const variants = new Set<string>();
    const baseSlug = slugify(trimmed);
    if (baseSlug && baseSlug !== 'uidentifisert') variants.add(baseSlug);

    const withoutParentheses = stripParenthetical(trimmed);
    const slugWithoutParentheses = slugify(withoutParentheses);
    if (slugWithoutParentheses && slugWithoutParentheses !== 'uidentifisert') {
      variants.add(slugWithoutParentheses);
    }

    const cleaned = normalizePieceTitle(trimmed);
    const slugDashNormalized = slugify(cleaned.replace(/[-–—]/g, ' '));
    if (slugDashNormalized && slugDashNormalized !== 'uidentifisert') {
      variants.add(slugDashNormalized);
    }

    const slugColonNormalized = slugify(cleaned.replace(/[:;·]/g, ' '));
    if (slugColonNormalized && slugColonNormalized !== 'uidentifisert') {
      variants.add(slugColonNormalized);
    }

    const baseTitleCandidates: string[] = [];
    if (withoutParentheses.includes('-')) {
      baseTitleCandidates.push(withoutParentheses.split(/[-–—]/)[0]);
    }
    if (withoutParentheses.includes(':')) {
      baseTitleCandidates.push(withoutParentheses.split(':')[0]);
    }

    for (const candidate of baseTitleCandidates) {
      const slugCandidate = slugify(candidate);
      if (slugCandidate && slugCandidate !== 'uidentifisert') {
        variants.add(slugCandidate);
      }
    }

    // Add variants with band name appended (for test pieces where streaming data includes band name)
    if (bandName && bandName.trim()) {
      const cleanBandName = bandName.trim();
      // Try: "Piece Name - Band Name"
      const withDashBand = `${trimmed} - ${cleanBandName}`;
      const slugWithBand = slugify(withDashBand);
      if (slugWithBand && slugWithBand !== 'uidentifisert') {
        variants.add(slugWithBand);
      }
      // Try: "Piece Name Band Name" (no separator)
      const withSpaceBand = `${trimmed} ${cleanBandName}`;
      const slugWithSpaceBand = slugify(withSpaceBand);
      if (slugWithSpaceBand && slugWithSpaceBand !== 'uidentifisert') {
        variants.add(slugWithSpaceBand);
      }
    }

    return Array.from(variants);
  }

  function findComposerForPiece(name: string, index: Map<string, PieceMetadataEntry[]>): string | null {
    const candidateSlugs = getCandidateSlugs(name);
    if (!candidateSlugs.length) return null;

    const normalizedName = normalizePieceTitle(name);
    const normalizedNameNoParentheses = normalizePieceTitle(stripParenthetical(name));

    for (const slug of candidateSlugs) {
      const bucket = index.get(slug);
      if (!bucket || bucket.length === 0) continue;

      if (bucket.length === 1) {
        return bucket[0].composer ?? null;
      }

      const exactMatch = bucket.find(
        (entry) => normalizePieceTitle(entry.title) === normalizedName
      );
      if (exactMatch) return exactMatch.composer ?? null;

      const baseMatch = bucket.find(
        (entry) => normalizePieceTitle(stripParenthetical(entry.title)) === normalizedNameNoParentheses
      );
      if (baseMatch) return baseMatch.composer ?? null;

      return bucket[0].composer ?? null;
    }

    return null;
  }

  function cloneEntry(entry: BandEntry, bandName?: string): ConductorPlacement {
    const clonedPieces = Array.isArray(entry.pieces)
      ? [...entry.pieces]
      : entry.pieces != null
        ? [`${entry.pieces}`.trim()].filter(Boolean)
        : [];

    const clone: ConductorPlacement = {
      ...entry,
      pieces: clonedPieces,
      conductor: entry.conductor
    };

    if (bandName) {
      clone.band_name = bandName;
    }

    return clone;
  }

  function buildConductorRecords(bands: BandRecord[]): BandRecord[] {
    const records = new Map<string, {
      name: string;
      slug: string;
      years: Map<number, { entries: ConductorPlacement[] }>;
    }>();

    for (const band of bands) {
      for (const entry of band.entries) {
        const rawName = entry.conductor?.trim();
        if (!rawName) continue;

        const slug = slugify(rawName);
        let record = records.get(slug);
        if (!record) {
          record = { name: rawName, slug, years: new Map() };
          records.set(slug, record);
        }

        let yearBucket = record.years.get(entry.year);
        if (!yearBucket) {
          yearBucket = { entries: [] };
          record.years.set(entry.year, yearBucket);
        }

        yearBucket.entries.push(cloneEntry(entry, band.name));
      }
    }

    return Array.from(records.values())
      .map((record) => ({
        name: record.name,
        slug: record.slug,
        entries: Array.from(record.years.entries())
          .map(([year, bucket]) => {
            const sortedEntries = [...bucket.entries].sort((a, b) => {
              const aPos = a.absolute_position ?? Number.POSITIVE_INFINITY;
              const bPos = b.absolute_position ?? Number.POSITIVE_INFINITY;
              if (aPos !== bPos) return aPos - bPos;
              return (a.rank ?? Number.POSITIVE_INFINITY) - (b.rank ?? Number.POSITIVE_INFINITY);
            });

            const primary = {
              ...sortedEntries[0],
              year,
              conductor: record.name,
              aggregate_entries: sortedEntries
            } satisfies ConductorPlacement & { aggregate_entries: ConductorPlacement[] };

            return primary;
          })
          .sort((a, b) => a.year - b.year)
      }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }

  // Helper function to add Elite test piece performances for brass bands
  // This is kept separate from own-choice piece logic to maintain clarity
  function addEliteTestPiecePerformances(
    records: Map<string, PieceRecord>,
    bands: BandRecord[],
    eliteTestPiecesData: EliteTestPiecesData | null
  ): void {
    if (!eliteTestPiecesData?.test_pieces) return;

    // Group entries by year for efficient lookups
    const entriesByYear = new Map<number, Array<{ band: string; entry: BandEntry }>>();
    for (const band of bands) {
      for (const entry of band.entries) {
        if (!entriesByYear.has(entry.year)) {
          entriesByYear.set(entry.year, []);
        }
        entriesByYear.get(entry.year)!.push({ band: band.name, entry });
      }
    }

    // Process each year that has a test piece
    for (const [yearStr, testPieceData] of Object.entries(eliteTestPiecesData.test_pieces)) {
      const year = Number(yearStr);
      if (!entriesByYear.has(year)) continue;

      const pieceName = testPieceData.piece;
      const composer = testPieceData.composer;
      const pieceSlug = slugify(pieceName);

      // Find all Elite division entries for this year
      const yearEntries = entriesByYear.get(year)!;
      const eliteEntries = yearEntries.filter(({ entry }) => 
        entry.division.toLowerCase() === 'elite'
      );

      if (eliteEntries.length === 0) continue;

      // Get or create the piece record
      let record = records.get(pieceSlug);
      if (!record) {
        const composerNames = composer ? extractComposerNames(composer) : [];
        record = {
          name: pieceName,
          slug: pieceSlug,
          composer: composer ?? null,
          composerNames,
          performances: []
        };
        records.set(pieceSlug, record);
      } else if (!record.composer && composer) {
        // Update composer info if not already set
        record.composer = composer;
        record.composerNames = extractComposerNames(composer);
      }

      // Add a performance for each Elite band
      for (const { band, entry } of eliteEntries) {
        const streaming = findStreamingLinkForPiece(entry, band, pieceName);
        record.performances.push({ band, entry, streaming });
      }
    }
  }

  function buildPieceRecords(
    bands: BandRecord[],
    composerIndex: Map<string, PieceMetadataEntry[]>,
    eliteTestPiecesData: EliteTestPiecesData | null,
    currentBandType: BandType
  ): PieceRecord[] {
    const records = new Map<string, PieceRecord>();

    // First, process all own-choice pieces from band entries
    for (const band of bands) {
      for (const entry of band.entries) {
        const pieces = Array.isArray(entry.pieces)
          ? entry.pieces
          : entry.pieces != null
            ? [`${entry.pieces}`]
            : [];

        for (const rawPiece of pieces) {
          const name = rawPiece.trim();
          if (!name) continue;

          const slug = slugify(name);
          let record = records.get(slug);
          const composerRaw = findComposerForPiece(name, composerIndex);
          const composerNames = composerRaw ? extractComposerNames(composerRaw) : [];
          const composerDisplay = composerNames.length > 0 ? composerNames.join(', ') : null;

          if (!record) {
            record = { name, slug, composer: composerDisplay, composerNames, performances: [] };
            records.set(slug, record);
          } else if ((!record.composer || !(record.composerNames?.length)) && composerDisplay) {
            record.composer = composerDisplay;
            record.composerNames = composerNames;
          }

          const streaming = findStreamingLinkForPiece(entry, band.name, name);
          record.performances.push({ band: band.name, entry, streaming });
        }
      }
    }

    // For brass bands, also add Elite test piece performances
    if (currentBandType === 'brass') {
      addEliteTestPiecePerformances(records, bands, eliteTestPiecesData);
    }

    return Array.from(records.values()).map((record) => ({
      ...record,
      performances: record.performances.map(({ band, entry, streaming }) => ({
        band,
        entry: { ...entry, pieces: [...entry.pieces] },
        streaming: streaming ?? null
      }))
    })).sort((a, b) => a.name.localeCompare(b.name));
  }

  function buildComposerRecords(pieces: PieceRecord[]): ComposerRecord[] {
    const records = new Map<string, {
      name: string;
      slug: string;
      normalized: string;
      pieces: Map<string, { name: string; slug: string }>;
    }>();

    for (const piece of pieces) {
      const composerNames = piece.composerNames && piece.composerNames.length > 0
        ? piece.composerNames
        : extractComposerNames(piece.composer ?? null);
      if (!composerNames.length) continue;

      for (const rawName of composerNames) {
        const normalizedName = normalizeComposerName(rawName);
        if (!normalizedName) continue;
        const slug = slugify(normalizedName);
        if (!slug || slug === 'uidentifisert') continue;

        let record = records.get(slug);
        if (!record) {
          record = {
            name: normalizedName,
            slug,
            normalized: normalizedName.toLowerCase(),
            pieces: new Map()
          };
          records.set(slug, record);
        }

        if (!record.pieces.has(piece.slug)) {
          record.pieces.set(piece.slug, { name: piece.name, slug: piece.slug });
        }
      }
    }

    const sorted = Array.from(records.values()).map((record) => ({
      name: record.name,
      slug: record.slug,
      normalized: record.normalized,
      pieces: Array.from(record.pieces.values()).sort((a, b) => a.name.localeCompare(b.name))
    })).sort((a, b) => a.name.localeCompare(b.name));

    composerPieceIndex = new Map(sorted.map((record) => [record.slug, record]));
    return sorted;
  }

  function getUrlParamKey(view: ViewType): string {
    if (view === 'data') return 'data'; // fallback for data view
    return URL_PARAM_KEYS[view as keyof typeof URL_PARAM_KEYS];
  }

  function getModeFromURL(): 'absolute' | 'relative' {
    if (typeof window === 'undefined') return DEFAULT_MODE;
    const params = new URLSearchParams(window.location.search);
    const raw = params.get(URL_MODE_KEY);
    const normalized = raw ? raw.toLowerCase() : null;
    return normalized === 'absolute' ? 'absolute' : 'relative';
  }

  function getYAxisScaleFromURL(): 'fitted' | 'full' {
    if (typeof window === 'undefined') return DEFAULT_YAXIS_SCALE;
    const params = new URLSearchParams(window.location.search);
    const raw = params.get(URL_YAXIS_KEY);
    const normalized = raw ? raw.toLowerCase() : null;
    return normalized === 'full' ? 'full' : 'fitted';
  }

  function resolveInitialTheme(): Theme {
    if (typeof window === 'undefined') return 'dark';
    try {
      const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
      if (stored === 'light' || stored === 'dark') {
        return stored;
      }
    } catch (err) {
      console.error('Kunne ikke lese lagret tema', err);
    }
    const prefersLight = window.matchMedia?.('(prefers-color-scheme: light)').matches;
    return prefersLight ? 'light' : 'dark';
  }

  function applyThemePreference(nextTheme: Theme): void {
    if (typeof document === 'undefined') return;
    if (nextTheme === 'dark') {
      document.documentElement.removeAttribute('data-theme');
    } else {
      document.documentElement.dataset.theme = 'light';
    }
  }

  function getBandTypeFromURL(): BandType {
    if (typeof window === 'undefined') return DEFAULT_BAND_TYPE;
    const params = new URLSearchParams(window.location.search);
    const raw = params.get(URL_BAND_TYPE_KEY)?.toLowerCase();
    if (raw === 'brass' || raw === 'brassband') return 'brass';
    if (raw === 'wind' || raw === 'janitsjar') return 'wind';
    return DEFAULT_BAND_TYPE;
  }

  function resolveInitialBandType(): BandType {
    if (typeof window === 'undefined') return DEFAULT_BAND_TYPE;
    
    // First priority: URL parameter
    const params = new URLSearchParams(window.location.search);
    const urlType = params.get(URL_BAND_TYPE_KEY)?.toLowerCase();
    if (urlType === 'brass' || urlType === 'brassband') {
      return 'brass';
    }
    if (urlType === 'wind' || urlType === 'janitsjar') {
      return 'wind';
    }
    
    // Second priority: localStorage
    try {
      const stored = window.localStorage.getItem(BAND_TYPE_STORAGE_KEY);
      if (stored === 'wind' || stored === 'brass') {
        return stored;
      }
    } catch (err) {
      console.error('Kunne ikke lese lagret korptype', err);
    }
    
    return DEFAULT_BAND_TYPE;
  }

  function applyBandTypePreference(nextBandType: BandType): void {
    if (typeof document === 'undefined') return;
    document.documentElement.dataset.bandType = nextBandType;
  }

  function setTheme(nextTheme: Theme): void {
    theme = nextTheme;
    applyThemePreference(nextTheme);
    if (typeof window !== 'undefined') {
      try {
        window.localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
      } catch (err) {
        console.error('Kunne ikke lagre tema', err);
      }
    }
  }

  function setBandType(nextBandType: BandType, updateUrl: boolean = true): void {
    if (bandType === nextBandType) return;
    
    bandType = nextBandType;
    applyBandTypePreference(nextBandType);
    
    if (typeof window !== 'undefined') {
      try {
        window.localStorage.setItem(BAND_TYPE_STORAGE_KEY, nextBandType);
      } catch (err) {
        console.error('Kunne ikke lagre korptype', err);
      }
    }

    // Clear selections and URL params except band type
    selectedBands = [];
    selectedConductors = [];
    selectedPieces = [];
    selectedComposers = [];
    searchTerm = '';
    focusedIndex = -1;
    
    // Update URL with new band type
    if (updateUrl && typeof window !== 'undefined') {
      const params = new URLSearchParams();
      params.set(URL_BAND_TYPE_KEY, nextBandType);
      const newUrl = `${window.location.pathname}?${params.toString()}${window.location.hash}`;
      window.history.replaceState({}, '', newUrl);
    }

    // Reload data
    loading = true;
    error = null;
    dataset = null;
    conductorRecords = [];
    pieceRecords = [];
    composerRecords = [];
    pieceStreamingIndex = new Map();
    loadDataForBandType(nextBandType);
  }

  function closeMenu(): void {
    menuOpen = false;
  }

  function toggleMenu(): void {
    menuOpen = !menuOpen;
  }

  function closeModeMenu(): void {
    modeMenuOpen = false;
  }

  function toggleModeMenu(): void {
    modeMenuOpen = !modeMenuOpen;
  }

  function closeBandTypeMenu(): void {
    bandTypeMenuOpen = false;
  }

  function toggleBandTypeMenu(): void {
    bandTypeMenuOpen = !bandTypeMenuOpen;
  }

  function toggleTheme(): void {
    setTheme(theme === 'dark' ? 'light' : 'dark');
    closeMenu();
    closeModeMenu();
    closeBandTypeMenu();
  }

  function toggleBandType(): void {
    setBandType(bandType === 'wind' ? 'brass' : 'wind');
    closeBandTypeMenu();
    closeMenu();
    closeModeMenu();
  }

  function getViewFromURL(): ViewType {
    if (typeof window === 'undefined') return DEFAULT_VIEW;
    const params = new URLSearchParams(window.location.search);
    const raw = params.get(URL_VIEW_KEY)?.toLowerCase();
    if (!raw) return DEFAULT_VIEW;
    if (raw === 'conductors' || raw === 'dirigent' || raw === 'conductor') {
      return 'conductors';
    }
    if (raw === 'pieces' || raw === 'piece' || raw === 'stykke' || raw === 'stykker') {
      return 'pieces';
    }
    if (raw === 'composers' || raw === 'komponist' || raw === 'composer') {
      return 'composers';
    }
    if (raw === 'data' || raw === 'resultat' || raw === 'results') {
      return 'data';
    }
    return 'bands';
  }

  function getSlugsFromURL(view: ViewType): string[] {
    if (typeof window === 'undefined') return [];
    const params = new URLSearchParams(window.location.search);
    const raw = params.get(getUrlParamKey(view));
    if (!raw) return [];
    return raw
      .split(URL_SEPARATOR)
      .map((slug) => decodeURIComponent(slug.trim()))
      .filter(Boolean);
  }

  function findMatches<T extends { slug: string }>(records: T[], slugs: string[]): T[] {
    if (!records.length || !slugs.length) return [];
    const recordMap = new Map(records.map((record) => [record.slug, record] as const));
    return slugs
      .map((slug) => recordMap.get(slug) ?? recordMap.get(slug.toLowerCase()))
      .filter((record): record is T => Boolean(record));
  }

  function areSelectionsEqual<T extends { slug: string }>(a: T[], b: T[]): boolean {
    if (a.length !== b.length) return false;
    return a.every((record, index) => record.slug === b[index].slug);
  }

  function updateUrlState(): void {
    if (typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search);

    // Always include band type in URL
    params.set(URL_BAND_TYPE_KEY, bandType);

    const bandSlugs = selectedBands.map((band) => encodeURIComponent(band.slug)).join(URL_SEPARATOR);
    if (bandSlugs.length) {
      params.set(getUrlParamKey('bands'), bandSlugs);
    } else {
      params.delete(getUrlParamKey('bands'));
    }

    const conductorSlugs = selectedConductors
      .map((conductor) => encodeURIComponent(conductor.slug))
      .join(URL_SEPARATOR);
    if (conductorSlugs.length) {
      params.set(getUrlParamKey('conductors'), conductorSlugs);
    } else {
      params.delete(getUrlParamKey('conductors'));
    }

    const pieceSlugs = selectedPieces.map((piece) => encodeURIComponent(piece.slug)).join(URL_SEPARATOR);
    if (pieceSlugs.length) {
      params.set(getUrlParamKey('pieces'), pieceSlugs);
    } else {
      params.delete(getUrlParamKey('pieces'));
    }

    const composerSlugs = selectedComposers
      .map((composer) => encodeURIComponent(composer.slug))
      .join(URL_SEPARATOR);
    if (composerSlugs.length) {
      params.set(getUrlParamKey('composers'), composerSlugs);
    } else {
      params.delete(getUrlParamKey('composers'));
    }

    params.set(URL_MODE_KEY, yAxisMode);
    params.set(URL_YAXIS_KEY, yAxisScale);
    params.set(URL_VIEW_KEY, activeView);

    const query = params.toString();
    const newUrl = `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`;
    window.history.replaceState({}, '', newUrl);
  }

  function syncSelectionFromURL({ updateHistory = false } = {}): boolean {
    const modeFromUrl = getModeFromURL();
    const yAxisScaleFromUrl = getYAxisScaleFromURL();
    const viewFromUrl = getViewFromURL();
    const bandTypeFromUrl = getBandTypeFromURL();
    let stateChanged = false;

    // Handle band type change from URL
    if (bandTypeFromUrl !== bandType) {
      setBandType(bandTypeFromUrl, false);
      stateChanged = true;
      // Return early as setBandType will reload data
      return stateChanged;
    }

    if (modeFromUrl !== yAxisMode) {
      yAxisMode = modeFromUrl;
      stateChanged = true;
    }
    if (yAxisScaleFromUrl !== yAxisScale) {
      yAxisScale = yAxisScaleFromUrl;
      stateChanged = true;
    }
    if (viewFromUrl !== activeView) {
      activeView = viewFromUrl;
      stateChanged = true;
    }

    if (!dataset) {
      if (updateHistory) updateUrlState();
      return stateChanged;
    }

    const bandMatches = findMatches(dataset.bands, getSlugsFromURL('bands'));
    // Merge new selections with existing ones (add unique items)
    const mergedBands = [...selectedBands];
    for (const match of bandMatches) {
      if (!mergedBands.some(b => b.slug === match.slug)) {
        mergedBands.push(match);
      }
    }
    if (!areSelectionsEqual(selectedBands, mergedBands)) {
      selectedBands = mergedBands;
      stateChanged = true;
    }

    if (!conductorRecords.length) {
      conductorRecords = buildConductorRecords(dataset.bands);
    }
    const conductorMatches = findMatches(conductorRecords, getSlugsFromURL('conductors'));
    // Merge new selections with existing ones (add unique items)
    const mergedConductors = [...selectedConductors];
    for (const match of conductorMatches) {
      if (!mergedConductors.some(c => c.slug === match.slug)) {
        mergedConductors.push(match);
      }
    }
    if (!areSelectionsEqual(selectedConductors, mergedConductors)) {
      selectedConductors = mergedConductors;
      stateChanged = true;
    }

    if (!pieceRecords.length) {
      pieceRecords = buildPieceRecords(dataset.bands, pieceComposerIndex, eliteTestPieces, bandType);
      composerRecords = buildComposerRecords(pieceRecords);
    }
    const pieceMatches = findMatches(pieceRecords, getSlugsFromURL('pieces'));
    // Merge new selections with existing ones (add unique items)
    const mergedPieces = [...selectedPieces];
    for (const match of pieceMatches) {
      if (!mergedPieces.some(p => p.slug === match.slug)) {
        mergedPieces.push(match);
      }
    }
    if (!areSelectionsEqual(selectedPieces, mergedPieces)) {
      selectedPieces = mergedPieces;
      stateChanged = true;
    }

    if (!composerRecords.length) {
      composerRecords = buildComposerRecords(pieceRecords);
    }
    const composerMatches = findMatches(composerRecords, getSlugsFromURL('composers'));
    // Merge new selections with existing ones (add unique items)
    const mergedComposers = [...selectedComposers];
    for (const match of composerMatches) {
      if (!mergedComposers.some(c => c.slug === match.slug)) {
        mergedComposers.push(match);
      }
    }
    if (!areSelectionsEqual(selectedComposers, mergedComposers)) {
      selectedComposers = mergedComposers;
      stateChanged = true;
    }

    if (updateHistory) {
      updateUrlState();
    }

    return stateChanged;
  }

  function getSelectedSignature(): string {
    const bandSignature = selectedBands.map((band) => band.slug).join(URL_SEPARATOR);
    const conductorSignature = selectedConductors.map((conductor) => conductor.slug).join(URL_SEPARATOR);
    const pieceSignature = selectedPieces.map((piece) => piece.slug).join(URL_SEPARATOR);
    const composerSignature = selectedComposers.map((composer) => composer.slug).join(URL_SEPARATOR);
    return `${bandType}|${activeView}|${yAxisMode}|${yAxisScale}|${bandSignature}|${conductorSignature}|${pieceSignature}|${composerSignature}`;
  }

  function syncUrlIfReady(): void {
    if (!initialUrlSyncDone) return;
    const signature = getSelectedSignature();
    if (signature !== lastSyncedSignature) {
      updateUrlState();
      lastSyncedSignature = signature;
    }
  }

  function chooseRecord(record: BandRecord | PieceRecord | ComposerRecord): void {
    if (activeView === 'bands') {
      if (selectedBands.some((item) => item.slug === record.slug)) return;
      selectedBands = [...selectedBands, record as BandRecord];
    } else if (activeView === 'conductors') {
      if (selectedConductors.some((item) => item.slug === record.slug)) return;
      selectedConductors = [...selectedConductors, record as BandRecord];
    } else if (activeView === 'pieces') {
      const pieceRecord = record as PieceRecord;
      if (selectedPieces.some((item) => item.slug === pieceRecord.slug)) return;
      selectedPieces = [...selectedPieces, pieceRecord];
    } else if (activeView === 'composers') {
      const composerRecord = record as ComposerRecord;
      if (selectedComposers.some((item) => item.slug === composerRecord.slug)) return;
      selectedComposers = [...selectedComposers, composerRecord];
    }
    searchTerm = '';
    focusedIndex = -1;
    syncUrlIfReady();
  }

  function removeRecord(slug: string): void {
    if (activeView === 'bands') {
      selectedBands = selectedBands.filter((item) => item.slug !== slug);
    } else if (activeView === 'conductors') {
      selectedConductors = selectedConductors.filter((item) => item.slug !== slug);
    } else if (activeView === 'pieces') {
      selectedPieces = selectedPieces.filter((item) => item.slug !== slug);
    } else if (activeView === 'composers') {
      selectedComposers = selectedComposers.filter((item) => item.slug !== slug);
    }
    focusedIndex = -1;
    syncUrlIfReady();
  }

  function handleSubmit(): void {
    if (trimmed.length === 0) return;
    const exact = activeRecords.find((record: any) => record.name.toLowerCase() === lowered);
    if (exact) {
      chooseRecord(exact);
    } else if (suggestions.length > 0) {
      chooseRecord(suggestions[0]);
    }
  }

  function onInput(event: Event): void {
    searchTerm = (event.target as HTMLInputElement).value;
    focusedIndex = -1;
  }

  function handleKeyDown(event: KeyboardEvent): void {
    if (!suggestions.length) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      focusedIndex = (focusedIndex + 1) % suggestions.length;
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      focusedIndex = (focusedIndex - 1 + suggestions.length) % suggestions.length;
    } else if (event.key === 'Enter' && focusedIndex >= 0) {
      event.preventDefault();
      chooseRecord(suggestions[focusedIndex]);
    }
  }

  function setView(view: ViewType): void {
    if (view === activeView) {
      closeMenu();
      closeModeMenu();
      return;
    }
    activeView = view;
    searchTerm = '';
    focusedIndex = -1;
    closeMenu();
    closeModeMenu();
    syncUrlIfReady();
  }

  function setYAxisMode(mode: 'absolute' | 'relative'): void {
    if (yAxisMode === mode) {
      closeModeMenu();
      return;
    }
    yAxisMode = mode;
    closeModeMenu();
    syncUrlIfReady();
  }

  function setYAxisScale(scale: 'fitted' | 'full'): void {
    if (yAxisScale === scale) return;
    yAxisScale = scale;
    syncUrlIfReady();
  }

  async function loadEliteTestPieces() {
    try {
      const res = await fetch('data/elite_test_pieces.json', { cache: 'no-cache' });
      if (!res.ok) throw new Error('Failed to load elite_test_pieces.json');
      eliteTestPieces = await res.json();
    } catch (err) {
      console.error('Could not load Elite test pieces:', err);
      eliteTestPieces = null;
    }
  }

  async function loadDataForBandType(type: BandType) {
    try {
      const dataFile = type === 'wind' ? 'data/band_positions.json' : 'data/brass_positions.json';
      const metadataFile = type === 'wind' ? 'data/piece_metadata.json' : 'data/brass_piece_metadata.json';
      const streamingFile = 'data/piece_streaming_links.json';
      const [positionsResponse, metadataResponse, streamingResponse] = await Promise.all([
        fetch(dataFile),
        fetch(metadataFile),
        fetch(streamingFile)
      ]);
      
      // Load Elite test pieces for brass bands
      if (type === 'brass' && eliteTestPieces === null) {
        await loadEliteTestPieces();
      }

      if (!positionsResponse.ok) {
        throw new Error(`Kunne ikke laste data (status ${positionsResponse.status})`);
      }

      let metadataEntries: PieceMetadataEntry[] = [];
      if (metadataResponse.ok) {
        try {
          const metadata = (await metadataResponse.json()) as PieceMetadataDataset;
          const entries = Array.isArray(metadata.pieces) ? metadata.pieces : [];
          metadataEntries = entries
            .filter((entry): entry is PieceMetadataEntry => Boolean(entry?.title && entry?.slug))
            .map((entry) => ({
              title: entry.title.trim(),
              slug: entry.slug.trim(),
              composer: entry.composer ?? null
            }));
        } catch (metadataError) {
          console.warn('Kunne ikke tolke stykke-metadata', metadataError);
        }
      } else {
        console.warn(`Kunne ikke laste stykke-metadata (status ${metadataResponse.status})`);
      }

      pieceComposerIndex = buildPieceComposerIndex(metadataEntries);

      let streamingEntries: PieceStreamingEntry[] = [];
      if (streamingResponse.ok) {
        try {
          const streamingDataset = (await streamingResponse.json()) as PieceStreamingDataset;
          const rawEntries = streamingDataset?.[type];
          if (Array.isArray(rawEntries)) {
            streamingEntries = rawEntries.filter((entry): entry is PieceStreamingEntry => Boolean(entry));
          }
        } catch (streamingError) {
          console.warn('Kunne ikke tolke opptakslenker', streamingError);
        }
      } else if (streamingResponse.status !== 404) {
        console.warn(`Kunne ikke laste opptakslenker (status ${streamingResponse.status})`);
      }

      pieceStreamingIndex = buildPieceStreamingIndex(streamingEntries);

      const parsedDataset = (await positionsResponse.json()) as BandDataset;
      dataset = parsedDataset;
      conductorRecords = buildConductorRecords(parsedDataset.bands);
      pieceRecords = buildPieceRecords(parsedDataset.bands, pieceComposerIndex, eliteTestPieces, type);
      composerRecords = buildComposerRecords(pieceRecords);
      syncSelectionFromURL({ updateHistory: false });
      lastSyncedSignature = getSelectedSignature();
      updateUrlState();
      initialUrlSyncDone = true;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Ukjent feil ved lasting av data.';
    } finally {
      loading = false;
    }
  }

  onMount(async () => {
    const initialTheme = resolveInitialTheme();
    theme = initialTheme;
    applyThemePreference(initialTheme);

    const initialBandType = resolveInitialBandType();
    bandType = initialBandType;
    applyBandTypePreference(initialBandType);

    await loadDataForBandType(initialBandType);
  });

  onMount(() => {
    const handlePopState = () => {
      if (!dataset) return;
      syncSelectionFromURL({ updateHistory: false });
      lastSyncedSignature = getSelectedSignature();
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  });

  onMount(() => {
    // Intercept clicks on entity links to merge selections instead of replacing
    const handleLinkClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement;
      const link = target.closest('a.entity-link, a.program-link');
      
      if (!link || !(link instanceof HTMLAnchorElement)) return;
      if (event.ctrlKey || event.metaKey || event.shiftKey) return; // Allow normal link behavior with modifiers
      
      try {
        const url = new URL(link.href);
        const params = new URLSearchParams(url.search);
        
        // Check if this is an entity selection link
        const bandSlug = params.get('band');
        const conductorSlug = params.get('conductor');
        const pieceSlug = params.get('piece');
        const composerSlug = params.get('composer');
        const newBandType = params.get('type');
        const newView = params.get('view');
        
        // If band type is changing, allow normal navigation (will clear selections)
        if (newBandType && newBandType !== bandType) {
          return;
        }
        
        // Prevent default navigation
        event.preventDefault();
        
        // Get current selections
        const currentParams = new URLSearchParams(window.location.search);
        const currentBands = currentParams.get('band')?.split(',').filter(Boolean) || [];
        const currentConductors = currentParams.get('conductor')?.split(',').filter(Boolean) || [];
        const currentPieces = currentParams.get('piece')?.split(',').filter(Boolean) || [];
        const currentComposers = currentParams.get('composer')?.split(',').filter(Boolean) || [];
        
        // Merge new selection with existing (add if not already present)
        if (bandSlug && !currentBands.includes(bandSlug)) {
          currentBands.push(bandSlug);
        }
        if (conductorSlug && !currentConductors.includes(conductorSlug)) {
          currentConductors.push(conductorSlug);
        }
        if (pieceSlug && !currentPieces.includes(pieceSlug)) {
          currentPieces.push(pieceSlug);
        }
        if (composerSlug && !currentComposers.includes(composerSlug)) {
          currentComposers.push(composerSlug);
        }
        
        // Build new URL with merged selections
        const newParams = new URLSearchParams(currentParams);
        
        if (currentBands.length) {
          newParams.set('band', currentBands.join(','));
        }
        if (currentConductors.length) {
          newParams.set('conductor', currentConductors.join(','));
        }
        if (currentPieces.length) {
          newParams.set('piece', currentPieces.join(','));
        }
        if (currentComposers.length) {
          newParams.set('composer', currentComposers.join(','));
        }
        
        // Set view if specified in link
        if (newView) {
          newParams.set('view', newView);
        }
        
        // Navigate to merged URL
        const newUrl = `${window.location.pathname}?${newParams.toString()}${window.location.hash}`;
        window.history.pushState({}, '', newUrl);
        
        // Trigger sync
        syncSelectionFromURL({ updateHistory: false });
        lastSyncedSignature = getSelectedSignature();
      } catch (err) {
        console.error('Error handling link click:', err);
      }
    };
    
    document.addEventListener('click', handleLinkClick);
    return () => document.removeEventListener('click', handleLinkClick);
  });

  $effect(() => {
    document.title = bandType === 'wind' ? 'NM Janitsjar - Resultatoversikt' : 'NM Brass - Resultatoversikt';
  });

  let trimmed = $derived(searchTerm.trim());
  let lowered = $derived(trimmed.toLowerCase());
  let isEntityView = $derived(
    activeView === 'bands' ||
    activeView === 'conductors' ||
    activeView === 'pieces' ||
    activeView === 'composers'
  );
  let activeRecords = $derived(isEntityView
    ? activeView === 'bands'
      ? dataset?.bands ?? []
      : activeView === 'conductors'
        ? conductorRecords
        : activeView === 'pieces'
          ? pieceRecords
          : composerRecords
    : []);
  let activeSelection = $derived(activeView === 'bands'
    ? selectedBands
    : activeView === 'conductors'
      ? selectedConductors
      : activeView === 'pieces'
        ? selectedPieces
        : activeView === 'composers'
          ? selectedComposers
          : []);
  let suggestions =
    $derived(isEntityView && activeRecords && lowered.length >= 2
      ? activeRecords
          .filter(
            (record: any) =>
              record.name.toLowerCase().includes(lowered) &&
              !activeSelection.some((selected) => selected.slug === record.slug)
          )
          .slice(0, 10)
      : []);

  let years = $derived(dataset ? dataset.metadata.years : []);
  let maxFieldSize = $derived(dataset ? dataset.metadata.max_field_size : 0);
  let entityCount = $derived(isEntityView
    ? activeView === 'bands'
      ? dataset?.bands.length ?? 0
      : activeView === 'conductors'
        ? conductorRecords.length
        : activeView === 'pieces'
          ? pieceRecords.length
          : composerRecords.length
    : 0);
  let entityLabel = $derived(activeView === 'bands'
    ? 'korps'
    : activeView === 'conductors'
      ? 'dirigenter'
      : activeView === 'pieces'
        ? 'stykker'
        : 'komponister');
  let coverageDescription = $derived(dataset
    ? `Dekker ${entityCount} ${entityLabel} · ${years.length} år (${dataset.metadata.min_year}–${dataset.metadata.max_year})`
    : '');

  let searchPlaceholder = $derived(activeView === 'bands'
    ? 'Begynn å skrive et korpsnavn (minst 2 bokstaver)…'
    : activeView === 'conductors'
      ? 'Begynn å skrive et dirigentnavn (minst 2 bokstaver)…'
      : activeView === 'pieces'
        ? 'Begynn å skrive en stykketittel (minst 2 bokstaver)…'
        : activeView === 'composers'
          ? 'Begynn å skrive et komponistnavn (minst 2 bokstaver)…'
          : '');
  let searchLabel = $derived(activeView === 'bands'
    ? 'Søk etter korps'
    : activeView === 'conductors'
      ? 'Søk etter dirigent'
      : activeView === 'pieces'
        ? 'Søk etter musikkstykke'
        : 'Søk etter komponist');
  let suggestionsLabel = $derived(activeView === 'bands'
    ? 'Korpsforslag'
    : activeView === 'conductors'
      ? 'Dirigentforslag'
      : activeView === 'pieces'
        ? 'Stykke-forslag'
        : 'Komponistforslag');
  let selectionLabel = $derived(activeView === 'bands'
    ? 'Valgte korps'
    : activeView === 'conductors'
      ? 'Valgte dirigenter'
      : activeView === 'pieces'
        ? 'Valgte stykker'
        : 'Valgte komponister');
  let emptyStateTitle = $derived(activeView === 'bands'
    ? 'Ingen korps valgt ennå'
    : activeView === 'conductors'
      ? 'Ingen dirigenter valgt ennå'
      : activeView === 'pieces'
        ? 'Ingen stykker valgt ennå'
        : 'Ingen komponister valgt ennå');
  let emptyStateBody = $derived(activeView === 'bands'
    ? 'Finn et navn i søkefeltet for å tegne kurven for samlet plassering.'
    : activeView === 'conductors'
      ? 'Finn en dirigent i søkefeltet for å tegne kurven for samlet plassering.'
      : activeView === 'pieces'
        ? 'Finn et musikkstykke i søkefeltet for å se alle registrerte fremføringer.'
        : 'Finn en komponist i søkefeltet for å se hvilke stykker vi har registrert av dem.');
  let leadText = $derived(activeView === 'bands'
    ? bandType === 'wind'
      ? 'Søk etter et janitsjarkorps for å se hvordan den samlede plasseringen utvikler seg år for år, på tvers av alle divisjoner.'
      : 'Søk etter et brassband for å se hvordan den samlede plasseringen utvikler seg år for år, på tvers av alle divisjoner.'
    : activeView === 'conductors'
      ? 'Søk etter en dirigent for å se hvordan deres beste plassering utvikler seg år for år, basert på korpsene de dirigerte.'
      : activeView === 'pieces'
        ? 'Søk etter et musikkstykke for å se alle fremføringer vi har registrert.'
        : activeView === 'composers'
          ? 'Søk etter en komponist for å se hvilke NM-stykker de står bak.'
          : 'Velg et år og en divisjon for å vise resultatlisten i den valgte finalen.');
  let themeToggleLabel = $derived(theme === 'dark' ? 'Bytt til lyst tema' : 'Bytt til mørkt tema');
  let themeToggleText = $derived(theme === 'dark' ? 'Mørk' : 'Lys');
  let themeToggleIcon = $derived(theme === 'dark' ? '🌙' : '☀️');
  let bandTypeToggleLabel = $derived(bandType === 'wind' ? 'Bytt til brassband' : 'Bytt til janitsjarkorps');
  let bandTypeToggleText = $derived(bandType === 'wind' ? 'Janitsjar' : 'Brass');
  let bandTypeToggleIcon = $derived(bandType === 'wind' ? '🎷' : '🎺');
  let menuToggleLabel = $derived(menuOpen ? 'Lukk meny' : 'Åpne meny');
  let modeMenuToggleLabel = $derived(modeMenuOpen ? 'Lukk tilpassingsmeny' : 'Åpne tilpassingsmeny');

  let chartHeading =
    $derived(activeSelection.length === 1
      ? activeSelection[0].name
      : activeSelection.length > 1
        ? `${activeSelection.length} ${entityLabel} valgt`
        : '');

  let comparisonSummary =
    $derived(activeSelection.length > 1 ? activeSelection.map((record) => record.name).join(' · ') : '');

  let pieceSelection = $derived(activeView === 'pieces' ? (activeSelection as PieceRecord[]) : []);
  let composerSelection = $derived(activeView === 'composers' ? (activeSelection as ComposerRecord[]) : []);
  let chartSelection =
    $derived(activeView === 'bands' || activeView === 'conductors'
      ? (activeSelection as BandRecord[])
      : []);
</script>

<main>
  <header class="page-header">
    <div class="page-header__title">
      <h1>{bandType === 'wind' ? 'NM Janitsjar' : 'NM Brass'}</h1>
      <button
        class="menu-toggle"
        type="button"
        aria-label={menuToggleLabel}
        aria-expanded={menuOpen}
        aria-controls="primary-controls"
        onclick={toggleMenu}
      >
        <span class="menu-toggle__icon" aria-hidden="true">☰</span>
        <span class="menu-toggle__text">Meny</span>
      </button>
    </div>
    <div
      class="header-controls"
      id="primary-controls"
      class:header-controls--mobile-open={menuOpen}
    >
      <div class="view-toggle" role="group" aria-label="Bytt visning">
        {#each viewOrder as view}
          {#if view !== 'repertoire' || bandType === 'wind'}
            <button
              type="button"
              class:selected={activeView === view}
              aria-pressed={activeView === view}
              onclick={() => setView(view)}
            >
              {viewLabels[view]}
            </button>
          {/if}
        {/each}
      </div>
      <button
        class="band-type-toggle"
        type="button"
        onclick={toggleBandType}
        aria-label={bandTypeToggleLabel}
      >
        <span aria-hidden="true">{bandTypeToggleIcon}</span>
        <span class="band-type-toggle__text">{bandTypeToggleText}</span>
      </button>
      <button
        class="theme-toggle"
        type="button"
        onclick={toggleTheme}
        aria-label={themeToggleLabel}
      >
        <span aria-hidden="true">{themeToggleIcon}</span>
        <span class="theme-toggle__text">{themeToggleText}</span>
      </button>
    </div>
  </header>
  <p class="lead">{leadText}</p>

  {#if isEntityView}
    <form class="search" onsubmit={preventDefault(handleSubmit)}>
      <label class="sr-only" for="entity-search">{searchLabel}</label>
      <input
        id="entity-search"
        type="search"
        placeholder={searchPlaceholder}
        bind:value={searchTerm}
        oninput={onInput}
        onkeydown={handleKeyDown}
        autocomplete="off"
      />
    </form>

    {#if suggestions.length > 0}
      <div class="suggestions" role="listbox" aria-label={suggestionsLabel}>
        {#each suggestions as record, index}
          <div
            class="suggestion {index === focusedIndex ? 'active' : ''}"
            role="option"
            tabindex="-1"
            aria-selected={index === focusedIndex}
            onmousedown={preventDefault(() => chooseRecord(record))}
          >
            {record.name}
          </div>
        {/each}
      </div>
    {/if}
  {/if}

  {#if loading}
    <section class="status">Laster data…</section>
  {:else if error}
    <section class="status error">{error}</section>
  {:else if !dataset}
    <section class="status">Ingen data tilgjengelig.</section>
  {:else if isEntityView}
    {#if activeSelection.length > 0}
      {#if activeView === 'pieces'}
        <PiecePerformances pieces={pieceSelection} {bandType} />
      {:else if activeView === 'composers'}
        <ComposerPieces composers={composerSelection} {bandType} />
      {:else}
        <section class="chart-card">
          <div class="mode-toggles-container">
            <div class="mode-toggle">
              <span class="mode-toggle__label">Plassering:</span>
              <div class="mode-toggle__buttons" role="group" aria-label="Velg plasseringsvisning">
                <button
                  type="button"
                  class:selected={yAxisMode === 'absolute'}
                  aria-pressed={yAxisMode === 'absolute'}
                  onclick={() => setYAxisMode('absolute')}
                >
                  Absolutt
                </button>
                <button
                  type="button"
                  class:selected={yAxisMode === 'relative'}
                  aria-pressed={yAxisMode === 'relative'}
                  onclick={() => setYAxisMode('relative')}
                >
                  Relativ
                </button>
              </div>
            </div>
            <div class="mode-toggle">
              <span class="mode-toggle__label">Y-akse:</span>
              <div class="mode-toggle__buttons" role="group" aria-label="Velg y-akse skalering">
                <button
                  type="button"
                  class:selected={yAxisScale === 'fitted'}
                  aria-pressed={yAxisScale === 'fitted'}
                  onclick={() => setYAxisScale('fitted')}
                >
                  Tilpasset
                </button>
                <button
                  type="button"
                  class:selected={yAxisScale === 'full'}
                  aria-pressed={yAxisScale === 'full'}
                  onclick={() => setYAxisScale('full')}
                >
                  Full
                </button>
              </div>
            </div>
            <button
              type="button"
              class="mode-toggle__menu-trigger"
              aria-label={modeMenuToggleLabel}
              aria-expanded={modeMenuOpen}
              aria-controls="mode-toggle-menu"
              onclick={toggleModeMenu}
            >
              Tilpass
            </button>
            {#if modeMenuOpen}
              <div class="mode-toggle__menu" id="mode-toggle-menu" role="menu">
                <button
                  type="button"
                  class:selected={yAxisMode === 'absolute'}
                  aria-pressed={yAxisMode === 'absolute'}
                  onclick={() => setYAxisMode('absolute')}
                >
                  Absolutt
                </button>
                <button
                  type="button"
                  class:selected={yAxisMode === 'relative'}
                  aria-pressed={yAxisMode === 'relative'}
                  onclick={() => setYAxisMode('relative')}
                >
                  Relativ
                </button>
              </div>
            {/if}
          </div>
          <div class="chart-header">
            <h2>{chartHeading}</h2>
            <p>{coverageDescription}</p>
            {#if comparisonSummary}
              <p class="comparison-summary">{comparisonSummary}</p>
            {/if}
          </div>
          <BandTrajectoryChart
            {years}
            {maxFieldSize}
            bands={chartSelection}
            yMode={yAxisMode}
            {yAxisScale}
            showConductorMarkers={activeView === 'bands'}
          />
        </section>
      {/if}
      <div class="selected-entities selected-entities--below" role="list" aria-label={selectionLabel}>
        {#each activeSelection as record, index}
          <span class="selected-entity" role="listitem">
            <span class="selected-entity__index">{index + 1}</span>
            <span class="selected-entity__name">{record.name}</span>
            <button type="button" aria-label={`Fjern ${record.name}`} onclick={() => removeRecord(record.slug)}>
              ×
            </button>
          </span>
        {/each}
      </div>
      {#if activeView === 'bands'}
        <BandPerformances
          bands={chartSelection}
          {bandType}
          streamingResolver={findStreamingLinkForPiece}
          {eliteTestPieces}
        />
      {:else if activeView === 'conductors'}
        <ConductorPerformances
          conductors={chartSelection}
          {bandType}
          streamingResolver={findStreamingLinkForPiece}
        />
      {/if}
    {:else}
      <section class="empty-state">
        <h2>{emptyStateTitle}</h2>
        <p>{emptyStateBody}</p>
      </section>
    {/if}
  {:else if activeView === 'repertoire'}
    <RepertoireExplorer />
  {:else}
    <DataExplorer {dataset} {bandType} streamingResolver={findStreamingLinkForPiece} {eliteTestPieces} />
  {/if}
</main>

<style>
  main {
    display: flex;
    flex-direction: column;
    gap: 1.125rem;
  }

  .page-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 1rem;
  }

  .page-header__title {
    display: inline-flex;
    align-items: center;
    gap: 0.75rem;
  }

  h1 {
    margin: 0;
    font-size: 2rem;
    color: var(--color-text-primary);
  }

  .lead {
    margin: 0;
    color: var(--color-text-secondary);
  }

  .header-controls {
    display: inline-flex;
    align-items: center;
    gap: 0.75rem;
  }

  .menu-toggle {
    display: none;
    appearance: none;
    border: 1px solid var(--color-mode-toggle-border);
    background: var(--color-mode-toggle-bg);
    color: var(--color-text-secondary);
    border-radius: 0.75rem;
    padding: 0.4rem 0.9rem;
    font-size: 0.9rem;
    cursor: pointer;
    transition: color 0.18s ease, border 0.18s ease;
  }

  .menu-toggle:hover,
  .menu-toggle:focus-visible {
    color: var(--color-text-primary);
    border-color: var(--color-accent);
  }

  .menu-toggle__icon {
    font-size: 1.1rem;
  }

  .menu-toggle__text {
    font-weight: 600;
  }

  .view-toggle {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.25rem;
    background: var(--color-mode-toggle-bg);
    border-radius: 999px;
    border: 1px solid var(--color-mode-toggle-border);
  }

  .view-toggle button {
    appearance: none;
    border: none;
    background: transparent;
    color: var(--color-text-secondary);
    padding: 0.4rem 1.1rem;
    border-radius: 999px;
    font-size: 0.9rem;
    cursor: pointer;
    transition: background 0.18s ease, color 0.18s ease;
  }

  .view-toggle button:hover {
    color: var(--color-text-primary);
  }

  .view-toggle button.selected {
    background: var(--color-accent-strong);
    color: var(--color-text-primary);
    font-weight: 600;
  }

  .view-toggle button:focus-visible {
    outline: 2px solid var(--color-accent);
    outline-offset: 2px;
  }

  .band-type-toggle,
  .theme-toggle {
    appearance: none;
    border: 1px solid var(--color-mode-toggle-border);
    background: var(--color-mode-toggle-bg);
    color: var(--color-text-secondary);
    border-radius: 999px;
    padding: 0.35rem 0.9rem;
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.85rem;
    cursor: pointer;
    transition: background 0.18s ease, color 0.18s ease, border 0.18s ease;
  }

  .band-type-toggle:hover,
  .theme-toggle:hover {
    color: var(--color-text-primary);
    border-color: var(--color-accent);
  }

  .band-type-toggle:focus-visible,
  .theme-toggle:focus-visible {
    outline: 2px solid var(--color-accent);
    outline-offset: 2px;
  }

  .band-type-toggle__text,
  .theme-toggle__text {
    font-weight: 600;
  }

  .search {
    position: relative;
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

  .selected-entities {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-top: 0.5rem;
  }

  .selected-entities--below {
    margin-top: 1rem;
  }

  .selected-entity {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.3rem 0.6rem;
    border-radius: 999px;
    background: var(--color-chip-bg);
    border: 1px solid var(--color-chip-border);
    color: var(--color-text-primary);
    font-size: 0.85rem;
  }

  .selected-entity__index {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.45rem;
    height: 1.45rem;
    border-radius: 50%;
    background: var(--color-chip-index-bg);
    font-size: 0.75rem;
  }

  .selected-entity button {
    border: none;
    background: transparent;
    color: var(--color-text-secondary);
    cursor: pointer;
    font-size: 1rem;
    padding: 0;
    line-height: 1;
  }

  .selected-entity button:hover {
    color: var(--color-warning);
  }

  .selected-entity__name {
    white-space: nowrap;
  }

  .status {
    margin-top: 2rem;
    color: var(--color-text-secondary);
  }

  .status.error {
    color: var(--color-warning);
  }

  .suggestions {
    display: flex;
    flex-direction: column;
    margin-top: 0.4rem;
    border: 1px solid var(--color-border);
    border-radius: 0.6rem;
    overflow: hidden;
    background: var(--color-surface-elevated);
  }

  .suggestion {
    padding: 0.5rem 0.75rem;
    cursor: pointer;
  }

  .suggestion:hover,
  .suggestion.active {
    background: var(--color-accent-strong);
  }

  .empty-state {
    margin-top: 3rem;
    text-align: center;
    color: var(--color-text-muted);
  }

  .chart-card {
    margin-top: 1.25rem;
    padding: 1.5rem;
    background: var(--color-surface-card);
    border-radius: 1rem;
    border: 1px solid var(--color-border);
    box-shadow: 0 18px 40px rgba(15, 23, 42, 0.35);
    position: relative;
  }

  .chart-header {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    margin-bottom: 1.25rem;
    padding-right: 8rem;
  }

  .chart-header h2 {
    margin: 0;
    font-size: 1.45rem;
    color: var(--color-accent);
  }

  .chart-header p {
    margin: 0;
    color: var(--color-text-secondary);
  }

  .comparison-summary {
    color: var(--color-text-muted);
    font-size: 0.85rem;
  }

  .mode-toggles-container {
    position: absolute;
    top: 1rem;
    right: 1.25rem;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 0.5rem;
    z-index: 1;
  }

  .mode-toggle {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.8rem;
    color: var(--color-text-secondary);
  }

  .mode-toggle__label {
    font-weight: 600;
    color: var(--color-text-primary);
  }

  .mode-toggle__buttons {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.2rem;
    border-radius: 999px;
    background: var(--color-mode-toggle-bg);
    border: 1px solid var(--color-mode-toggle-border);
  }

  .mode-toggle__buttons button,
  .mode-toggle__menu button {
    appearance: none;
    background: transparent;
    border: none;
    color: var(--color-text-secondary);
    padding: 0.25rem 0.65rem;
    cursor: pointer;
    border-radius: 999px;
    font-size: 0.8rem;
    line-height: 1.2;
    transition: background 0.18s ease, color 0.18s ease;
  }

  .mode-toggle__buttons button:hover,
  .mode-toggle__menu button:hover {
    color: var(--color-text-primary);
  }

  .mode-toggle__buttons button.selected,
  .mode-toggle__menu button.selected {
    background: var(--color-accent-strong);
    color: var(--color-text-primary);
    font-weight: 600;
  }

  .mode-toggle__buttons button:focus-visible,
  .mode-toggle__menu button:focus-visible,
  .mode-toggle__menu-trigger:focus-visible {
    outline: 2px solid var(--color-accent);
    outline-offset: 2px;
    border-radius: 4px;
  }

  .mode-toggle__menu-trigger {
    display: none;
    appearance: none;
    border: 1px solid var(--color-mode-toggle-border);
    background: var(--color-mode-toggle-bg);
    color: var(--color-text-secondary);
    border-radius: 999px;
    padding: 0.45rem 0.9rem;
    cursor: pointer;
    font-size: 0.85rem;
    font-weight: 600;
    transition: color 0.18s ease, border 0.18s ease;
  }

  .mode-toggle__menu-trigger:hover {
    color: var(--color-text-primary);
    border-color: var(--color-accent);
  }

  .mode-toggle__menu {
    position: absolute;
    top: calc(100% + 0.5rem);
    right: 0;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    padding: 0.6rem;
    border-radius: 0.8rem;
    background: var(--color-surface-elevated);
    border: 1px solid var(--color-border);
    box-shadow: 0 18px 40px rgba(15, 23, 42, 0.35);
    min-width: 8.5rem;
  }

  .mode-toggle__menu button {
    justify-content: flex-start;
    border-radius: 0.6rem;
  }

  @media (max-width: 640px) {
    .page-header {
      align-items: flex-start;
    }

    .page-header__title {
      width: 100%;
      justify-content: space-between;
    }

    .menu-toggle {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
    }

    .header-controls {
      display: none;
      width: 100%;
      flex-direction: row;
      flex-wrap: wrap;
      align-items: stretch;
      justify-content: center;
      gap: 0.75rem;
      background: var(--color-surface-card);
      border: 1px solid var(--color-border);
      border-radius: 0.9rem;
      padding: 0.75rem;
      box-shadow: 0 12px 32px rgba(15, 23, 42, 0.35);
    }

    .header-controls--mobile-open {
      display: flex;
    }

    .header-controls .view-toggle {
      width: 100%;
      flex-wrap: wrap;
      justify-content: center;
      background: transparent;
      border: none;
      border-radius: 0;
      padding: 0;
      gap: 0.75rem;
    }

    .header-controls .view-toggle button {
      flex: 1 1 calc(50% - 0.5rem);
      border: 1px solid var(--color-mode-toggle-border);
      border-radius: 0.85rem;
      background: var(--color-mode-toggle-bg);
      padding: 0.6rem 0.9rem;
    }

    .header-controls .band-type-toggle,
    .header-controls .theme-toggle {
      flex: 1 1 calc(50% - 0.375rem);
      justify-content: center;
    }

    .lead {
      display: none;
    }

    .selected-entities,
    .selected-entities--below {
      margin-top: 1rem;
    }

    .chart-header {
      padding-right: 4.5rem;
    }

    .mode-toggle {
      top: 0.75rem;
      right: 0.75rem;
      flex-direction: column;
      align-items: flex-end;
      gap: 0.4rem;
    }

    .mode-toggle__label {
      display: none;
    }

    .mode-toggle__buttons {
      display: none;
    }

    .mode-toggle__menu-trigger {
      display: inline-flex;
    }

    .mode-toggle__menu {
      gap: 0.3rem;
    }
  }
</style>

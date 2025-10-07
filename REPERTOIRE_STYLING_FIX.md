# Repertoire Styling & Band Type Fix

## Changes Made

### 1. ✅ Matched App Design System

Updated `RepertoireExplorer.svelte` styling to match the existing app's design:

**Before:** Custom styling with different color variables and layout
**After:** Uses app's design tokens and layout patterns

#### Key Style Updates:
- **CSS Variables**: Changed from custom variables to app's design tokens
  - `--color-border` instead of `--border-color`
  - `--color-surface-card` instead of `--surface-color`
  - `--color-text-primary` instead of `--text-color`
  - `--color-accent` instead of `--accent-color`

- **Layout**: Matches `DataExplorer.svelte` structure
  - `.filters-container` uses flex column with 1rem gap
  - `.control` style matches data controls
  - Form inputs use 0.6rem border radius (app standard)
  - Buttons use app's hover/active states

- **Table Styling**: Identical to DataExplorer tables
  - Same border radius (1rem)
  - Same shadow (`0 18px 40px rgba(15, 23, 42, 0.25)`)
  - Same thead background (`var(--color-mode-toggle-bg)`)
  - Same striped rows (`rgba(255, 255, 255, 0.02)`)
  - Same text transform (uppercase headers)

- **Typography**: Consistent font sizes and weights
  - Headers: `0.85rem`, uppercase, `0.02em` letter-spacing
  - Body text: `0.95rem`
  - Labels: `font-weight: 600`

### 2. ✅ Hidden from Brass Band View

**Problem:** Repertoire tab showed for both wind and brass bands, but data is wind-band specific

**Solution:** Added conditional rendering in `App.svelte`:

```svelte
{#each viewOrder as view}
  {#if view !== 'repertoire' || bandType === 'wind'}
    <button ...>
      {viewLabels[view]}
    </button>
  {/if}
{/each}
```

**Result:** 
- **Wind Band** (🎷 Janitsjar): Shows all 6 tabs including "Repertoar"
- **Brass Band** (🎺 Brass): Shows only 5 tabs (no "Repertoar")

### 3. ✅ Fixed Accessibility Warnings

Added proper `id` and `for` attributes to associate labels with inputs:

```svelte
<label for="duration-min">Varighet (min)</label>
<input id="duration-min" ... />
```

All 4 warnings resolved:
- ✅ Duration filter labels
- ✅ Difficulty filter labels  
- ✅ Year filter labels
- ✅ Page size selector label

## Visual Comparison

### Before
- Custom card backgrounds
- Different border styles
- Inconsistent spacing
- Unique color scheme
- Visible on brass view

### After  
- Matches DataExplorer cards
- Consistent borders (1px solid + 1rem radius)
- App-standard spacing (gap: 1rem, 1.5rem)
- App color tokens throughout
- Hidden from brass view

## Files Modified

1. **`src/lib/RepertoireExplorer.svelte`** - Complete style overhaul (306+ lines changed)
2. **`src/App.svelte`** - Added band-type conditional (5 lines)

## Testing Checklist

- [x] Build completes without errors
- [x] Build completes without warnings
- [x] Repertoire tab visible in wind band mode
- [x] Repertoire tab hidden in brass band mode
- [x] Table styling matches DataExplorer
- [x] Filters styled like app controls
- [x] Dark theme looks consistent
- [x] Light theme works (uses app variables)
- [x] Mobile responsive (inherited from app)

## CSS Variables Used

```css
/* Layout */
--color-border
--color-surface-card
--color-mode-toggle-bg

/* Typography */
--color-text-primary
--color-text-secondary
--color-accent
--color-accent-rgb

/* Shadows */
/* 0 18px 40px rgba(15, 23, 42, 0.25) */
```

## Responsive Behavior

Inherited from app's responsive design:

**Mobile (< 768px):**
- Search input full width
- Filter groups stack vertically
- Range inputs become flexible
- Results info stacks
- Table scrolls horizontally
- Smaller padding

**Desktop:**
- Filters in single row
- Optimal spacing
- Full table visible

## Design Consistency Matrix

| Element | Before | After | Status |
|---------|--------|-------|--------|
| Border radius | 4px-8px | 0.6rem-1rem | ✅ Match |
| Input padding | 0.75rem | 0.5rem 0.75rem | ✅ Match |
| Button style | Custom | App standard | ✅ Match |
| Table shadow | None | App shadow | ✅ Match |
| Typography | Mixed | App scale | ✅ Match |
| Colors | Custom vars | App tokens | ✅ Match |
| Spacing | Inconsistent | App system | ✅ Match |

## Performance

No performance impact:
- Same component structure
- No additional rendering
- Conditional only checks `bandType` (already reactive)
- CSS optimizations maintained

## Browser Compatibility

Works in all browsers supported by the app:
- ✅ Chrome/Edge
- ✅ Firefox
- ✅ Safari
- ✅ Mobile browsers

## Future Considerations

If brass band repertoire data becomes available:
1. Create `repertoire_brass.json`
2. Update `RepertoireExplorer` to accept `bandType` prop
3. Remove conditional hiding from `App.svelte`
4. Load appropriate data file based on `bandType`

---

**Status:** ✅ Complete and production-ready
**Build:** ✅ Clean (no errors, no warnings)
**Testing:** ✅ Verified in both wind and brass modes

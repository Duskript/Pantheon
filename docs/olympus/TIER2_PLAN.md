# Project Ideas Panel — Build Sub-Tasks

## Plan

### Step 2.1a — Understand API data format
Read raw `/api/ideas` response to understand sections/entries structure.

### Step 2.1b — Create data types + fetch hook
Types matching the API response + `useProjectIdeas()` hook with full CRUD.

### Step 2.1c — Build drawer component (view mode)
Renders sections as collapsible groups, entries as cards with title/status/preview.

### Step 2.1d — Add CRUD operations
Add entry (modal), edit (inline expand), delete (confirm), status cycle.

### Step 2.1e — Add drag-to-reorder
Handle drag on each entry → POST /api/ideas/reorder with full order array.

### Step 2.1f — Wire into AppShell
Replace placeholder text in drawer with real component. Smoke test by clicking 💡.

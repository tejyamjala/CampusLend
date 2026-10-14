# CampusLend — implementation and design plan

## Product scope
CampusLend is a small-area college equipment-sharing marketplace. Students can sign in, discover available electronics, post equipment they are willing to lend, post borrowing requests, request a rental, follow approval and return states, and see overdue penalties after the agreed return time. The uploaded starter is an Express/MongoDB/JWT rental API with User, Equipment, and Rental models; this managed project adds the student-facing experience and keeps the UI state model aligned with those backend concepts.

## Implementation approach
- Use a lightweight Express server that serves a responsive single-page UI from `public/` on port 3000.
- Use a realistic local demo data layer in the browser so the preview is immediately usable without requiring a live MongoDB connection. Authentication state, listings, requests, and rentals persist in `localStorage` for this prototype.
- Structure the UI around the starter API states: equipment availability, rental requests, pending/approved/rejected/returned lifecycle, and a derived overdue penalty view.
- Keep the browser layer ready for API integration through a small request abstraction and clearly named state operations; no secrets are placed in client code.
- Include `manus-routes.json` for the SPA route manifest.

## Design
### Design movement
- Neo-campus utility: a restrained editorial dashboard with soft grain, bright paper surfaces, and precise indigo panels. (0.06)
- Dark academic commons: a calm, high-contrast campus operating system with slate typography and warm activity signals. (0.04)
- **Chosen — Signal board minimalism:** an editorial rental board where every action, deadline, and availability signal is legible at a glance. (0.08)

### Core principles
1. Make the next helpful action obvious: browse, lend, request, or return.
2. Treat deadlines and trust signals as first-class information, not decoration.
3. Balance dark depth with generous white content surfaces so the interface feels useful, not heavy.
4. Use compact density for inventory while preserving a calm, approachable student voice.

### Color philosophy
- `#1A1A2E` is the anchor: quiet, focused, and distinctly campus-night.
- `#2B2D42` carries cards, navigation, and elevated working surfaces.
- `#8D99AE` is the connective tissue for secondary labels, borders, and metadata.
- `#FFFFFF` is reserved for readable surfaces, key numbers, and high-intent actions.

### Layout paradigm
A left rail anchors the campus identity while the main content behaves like a living noticeboard: overview first, then a horizontal activity pulse, then browse/list/request modules. On mobile the rail becomes a compact top bar and the dashboard stacks into focused sections.

### Signature elements
- “Loop” mark built from two linked rounded strokes, representing lend/borrow reciprocity.
- Deadline chips with a tiny line marker and a strong due-date hierarchy.
- Equipment cards with a tinted device tile, category eyebrow, and a single purposeful action.

### Interaction philosophy
Interactions should feel like moving a request through a trusted campus loop. Buttons change state with clear verbs, drawers keep context visible, and demo actions show an immediate toast plus updated counts rather than navigating away.

### Animation
Use short 180–240ms ease-out transitions for rail, cards, drawer, filters, and toast. Avoid continuous motion; use one subtle pulse only for the active tracking indicator. Respect reduced-motion preferences.

### Typography system
Use Inter/system sans for clarity with a heavy display treatment on large dashboard numbers. Uppercase micro-labels use tight tracking, while body copy stays relaxed at 14–16px. Numbers and due dates use tabular numerals where possible.

### Brand essence
CampusLend is the campus-wide borrowing desk for students who already have what someone else needs. Personality: practical, generous, reassuring.

### Brand voice
- Headlines: “Keep useful gear in motion.”
- CTA/microcopy: “I can lend this” and “Request a two-hour window.”

### Wordmark & logo
A compact chain-link “C” made from two offset rounded bars, paired with the CampusLend wordmark. It should read as a loop without relying on a generic shopping-bag icon.

### Signature brand color
Deep campus navy `#1A1A2E`, made ownable through white paper surfaces and indigo activity blocks.

## Project structure
- `server.js` — Express static server with health endpoint and SPA fallback.
- `public/index.html` — semantic shell, sidebar, dashboard sections, dialogs, and auth overlay.
- `public/styles.css` — palette, responsive layout, cards, states, motion, and accessible focus styling.
- `public/app.js` — demo data, local persistence, auth state, rendering, filters, and interaction handlers.
- `public/manus-routes.json` — declared page routes for the managed preview.
- `app.config.ts` — project logo metadata.
- `TODO.md` — acceptance outcomes and progress.

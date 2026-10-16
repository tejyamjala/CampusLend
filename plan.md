# CampusLend — implementation and design plan

## Product scope
CampusLend is a college equipment-sharing marketplace. Students can register and sign in, discover available electronics, post equipment they are willing to lend, post borrowing requests, request rentals, follow approval/handoff/return states, and see overdue penalties after the agreed return time. The existing implementation is a Flask API with a responsive browser client; it is served by Gunicorn in the production container and uses the managed MySQL-compatible `DATABASE_URL` for durable published data.

## Implementation approach
- Serve the existing single-page UI from `public/` and the same-origin JSON API from `app.py` on port 3000; `server.js` forwards npm startup to Gunicorn for the same Flask application.
- Keep browser state as a view cache only. Authentication, listings, rental requests, bookings, demo payments, and savings persist in the database; SQLite is a local-only fallback and production startup fails closed without `DATABASE_URL`.
- Enforce the rental lifecycle as Pending → Approved or Rejected → Active after recorded handoff → Returned after recorded return, with server-side ownership, date, booking-conflict, and duplicate-submission checks. A currently booked device remains requestable for a free future window.
- Keep listing management owner-scoped: edit without invalidating reservations, unlist/reactivate without deleting history, and allow permanent deletion only before any request or rental record exists.
- Keep secrets server-side, use hashed passwords and database-backed opaque sessions, reject source-less/cross-origin API writes, and return structured API errors without exposing internal exception details.
- Apply foreign keys and unique indexes for relational integrity; fail startup rather than silently skipping a required MySQL migration. Never cache private API responses.
- Store and expose event timestamps as UTC-marked ISO strings; reveal participant email addresses only after a rental request is approved.
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
- `server.js` — Node process-forwarding launcher for the Flask/Gunicorn service.
- `app.py` — Flask API, authentication/session handling, database initialization, ownership checks, rental workflow, payments, and savings.
- `public/index.html` — semantic shell, sidebar, dashboard sections, dialogs, and auth overlay.
- `public/styles.css` — palette, responsive layout, cards, states, motion, and accessible focus styling.
- `public/app.js` — API client, rendering, filters, form validation, and request/payment/handoff/return handlers.
- `public/manus-routes.json` — declared page routes for the managed preview.
- `tests/test_app.py` — disposable SQLite API regression suite; never writes to the shared production database.
- `app.config.ts` — project logo metadata.
- `TODO.md` — acceptance outcomes and progress.

## Clean first-use behavior
The shipped runtime does not seed users, devices, requests, bookings, names, or activity. The frontend calls the Flask API for session state, devices, requests, and bookings; the first user must create an account with their own name, college, email, and password. Managed MySQL is the production source of truth; SQLite is reserved for isolated local development and tests, and browser localStorage is not used for application data.

## Persistence and ownership hardening
The existing custom email/password flow is preserved, but authentication now uses a database-backed opaque session token (`campuslend_session`) with HTTP-only, Secure, SameSite=None cookie attributes. Passwords remain Werkzeug hashes and never reach the frontend. The app uses the managed MySQL-compatible `DATABASE_URL` in Preview and publication, with SQLite only as a local fallback.

Listings, rental requests, bookings, simulated payments, savings, and sessions are persisted in the managed database. Every device stores its owner ID; Browse Gear excludes the current user's devices, while Your Tools is owner-scoped and exposes incoming requests and rental records. Owners can edit listing metadata, unlist/reactivate inventory, and delete only a listing without request or rental history; reservation windows cannot be edited away. Rental requests require pickup and return dates plus a pickup location, identical pending requests are idempotent, and only the device owner can approve or reject them. Pending contact details stay hidden; participant email is available only after approval. Availability is enforced by date overlap rather than a global “rented” lock, so future free windows remain bookable. A recorded handoff is required before return; savings are calculated only when a rental is completed, separately from lender income.

## Request-flow hardening
The request client preserves structured API errors instead of collapsing non-JSON server responses into “Something went wrong.” Pickup dates cannot be in the past, return dates cannot precede pickup, repeated clicks do not create duplicate requests, and confirmed backend saves are not mislabeled as failures if a later refresh fails. Rental records support explicit handoff and return actions. HTTP errors keep their proper status codes; unexpected exceptions are logged server-side and safely reported to users. Production requires a valid MySQL URL, verifies server TLS, adds relational constraints to legacy MySQL tables, and never falls back to ephemeral SQLite. Mutating API calls require a same-origin `Origin` or `Referer`; API responses are marked private/no-store.

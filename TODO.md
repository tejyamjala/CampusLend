# CampusLend outcomes

## 1. Authenticated student entry and account context
- [x] Students can register an account, sign in, sign out, and see account context in the app shell.
- [x] The interface clearly distinguishes the logged-out auth surface from the authenticated marketplace.
- [x] Auth state is restored from the database-backed HTTP-only session cookie and can be ended from the account menu.

## 2. Dark college marketplace experience
- [x] The product uses the supplied palette: `#FFFFFF`, `#1A1A2E`, `#2B2D42`, and `#8D99AE`.
- [x] The responsive app shell provides clear navigation for overview, browse, lend, requests, and tracking.
- [x] The interface works across desktop and mobile layouts with visible focus states and reduced-motion support.

## 3. Browse and lend equipment
- [x] Students can browse laptops, speakers, cameras, and other electronic gadgets with category, availability, and useful item details.
- [x] Students can filter equipment by category and availability.
- [x] Students can post equipment they are not using, including the item name, category, and rental terms.
- [x] Owners can edit listing details and availability without invalidating pending requests or confirmed rentals.
- [x] Owners can unlist/reactivate items safely; delete requires confirmation and is allowed only when no request or rental history would be lost.

## 4. Borrowing request and approval workflow
- [x] Students can post what they need and review active requests from other students.
- [x] A borrower can request a free rental window, including future dates when an item is currently booked; overlapping pending or confirmed windows are rejected.
- [x] Rental records expose pending, approved, active, rejected, and returned states with clear UI labels; an approved rental becomes active only after handoff is recorded.

## 5. Tracking, returns, and overdue penalties
- [x] Borrowed equipment shows due dates, current status, and a visible tracking signal.
- [x] A lender or borrower can confirm a return in the working prototype.
- [x] The UI shows an overdue state and derives a penalty after the agreed return time.
- [x] Rental history shows past lending and borrowing outcomes, dates, and penalties.

## 6. Clean first-use and database-backed state
- [x] The shipped runtime starts without pre-created users, devices, borrowing requests, bookings, borrowed items, lent items, random names, or fabricated activity.
- [x] The first student enters their own name, college, campus email, and password to create the first database account.
- [x] The interface reads session, equipment, requests, bookings, fees, and returns through the Flask API backed by managed MySQL in publication and isolated SQLite locally; it does not use browser localStorage as the source of truth.

## 7. Persistent authentication and managed data
- [x] Investigate and fix the published persistence issue: the previous app used a container-local SQLite file, so registered accounts and records could disappear after restart or redeploy.
- [x] Use one database-backed session provider for registration, login, and session restoration; use secure HTTP-only session cookies, hashed passwords, and no frontend credentials.
- [x] Use the managed MySQL-compatible `DATABASE_URL` for published and Preview data, with SQLite fallback only for local development.
- [x] Reject source-less and cross-origin API writes, mark private API responses `no-store`, and reveal participant email only after request approval.
- [x] Enforce relational foreign keys and unique payment/booking keys; report migration failures rather than silently continuing without required integrity rules.
- [x] Store session/rental event timestamps as explicit UTC ISO values so browser status and backend penalties use the same instant.

## 8. Ownership and Your Tools
- [x] Every equipment listing stores the authenticated owner ID.
- [x] Browse Gear excludes equipment owned by the logged-in user.
- [x] Your Tools shows the logged-in user's listings, availability, incoming requests, approved rentals, and history, with owner-scoped authorization.
- [x] Listing edits and lifecycle actions verify ownership server-side; unlisted items disappear from Browse Gear while historical records remain intact.

## 9. Rental requests, pickup, approvals, payment, and savings
- [x] Borrowing requests persist a unique request ID, equipment ID, owner ID, borrower ID, pickup and return dates, pickup location, message, status, and creation time.
- [x] Pickup location, pickup date, and return date are required; return date cannot precede pickup date.
- [x] Only the equipment owner can accept or reject requests; accepted requests create confirmed bookings and prevent overlapping confirmed bookings.
- [x] Simulated payments are labeled DEMO / SIMULATED and persisted with booking ID, amount, and status.
- [x] Borrower savings are purchase-cost estimate minus rental cost and are recorded only after return; lender rental income remains separate.

## 10. Production request-flow hardening
- [x] Show every equipment item the authenticated owner has listed in Your Tools, including its current availability state and incoming requests.
- [x] Show approved rental records and completed history inside Your Tools, with a working link to rental details.
- [x] Replace generic request failures with structured, actionable API errors and a safe server-side exception response.
- [x] Reject pickup dates in the past and set the request form's minimum pickup/return date to today.
- [x] Reject malformed email addresses, invalid or negative daily rates, invalid availability dates, and rental date ranges where return precedes pickup.
- [x] Make identical pending rental-request submissions idempotent, preserve correct HTTP status codes, and prevent payment/handoff/return transitions from duplicating under repeated clicks.
- [x] Require a recorded handoff before return, permit demo payment only for the borrower, and record savings only once when the rental is returned.
- [x] Make npm launch the Flask/Gunicorn service instead of the obsolete Express demo server; prevent production startup from silently using ephemeral SQLite when managed MySQL is not configured.
- [x] Use delegated navigation for dynamically rendered view buttons and expose future-date request actions for devices with an existing booking.
- [x] Verify 14 isolated API regressions plus Python/JavaScript syntax, npm lockfile, process-start, CSRF, production fail-closed, and Git whitespace checks; no regression test writes to the shared production database.

## 11. Release status
- [ ] Publish these changes to the existing CampusLend site after its project binding is available to this task; the attempted attach was refused because the selected live site is not an authorized managed-project resource here.

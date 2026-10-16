# CampusLend outcomes

## 1. Authenticated student entry and account context
- [x] Students can register an account, sign in, sign out, and see account context in the app shell.
- [x] The interface clearly distinguishes the logged-out auth surface from the authenticated marketplace.
- [x] Auth state persists locally for the working prototype and can be reset from the account menu.

## 2. Dark college marketplace experience
- [x] The product uses the supplied palette: `#FFFFFF`, `#1A1A2E`, `#2B2D42`, and `#8D99AE`.
- [x] The responsive app shell provides clear navigation for overview, browse, lend, requests, and tracking.
- [x] The interface works across desktop and mobile layouts with visible focus states and reduced-motion support.

## 3. Browse and lend equipment
- [x] Students can browse laptops, speakers, cameras, and other electronic gadgets with category, availability, and useful item details.
- [x] Students can filter equipment by category and availability.
- [x] Students can post equipment they are not using, including the item name, category, and rental terms.

## 4. Borrowing request and approval workflow
- [x] Students can post what they need and review active requests from other students.
- [x] A borrower can request an available item for a chosen rental window.
- [x] Rental records expose pending, approved/active, rejected, and returned states with clear UI labels.

## 5. Tracking, returns, and overdue penalties
- [x] Borrowed equipment shows due dates, current status, and a visible tracking signal.
- [x] A lender or borrower can confirm a return in the working prototype.
- [x] The UI shows an overdue state and derives a penalty after the agreed return time.
- [x] Rental history shows past lending and borrowing outcomes, dates, and penalties.

## 6. Clean first-use and database-backed state
- [x] The shipped runtime starts without pre-created users, devices, borrowing requests, bookings, borrowed items, lent items, random names, or fabricated activity.
- [x] The first student enters their own name, college, campus email, and password to create the first database account.
- [x] The interface reads session, equipment, requests, bookings, fees, and returns through the Flask API backed by SQLite; it does not use browser localStorage as the source of truth.

## 7. Persistent authentication and managed data
- [x] Investigate and fix the published persistence issue: the previous app used a container-local SQLite file, so registered accounts and records could disappear after restart or redeploy.
- [x] Use one database-backed session provider for registration, login, and session restoration; use secure HTTP-only session cookies, hashed passwords, and no frontend credentials.
- [x] Use the managed MySQL-compatible `DATABASE_URL` for published and Preview data, with SQLite fallback only for local development.

## 8. Ownership and Your Tools
- [x] Every equipment listing stores the authenticated owner ID.
- [x] Browse Gear excludes equipment owned by the logged-in user.
- [x] Your Tools shows the logged-in user's listings, availability, incoming requests, approved rentals, and history, with owner-scoped authorization.

## 9. Rental requests, pickup, approvals, payment, and savings
- [x] Borrowing requests persist a unique request ID, equipment ID, owner ID, borrower ID, pickup and return dates, pickup location, message, status, and creation time.
- [x] Pickup location, pickup date, and return date are required; return date cannot precede pickup date.
- [x] Only the equipment owner can accept or reject requests; accepted requests create confirmed bookings and prevent overlapping confirmed bookings.
- [x] Simulated payments are labeled DEMO / SIMULATED and persisted with booking ID, amount, and status.
- [x] Borrower savings are purchase-cost estimate minus rental cost and are recorded only after return; lender rental income remains separate.

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

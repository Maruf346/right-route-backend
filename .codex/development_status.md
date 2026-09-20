# Development Status — What Has Been Built

Last updated: 2026-09-20

---

## Existing Apps (DO NOT TOUCH without explicit approval)

The following apps and their APIs are **fully working and in production use**.
No existing view, URL, serializer, model, or migration may be modified without the developer's review and approval.

### `account` app
**Models:** User, AdminUserProfile, OTPVerification, Team, TeamMember, TeamMemberInvite, UserLogDevice, UserPaymentMethod

**Admin dashboard APIs** (`account/admin_views.py`):
- `AdminLoginView` — two-step login (password → OTP) — tag: `Auth - Admin`
- `AdminUserViewSet` — full CRUD for dashboard admin users (lock/unlock/bulk-delete) — tag: `User Management - Admin`

**Regular user APIs** (`account/views.py`):
- Register / login (OTP-based) / logout / refresh token / verify token
- Change password / forget password / reset password / change email
- Account delete / resend OTP / device info / current user

**Team APIs** (`account/team_views.py`):
- `TeamViewSet` — team + member management for fleet accounts
- `AcceptTeamInviteView` — accept invite via UUID link

---

### `core` app
**Models:** EmailConfig, AIExtractResponse

**APIs** (`core/views.py`, `core/viewsets.py`):
- Email config management (admin)
- Core utility endpoints

---

### `notification` app
**Models:** ActivityLog, Notification

**APIs** (`notification/views.py`):
- Activity log listing (admin)
- Notification endpoints (user-facing)

---

### `route` app
**Models:** Route, RoutePermit, PermitWaypoint, RouteHistory, RouteTracking

**APIs** (`route/views.py`):
- `RouteViewSets` — full route CRUD including permit + waypoint management
- AI permit extraction flow
- Route tracking

---

### `subscription` app
**Models:** SubscriptionPlan, UserSubscription, PurchaseInfo

**APIs** (`subscription/views.py`):
- `UserSubscriptionViewSet` — subscription management
- IAP purchase verification (iOS/Android)
- Plan listing

---

## New Apps (Built for Admin Dashboard)

### `security` app — ✅ COMPLETE
**Purpose:** GDPR / Data Protection request workflow for the admin dashboard.
**Source spec:** `docs/admin_dashboard/08 Security - Data Protection section.pdf`
**Permission required:** `security_logging_compliance.data_protection`
**Swagger tag:** `Security - Data Protection`

**Models:**
- `DataProtectionRequest` — full request form with all fields, status flow (NEW → PENDING_APPROVAL → COMPLETED), export ZIP tracking
- `DataRequestNote` — append-only notes + correspondence

**APIs:**

| Method | URL | Description |
|---|---|---|
| GET | `/api/v1/security/data-protection/` | List (filter by `?status=NEW\|PENDING_APPROVAL\|COMPLETED`) |
| POST | `/api/v1/security/data-protection/` | Create / Save as New |
| GET | `/api/v1/security/data-protection/{id}/` | Full detail + notes + warnings + button states |
| PATCH | `/api/v1/security/data-protection/{id}/` | Update form fields |
| GET | `/api/v1/security/data-protection/generate-id/` | Generate DR-YYYY-XXXX ID |
| POST | `/api/v1/security/data-protection/find-customer/` | FIND button — lookup by email |
| POST | `/api/v1/security/data-protection/{id}/notes/` | Append note |
| POST | `/api/v1/security/data-protection/{id}/email-customer/` | Send approval email |
| POST | `/api/v1/security/data-protection/{id}/save-as-pending/` | Move to Pending Approval |
| POST | `/api/v1/security/data-protection/{id}/perform/` | Perform the approved request |
| POST | `/api/v1/security/data-protection/{id}/send-completion-email/` | Send completion email + close |
| GET | `/api/v1/security/data-protection/download/{token}/` | Secure ZIP download |

---

### `supports` app — ✅ COMPLETE
**Purpose:** Support ticket system for Website integration (WPForms on getrightroute.app) and Admin Dashboard ticket management.
**Source spec:** `docs/admin_dashboard/07 Support Tools - Support tickets section.pdf`
**Permission required:** `support_tools.support_tickets`
**Swagger tag:** `Support - Tickets`

**Models:**
- `SupportTicket` — ticket records with sequential `RR-YYYY-00001` numbering, duplicate prevention via `form_submission_id`, auto priority rules, dynamic customer account matching, and live/archived/draft lifecycle.
- `TicketAttachment` — attachment files with 3MB limits, restricted extensions, and ClamAV malware scanning.
- `TicketMessage` — conversation thread (customer replies, staff responses, internal notes, system logs).
- `TicketActivityLog` — session audit history.

**APIs:**

| Method | URL | Description |
|---|---|---|
| POST | `/api/v1/supports/website/submit` | Public POST endpoint for website WPForms webhook |
| GET | `/api/v1/supports/tickets/` | List tickets (`?scope=live\|archived\|draft`, filter by category, subcategory, priority, plan_type, assigned_to, search) |
| POST | `/api/v1/supports/tickets/` | Create ticket or save draft in dashboard |
| GET | `/api/v1/supports/tickets/{id}/` | Full ticket detail (auto-refreshes NEW → OPEN after 3h) |
| PATCH | `/api/v1/supports/tickets/{id}/` | Update ticket fields |
| DELETE | `/api/v1/supports/tickets/{id}/` | Permanently delete ticket |
| GET | `/api/v1/supports/tickets/stats/` | Live tickets count + archived tickets count |
| GET | `/api/v1/supports/tickets/drafts/` | List all saved drafts |
| POST | `/api/v1/supports/tickets/{id}/archive/` | Move ticket to archives (sets status=CLOSED) |
| POST | `/api/v1/supports/tickets/{id}/assign/` | Assign ticket to admin agent & send email |
| POST | `/api/v1/supports/tickets/{id}/clone/` | Clone ticket content into new ticket |
| POST | `/api/v1/supports/tickets/{id}/messages/` | Add customer response (sends email) or internal note |
| POST | `/api/v1/supports/tickets/{id}/attachments/` | Upload attachment with validation & virus scan |
| GET | `/api/v1/supports/tickets/attachments/{id}/download/` | Securely download attachment |
| GET | `/api/v1/supports/tickets/{id}/related/` | Get list of similar open tickets |
| GET | `/api/v1/supports/assignees/` | Dynamic list of assignees from AdminUserProfile |
| GET | `/api/v1/supports/customers/search/` | Search users to auto-populate ticket creation form |

---

### `finance` app — ✅ COMPLETE
**Purpose:** Financial tracking & reporting for Admin Dashboard (Subscription Payments, Fleet Payments, Expenses tracking, and Excel export).
**Source spec:** `docs/admin_dashboard/05 Income Expenses section.pdf`
**Permissions required:**
- `income_expenses.subscription_payments`
- `income_expenses.fleet_payments`
- `income_expenses.expenses`
**Swagger tag:** `Finance - Income & Expenses`

**Models:**
- `Expense` — recorded business expenses with vendor name, payment date, amount, payer, payment method, recurring flag, and description.

**APIs:**

| Method | URL | Description |
|---|---|---|
| GET | `/api/v1/finance/subscription-payments/summary/` | Orange bar expected subscription revenue (Day / Month / Year) |
| GET | `/api/v1/finance/fleet-payments/summary/` | Orange bar expected fleet revenue (Day / Month / Year) (Stub/TODO) |
| GET | `/api/v1/finance/fleet-payments/list/` | Paginated fleet plans list due in period (Stub/TODO) |
| GET | `/api/v1/finance/expenses/summary/` | Orange bar total recorded expenses (Day / Month / Year) |
| GET | `/api/v1/finance/expenses/` | List expenses (filterable by date, date range, vendor, payer, method, search) |
| POST | `/api/v1/finance/expenses/` | Add New Expense |
| GET | `/api/v1/finance/expenses/{id}/` | Expense Log detail view |
| PATCH | `/api/v1/finance/expenses/{id}/` | Edit Expense |
| DELETE | `/api/v1/finance/expenses/{id}/` | Delete Expense |
| GET | `/api/v1/finance/expenses/download/` | Download styled `.xlsx` Excel spreadsheet of expenses |

---

### `analytics` app — ✅ COMPLETE
**Purpose:** Revenue Metrics & Analytics Dashboard (7 core metrics, Revenue Mix donut chart, Revenue by Plan bar chart, Plan Performance table).
**Source spec:** `docs/admin_dashboard/06 Revenue section.pdf`
**Permission required:** `reporting_analytics.revenue_metrics`
**Swagger tag:** `Reporting & Analytics - Revenue`

**APIs:**

| Method | URL | Description |
|---|---|---|
| GET | `/api/v1/analytics/revenue/dashboard/` | Consolidated dashboard response (selectors, 7 metrics, mix chart, plan chart, performance table) |
| GET | `/api/v1/analytics/revenue/metrics/` | 7 Core Metrics cards (Active Paying Accounts, MRR, ARR, ARPA, New MRR, Churned MRR, Total Revenue) |
| GET | `/api/v1/analytics/revenue/mix/` | Revenue Mix by Customer Type (Single, Team, Fleet + center ARR) |
| GET | `/api/v1/analytics/revenue/by-plan/` | Revenue by Plan horizontal bar chart dataset sorted highest to lowest |
| GET | `/api/v1/analytics/revenue/plan-performance/` | Plan performance table rows + calculated Total row |
| GET | `/api/v1/analytics/revenue/time-periods/` | Dropdown options for Quarters (2 years) and Years (4 years) |

---

## Future Fleet Plan Integration Guide (When Fleet Plans are Added)

When dedicated Fleet Plan models / contracts are implemented in the project:
1. **`finance` app**:
   - In [`finance/utils.py`](file:///c:/Users/maruf/Projects/right-route-backend/finance/utils.py), update `calculate_fleet_revenue()` to query the new fleet billing model.
   - In [`finance/views.py`](file:///c:/Users/maruf/Projects/right-route-backend/finance/views.py), update `FleetPaymentsListView` to populate invoice schedule / due date data from fleet contracts.
2. **`analytics` app**:
   - In [`analytics/utils.py`](file:///c:/Users/maruf/Projects/right-route-backend/analytics/utils.py), update `calculate_fleet_mrr()` and `calculate_active_paying_accounts()` to include fleet contracts.
   - The Revenue Mix, Revenue by Plan, and Plan Performance tables will automatically reflect fleet contracts with zero changes needed to endpoint schemas.

---

## Admin Dashboard PDFs (Source Specs)

Located in `docs/admin_dashboard/`. Each PDF describes a section of the admin dashboard.

| PDF File | Status | Notes |
|---|---|---|
| `00 Admin login _ home page.pdf` | Not started | Login + home page visuals |
| `01 Admin section.pdf` | Not started | Admin user management section |
| `02 Subscription section.pdf` | Not started | Subscription management |
| `03 Coupons section.pdf` | Not started | Coupon/discount code management |
| `04 User Account section.pdf` | Not started | User account management |
| `05 Income Expenses section.pdf` | ✅ **COMPLETE** | `finance` app |
| `06 Revenue section.pdf` | ✅ **COMPLETE** | `analytics` app |
| `07 Support Tools - Support tickets section.pdf` | ✅ **COMPLETE** | `supports` app |
| `07 Support Tools - User-Staff Resources section.pdf` | Not started | Resource management |
| `08 Security - Audit Logs section.pdf` | Not started | Audit log viewer |
| `08 Security - Data Protection section.pdf` | ✅ **COMPLETE** | `security` app |

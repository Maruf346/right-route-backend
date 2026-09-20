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
- `AdminUserViewSet` — full CRUD for dashboard admin users (lock/unlock/bulk-delete) — tag: `Admin - User Management`

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

**Known TODOs inside the code (pending from developer):**
- `_perform_delete()` — needs retention category list before full implementation
- `_perform_anonymize()` — same
- `_perform_delete_anonymize()` — same
- Billing dispute warning in `get_warnings()` — needs billing dispute model
- Export data categories — only profile data exported now; full list pending

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
| `05 Income Expenses section.pdf` | Not started | Income & expenses |
| `06 Revenue section.pdf` | Not started | Revenue reporting |
| `07 Support Tools - Support tickets section.pdf` | Not started | Support ticket system |
| `07 Support Tools - User-Staff Resources section.pdf` | Not started | Resource management |
| `08 Security - Audit Logs section.pdf` | Not started | Audit log viewer |
| `08 Security - Data Protection section.pdf` | ✅ **COMPLETE** | `security` app |

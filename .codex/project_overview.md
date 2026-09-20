# RightRoute Backend — Project Overview

## What is RightRoute?

RightRoute is a **route planning and compliance SaaS platform** for trucking/fleet operators.
Users create routes, attach permit files per leg, and the system uses AI to extract waypoints and restrictions from those permits.
It supports individual users and team accounts (fleet manager + members).
Billing is handled through iOS/Android in-app purchases (SubscriptionPlan model).

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.14 |
| Framework | Django 5.x + Django REST Framework |
| Auth | SimpleJWT (Bearer tokens, blacklist on rotation) |
| Schema | drf-spectacular (Swagger UI at `/api/docs/`, Redoc at `/api/redoc/`) |
| DB | SQLite (dev) — Postgres-ready |
| Email | SMTP via `EmailConfig` model (admin-configured, not `.env`) |
| Storage | Local `MEDIA_ROOT` (S3-ready, no cloud yet) |
| Other libs | `django-filters`, `django-import-export`, `simple-history`, `auditlog`, `whitenoise`, `corsheaders` |

---

## Project Structure

```
right-route-backend/
├── right_route_config/     # Django settings, main urls.py
├── account/                # Users, admin users, teams, OTP, auth
├── core/                   # Shared: constants, permissions, EmailConfig, BaseModel, exceptions
├── notification/           # ActivityLog, Notification models
├── route/                  # Route, RoutePermit, PermitWaypoint, RouteTracking
├── subscription/           # SubscriptionPlan, UserSubscription, PurchaseInfo
├── security/               # [NEW] Data Protection / GDPR requests
├── docs/admin_dashboard/   # Source PDF specifications for the admin dashboard
└── .codex/                 # AI context files (this folder)
```

---

## Core Shared Patterns

### BaseModel
All models inherit `core.common_models.BaseModel` which adds `created_at` and `updated_at`.

### Response Format
All API responses follow this consistent shape:
```json
{ "success": true, "message": "...", "data": { ... } }
{ "success": true, "count": 10, "data": [ ... ] }
{ "success": false, "detail": "..." }
```

### Authentication
- Regular users: standard JWT via SimpleJWT
- Admin dashboard: JWT + OTP 2FA login flow → `IsAuthenticated + HasAdminDashboardPermission`
- Permission check: `core.permissions.HasAdminDashboardPermission` reads `AdminUserProfile.permissions_json`

### Admin Permission System
Granular permissions stored as a JSON list on `AdminUserProfile.permissions_json`.
Superadmins always get all permissions.
Full list lives in `core.permissions.ADMIN_DASHBOARD_PERMISSIONS`.

The permissions relevant to the admin dashboard:
```
admin_users / admin_users.list / admin_users.add
subscription_plans / subscription_plans.manage
discount_codes / discount_codes.manage
user_accounts / user_accounts.single / user_accounts.teams / user_accounts.fleet
income_expenses / income_expenses.* (4 sub-perms)
reporting_analytics / reporting_analytics.revenue_metrics
support_tools / support_tools.* (4 sub-perms)
security_logging_compliance / security_logging_compliance.audit_logs / security_logging_compliance.data_protection
```

### Swagger Tags Convention
Tags are formatted as `"Section - Subsection"`, for example:
- `"Auth - Admin"`, `"Auth - User"`
- `"User Management - Admin"`
- `"Security - Data Protection"`, `"Security - Audit Logs"`

All new views **must** use `@extend_schema(tags=[...])` or `@extend_schema_view(...)`.
All new `SerializerMethodField` methods **must** use `@extend_schema_field(...)` to avoid schema warnings.

### Email Sending
Use `core.models.EmailConfig` (first active record) to build a dynamic SMTP connection.
Never use `settings.EMAIL_*` directly. Pattern lives in `account/emailsend.py`.

### ActivityLog
Write audit entries via `notification.models.ActivityLog`. Fields:
`user`, `action` (NotifyLogAction choice), `message`, `status` (LogStatus), `entity_type` (ContentType), `entity_id`, `ip_address`, `device_info`, `metadata_json`.

---

## Key Models Summary

### account app
- `User` — custom user model (email as username, `user_type`: ADMIN / MAIN_USER, `status`: ACTIVE / SUSPENDED / BLOCKED)
- `AdminUserProfile` — profile for admin dashboard users (`full_name`, `phone`, `permissions_json`)
- `OTPVerification` — OTP records for login / register / reset
- `Team` — fleet team owned by a MAIN_USER
- `TeamMember` — users inside a team
- `TeamMemberInvite` — invite links (UUID-based)
- `UserPaymentMethod` — stored payment methods

### core app
- `EmailConfig` — SMTP configuration, admin-managed, supports daily limits
- `AIExtractResponse` — raw AI extraction results

### notification app
- `ActivityLog` — immutable audit trail (admin actions, user actions)
- `Notification` — in-app notifications (WIP)

### route app
- `Route` — top-level route (created by user or team, AI processing status, tracking fields)
- `RoutePermit` — one permit per route leg (file upload, AI extraction, waypoints)
- `PermitWaypoint` — extracted waypoints per permit
- `RouteHistory` — status change log
- `RouteTracking` — real-time GPS tracking records

### subscription app
- `SubscriptionPlan` — plan catalog (iOS/Android product IDs, price, team_limit)
- `UserSubscription` — active user subscriptions (status, grace period, payment_status)
- `PurchaseInfo` — raw IAP receipt/token data per platform

### security app  ← **NEW (built in this project)**
- `DataProtectionRequest` — GDPR/data request form (full lifecycle)
- `DataRequestNote` — append-only notes + correspondence per request

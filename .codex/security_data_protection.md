# Security App — Data Protection Context

## Source
`docs/admin_dashboard/08 Security - Data Protection section.pdf`

## Purpose
GDPR/legal compliance — allows admins to process customer data requests (export, delete, anonymize) in a structured, auditable workflow.

## Status Flow
```
NEW  →  PENDING_APPROVAL  →  COMPLETED
```

## Request ID Format
- Pattern: `DR-{YEAR}-{4_DIGIT_RANDOM}` e.g. `DR-2026-0048`
- Must be unique — never reuse a 4-digit suffix
- Auto-generated when the page is opened (before saving)

## Form Fields (Active Request Form)

| Field | Source | Notes |
|---|---|---|
| request_id | Auto-generated | DR-YYYY-XXXX |
| date_requested | Defaults to now | Admin-correctable; reflects when RightRoute *received* the request |
| customer_email | Admin input | Email the customer provided at time of request |
| customer_user | Auto-filled via FIND | FK to User account |
| customer_name | Auto-filled | From User profile |
| plan_type | Auto-filled | Current plan |
| account_status | Auto-filled | ACTIVE / SUSPENDED / BLOCKED |
| account_created_at | Auto-filled | |
| phone_number | Auto-filled | When stored |
| warning | System-computed | See warnings section |
| source | Dropdown | PHONE, EMAIL, WRITTEN, OTHER |
| source_other_detail | Text | Only when source=OTHER |
| request_type | Dropdown | EXPORT, DELETE, ANONYMIZE, DELETE_ANONYMIZE |
| approval_received | Checkbox | Customer replied confirming |
| approval_source | Text | How approval came (email/phone/letter) |
| approval_received_date | Date | When admin received approval |
| admin_confirmed | Checkbox | Admin confirms they understand irreversibility |

## Warning Conditions (checked automatically after FIND)
1. **Active paid subscription** — user has an active subscription
2. **Open billing dispute** — open payment dispute found
3. **Previous privacy request already open** — another DataProtectionRequest for this user with status != COMPLETED
4. **Customer account blocked** — account status is BLOCKED

## Request Types & Descriptions
| Type | Description |
|---|---|
| EXPORT | Collect eligible data → PDF/CSV/JSON → ZIP → secure download link |
| DELETE | Run approved deletion workflow (categories: deleted/retained/not found/unable/backup-scheduled) |
| ANONYMIZE | Remove/transform direct+indirect identifiers, break links, confirm no re-identification possible |
| DELETE_ANONYMIZE | Delete no-longer-needed personal data + anonymize retained records |

> **PDF note**: Only implement EXPORT fully for now. Stub others with TODO.

## Buttons & State Transitions

### EMAIL CUSTOMER
- Formats request info into email preview
- Recipient locked to verified account email (cannot be changed)
- Admin can add short personal message
- On send: logs email text into Notes as system note
- Form stays open

### SAVE AS NEW
- Saves form, closes it, places in New Requests list
- Records who saved it + when in Notes

### SAVE AS PENDING APPROVAL
- Requires: account found + request type selected + approval email sent + verified email present
- Records approval email sent date + admin responsible
- Places in Pending Approval list

### PERFORM APPROVED REQUEST
- Requires ALL 4 checks: approval_received + approval_source + approval_received_date + admin_confirmed
- Shows final confirmation dialog with customer name, email, request type
- Admin clicks CONFIRM AND PERFORM REQUEST
- Runs the backend process
- Logs system note in Notes

### SEND COMPLETION EMAIL AND CLOSE
- Opens completion email preview (full form + notes + download link for export)
- Download link: not public, expires 7 days, revocable, auto-removed after retention period
- Sends to verified account email
- Logs full email in Notes
- Records completion date
- Changes status to COMPLETED
- Moves to Completed Requests list
- Logs in Audit Log

## Right-Side Lists (pagination: 4 rows each)

### New Requests
- Customer name + email
- Request type
- OPEN button

### Pending Approval
- Customer name + email
- Request type
- Approval email sent date
- OPEN button

### Completed Requests
- Customer name + email
- Request type
- Completion date
- OPEN button

## API Endpoints

| Method | URL | Description |
|---|---|---|
| GET | `/api/v1/security/data-protection/` | List all (filter by status) |
| POST | `/api/v1/security/data-protection/` | Create new request |
| GET | `/api/v1/security/data-protection/{id}/` | Retrieve detail |
| PATCH | `/api/v1/security/data-protection/{id}/` | Update form fields |
| POST | `/api/v1/security/data-protection/generate-id/` | Get next auto-generated DR ID |
| POST | `/api/v1/security/data-protection/find-customer/` | Find user by email |
| POST | `/api/v1/security/data-protection/{id}/notes/` | Add note |
| POST | `/api/v1/security/data-protection/{id}/email-customer/` | Send approval email |
| POST | `/api/v1/security/data-protection/{id}/save-as-pending/` | Move to pending |
| POST | `/api/v1/security/data-protection/{id}/perform/` | Perform the request |
| POST | `/api/v1/security/data-protection/{id}/send-completion-email/` | Send completion + close |
| GET | `/api/v1/security/data-protection/download/{token}/` | Secure download of ZIP |

## Swagger Tag
`Security - Data Protection`

## Permission
`security_logging_compliance.data_protection` (already in ADMIN_DASHBOARD_PERMISSIONS in `core/permissions.py`)

# AI Agent Behavior Guide

This file governs how the AI assistant should behave when working on the RightRoute backend.
Read this before taking any action on the codebase.

---

## 0. Always Read First

Before starting any task:
1. Read `.codex/project_overview.md` — understand the tech stack, patterns, and conventions.
2. Read `.codex/development_status.md` — know what's already built and what PDFs map to what.
3. Read any other `.codex/*.md` file relevant to the task at hand.

---

## 1. The Golden Rule — Do Not Touch Existing Code

**Existing APIs, views, serializers, models, URLs, and migrations are in production and must not be modified without explicit developer approval.**

- If a change to existing code is required (even one line), **stop**, explain what needs to change and why, and **wait for approval** before proceeding.
- New features go into new files or new apps only.
- Adding to `INSTALLED_APPS` or to `urlpatterns` in the main `urls.py` is acceptable as an additive change, but still flag it clearly to the developer.

---

## 2. How to Handle a New PDF Section

When the developer tells you to read a specific PDF:

### Step 1 — Extract the PDF
Use PyMuPDF to extract all text to a scratch file:
```python
import pymupdf
doc = pymupdf.open(r'docs/admin_dashboard/<filename>.pdf')
with open(r'<scratch_path>.txt', 'w', encoding='utf-8') as f:
    for i, page in enumerate(doc):
        f.write(f'--- PAGE {i+1} ---\n')
        f.write(page.get_text())
doc.close()
```

### Step 2 — Analyze the full content carefully
Read every page. Extract:
- All form fields and their data types
- All API endpoints implied by the UI
- All workflows (button actions, status transitions, conditional logic)
- All business rules (who can do what, when buttons are enabled/disabled)
- All email content requirements

### Step 3 — Present an implementation plan
Write an `implementation_plan.md` artifact and **wait for approval** before writing any code.
The plan must include:
- Model fields (with types and constraints)
- API endpoint table (method, URL, description, swagger tag)
- Any open questions for the developer
- The two additive changes needed to `settings.py` and `urls.py`
- Verification plan

### Step 4 — Execute after approval
Build in this order: constants → models → admin → emails → serializers → views → urls → settings → urls.py

### Step 5 — Verify
```bash
.venv\Scripts\python.exe manage.py makemigrations <app>
.venv\Scripts\python.exe manage.py migrate <app>
.venv\Scripts\python.exe manage.py check
.venv\Scripts\python.exe manage.py show_urls | Select-String "<app>"
```

### Step 6 — Update `.codex/development_status.md`
Mark the PDF as complete and document all new endpoints.

---

## 3. Code Conventions

### Always follow these patterns — no exceptions:

**Views:**
- All admin dashboard views → `permission_classes = [IsAuthenticated, HasAdminDashboardPermission]`
- Set `required_admin_permission = "section.subsection"` on the view class
- Every view and action must have `@extend_schema(...)` with `tags`, `operation_id`, `summary`, `description`, `request`, and `responses`
- Response format: `{"success": True/False, "message": "...", "data": ...}`

**Serializers:**
- Every `SerializerMethodField` must have `@extend_schema_field(serializers.SomeType())` to avoid schema warnings
- `get_*` methods on serializers must be typed

**Swagger Tags:**
- Format: `"Section - Subsection"` (e.g. `"Security - Data Protection"`, `"Security - Audit Logs"`)
- Use `@extend_schema(tags=[TAG])` on the ViewSet class and `@extend_schema_view(action=extend_schema(...))` for individual actions
- Or `@extend_schema(tags=[TAG], ...)` directly on `APIView` methods

**Models:**
- Inherit from `core.common_models.BaseModel` for `created_at` / `updated_at`
- Use `TextChoices` for all choices — define them in `constants.py`
- Add `db_index=True` on fields used in filters
- Add `Meta.indexes` for composite queries

**Email:**
- Always use `EmailConfig.objects.filter(is_active=True).first()` to get SMTP credentials
- Never hard-code SMTP settings from `settings.py`
- Log sent email content as a system note (append-only) on the relevant model

**Audit:**
- Write to `notification.models.ActivityLog` for every CREATE / UPDATE / DELETE action performed by an admin

**New apps:**
- Must be added to `INSTALLED_APPS` in `settings.py`
- Must be included in `urlpatterns` in `right_route_config/urls.py`
- Always under `api/v1/`

---

## 4. File Layout for a New App

```
<app_name>/
├── __init__.py
├── apps.py
├── constants.py       ← TextChoices enums
├── models.py          ← inherit BaseModel, use constants
├── admin.py           ← register models, use inlines + fieldsets
├── emails.py          ← email builder + sender functions
├── serializers.py     ← all serializers with @extend_schema_field
├── views.py           ← ViewSet + APIView with full @extend_schema
├── urls.py            ← DefaultRouter + manual paths
└── migrations/
    └── 0001_initial.py
```

---

## 5. Stub Policy

When a feature is described in the PDF but cannot be fully implemented yet (e.g. waiting on a data list from the developer), **stub the function** with:
1. A clear `# TODO:` comment explaining what is needed
2. A working placeholder response (don't raise `NotImplementedError` in production paths)
3. A note in `.codex/development_status.md` listing the known TODOs

---

## 6. Run Python Commands

The project uses a virtual environment. Always run Python via:
```
.venv\Scripts\python.exe manage.py <command>
```

---

## 7. What NOT to Do

- Do not run `python manage.py` directly (wrong Python version)
- Do not use `&&` in PowerShell — run commands separately
- Do not modify any existing view, serializer, model, or URL
- Do not use TailwindCSS or any frontend framework in this backend project
- Do not create migrations for other apps — only for the new app being built
- Do not expose the `export_download_token` or export file path in public API responses (security-sensitive)

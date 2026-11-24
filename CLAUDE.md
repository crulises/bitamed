# CLAUDE.md

Project briefing. Read this before doing anything in this repository.

---

## What bitamed is

A web app for keeping a shared medical logbook of a family's clinical
history. It stores scans and reports, extracts what can be extracted from
them, charts what is worth trending, tracks home measurements, and lets a
family member hand a doctor exactly the slice of the record they need through
a link and a PIN.

It is **not** a medical device. It records and organizes. It does not
diagnose, does not interpret values, and does not tell anyone what a result
means. That boundary is a design constraint, not a disclaimer.

Real users: the author, his siblings, and their parents' records. Deployed
self-hosted. Possibly opened to the public later, which is why multi-tenancy,
i18n and consent are designed in from the start rather than retrofitted.

A secondary long-term goal shapes the data model: the structured layer is
meant to become a metadata base a specialised health agent can reason over.
That is why the schema mirrors FHIR resource names and uses a controlled
vocabulary for analytes.

---

## Stack

| Layer | Choice | Why |
|---|---|---|
| Web | FastAPI + Jinja2 + HTMX + Tailwind | Server-rendered. No SPA: one app to maintain, not two. |
| DB | PostgreSQL 16 | `pgcrypto`, `citext`, `unaccent`, `pg_trgm`. `pgvector` planned. |
| Objects | MinIO in dev, S3/R2 in prod | S3 API either way, so no code change between them. |
| Queue | Redis + arq | Ingestion cannot run in a request. Celery is overkill at this size. |
| OCR | ocrmypdf + Tesseract (spa+por+eng) | Self-hosted and deterministic. Adds a text layer without altering the PDF. |
| Preprocessing | OpenCV (perspective only) | ocrmypdf's `--deskew --clean --rotate-pages` covers the rest. |
| Auth | Server-side sessions in Redis, argon2id | Revocation has to be real. |
| Dev env | Docker Compose | Reproducible on Windows/WSL2 and macOS (arm64 + amd64 native). |

**The root Python package is `app`.** Do not rename it. `docker-compose.yml`,
`Dockerfile` and `README.md` all reference `app/` by path.

Mobile-first. Most usage is a phone: scanning a QR at a clinic, entering a
blood pressure reading, photographing a lab report. Desktop matters for bulk
work only.

---

## Build order

Three phases, in this order, because each depends on the previous.

1. **Ingestion pipeline** — upload N photos or a PDF, preprocess, OCR,
   compile a searchable PDF, extract candidate observations, park them in a
   human review queue.
2. **Auth, roles and permissions** — accounts, closed registration with admin
   approval, per-logbook membership, the capability matrix, consent gating,
   invitations, ownership transfer, audit log. **← CURRENT PHASE**
3. **Shares end to end** — scoped share creation, QR generation, public view
   with PIN and rate limiting, access log, active-shares management screen.

Phase 2 exists as code. Phases 1 and 3 are schema-only so far.

Do not start work on phase 1 or 3 unless asked. If a phase-2 task seems to
require something from another phase, say so and wait.

---

## Non-negotiable principles

These are decisions already made after discussion. Do not relitigate them in
code.

1. **The original file is the only source of truth.** OCR text and extracted
   values are an index over it. Originals are never modified and never
   deleted, even when a document is soft-deleted.
2. **Nothing automatic is trusted.** Every extracted observation enters as
   `unconfirmed` and requires a human editor to promote it. A CHECK
   constraint enforces that manual entries cannot be unconfirmed and that
   confirmed rows name who confirmed them.
3. **Consent is per logbook and revocable.** Revoking it fires a database
   trigger that kills every active share and flips the logbook to read-only.
   Enforced in the database, not in application politeness.
4. **Every share is scoped, expiring, revocable and logged.**
5. **The system never interprets.** It shows values and the reference range
   the lab printed. Never add thresholds, alerts, colour-coded "abnormal"
   flags, risk scores or clinical suggestions.
6. **Routes never check roles.** They declare a `Permission` and
   `require(...)` decides. All policy lives in `app/auth/permissions.py`.

---

## Feature set

### Documents and ingestion (phase 1)
- Upload N phone photos or a PDF; they compile into one document.
- OpenCV perspective correction for phone photos, with a preview and an
  escape hatch to use the raw original.
- `ocrmypdf` adds a searchable text layer. Languages `spa+por` by default,
  configurable per logbook and per document.
- Digital PDFs skip OCR and go through pymupdf text extraction.
- hOCR word-level bounding boxes are stored, so tapping a chart point can
  highlight the exact source line in the PDF.
- Extraction engine is pluggable and recorded per job (`rules-v1` today; an
  LLM-backed extractor plugs in later without a schema change).
- Human review queue for every extracted value.
- Study types: laboratory, imaging, functional (ECG, spirometry), pathology,
  discharge summary, prescription, consultation note, other.
- Tags plus full-text search over OCR text, using `unaccent` + `pg_trgm`
  rather than per-language stemming.
- Bulk backfill mode for digitising a box of old paper studies.

### Structured data
- Two separate layers: **documents** (immutable, source of truth) and
  **observations** (structured, derived, with full provenance).
- Controlled vocabulary of **analytes** with a language-agnostic **alias**
  table that maps whatever string a lab printed onto a stable analyte id.
  The review queue grows the alias table ("remember this name").
- UCUM units, with per-analyte conversion to a canonical unit.
- LOINC codes optional and nullable. Do not import all of LOINC.
- Reference ranges live on the observation, as printed on that report.
- Trend charts per analyte across labs and across years.

### Home tracking
- Home readings reuse `observation`; they simply have no backing document.
- Blood pressure, capillary glucose, fluid intake, weight, heart rate,
  temperature, SpO2, pain score.
- `effective_time` alongside `effective_date`.
- `reading_group_id` pairs systolic + diastolic + pulse from one measurement.
- `context_code` (fasting, pre/post meal, seated, standing, post-medication).
- `aggregation` per analyte: `instant`, `daily_sum` (fluid intake),
  `daily_mean`.
- `reported_by_name`: who took the reading, who may have no account.
- **`journal_entry`** for what is not a number: symptoms, how the night went,
  a fall, a missed dose. Free text, optional 0-10 severity, tags, optional
  link to an episode.
- **`tracking_plan`**: what a professional asked the family to record, how
  often, since when, who prescribed it. The instruction is stored as text
  exactly as given and is **never** turned into a threshold the app evaluates.

### Status page (per person)
- Modelled on software incident pages.
- `episode` (open / monitoring / resolved, with severity) plus an
  append-only `episode_update` timeline. Corrections are new updates, never
  edits, so the timeline a reader saw yesterday still reads the same today.
- Shareable independently from the clinical record: relatives who want to
  know how a hospitalisation is going do not need the lab history.

### Sharing (phase 3)
- Scope: `all`, `selection`, or `filter` (date range, tags, study types,
  analytes).
- `snapshot` by default: the document list is materialised at creation and
  frozen. `live` re-evaluates the filter on each view and is forced to a
  short expiry; it exists for ongoing hospitalisations.
- Link + 4-digit PIN, communicated separately from the link.
- Expiry, revocation, optional max views, full access log.
- QR code generation.
- Home readings and journal entries are excluded by default and have their
  own date window.
- "Active shares" screen: who, what scope, expires when, viewed how often,
  and a large revoke button.

### Accounts and permissions (phase 2, current)
- Closed registration by default: signup creates a `registration_request`, an
  instance admin approves, then the account exists. Opening to the public is
  a config flag.
- Roles per logbook: `owner`, `editor`, `commenter`, `viewer`. Exactly one
  owner, enforced by a partial unique index. Ownership is transferred under a
  row lock, never invited.
- **The instance admin has no access to any logbook's contents.** Approving
  signups and reading a medical record are different powers.
- Invitations are bound to the email they were sent to.
- Audit log on every privileged action.
- Terms acceptance per user at signup; subject consent per logbook.

---

## Legal context

Argentina. Health data is **sensitive personal data** under Ley 25.326 art. 2.

- The operator is not a health professional, so the lawful basis for holding a
  family member's data is that person's **consent**, not the terms of service.
  Hence `subject_consent`, separate from `terms_acceptance`.
- Every share is a **cesión** under art. 11: consented, informed, revocable.
- Art. 9 requires technical security measures; AAIP Resolución 47/2018 is the
  practical checklist being followed.
- Ley 26.529 makes the patient the owner of their clinical history, with a
  right to a copy within 48 hours. Useful for sourcing historical records.
- Registering the database with the AAIP and GDPR-style compliance are
  deferred until the instance opens beyond family.

Design consequences already implemented: consent revocation cascades, raw IPs
are never stored (salted hashes only), tokens are stored hashed, and export is
always available so the right of access survives.

---

## Internationalisation

- Languages: `es` (default), `pt`, `en`.
- **Interface is translated. Content is never translated.** Documents,
  observations, journal entries and comments stay as entered. Never machine
  translate clinical content.
- Analyte display names are per language; aliases are raw strings with no
  language attached (Portuguese "Creatinina" is just another alias).
- Code, schema, comments and documentation are in English. UI strings are in
  the i18n catalogs.
- **Decimal comma trap**: Argentine and Brazilian reports write `1,20`.
  Always store `numeric` normalised and format in the view. Parsing with the
  wrong locale introduces a factor of 100 into a clinical value.

---

## Repository layout

See `docs/STRUCTURE.md` for the canonical file manifest. In short:

```
db/schema.sql           reference for the FULL database schema
db/seed_analytes.sql    analyte vocabulary
db/migrations/          incremental changes
docs/GLOSSARY.md        domain terms in en / es / pt
app/models/             SQLAlchemy, mirrors only the subset the code touches
app/auth/               permissions matrix, sessions, dependencies, routes
app/logbooks/           membership, invitations, ownership, consent
tests/                  the permission matrix as an executable specification
```

`db/schema.sql` is the reference for the database. The ORM models
deliberately cover only part of it. That is a decision, not an omission.

---

## Working rules

- **Do not rename, restructure, reformat or "improve" existing files.** If
  something looks wrong, say so and wait. Prior sessions authored this code
  after long design discussion; what looks like an oddity is usually a
  decision recorded in a comment.
- **Do not add features that were not asked for.**
- **Do not relitigate the principles above in code.** Raise them in
  conversation instead.
- Ask before any destructive operation: deleting files, `git reset --hard`,
  dropping volumes, bulk `sed` across the tree.
- Prefer small, reviewable changes. One concern per commit.
- Comments explain *why*, not *what*. Follow the density and tone of the
  existing files.
- Never commit `.env`, credentials, or any real patient data. Test fixtures
  use invented names.
- Never write clinical data into logs.
- When a decision has two reasonable answers, state the trade-off and let the
  author choose. Do not pick silently.

---

## Security requirements

These have bitten before or will:

- A 4-digit PIN has ~13 bits of entropy. **Rate limiting is what protects it**,
  not hashing. 5 attempts, exponential backoff, owner notified.
- Files are **never** served from a public MinIO/S3 URL. Every view goes
  through the backend, which validates the share and issues a short-lived
  presigned URL.
- `Referrer-Policy: no-referrer` and `X-Robots-Tag: noindex` on all shared
  views, so a token never leaks through a Referer header or a search index.
- Share tokens and session ids are stored hashed. A database dump must not
  yield working links or cookies.
- Return **404, not 403**, when someone is not a member of a logbook.
  Confirming that a logbook exists is itself a disclosure.
- Login failures are indistinguishable: wrong password, no such account,
  suspended and pending all return the same message, with constant-ish timing.
- Suspension and password change kill all live sessions immediately.
- Never surface stack traces or database errors to a client.

---

## Known gaps

Confirm these are still open. Do not fix them unprompted.

- `app/worker.py` does not exist; the compose `worker` service crash-loops.
  Comment the service out until phase 1.
- `templates/` and `static/` are mounted by compose but do not exist. Create
  them empty with `.gitkeep`.
- No `legal_document` rows exist. Registration and logbook creation fail by
  design until a bootstrap script inserts terms, privacy and subject_consent
  for es/pt/en.
- ~~Alembic is in `requirements.txt` but not wired up.~~ Resolved: Alembic
  owns migrations from `db/migrations/`, run via `alembic -c db/alembic.ini`.
  `db/schema.sql` is now reference documentation only, regenerated by hand
  when a migration lands.
- Password recovery by email is not implemented. With closed registration, an
  admin-triggered reset may be sufficient.
- The seed maps the alias `PCR` to C-reactive protein, which is ambiguous in
  Spanish (it can also mean polymerase chain reaction). The
  `analyte_alias.seen_in_lab` column exists to disambiguate when it comes up.

---

## Out of scope

Naming these keeps them from creeping in.

- DICOM handling and any analysis of medical images. Imaging studies are
  stored, OCR'd and tagged; the radiologist's report is the finding.
- Diagnoses and medications as coded data. Free text plus tags. No SNOMED CT,
  no drug database, no interaction checking.
- Any clinical interpretation, scoring, alerting or recommendation.
- Appointment booking, billing, insurance, pharmacy integration.
- Native mobile apps. The web app is mobile-first; a PWA with an offline
  queue for home readings is the plan, not a separate codebase.

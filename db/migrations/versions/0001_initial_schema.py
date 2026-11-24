"""Initial schema.

Wraps the hand-written schema.sql as a single statement: this predates
Alembic, and splitting ~700 lines of enums/tables/views/triggers into
op.create_table() calls would just be a lossy transcription of the same SQL.

Revision ID: 0001
Revises:
Create Date: 2025-09-12

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SQL = r"""
-- =============================================================================
-- bitamed - database schema
-- PostgreSQL 16
--
-- Naming: English throughout. FHIR-inspired resource names where a mapping
-- exists, noted per table. See docs/GLOSSARY.md for the Spanish/Portuguese
-- equivalents of every domain term used here.
--
-- Design rules encoded in this file:
--   1. The uploaded file is the single source of truth. Everything derived
--      (OCR text, observations) points back to it and is never authoritative.
--   2. Extracted data starts UNCONFIRMED and requires a human editor to
--      promote it. Nothing automatic is trusted.
--   3. Health data is sensitive personal data. Consent is per logbook and
--      revocable; revoking it kills every active share.
--   4. Shares are scoped, expiring, revocable and fully audited.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS citext;     -- case-insensitive email
CREATE EXTENSION IF NOT EXISTS unaccent;   -- accent-insensitive search
CREATE EXTENSION IF NOT EXISTS pg_trgm;    -- trigram search over OCR text

-- Immutable accent-stripping wrapper so it can be used in generated columns
-- and expression indexes (unaccent() itself is only STABLE).
CREATE OR REPLACE FUNCTION immutable_unaccent(text)
RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT AS
$$ SELECT public.unaccent('public.unaccent', $1) $$;

-- Normalizes any free-text label to its matching key: lowercase, unaccented,
-- collapsed whitespace. Used for analyte alias lookup and tag slugs.
CREATE OR REPLACE FUNCTION normalize_label(text)
RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT AS
$$ SELECT regexp_replace(lower(immutable_unaccent($1)), '\s+', ' ', 'g') $$;


-- =============================================================================
-- ENUMS
-- =============================================================================

CREATE TYPE user_status        AS ENUM ('pending', 'active', 'suspended');
CREATE TYPE membership_role    AS ENUM ('owner', 'editor', 'commenter', 'viewer');
CREATE TYPE legal_kind         AS ENUM ('terms', 'privacy', 'subject_consent');
CREATE TYPE consent_capacity   AS ENUM ('self', 'legal_representative');
CREATE TYPE logbook_status     AS ENUM ('active', 'consent_revoked', 'archived');

-- Study families. Deliberately coarse: fine-grained typing lives in tags.
CREATE TYPE study_type AS ENUM (
    'laboratory',        -- blood, urine, any analyte-bearing panel
    'imaging',           -- ultrasound, x-ray, CT, MRI, scintigraphy
    'functional',        -- ECG, spirometry, stress test, EEG
    'pathology',         -- biopsy, cytology
    'discharge_summary', -- epicrisis / hospitalization discharge
    'prescription',
    'consultation_note',
    'other'
);

CREATE TYPE asset_role AS ENUM (
    'original_upload',   -- exactly as received. NEVER modified, NEVER deleted.
    'processed_page',    -- deskewed/cropped derivative of one original page
    'compiled_pdf',      -- the assembled, OCR'd PDF the doctor actually sees
    'thumbnail'
);

CREATE TYPE ingestion_state AS ENUM (
    'queued', 'preprocessing', 'ocr', 'extraction', 'awaiting_review',
    'done', 'failed'
);

-- Where a value came from and how much we trust it.
CREATE TYPE entry_mode AS ENUM ('manual', 'extracted');
CREATE TYPE observation_status AS ENUM ('unconfirmed', 'confirmed', 'rejected');

CREATE TYPE encounter_class AS ENUM (
    'ambulatory', 'inpatient', 'emergency', 'home_health', 'virtual'
);

CREATE TYPE episode_state    AS ENUM ('open', 'monitoring', 'resolved');
CREATE TYPE episode_severity AS ENUM ('info', 'minor', 'major', 'critical');

CREATE TYPE share_scope      AS ENUM ('all', 'selection', 'filter');
CREATE TYPE share_resolution AS ENUM ('snapshot', 'live');
CREATE TYPE share_outcome    AS ENUM ('ok', 'pin_failed', 'expired', 'revoked', 'not_found');

CREATE TYPE comment_visibility AS ENUM ('internal', 'shared');


-- =============================================================================
-- IDENTITY AND ACCESS
-- =============================================================================

-- "user" is reserved in SQL, hence user_account.
CREATE TABLE user_account (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email           citext NOT NULL UNIQUE,
    password_hash   text   NOT NULL,          -- argon2id
    display_name    text   NOT NULL,
    locale          text   NOT NULL DEFAULT 'es',  -- 'es' | 'pt' | 'en'
    timezone        text   NOT NULL DEFAULT 'America/Argentina/Buenos_Aires',
    status          user_status NOT NULL DEFAULT 'pending',
    is_instance_admin boolean NOT NULL DEFAULT false,
    -- Instance admin is a global flag. Everything else is per logbook.
    totp_secret     text,
    last_login_at   timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- Self-service signup lands here. An instance admin approves before the
-- account becomes usable. Lets the deployment stay closed to family and be
-- opened later without a schema change.
CREATE TABLE registration_request (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email         citext NOT NULL,
    display_name  text NOT NULL,
    note          text,                        -- "soy el hermano de Uli"
    requested_at  timestamptz NOT NULL DEFAULT now(),
    reviewed_at   timestamptz,
    reviewed_by   uuid REFERENCES user_account(id),
    approved      boolean,
    rejection_reason text
);
CREATE UNIQUE INDEX registration_request_open_email_uq
    ON registration_request (email) WHERE reviewed_at IS NULL;


-- =============================================================================
-- LEGAL: TERMS, PRIVACY NOTICE, SUBJECT CONSENT
-- =============================================================================

-- Versioned legal texts, one row per (kind, lang, version).
-- Never UPDATE a published row: publish a new version instead, so that
-- "which text did this person accept" always has an exact answer.
CREATE TABLE legal_document (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind           legal_kind NOT NULL,
    lang           text NOT NULL,              -- 'es' | 'pt' | 'en'
    version        text NOT NULL,              -- '0.1.0'
    effective_from timestamptz NOT NULL,
    body_md        text NOT NULL,
    content_hash   text NOT NULL,              -- sha256 of body_md
    UNIQUE (kind, lang, version)
);

-- Accepted by a USER, at signup. Covers the user <-> operator relationship.
CREATE TABLE terms_acceptance (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           uuid NOT NULL REFERENCES user_account(id) ON DELETE CASCADE,
    legal_document_id uuid NOT NULL REFERENCES legal_document(id),
    accepted_at       timestamptz NOT NULL DEFAULT now(),
    ip_hash           text,                    -- hashed, not raw
    user_agent        text,
    UNIQUE (user_id, legal_document_id)
);


-- =============================================================================
-- LOGBOOK (the aggregate root) + PATIENT
-- =============================================================================

-- One logbook == one person's medical record.
-- Patient demographics are folded in here (1:1). Maps to FHIR Patient; split
-- into its own table only if a logbook ever needs to cover several people.
CREATE TABLE logbook (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug            text NOT NULL UNIQUE,
    display_name    text NOT NULL,             -- "Papá"

    -- FHIR Patient
    patient_given_name  text NOT NULL,
    patient_family_name text NOT NULL,
    patient_birth_date  date,
    patient_sex         text,                  -- 'male'|'female'|'other'|'unknown'
    patient_national_id text,                  -- DNI. Optional, encrypted at rest.
    blood_type          text,

    default_locale  text NOT NULL DEFAULT 'es',
    ocr_languages   text NOT NULL DEFAULT 'spa+por',  -- tesseract -l argument
    status          logbook_status NOT NULL DEFAULT 'active',
    created_by      uuid NOT NULL REFERENCES user_account(id),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- Accepted per LOGBOOK, by the data subject (or their legal representative).
-- This, not terms_acceptance, is the lawful basis for processing the health
-- data of a third party. Revoking it flips logbook.status and must cascade
-- into revoking every active share (enforced in application logic + trigger).
CREATE TABLE subject_consent (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    logbook_id           uuid NOT NULL REFERENCES logbook(id) ON DELETE CASCADE,
    legal_document_id    uuid NOT NULL REFERENCES legal_document(id),
    subject_name         text NOT NULL,
    capacity             consent_capacity NOT NULL,
    representative_note  text,                 -- basis, if not 'self'
    granted_by_user_id   uuid NOT NULL REFERENCES user_account(id),
    granted_at           timestamptz NOT NULL DEFAULT now(),
    revoked_at           timestamptz,
    revocation_note      text,
    evidence_document_id uuid                  -- FK added after document exists
);
CREATE UNIQUE INDEX subject_consent_active_uq
    ON subject_consent (logbook_id) WHERE revoked_at IS NULL;

CREATE TABLE membership (
    logbook_id  uuid NOT NULL REFERENCES logbook(id) ON DELETE CASCADE,
    user_id     uuid NOT NULL REFERENCES user_account(id) ON DELETE CASCADE,
    role        membership_role NOT NULL,
    invited_by  uuid REFERENCES user_account(id),
    invited_at  timestamptz NOT NULL DEFAULT now(),
    joined_at   timestamptz,
    PRIMARY KEY (logbook_id, user_id)
);
-- Exactly one owner per logbook. Ownership transfer must be a single
-- transaction that demotes the old owner and promotes the new one.
CREATE UNIQUE INDEX membership_single_owner_uq
    ON membership (logbook_id) WHERE role = 'owner';

CREATE TABLE invitation (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    logbook_id   uuid NOT NULL REFERENCES logbook(id) ON DELETE CASCADE,
    email        citext NOT NULL,
    role         membership_role NOT NULL,
    token_hash   text NOT NULL,
    invited_by   uuid NOT NULL REFERENCES user_account(id),
    expires_at   timestamptz NOT NULL,
    accepted_at  timestamptz,
    revoked_at   timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CHECK (role <> 'owner')   -- ownership is transferred, never invited
);


-- =============================================================================
-- BLOB STORAGE
-- =============================================================================

-- One row per object in MinIO/S3. Content-addressed by sha256 so identical
-- re-uploads deduplicate instead of doubling storage.
CREATE TABLE stored_object (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    bucket        text NOT NULL,
    object_key    text NOT NULL,
    sha256        text NOT NULL,
    byte_size     bigint NOT NULL,
    mime_type     text NOT NULL,
    -- Client-side envelope encryption metadata. NULL means server-side only.
    encryption_key_id text,
    uploaded_by   uuid REFERENCES user_account(id),
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (bucket, object_key)
);
CREATE INDEX stored_object_sha256_idx ON stored_object (sha256);


-- =============================================================================
-- DOCUMENTS  (FHIR DocumentReference + DiagnosticReport, merged)
-- =============================================================================

CREATE TABLE document (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    logbook_id      uuid NOT NULL REFERENCES logbook(id) ON DELETE CASCADE,

    title           text NOT NULL,             -- "Laboratorio completo"
    study_type      study_type NOT NULL,
    -- effective_date is the CLINICAL date (when the sample was taken / the
    -- study was performed), not the upload date. This is the axis every chart
    -- and every date-range share filters on.
    effective_date  date NOT NULL,
    performer_name  text,                      -- lab or imaging centre
    ordering_physician text,
    note            text,

    -- Denormalized rollup of the compiled artifact, for fast rendering.
    compiled_pdf_object_id uuid REFERENCES stored_object(id),
    page_count      int,

    -- Full OCR text of the whole document, for search. Kept denormalized on
    -- purpose: pg_trgm over one column beats joining page rows at this scale.
    ocr_text        text,
    search_text     text GENERATED ALWAYS AS (
                        normalize_label(coalesce(title,'') || ' ' ||
                                        coalesce(performer_name,'') || ' ' ||
                                        coalesce(note,'') || ' ' ||
                                        coalesce(ocr_text,''))
                    ) STORED,

    encounter_id    uuid,                      -- FK added below
    created_by      uuid NOT NULL REFERENCES user_account(id),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    deleted_at      timestamptz                -- soft delete; originals survive
);
CREATE INDEX document_logbook_date_idx ON document (logbook_id, effective_date DESC);
CREATE INDEX document_search_trgm_idx  ON document USING gin (search_text gin_trgm_ops);

ALTER TABLE subject_consent
    ADD CONSTRAINT subject_consent_evidence_fk
    FOREIGN KEY (evidence_document_id) REFERENCES document(id);

-- Every physical file attached to a document, including every original upload.
-- Deleting a document never deletes rows with role='original_upload'.
CREATE TABLE document_asset (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id      uuid NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    stored_object_id uuid NOT NULL REFERENCES stored_object(id),
    role             asset_role NOT NULL,
    page_number      int,                      -- 1-based, NULL for whole-doc
    derived_from_id  uuid REFERENCES document_asset(id),  -- processed -> original
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX document_asset_document_idx ON document_asset (document_id, role, page_number);

-- Per-page OCR output. hocr holds word-level bounding boxes; that is what
-- makes "tap a chart point, see the exact line highlighted in the PDF" work.
CREATE TABLE document_page_text (
    document_id  uuid NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    page_number  int  NOT NULL,
    text         text NOT NULL,
    hocr         text,
    ocr_engine   text NOT NULL,                -- 'tesseract-5.3.4'
    ocr_language text NOT NULL,                -- 'spa+por'
    mean_confidence real,
    PRIMARY KEY (document_id, page_number)
);

CREATE TABLE tag (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    logbook_id  uuid NOT NULL REFERENCES logbook(id) ON DELETE CASCADE,
    label       text NOT NULL,
    slug        text GENERATED ALWAYS AS (normalize_label(label)) STORED,
    color       text,
    UNIQUE (logbook_id, label)
);

CREATE TABLE document_tag (
    document_id uuid NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    tag_id      uuid NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
    PRIMARY KEY (document_id, tag_id)
);


-- =============================================================================
-- INGESTION PIPELINE
-- =============================================================================

CREATE TABLE ingestion_job (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id   uuid NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    state         ingestion_state NOT NULL DEFAULT 'queued',
    -- Pluggable engines, set per job so the choice is recorded forever and
    -- an LLM-based extractor can be introduced later without a migration.
    preprocess_engine text NOT NULL DEFAULT 'opencv-perspective+ocrmypdf-clean',
    ocr_engine        text NOT NULL DEFAULT 'tesseract',
    extraction_engine text NOT NULL DEFAULT 'rules-v1',
    attempts      int NOT NULL DEFAULT 0,
    error_message text,
    started_at    timestamptz,
    finished_at   timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ingestion_job_state_idx ON ingestion_job (state, created_at);


-- =============================================================================
-- CONTROLLED VOCABULARY: ANALYTES
-- =============================================================================

-- The canonical list of measurable quantities we track over time.
-- Small and hand-curated on purpose. loinc_code stays NULL until someone
-- cares enough to fill it in; importing all of LOINC is a non-goal.
CREATE TABLE analyte (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code              text NOT NULL UNIQUE,    -- 'creatinine_serum', stable forever
    loinc_code        text,                    -- '2160-0'
    specimen          text NOT NULL,           -- 'serum'|'plasma'|'whole_blood'|'urine'|...
    category          text NOT NULL,           -- 'renal'|'hepatic'|'lipids'|...

    reported_unit     text NOT NULL,           -- UCUM, unit we display: 'mg/dL'
    canonical_unit    text NOT NULL,           -- UCUM, unit we store: 'umol/L'
    -- value_canonical = value * conversion_factor. Molar-mass dependent,
    -- which is exactly why it lives per analyte and not in a generic table.
    conversion_factor numeric NOT NULL DEFAULT 1,

    -- Plausibility bounds, NOT clinical reference ranges. Used only to flag
    -- an OCR that read 1.2 as 12. Reference ranges live on the observation.
    plausible_low     numeric,
    plausible_high    numeric,
    higher_is_worse   boolean,                 -- chart direction hint, nullable
    sort_order        int NOT NULL DEFAULT 100,
    is_active         boolean NOT NULL DEFAULT true
);

-- Display names per UI language. Content is never translated; only labels.
CREATE TABLE analyte_name (
    analyte_id   uuid NOT NULL REFERENCES analyte(id) ON DELETE CASCADE,
    lang         text NOT NULL,                -- 'es' | 'pt' | 'en'
    display_name text NOT NULL,
    short_name   text,
    PRIMARY KEY (analyte_id, lang)
);

-- The workhorse. Maps whatever string a lab printed to a known analyte.
-- Language-agnostic by design: "Creatinina" serves both es and pt.
-- Populated incrementally from the review queue ("remember this name").
CREATE TABLE analyte_alias (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    analyte_id    uuid NOT NULL REFERENCES analyte(id) ON DELETE CASCADE,
    raw_text      text NOT NULL,               -- as printed
    normalized    text GENERATED ALWAYS AS (normalize_label(raw_text)) STORED,
    seen_in_lab   text,                        -- disambiguates conflicting labs
    created_by    uuid REFERENCES user_account(id),
    created_at    timestamptz NOT NULL DEFAULT now()
);
-- A normalized string maps to at most one analyte per lab context.
CREATE UNIQUE INDEX analyte_alias_lookup_uq
    ON analyte_alias (normalized, coalesce(seen_in_lab, ''));
CREATE INDEX analyte_alias_trgm_idx
    ON analyte_alias USING gin (normalized gin_trgm_ops);  -- fuzzy suggestions


-- =============================================================================
-- OBSERVATIONS  (FHIR Observation)
-- =============================================================================

CREATE TABLE observation (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    logbook_id     uuid NOT NULL REFERENCES logbook(id) ON DELETE CASCADE,
    analyte_id     uuid NOT NULL REFERENCES analyte(id),
    effective_date date NOT NULL,              -- copied from document, indexable

    -- As reported, untouched.
    value_numeric  numeric,
    value_text     text,                       -- 'Negativo', 'No reactivo'
    comparator     text,                       -- '<' | '>' | '<=' | '>='
    unit_reported  text,                       -- UCUM, as the lab reported it
    -- Derived, for cross-lab charting. NULL when unit conversion is unknown.
    value_canonical numeric,

    -- Reference range AS PRINTED ON THIS REPORT. Varies by lab, sex, age and
    -- method, so it belongs to the measurement, never to the analyte.
    ref_low        numeric,
    ref_high       numeric,
    ref_text       text,
    method_note    text,

    -- Provenance. Everything needed to jump back to the exact spot on paper.
    document_id    uuid REFERENCES document(id) ON DELETE SET NULL,
    source_page    int,
    source_snippet text,                       -- raw OCR line it came from
    source_bbox    int[],                      -- [x0,y0,x1,y1] in page pixels
    matched_alias_id uuid REFERENCES analyte_alias(id),

    -- Trust.
    entry_mode     entry_mode NOT NULL,
    status         observation_status NOT NULL DEFAULT 'unconfirmed',
    extraction_confidence real,
    confirmed_by   uuid REFERENCES user_account(id),
    confirmed_at   timestamptz,

    created_by     uuid REFERENCES user_account(id),
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),

    CHECK (value_numeric IS NOT NULL OR value_text IS NOT NULL),
    -- Manually entered values are confirmed by definition; extracted ones
    -- must go through a human before they count.
    CHECK (entry_mode = 'extracted' OR status <> 'unconfirmed'),
    CHECK (status <> 'confirmed' OR confirmed_by IS NOT NULL)
);
-- The index behind every trend chart.
CREATE INDEX observation_series_idx
    ON observation (logbook_id, analyte_id, effective_date)
    WHERE status = 'confirmed';
CREATE INDEX observation_review_queue_idx
    ON observation (logbook_id, created_at)
    WHERE status = 'unconfirmed';
CREATE INDEX observation_document_idx ON observation (document_id);


-- =============================================================================
-- ENCOUNTERS AND STATUS PAGE
-- =============================================================================

-- FHIR Encounter: a hospitalization, a consultation, an ER visit.
CREATE TABLE encounter (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    logbook_id    uuid NOT NULL REFERENCES logbook(id) ON DELETE CASCADE,
    class         encounter_class NOT NULL,
    facility_name text,
    reason        text,
    started_at    timestamptz NOT NULL,
    ended_at      timestamptz,
    created_by    uuid NOT NULL REFERENCES user_account(id),
    created_at    timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE document
    ADD CONSTRAINT document_encounter_fk
    FOREIGN KEY (encounter_id) REFERENCES encounter(id) ON DELETE SET NULL;

-- The status-page primitive. Modelled on software incident pages: an episode
-- is a thing being followed, and updates are the append-only timeline of it.
CREATE TABLE episode (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    logbook_id   uuid NOT NULL REFERENCES logbook(id) ON DELETE CASCADE,
    encounter_id uuid REFERENCES encounter(id) ON DELETE SET NULL,
    title        text NOT NULL,                -- "Internación por neumonía"
    summary      text,
    state        episode_state NOT NULL DEFAULT 'open',
    severity     episode_severity NOT NULL DEFAULT 'info',
    started_at   timestamptz NOT NULL DEFAULT now(),
    resolved_at  timestamptz,
    created_by   uuid NOT NULL REFERENCES user_account(id),
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX episode_open_idx ON episode (logbook_id, started_at DESC)
    WHERE state <> 'resolved';

-- Append-only. Corrections are new updates, never edits, so the timeline
-- readers saw yesterday still reads the same today.
CREATE TABLE episode_update (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    episode_id   uuid NOT NULL REFERENCES episode(id) ON DELETE CASCADE,
    body_md      text NOT NULL,
    new_state    episode_state,                -- set when this update transitions
    new_severity episode_severity,
    posted_by    uuid NOT NULL REFERENCES user_account(id),
    posted_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX episode_update_timeline_idx ON episode_update (episode_id, posted_at DESC);


-- =============================================================================
-- COMMENTS
-- =============================================================================

-- Exactly one target, enforced by CHECK. Real foreign keys instead of a
-- polymorphic target_type/target_id pair, which buys referential integrity.
CREATE TABLE comment (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    logbook_id     uuid NOT NULL REFERENCES logbook(id) ON DELETE CASCADE,
    document_id    uuid REFERENCES document(id) ON DELETE CASCADE,
    observation_id uuid REFERENCES observation(id) ON DELETE CASCADE,
    episode_id     uuid REFERENCES episode(id) ON DELETE CASCADE,
    body_md        text NOT NULL,
    visibility     comment_visibility NOT NULL DEFAULT 'internal',
    author_id      uuid NOT NULL REFERENCES user_account(id),
    created_at     timestamptz NOT NULL DEFAULT now(),
    edited_at      timestamptz,
    deleted_at     timestamptz,
    CHECK (num_nonnulls(document_id, observation_id, episode_id) = 1)
);
CREATE INDEX comment_document_idx    ON comment (document_id)    WHERE deleted_at IS NULL;
CREATE INDEX comment_episode_idx     ON comment (episode_id)     WHERE deleted_at IS NULL;
CREATE INDEX comment_observation_idx ON comment (observation_id) WHERE deleted_at IS NULL;


-- =============================================================================
-- SHARES
-- =============================================================================

CREATE TABLE share (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    logbook_id          uuid NOT NULL REFERENCES logbook(id) ON DELETE CASCADE,
    label               text NOT NULL,         -- "Dr. Gómez, control marzo"
    recipient_note      text,

    -- 128-bit random token lives only in the URL. We store the hash, so a
    -- database leak does not hand over working links.
    token_hash          text NOT NULL UNIQUE,
    token_prefix        text NOT NULL,         -- first 8 chars, for the UI list
    pin_hash            text,                  -- argon2id, 4-digit PIN
    pin_failed_count    int NOT NULL DEFAULT 0,
    pin_locked_until    timestamptz,           -- exponential backoff

    scope_type          share_scope NOT NULL,
    resolution_mode     share_resolution NOT NULL DEFAULT 'snapshot',
    include_status_page boolean NOT NULL DEFAULT false,
    include_observations boolean NOT NULL DEFAULT true,
    allow_download      boolean NOT NULL DEFAULT true,

    expires_at          timestamptz NOT NULL,
    revoked_at          timestamptz,
    revoked_by          uuid REFERENCES user_account(id),
    max_views           int,
    view_count          int NOT NULL DEFAULT 0,
    last_viewed_at      timestamptz,

    created_by          uuid NOT NULL REFERENCES user_account(id),
    created_at          timestamptz NOT NULL DEFAULT now(),

    -- 'live' shares must expire quickly: they keep picking up new documents.
    CHECK (resolution_mode = 'snapshot' OR expires_at < created_at + interval '30 days')
);
CREATE INDEX share_active_idx ON share (logbook_id, created_at DESC)
    WHERE revoked_at IS NULL;

-- Criteria, for scope_type='filter'. Re-evaluated on each view in 'live' mode.
CREATE TABLE share_filter (
    share_id     uuid PRIMARY KEY REFERENCES share(id) ON DELETE CASCADE,
    date_from    date,
    date_to      date,
    tag_ids      uuid[],
    study_types  study_type[],
    analyte_ids  uuid[]
);

-- Materialized document list. Written at creation time for 'snapshot' shares
-- and refreshed on view for 'live' ones. Its real value is forensic: it
-- answers "exactly what did this person see" even after documents change.
CREATE TABLE share_item (
    share_id    uuid NOT NULL REFERENCES share(id) ON DELETE CASCADE,
    document_id uuid NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    added_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (share_id, document_id)
);

CREATE TABLE share_access_log (
    id          bigserial PRIMARY KEY,
    share_id    uuid NOT NULL REFERENCES share(id) ON DELETE CASCADE,
    accessed_at timestamptz NOT NULL DEFAULT now(),
    outcome     share_outcome NOT NULL,
    action      text NOT NULL,                 -- 'view'|'download'|'pin_attempt'
    document_id uuid REFERENCES document(id) ON DELETE SET NULL,
    ip_hash     text,                          -- salted hash, never raw IP
    user_agent  text,
    country     text
);
CREATE INDEX share_access_log_share_idx ON share_access_log (share_id, accessed_at DESC);


-- =============================================================================
-- AUDIT
-- =============================================================================

-- Append-only record of every privileged action. Required by the security
-- posture expected for sensitive data, and the first thing you will want
-- when something looks wrong.
CREATE TABLE audit_log (
    id           bigserial PRIMARY KEY,
    occurred_at  timestamptz NOT NULL DEFAULT now(),
    actor_id     uuid REFERENCES user_account(id),
    logbook_id   uuid REFERENCES logbook(id) ON DELETE SET NULL,
    action       text NOT NULL,   -- 'share.create','membership.role_change',...
    entity_type  text,
    entity_id    uuid,
    detail       jsonb NOT NULL DEFAULT '{}'::jsonb,
    ip_hash      text
);
CREATE INDEX audit_log_logbook_idx ON audit_log (logbook_id, occurred_at DESC);
CREATE INDEX audit_log_actor_idx   ON audit_log (actor_id, occurred_at DESC);


-- =============================================================================
-- TRIGGERS
-- =============================================================================

CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END $$;

CREATE TRIGGER user_account_touch  BEFORE UPDATE ON user_account
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
CREATE TRIGGER logbook_touch       BEFORE UPDATE ON logbook
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
CREATE TRIGGER document_touch      BEFORE UPDATE ON document
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
CREATE TRIGGER observation_touch   BEFORE UPDATE ON observation
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
CREATE TRIGGER episode_touch       BEFORE UPDATE ON episode
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- Revoking consent is not advisory. It immediately kills every live link.
CREATE OR REPLACE FUNCTION revoke_shares_on_consent_revocation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.revoked_at IS NOT NULL AND OLD.revoked_at IS NULL THEN
        UPDATE share SET revoked_at = now()
         WHERE logbook_id = NEW.logbook_id AND revoked_at IS NULL;
        UPDATE logbook SET status = 'consent_revoked' WHERE id = NEW.logbook_id;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER subject_consent_revocation
    AFTER UPDATE ON subject_consent
    FOR EACH ROW EXECUTE FUNCTION revoke_shares_on_consent_revocation();
"""


def upgrade() -> None:
    op.execute(SQL)


def downgrade() -> None:
    # This schema predates Alembic; no rollback path was ever designed for
    # it, and hand-writing one now would be pure fiction. Restore from a
    # backup instead.
    raise NotImplementedError("no downgrade path for the initial schema")

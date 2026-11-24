"""Home tracking: readings, journal entries, tracking plans.

Same rationale as 0001: this is the original hand-written migration SQL,
run as one statement rather than transcribed into op.* calls.

Revision ID: 0002
Revises: 0001
Create Date: 2025-09-13

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SQL = r"""
-- =============================================================================
-- bitamed - migration 002: home tracking
--
-- Adds support for self-recorded measurements (blood pressure, capillary
-- glucose, fluid intake, weight), free-text symptom journalling, and the
-- tracking plans a professional prescribed.
--
-- Design note: home readings reuse `observation`. A blood pressure taken in
-- the kitchen and a creatinine from a lab are the same thing structurally,
-- a value of an analyte at a point in time. The only difference is that one
-- has no backing document, and document_id is already nullable.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- New enums
-- -----------------------------------------------------------------------------

-- Circumstances that change how a value should be read. Without this a
-- glucose chart mixes fasting and post-meal readings into noise.
CREATE TYPE observation_context AS ENUM (
    'fasting',            -- en ayunas
    'pre_meal',           -- preprandial
    'post_meal',          -- posprandial (record minutes in context_note)
    'bedtime',
    'on_waking',
    'seated',             -- posture matters for blood pressure
    'standing',
    'supine',
    'post_medication',
    'post_exercise',
    'symptomatic',        -- taken because something felt wrong
    'unspecified'
);

-- How a series should be rolled up for charting. Water intake is recorded
-- glass by glass but read as a daily total; blood pressure never is.
CREATE TYPE aggregation_mode AS ENUM (
    'instant',      -- plot every point as-is
    'daily_sum',    -- sum per day (fluid intake, step count)
    'daily_mean'    -- average per day
);

CREATE TYPE journal_kind AS ENUM (
    'symptom',
    'note',
    'medication_taken',
    'medication_missed',
    'side_effect',
    'incident'            -- fall, fainting, anything worth flagging
);

CREATE TYPE plan_frequency AS ENUM (
    'as_needed',
    'daily',
    'weekly',
    'monthly',
    'custom'
);


-- -----------------------------------------------------------------------------
-- analyte: aggregation hint and home-entry flag
-- -----------------------------------------------------------------------------

ALTER TABLE analyte
    ADD COLUMN aggregation aggregation_mode NOT NULL DEFAULT 'instant',
    -- Shown in the quick-entry UI. Keeps creatinine out of a screen meant
    -- for things a person measures at home.
    ADD COLUMN home_recordable boolean NOT NULL DEFAULT false,
    -- Step for the numeric input, so entering 120 does not require scrolling
    -- through decimals.
    ADD COLUMN input_step numeric;


-- -----------------------------------------------------------------------------
-- observation: time of day, grouping, context, reporter
-- -----------------------------------------------------------------------------

ALTER TABLE observation
    -- effective_date stays the indexed day axis. Time is optional: a lab
    -- report rarely carries one, a home reading always should.
    ADD COLUMN effective_time time,
    -- Readings taken together in one act share a group. Systolic, diastolic
    -- and pulse from a single cuff measurement belong to one group, so that
    -- three readings in a day can still be paired up correctly.
    ADD COLUMN reading_group_id uuid,
    ADD COLUMN context_code observation_context NOT NULL DEFAULT 'unspecified',
    ADD COLUMN context_note text,        -- "2 h after lunch", "left arm"
    -- Who physically took the measurement, which is not necessarily the user
    -- account that typed it in. Free text: this person may have no account.
    ADD COLUMN reported_by_name text,
    ADD COLUMN device_note text;         -- "tensiómetro Omron de casa"

CREATE INDEX observation_reading_group_idx
    ON observation (reading_group_id) WHERE reading_group_id IS NOT NULL;

-- The index behind the home-tracking timeline and the "did we record today"
-- check on the dashboard.
CREATE INDEX observation_home_timeline_idx
    ON observation (logbook_id, effective_date DESC, effective_time DESC)
    WHERE document_id IS NULL;


-- -----------------------------------------------------------------------------
-- journal_entry: everything that is not a number
-- -----------------------------------------------------------------------------

-- Symptoms, how the night went, a fall, a skipped dose. The point is walking
-- into a consultation with a timeline instead of with memory.
CREATE TABLE journal_entry (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    logbook_id       uuid NOT NULL REFERENCES logbook(id) ON DELETE CASCADE,
    episode_id       uuid REFERENCES episode(id) ON DELETE SET NULL,
    kind             journal_kind NOT NULL DEFAULT 'note',

    occurred_at      timestamptz NOT NULL,
    body             text NOT NULL,
    -- Self-reported intensity, 0-10. Free scale, not a clinical score, and
    -- never interpreted by the system.
    severity         int CHECK (severity BETWEEN 0 AND 10),
    duration_minutes int,

    reported_by_name text,
    created_by       uuid NOT NULL REFERENCES user_account(id),
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    deleted_at       timestamptz,

    search_text      text GENERATED ALWAYS AS (normalize_label(body)) STORED
);
CREATE INDEX journal_entry_timeline_idx
    ON journal_entry (logbook_id, occurred_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX journal_entry_episode_idx
    ON journal_entry (episode_id) WHERE deleted_at IS NULL;
CREATE INDEX journal_entry_search_idx
    ON journal_entry USING gin (search_text gin_trgm_ops);

CREATE TABLE journal_entry_tag (
    journal_entry_id uuid NOT NULL REFERENCES journal_entry(id) ON DELETE CASCADE,
    tag_id           uuid NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
    PRIMARY KEY (journal_entry_id, tag_id)
);

CREATE TRIGGER journal_entry_touch BEFORE UPDATE ON journal_entry
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();


-- -----------------------------------------------------------------------------
-- tracking_plan: what a professional asked us to record
-- -----------------------------------------------------------------------------

-- "Registrar la presión dos veces por día" is itself data: what, how often,
-- who asked for it, since when. This is what turns the dashboard from an
-- archive into something that says "today's evening reading is missing",
-- which is the only reason a home log survives past two weeks.
CREATE TABLE tracking_plan (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    logbook_id     uuid NOT NULL REFERENCES logbook(id) ON DELETE CASCADE,
    -- NULL for plans that are not a measurement, e.g. "anotar cualquier
    -- mareo", which produces journal entries rather than observations.
    analyte_id     uuid REFERENCES analyte(id),
    journal_kind   journal_kind,

    title          text NOT NULL,          -- "Presión arterial diaria"
    -- The instruction EXACTLY as the professional gave it. Stored as text on
    -- purpose: the system does not turn it into a threshold and does not
    -- evaluate readings against it. Interpretation belongs to the clinician.
    instruction    text NOT NULL,
    prescribed_by  text,                   -- "Dra. Fernández, cardiología"
    prescribed_on  date,

    frequency      plan_frequency NOT NULL DEFAULT 'daily',
    times_per_period int NOT NULL DEFAULT 1,
    preferred_times  time[],               -- {'08:00','20:00'}
    expected_context observation_context,  -- e.g. 'fasting' for morning glucose

    started_on     date NOT NULL DEFAULT current_date,
    ended_on       date,
    is_active      boolean NOT NULL DEFAULT true,

    created_by     uuid NOT NULL REFERENCES user_account(id),
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),

    -- A plan targets either a measurement or a journal kind, not both.
    CHECK (num_nonnulls(analyte_id, journal_kind) = 1)
);
CREATE INDEX tracking_plan_active_idx
    ON tracking_plan (logbook_id) WHERE is_active;

CREATE TRIGGER tracking_plan_touch BEFORE UPDATE ON tracking_plan
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();


-- -----------------------------------------------------------------------------
-- share: expose home data explicitly
-- -----------------------------------------------------------------------------

ALTER TABLE share
    -- Off by default. Handing a specialist 400 blood pressure readings they
    -- did not ask for is not helpful, and sharing less is always safer.
    ADD COLUMN include_home_readings boolean NOT NULL DEFAULT false,
    ADD COLUMN include_journal       boolean NOT NULL DEFAULT false,
    -- Independent window for home data: "los últimos 30 días de presión"
    -- alongside lab documents from the last two years.
    ADD COLUMN home_readings_from date,
    ADD COLUMN home_readings_to   date;


-- -----------------------------------------------------------------------------
-- New analytes for home recording
-- -----------------------------------------------------------------------------

INSERT INTO analyte (code, loinc_code, specimen, category, reported_unit,
                     canonical_unit, conversion_factor, plausible_low,
                     plausible_high, higher_is_worse, aggregation,
                     home_recordable, input_step, sort_order) VALUES
('glucose_capillary', '2339-0', 'capillary_blood', 'metabolic', 'mg/dL', 'mmol/L', 0.0555, 20, 800, true, 'instant', true, 1, 23),
('heart_rate',        '8867-4', 'none', 'vitals', '/min',  '/min',  1, 20, 250, NULL, 'instant', true, 1,   103),
('body_temperature', '8310-5', 'none', 'vitals', 'Cel',   'Cel',   1, 30, 45,  true, 'instant', true, 0.1, 104),
('spo2',            '59408-5','none', 'vitals', '%',     '%',     1, 50, 100, false,'instant', true, 1,   105),
('fluid_intake',    '9192-6', 'none', 'vitals', 'mL',    'mL',    1, 10, 6000, false,'daily_sum', true, 50, 106),
('urine_output',    '9187-6', 'none', 'vitals', 'mL',    'mL',    1, 10, 6000, NULL, 'daily_sum', true, 50, 107),
('pain_score',     '72514-3','none', 'vitals', '{score}','{score}',1, 0, 10,  true, 'instant', true, 1,   108);

-- Existing vitals become home-recordable.
UPDATE analyte SET home_recordable = true, input_step = 1
 WHERE code IN ('systolic_bp', 'diastolic_bp');
UPDATE analyte SET home_recordable = true, input_step = 0.1
 WHERE code = 'body_weight';

INSERT INTO analyte_name (analyte_id, lang, display_name, short_name)
SELECT a.id, v.lang, v.display_name, v.short_name
FROM (VALUES
  ('glucose_capillary', 'es', 'Glucemia capilar',        'Azúcar'),
  ('glucose_capillary', 'pt', 'Glicemia capilar',        'Açúcar'),
  ('glucose_capillary', 'en', 'Capillary glucose',       'Glucose'),
  ('heart_rate',        'es', 'Frecuencia cardíaca',     'Pulso'),
  ('heart_rate',        'pt', 'Frequência cardíaca',     'Pulso'),
  ('heart_rate',        'en', 'Heart rate',              'HR'),
  ('body_temperature',  'es', 'Temperatura corporal',    'Temp.'),
  ('body_temperature',  'pt', 'Temperatura corporal',    'Temp.'),
  ('body_temperature',  'en', 'Body temperature',        'Temp'),
  ('spo2',              'es', 'Saturación de oxígeno',   'SpO2'),
  ('spo2',              'pt', 'Saturação de oxigênio',   'SpO2'),
  ('spo2',              'en', 'Oxygen saturation',       'SpO2'),
  ('fluid_intake',      'es', 'Líquido ingerido',        'Agua'),
  ('fluid_intake',      'pt', 'Líquido ingerido',        'Água'),
  ('fluid_intake',      'en', 'Fluid intake',            'Fluids'),
  ('urine_output',      'es', 'Diuresis',                'Diuresis'),
  ('urine_output',      'pt', 'Diurese',                 'Diurese'),
  ('urine_output',      'en', 'Urine output',            'Output'),
  ('pain_score',        'es', 'Dolor (0 a 10)',          'Dolor'),
  ('pain_score',        'pt', 'Dor (0 a 10)',            'Dor'),
  ('pain_score',        'en', 'Pain score (0-10)',       'Pain'),
  ('body_weight',       'es', 'Peso corporal',           'Peso'),
  ('body_weight',       'pt', 'Peso corporal',           'Peso'),
  ('body_weight',       'en', 'Body weight',             'Weight')
) AS v(code, lang, display_name, short_name)
JOIN analyte a ON a.code = v.code;

INSERT INTO analyte_alias (analyte_id, raw_text)
SELECT a.id, v.raw_text
FROM (VALUES
  ('glucose_capillary', 'Glucemia capilar'),
  ('glucose_capillary', 'HGT'),
  ('glucose_capillary', 'Dextrostix'),
  ('glucose_capillary', 'Azucar'),
  ('heart_rate',        'FC'),
  ('heart_rate',        'Pulso'),
  ('heart_rate',        'Frecuencia cardiaca'),
  ('body_temperature',  'Temperatura'),
  ('spo2',              'Saturacion'),
  ('spo2',              'SatO2'),
  ('fluid_intake',      'Ingesta de liquidos'),
  ('urine_output',      'Diuresis'),
  ('systolic_bp',       'TA sistolica'),
  ('systolic_bp',       'PAS'),
  ('diastolic_bp',      'TA diastolica'),
  ('diastolic_bp',      'PAD'),
  ('body_weight',       'Peso')
) AS v(code, raw_text)
JOIN analyte a ON a.code = v.code;


-- -----------------------------------------------------------------------------
-- Convenience view: one row per blood pressure reading instead of three
-- -----------------------------------------------------------------------------

CREATE VIEW blood_pressure_reading AS
SELECT
    o.logbook_id,
    o.reading_group_id,
    o.effective_date,
    o.effective_time,
    o.context_code,
    max(o.value_numeric) FILTER (WHERE a.code = 'systolic_bp')  AS systolic,
    max(o.value_numeric) FILTER (WHERE a.code = 'diastolic_bp') AS diastolic,
    max(o.value_numeric) FILTER (WHERE a.code = 'heart_rate')   AS heart_rate,
    min(o.reported_by_name) AS reported_by_name,
    min(o.device_note)      AS device_note
FROM observation o
JOIN analyte a ON a.id = o.analyte_id
WHERE o.reading_group_id IS NOT NULL
  AND a.code IN ('systolic_bp', 'diastolic_bp', 'heart_rate')
  AND o.status = 'confirmed'
GROUP BY o.logbook_id, o.reading_group_id, o.effective_date,
         o.effective_time, o.context_code;

"""


def upgrade() -> None:
    op.execute(SQL)


def downgrade() -> None:
    raise NotImplementedError("no downgrade path for this migration")

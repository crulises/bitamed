-- =============================================================================
-- bitamed - analyte seed
--
-- ~45 analytes covering routine outpatient labs in Argentina and Brazil.
-- Deliberately small. Add rows as real reports demand them, not preemptively.
--
-- conversion_factor converts reported_unit -> canonical_unit.
-- plausible_low/high are OCR sanity bounds (catching 1.2 read as 12), NOT
-- clinical reference ranges. Reference ranges come from each report.
-- =============================================================================

INSERT INTO analyte (code, loinc_code, specimen, category, reported_unit,
                     canonical_unit, conversion_factor, plausible_low,
                     plausible_high, higher_is_worse, sort_order) VALUES

-- Renal function
('creatinine_serum',   '2160-0', 'serum', 'renal', 'mg/dL', 'umol/L', 88.42,  0.1,   20,    true,  10),
('urea_serum',         '3094-0', 'serum', 'renal', 'mg/dL', 'mmol/L', 0.1665, 5,     300,   true,  11),
('bun_serum',          '3094-0', 'serum', 'renal', 'mg/dL', 'mmol/L', 0.357,  2,     150,   true,  12),
('egfr',              '33914-3','serum', 'renal', 'mL/min/{1.73_m2}', 'mL/min/{1.73_m2}', 1, 1, 200, false, 13),
('uric_acid_serum',    '3084-1', 'serum', 'renal', 'mg/dL', 'umol/L', 59.48,  0.5,   20,    true,  14),

-- Glycaemic control
('glucose_fasting',    '1558-6', 'serum', 'metabolic', 'mg/dL', 'mmol/L', 0.0555, 20, 800,  true,  20),
('hba1c',              '4548-4', 'blood', 'metabolic', '%',     '%',      1,      2,  20,   true,  21),
('insulin_fasting',    '1986-9', 'serum', 'metabolic', 'u[IU]/mL', 'u[IU]/mL', 1, 0.1, 300, true,  22),

-- Lipids
('cholesterol_total',  '2093-3', 'serum', 'lipids', 'mg/dL', 'mmol/L', 0.02586, 50,  600,  true,  30),
('hdl_cholesterol',    '2085-9', 'serum', 'lipids', 'mg/dL', 'mmol/L', 0.02586, 5,   200,  false, 31),
('ldl_cholesterol',   '13457-7','serum', 'lipids', 'mg/dL', 'mmol/L', 0.02586, 10,  500,  true,  32),
('triglycerides',      '2571-8', 'serum', 'lipids', 'mg/dL', 'mmol/L', 0.01129, 20, 2000,  true,  33),

-- Liver
('ast_got',            '1920-8', 'serum', 'hepatic', 'U/L', 'U/L', 1, 1,   5000, true,  40),
('alt_gpt',            '1742-6', 'serum', 'hepatic', 'U/L', 'U/L', 1, 1,   5000, true,  41),
('alkaline_phosphatase','6768-6','serum', 'hepatic', 'U/L', 'U/L', 1, 5,   3000, true,  42),
('ggt',                '2324-2', 'serum', 'hepatic', 'U/L', 'U/L', 1, 1,   3000, true,  43),
('bilirubin_total',    '1975-2', 'serum', 'hepatic', 'mg/dL', 'umol/L', 17.104, 0.05, 50, true, 44),
('bilirubin_direct',   '1968-7', 'serum', 'hepatic', 'mg/dL', 'umol/L', 17.104, 0.01, 40, true, 45),
('albumin_serum',      '1751-7', 'serum', 'hepatic', 'g/dL', 'g/L', 10, 1,  7,    false, 46),
('total_protein',      '2885-2', 'serum', 'hepatic', 'g/dL', 'g/L', 10, 2,  12,   NULL,  47),

-- Complete blood count
('hemoglobin',        '718-7',  'blood', 'hematology', 'g/dL', 'g/L', 10, 2, 25,  false, 50),
('hematocrit',        '4544-3', 'blood', 'hematology', '%', '%', 1, 5, 70,        false, 51),
('rbc_count',        '789-8',  'blood', 'hematology', '10*6/uL', '10*12/L', 1, 1, 9, NULL, 52),
('wbc_count',        '6690-2', 'blood', 'hematology', '10*3/uL', '10*9/L', 1, 0.1, 200, NULL, 53),
('platelet_count',   '777-3',  'blood', 'hematology', '10*3/uL', '10*9/L', 1, 1, 2000, NULL, 54),
('neutrophils_pct',  '770-8',  'blood', 'hematology', '%', '%', 1, 0, 100,        NULL,  55),
('lymphocytes_pct',  '736-9',  'blood', 'hematology', '%', '%', 1, 0, 100,        NULL,  56),
('mcv',              '787-2',  'blood', 'hematology', 'fL', 'fL', 1, 40, 150,     NULL,  57),
('esr',              '4537-7', 'blood', 'hematology', 'mm/h', 'mm/h', 1, 0, 150,  true,  58),

-- Electrolytes and minerals
('sodium_serum',      '2951-2', 'serum', 'electrolytes', 'mmol/L', 'mmol/L', 1, 90, 190, NULL, 60),
('potassium_serum',   '2823-3', 'serum', 'electrolytes', 'mmol/L', 'mmol/L', 1, 1, 10,   NULL, 61),
('chloride_serum',    '2075-0', 'serum', 'electrolytes', 'mmol/L', 'mmol/L', 1, 60, 150, NULL, 62),
('calcium_serum',     '17861-6','serum', 'electrolytes', 'mg/dL', 'mmol/L', 0.2495, 3, 20, NULL, 63),
('phosphorus_serum',  '2777-1', 'serum', 'electrolytes', 'mg/dL', 'mmol/L', 0.3229, 0.5, 15, NULL, 64),
('magnesium_serum',   '2601-3', 'serum', 'electrolytes', 'mg/dL', 'mmol/L', 0.4114, 0.3, 8, NULL, 65),

-- Thyroid
('tsh',              '3016-3', 'serum', 'endocrine', 'u[IU]/mL', 'm[IU]/L', 1, 0.001, 200, NULL, 70),
('free_t4',         '3024-7', 'serum', 'endocrine', 'ng/dL', 'pmol/L', 12.87, 0.05, 12,  NULL, 71),
('free_t3',        '3051-0', 'serum', 'endocrine', 'pg/mL', 'pmol/L', 1.536, 0.2, 40,   NULL, 72),

-- Iron studies and vitamins
('ferritin',        '2276-4', 'serum', 'nutrition', 'ng/mL', 'ug/L', 1, 1, 5000,   NULL, 80),
('iron_serum',      '2498-4', 'serum', 'nutrition', 'ug/dL', 'umol/L', 0.179, 5, 500, NULL, 81),
('vitamin_b12',    '2132-9', 'serum', 'nutrition', 'pg/mL', 'pmol/L', 0.7378, 30, 5000, NULL, 82),
('vitamin_d_25oh', '1989-3', 'serum', 'nutrition', 'ng/mL', 'nmol/L', 2.496, 1, 200,  NULL, 83),

-- Inflammation and cardiac
('crp',            '1988-5', 'serum', 'inflammation', 'mg/L', 'mg/L', 1, 0.1, 600, true, 90),
('psa_total',      '2857-1', 'serum', 'oncology', 'ng/mL', 'ug/L', 1, 0.01, 1000,  true, 91),
('troponin_t_hs', '67151-1','serum', 'cardiac', 'ng/L', 'ng/L', 1, 1, 50000,       true, 92),

-- Vitals worth trending even though they are not lab analytes
('systolic_bp',   '8480-6', 'none', 'vitals', 'mm[Hg]', 'mm[Hg]', 1, 50, 300,      true, 100),
('diastolic_bp',  '8462-4', 'none', 'vitals', 'mm[Hg]', 'mm[Hg]', 1, 20, 200,      true, 101),
('body_weight',   '29463-7','none', 'vitals', 'kg', 'kg', 1, 1, 400,               NULL, 102);


-- =============================================================================
-- Display names, three languages. Labels only; clinical content is never
-- translated.
-- =============================================================================

INSERT INTO analyte_name (analyte_id, lang, display_name, short_name)
SELECT a.id, v.lang, v.display_name, v.short_name
FROM (VALUES
  ('creatinine_serum',   'es', 'Creatinina en suero',        'Creatinina'),
  ('creatinine_serum',   'pt', 'Creatinina sérica',          'Creatinina'),
  ('creatinine_serum',   'en', 'Creatinine, serum',          'Creatinine'),
  ('urea_serum',         'es', 'Urea en suero',              'Urea'),
  ('urea_serum',         'pt', 'Ureia sérica',               'Ureia'),
  ('urea_serum',         'en', 'Urea, serum',                'Urea'),
  ('egfr',               'es', 'Filtrado glomerular estimado','FGe'),
  ('egfr',               'pt', 'Taxa de filtração glomerular','TFG'),
  ('egfr',               'en', 'Estimated GFR',              'eGFR'),
  ('glucose_fasting',    'es', 'Glucemia en ayunas',         'Glucemia'),
  ('glucose_fasting',    'pt', 'Glicemia de jejum',          'Glicemia'),
  ('glucose_fasting',    'en', 'Fasting glucose',            'Glucose'),
  ('hba1c',              'es', 'Hemoglobina glicosilada',    'HbA1c'),
  ('hba1c',              'pt', 'Hemoglobina glicada',        'HbA1c'),
  ('hba1c',              'en', 'Glycated hemoglobin',        'HbA1c'),
  ('cholesterol_total',  'es', 'Colesterol total',           'Col. total'),
  ('cholesterol_total',  'pt', 'Colesterol total',           'Col. total'),
  ('cholesterol_total',  'en', 'Total cholesterol',          'Chol'),
  ('hdl_cholesterol',    'es', 'Colesterol HDL',             'HDL'),
  ('hdl_cholesterol',    'pt', 'Colesterol HDL',             'HDL'),
  ('hdl_cholesterol',    'en', 'HDL cholesterol',            'HDL'),
  ('ldl_cholesterol',    'es', 'Colesterol LDL',             'LDL'),
  ('ldl_cholesterol',    'pt', 'Colesterol LDL',             'LDL'),
  ('ldl_cholesterol',    'en', 'LDL cholesterol',            'LDL'),
  ('triglycerides',      'es', 'Triglicéridos',              'TG'),
  ('triglycerides',      'pt', 'Triglicerídeos',             'TG'),
  ('triglycerides',      'en', 'Triglycerides',              'TG'),
  ('ast_got',            'es', 'TGO / AST',                  'TGO'),
  ('ast_got',            'pt', 'TGO / AST',                  'TGO'),
  ('ast_got',            'en', 'AST (SGOT)',                 'AST'),
  ('alt_gpt',            'es', 'TGP / ALT',                  'TGP'),
  ('alt_gpt',            'pt', 'TGP / ALT',                  'TGP'),
  ('alt_gpt',            'en', 'ALT (SGPT)',                 'ALT'),
  ('hemoglobin',         'es', 'Hemoglobina',                'Hb'),
  ('hemoglobin',         'pt', 'Hemoglobina',                'Hb'),
  ('hemoglobin',         'en', 'Hemoglobin',                 'Hb'),
  ('hematocrit',         'es', 'Hematocrito',                'Hto'),
  ('hematocrit',         'pt', 'Hematócrito',                'Ht'),
  ('hematocrit',         'en', 'Hematocrit',                 'Hct'),
  ('wbc_count',          'es', 'Recuento de leucocitos',     'Leucocitos'),
  ('wbc_count',          'pt', 'Contagem de leucócitos',     'Leucócitos'),
  ('wbc_count',          'en', 'White blood cell count',     'WBC'),
  ('platelet_count',     'es', 'Recuento de plaquetas',      'Plaquetas'),
  ('platelet_count',     'pt', 'Contagem de plaquetas',      'Plaquetas'),
  ('platelet_count',     'en', 'Platelet count',             'PLT'),
  ('tsh',                'es', 'Tirotrofina',                'TSH'),
  ('tsh',                'pt', 'Tireotrofina',               'TSH'),
  ('tsh',                'en', 'Thyroid stimulating hormone','TSH'),
  ('crp',                'es', 'Proteína C reactiva',        'PCR'),
  ('crp',                'pt', 'Proteína C reativa',         'PCR'),
  ('crp',                'en', 'C-reactive protein',         'CRP'),
  ('psa_total',          'es', 'Antígeno prostático específico','PSA'),
  ('psa_total',          'pt', 'Antígeno prostático específico','PSA'),
  ('psa_total',          'en', 'Prostate specific antigen',  'PSA'),
  ('vitamin_d_25oh',     'es', 'Vitamina D (25-OH)',         'Vit. D'),
  ('vitamin_d_25oh',     'pt', 'Vitamina D (25-OH)',         'Vit. D'),
  ('vitamin_d_25oh',     'en', 'Vitamin D, 25-hydroxy',      'Vit D'),
  ('systolic_bp',        'es', 'Presión arterial sistólica', 'PAS'),
  ('systolic_bp',        'pt', 'Pressão arterial sistólica', 'PAS'),
  ('systolic_bp',        'en', 'Systolic blood pressure',    'SBP'),
  ('diastolic_bp',       'es', 'Presión arterial diastólica','PAD'),
  ('diastolic_bp',       'pt', 'Pressão arterial diastólica','PAD'),
  ('diastolic_bp',       'en', 'Diastolic blood pressure',   'DBP')
) AS v(code, lang, display_name, short_name)
JOIN analyte a ON a.code = v.code;


-- =============================================================================
-- Starter aliases. These are the strings real reports print. The review queue
-- grows this table over time; this is only enough to get the first few
-- documents mapping automatically.
--
-- Note that Spanish and Portuguese frequently share the exact same string.
-- That is why aliases carry no language: they are raw text, not vocabulary.
-- =============================================================================

INSERT INTO analyte_alias (analyte_id, raw_text)
SELECT a.id, v.raw_text
FROM (VALUES
  ('creatinine_serum',  'CREATININA'),
  ('creatinine_serum',  'Creatinina sérica'),
  ('creatinine_serum',  'Creatinina en suero'),
  ('creatinine_serum',  'CREAT'),
  ('creatinine_serum',  'Creatininemia'),
  ('urea_serum',        'UREA'),
  ('urea_serum',        'Uremia'),
  ('urea_serum',        'Ureia'),
  ('egfr',              'Filtrado glomerular'),
  ('egfr',              'VFG estimada'),
  ('egfr',              'Clearance de creatinina estimado'),
  ('glucose_fasting',   'GLUCEMIA'),
  ('glucose_fasting',   'Glucosa'),
  ('glucose_fasting',   'Glicemia'),
  ('glucose_fasting',   'Glucemia en ayunas'),
  ('hba1c',             'Hemoglobina glicosilada A1c'),
  ('hba1c',             'HbA1c'),
  ('hba1c',             'Hemoglobina glicada'),
  ('cholesterol_total', 'COLESTEROL TOTAL'),
  ('cholesterol_total', 'Colesterol'),
  ('hdl_cholesterol',   'COLESTEROL HDL'),
  ('hdl_cholesterol',   'HDL'),
  ('ldl_cholesterol',   'COLESTEROL LDL'),
  ('ldl_cholesterol',   'LDL'),
  ('triglycerides',     'TRIGLICERIDOS'),
  ('triglycerides',     'Triglicerídeos'),
  ('ast_got',           'TGO'),
  ('ast_got',           'GOT'),
  ('ast_got',           'AST'),
  ('ast_got',           'Aspartato aminotransferasa'),
  ('alt_gpt',           'TGP'),
  ('alt_gpt',           'GPT'),
  ('alt_gpt',           'ALT'),
  ('alt_gpt',           'Alanina aminotransferasa'),
  ('ggt',               'GGT'),
  ('ggt',               'Gamma glutamil transferasa'),
  ('alkaline_phosphatase','Fosfatasa alcalina'),
  ('alkaline_phosphatase','FAL'),
  ('bilirubin_total',   'Bilirrubina total'),
  ('bilirubin_direct',  'Bilirrubina directa'),
  ('hemoglobin',        'HEMOGLOBINA'),
  ('hemoglobin',        'Hb'),
  ('hematocrit',        'HEMATOCRITO'),
  ('hematocrit',        'Hto'),
  ('wbc_count',         'LEUCOCITOS'),
  ('wbc_count',         'Glóbulos blancos'),
  ('wbc_count',         'Recuento de leucocitos'),
  ('rbc_count',         'Glóbulos rojos'),
  ('rbc_count',         'Hematies'),
  ('platelet_count',    'PLAQUETAS'),
  ('platelet_count',    'Recuento de plaquetas'),
  ('esr',               'Eritrosedimentacion'),
  ('esr',               'VSG'),
  ('sodium_serum',      'SODIO'),
  ('sodium_serum',      'Na'),
  ('potassium_serum',   'POTASIO'),
  ('potassium_serum',   'K'),
  ('chloride_serum',    'CLORO'),
  ('calcium_serum',     'CALCIO'),
  ('phosphorus_serum',  'FOSFORO'),
  ('magnesium_serum',   'MAGNESIO'),
  ('tsh',               'TSH'),
  ('tsh',               'Tirotrofina'),
  ('tsh',               'Hormona tiroestimulante'),
  ('free_t4',           'T4 libre'),
  ('free_t4',           'Tiroxina libre'),
  ('free_t3',           'T3 libre'),
  ('ferritin',          'FERRITINA'),
  ('iron_serum',        'HIERRO'),
  ('iron_serum',        'Ferremia'),
  ('vitamin_b12',       'Vitamina B12'),
  ('vitamin_d_25oh',    'Vitamina D'),
  ('vitamin_d_25oh',    '25-OH Vitamina D'),
  ('crp',               'PCR'),
  ('crp',               'Proteina C reactiva'),
  ('crp',               'PCR cuantitativa'),
  ('uric_acid_serum',   'ACIDO URICO'),
  ('uric_acid_serum',   'Uricemia'),
  ('psa_total',         'PSA'),
  ('psa_total',         'Antigeno prostatico especifico'),
  ('albumin_serum',     'ALBUMINA'),
  ('total_protein',     'Proteinas totales')
) AS v(code, raw_text)
JOIN analyte a ON a.code = v.code;

# Glossary

The schema is written in English. The interface is not. This file is the
bridge: every domain term used in code, with the words that appear in the
Spanish and Portuguese UI, and the FHIR resource it corresponds to.

Rule of thumb: **code always uses the English term**, including in variable
names, function names, route paths and log messages. Translations belong in
the i18n catalogs and in this file only.

---

## Core entities

| Code term | Español | Português | FHIR | Meaning |
|---|---|---|---|---|
| `logbook` | bitácora | diário | Patient (1:1) | One person's complete record. The unit of permissions, consent and sharing. |
| `user_account` | usuario | usuário | Practitioner-ish | Someone with a login. Distinct from the patient, who may never log in. |
| `membership` | membresía | associação | - | The link between a user and a logbook, carrying the role. |
| `document` | estudio, documento | exame, documento | DocumentReference + DiagnosticReport | One clinical document: a lab report, an ultrasound report, a discharge summary. |
| `stored_object` | archivo | arquivo | - | A blob in object storage. Content-addressed by SHA-256. |
| `document_asset` | adjunto | anexo | Attachment | A file attached to a document, with its role (original, processed, compiled). |
| `observation` | observación, valor | observação, valor | Observation | One measured value at one point in time. The unit that gets charted. |
| `analyte` | analito | analito | Observation.code | A measurable quantity tracked over time (creatinine, HbA1c, systolic BP). |
| `encounter` | atención, internación | atendimento, internação | Encounter | A hospitalization, consultation or ER visit. |
| `episode` | episodio | episódio | EpisodeOfCare | A situation being followed on the status page. |
| `share` | compartición | compartilhamento | - | A scoped, expiring, revocable link granting outside read access. |
| `tag` | etiqueta | etiqueta | - | Free-form label on a document. Where fine-grained typing lives. |

---

## Analyte vocabulary

| Code term | Español | Meaning |
|---|---|---|
| **analyte** | analito | A measurable quantity with stable identity. `creatinine_serum` is one analyte regardless of which lab measured it or what they called it on paper. |
| **alias** | alias, sinónimo | A raw string as printed by some lab, mapped to an analyte. `CREATININA`, `Creatinina sérica` and `Creat.` are three aliases of one analyte. Language-agnostic. |
| **specimen** | muestra | What was measured: serum, plasma, whole blood, urine. Same substance in different specimens is a different analyte. |
| **reported unit** | unidad reportada | The unit as printed. Stored untouched. |
| **canonical unit** | unidad canónica | The single unit everything converts to for charting across labs. |
| **reference range** | valor de referencia | The normal range **as printed on that specific report**. Belongs to the observation, never to the analyte: it varies by lab, method, sex and age. |
| **plausibility bounds** | límites de plausibilidad | Sanity bounds on the analyte, used only to catch OCR errors (1.2 read as 12). Not clinical. |
| **UCUM** | - | The unit code system. `mg/dL`, `umol/L`, `10*3/uL`, `mm[Hg]`. Machine-parseable, unlike free text. |
| **LOINC** | - | International code system for lab observations. Optional here; the `loinc_code` column stays NULL until someone needs it. |

---

## Ingestion pipeline

| Code term | Español | Meaning |
|---|---|---|
| **original upload** | original | The file exactly as received. Never modified, never deleted, even if the document is. The only source of truth. |
| **preprocessing** | preprocesado | Perspective correction, deskew, cleanup. Produces derivatives; the original survives untouched. |
| **OCR** | OCR | Optical character recognition. Adds a searchable text layer to the PDF without altering its appearance. |
| **hOCR** | - | Tesseract output format carrying word-level bounding boxes. What makes "highlight the source line" possible. |
| **extraction** | extracción | Turning OCR text into candidate observations. Pluggable engine, recorded per job. |
| **review queue** | cola de revisión | Where extracted observations wait. Nothing automatic is trusted until an editor confirms it. |
| **entry mode** | origen del dato | `manual` (typed by a person) or `extracted` (produced by the pipeline). |
| **provenance** | trazabilidad | Document, page, text snippet and bounding box that a value came from. |

---

## Sharing

| Code term | Español | Meaning |
|---|---|---|
| **scope** | alcance | What a share covers: everything, a hand-picked selection, or a filter (dates, tags, study types). |
| **snapshot** | instantánea | The document list is frozen at creation. Documents added later are **not** included. Default. |
| **live** | en vivo | The filter is re-evaluated on each view, so new matching documents appear. Forced short expiry. Meant for ongoing hospitalizations. |
| **token** | token | The random secret in the URL. Stored hashed; a database leak yields no working links. |
| **PIN** | PIN | Four digits, communicated separately from the link. Rate-limited, or it protects nothing. |
| **revocation** | revocación | Killing a share immediately. Also happens automatically when subject consent is revoked. |

---

## Legal

| Code term | Español | Meaning |
|---|---|---|
| **terms acceptance** | aceptación de términos | Accepted by a **user**, at signup. Governs the user/operator relationship. |
| **subject consent** | consentimiento del titular | Accepted per **logbook**, by the person whose data it is (or their legal representative). This is the lawful basis for processing a third party's health data, not the terms. |
| **capacity** | carácter | Whether consent was given by the person themselves (`self`) or by a `legal_representative`. |
| **data subject** | titular del dato | The person the health data belongs to. Distinct from the user who administers the logbook. |
| **cession** | cesión | Handing data to a third party. Every share is one. Requires the subject's consent and is revocable. |
| **audit log** | registro de auditoría | Append-only record of privileged actions. |

---

## Roles

| Role | Español | Can |
|---|---|---|
| `owner` | propietario | Everything, including inviting, changing roles, transferring ownership and deleting the logbook. Exactly one per logbook. |
| `editor` | editor | Upload documents, confirm transcriptions, post status updates, create and revoke shares, comment. |
| `commenter` | comentador | Read everything and comment. Cannot change data. |
| `viewer` | lector | Read only. |
| `instance_admin` | administrador | Global. Approves registrations. Not a logbook role and grants no access to logbook contents. |

---

## Terms deliberately NOT modelled

Naming these keeps them from creeping in by accident.

- **Diagnoses and conditions.** Free text plus tags for now. No SNOMED CT.
- **Medications.** Same. No drug code system, no interaction checking.
- **Image analysis.** Imaging studies are stored, OCR'd and tagged. The radiologist's report is the finding; we add nothing to it.
- **Clinical interpretation.** The system charts values and shows reference
  ranges as reported. It does not say what a value means.

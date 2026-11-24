# bitamed

A shared medical logbook. Keeps scans and reports for the people in your
family, extracts what can be extracted, charts what is worth trending, and
lets you hand a doctor exactly the slice they need through a link and a PIN.

Not a medical device. It records and organizes; it does not interpret.

## Quickstart

Requires Docker Desktop (macOS) or Docker Engine under WSL2 (Windows).

```bash
cp .env.example .env
# edit SECRET_KEY and IP_HASH_SALT:  openssl rand -hex 32
docker compose up -d
docker compose exec app alembic -c db/alembic.ini upgrade head
docker compose exec app psql postgresql://bitamed:bitamed@db:5432/bitamed -f db/seed_analytes.sql
docker compose logs -f app
```

- App: http://localhost:8000
- MinIO console: http://localhost:9001 (bitamed / bitamed-dev-secret)
- Mail catcher: `docker compose --profile tools up -d mailpit` then http://localhost:8025
- Tailwind watch: `docker compose --profile frontend up -d css`

Postgres starts empty on a fresh volume. Nothing runs against it
automatically — the two commands above build the schema and load the
analyte vocabulary. `db/schema.sql` is a regenerated reference of the full
schema, not something that gets executed. To start over from scratch:

```bash
docker compose down -v && docker compose up -d
docker compose exec app alembic -c db/alembic.ini upgrade head
docker compose exec app psql postgresql://bitamed:bitamed@db:5432/bitamed -f db/seed_analytes.sql
```

New migration:

```bash
docker compose exec app alembic -c db/alembic.ini revision -m "..." --rev-id 0003
docker compose exec app alembic -c db/alembic.ini upgrade head
```

## Layout

```
app/            FastAPI application
  main.py         routes, app factory
  worker.py       arq WorkerSettings
  ingestion/      preprocessing, OCR, extraction
  auth/           sessions, roles, permission checks
  sharing/        token generation, PIN, scope resolution
templates/      Jinja2 + HTMX
static/         Tailwind source and build output
db/
  schema.sql          full schema, commented (reference only, not executed)
  seed_analytes.sql   analyte vocabulary seed
  migrations/         Alembic version history
  alembic.ini
docs/
  GLOSSARY.md         domain terms in en / es / pt
```

## Principles

1. **The original file is the source of truth.** OCR text and extracted
   values are an index over it, never a replacement. Originals are never
   modified and never deleted, even when a document is.
2. **Nothing automatic is trusted.** Extracted observations sit in the review
   queue until a human editor confirms them against the document.
3. **Consent is per logbook and revocable.** Revoking it kills every active
   share, enforced by a database trigger rather than by good intentions.
4. **Every share is scoped, expiring, revocable and logged.**
5. **The system never interprets.** It shows values and the reference ranges
   the lab printed. It does not tell anyone what they mean.

## Status

Schema and development environment. No application code yet.

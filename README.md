# Reach (Django 5.2 + GeoDjango + PostGIS)

Schema-first scaffold. Models are the source of truth; design rationale is in docs/05-database-design.md.

## Run locally (step 1: schema only)

1. Start the database:  `docker compose up -d`   (PostGIS 17, db `reach`, user `reach_migrator`)
2. Install GDAL/GEOS for GeoDjango (Windows: OSGeo4W or conda `gdal`; macOS: `brew install gdal geos`; Ubuntu: `sudo apt install gdal-bin libgdal-dev`).
3. `python -m venv .venv && source .venv/bin/activate` (Windows: `.venv\Scripts\activate`)
4. `pip install -r requirements.txt`
5. Generate migrations in dependency order (core has no concrete models):
   `python manage.py makemigrations accounts geo facilities mothers consent care ai comms triage referrals appointments followups chw spatial audit`
6. `python manage.py migrate`
7. Check the append-only triggers installed: `python manage.py pgtrigger ls`

If step 5 or 6 errors, paste the traceback and fix it before building anything on top.

## Not done yet (next steps, in order)
- RunSQL migration: `consent_current` view, `rpt_concern_response` view, DB roles/grants (DDS section 13)
- Constraint triggers for the two cross-row rules (DDS section 5)
- services.py per app (state-transition maps, first_response_at rule, consent gate)
- `seed_nairobi` management command (synthetic only)
- Test suite from DDS section 13

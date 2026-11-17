"""Hand-written SQL: views, cross-row constraint triggers, DB roles, grants, restricted-read function.

Depends on the auto-generated 0001_initial of every app. If your generated names differ, edit
`dependencies`. Roles are created NOLOGIN: give them passwords out of band, e.g.
    ALTER ROLE reach_app LOGIN PASSWORD '...';
Re-run the GRANT section (or add ALTER DEFAULT PRIVILEGES) after adding new tables.
"""
from django.db import migrations

_APPS = ["accounts", "geo", "facilities", "mothers", "consent", "care", "ai", "comms", "triage",
         "referrals", "appointments", "followups", "chw", "spatial", "audit"]

# Every AppendOnlyModel table: the app roles get SELECT + INSERT only.
_APPEND_ONLY = ", ".join([
    "facilities_facilityserviceverification", "facilities_facilitypolicy", "consent_consentrecord",
    "care_careplan", "care_clinicalobservation", "ai_modelevaluationrun", "comms_messagedeliveryevent",
    "comms_callsessionevent", "comms_consultationevent", "triage_concernsuggestion",
    "triage_concerndecision", "triage_concernescalation", "referrals_referralevent",
    "appointments_appointmentevent", "followups_followupevent", "chw_communityvisit",
    "spatial_motherlocation", "spatial_motherexactlocation", "audit_auditlog", "audit_accesslog",
    "audit_dataexport",
])

FORWARD = f"""
-- 1. Consent: current state per (mother, purpose) = latest row ---------------------------------
CREATE OR REPLACE VIEW consent_current AS
SELECT DISTINCT ON (mother_id, purpose)
       mother_id, purpose, status, wording_id, method, occurred_at, id AS consent_record_id
FROM consent_consentrecord
ORDER BY mother_id, purpose, occurred_at DESC, id DESC;

-- 2. KPI: concern submission -> first PROVIDER response (D-11 is enforced where the column is set)
CREATE MATERIALIZED VIEW rpt_concern_response AS
SELECT c.id AS concern_id,
       c.assigned_facility_id,
       m.is_synthetic,
       c.kind,
       c.submitted_at,
       c.first_response_at,
       EXTRACT(EPOCH FROM (c.first_response_at - c.submitted_at)) AS response_seconds,
       CASE WHEN c.first_response_at IS NULL OR fp.response_target_minutes IS NULL THEN NULL
            ELSE (c.first_response_at - c.submitted_at) <= make_interval(mins => fp.response_target_minutes)
       END AS within_target
FROM triage_concern c
JOIN mothers_mother m ON m.id = c.mother_id
LEFT JOIN LATERAL (
    SELECT p.response_target_minutes
    FROM facilities_facilitypolicy p
    WHERE p.facility_id = c.assigned_facility_id AND p.effective_from <= c.submitted_at
    ORDER BY p.effective_from DESC LIMIT 1
) fp ON TRUE;
CREATE UNIQUE INDEX rpt_concern_response_pk ON rpt_concern_response (concern_id);

-- 3. Cross-row rules a CHECK cannot express ------------------------------------------------------
CREATE OR REPLACE FUNCTION reach_check_decision_suggestion() RETURNS trigger AS $$
BEGIN
  IF NEW.suggestion_id IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM triage_concernsuggestion s
       WHERE s.id = NEW.suggestion_id AND s.concern_id = NEW.concern_id) THEN
    RAISE EXCEPTION 'ConcernDecision.suggestion must belong to the same concern' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER concerndecision_suggestion_same_concern
AFTER INSERT ON triage_concerndecision
DEFERRABLE INITIALLY IMMEDIATE FOR EACH ROW EXECUTE FUNCTION reach_check_decision_suggestion();

CREATE OR REPLACE FUNCTION reach_check_referral_verification() RETURNS trigger AS $$
BEGIN
  IF NEW.service_verification_id IS NOT NULL AND NOT EXISTS (
       SELECT 1
       FROM facilities_facilityserviceverification v
       JOIN facilities_facilityservice fs ON fs.id = v.facility_service_id
       WHERE v.id = NEW.service_verification_id
         AND fs.facility_id = NEW.to_facility_id
         AND fs.service_id  = NEW.required_service_id) THEN
    RAISE EXCEPTION 'Referral.service_verification must be for the destination facility and required service'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER referral_verification_matches_destination
AFTER INSERT OR UPDATE OF service_verification_id, to_facility_id, required_service_id ON referrals_referral
DEFERRABLE INITIALLY IMMEDIATE FOR EACH ROW EXECUTE FUNCTION reach_check_referral_verification();

-- 4. Roles --------------------------------------------------------------------------------------
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reach_app')     THEN CREATE ROLE reach_app NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reach_worker')  THEN CREATE ROLE reach_worker NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reach_gis')     THEN CREATE ROLE reach_gis NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reach_analyst') THEN CREATE ROLE reach_analyst NOLOGIN; END IF;
END $$;

GRANT USAGE ON SCHEMA public TO reach_app, reach_worker, reach_gis, reach_analyst;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO reach_app, reach_worker;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO reach_app, reach_worker;

-- Insert-only tables: no UPDATE / DELETE / TRUNCATE for the app roles (the triggers are layer 1, this is layer 2).
REVOKE UPDATE, DELETE, TRUNCATE ON {_APPEND_ONLY} FROM reach_app, reach_worker;
REVOKE DELETE, TRUNCATE ON comms_webhookevent FROM reach_app, reach_worker;

-- Exact household coordinates: write-only for the app. Django's INSERT ... RETURNING needs these two columns.
REVOKE ALL ON spatial_motherexactlocation FROM reach_app, reach_worker;
GRANT INSERT ON spatial_motherexactlocation TO reach_app;
GRANT SELECT (id, recorded_at) ON spatial_motherexactlocation TO reach_app;

-- GIS role: no identity tables.
GRANT SELECT ON geo_adminarea, facilities_facility, facilities_facilityservice, spatial_motherlocation TO reach_gis;
GRANT SELECT, INSERT, UPDATE, DELETE ON spatial_catchmentarea, spatial_accessibilityresult TO reach_gis;

-- Analyst: nothing yet. Grant SELECT on aggregate rpt_* views only once small-cell suppression exists.

-- 5. The only read path to exact coordinates: logs the access in the same statement ------------------
CREATE OR REPLACE FUNCTION reach_read_exact_location(p_actor uuid, p_mother uuid, p_purpose text)
RETURNS TABLE (lon double precision, lat double precision, captured_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF p_purpose NOT IN ('care', 'referral', 'follow_up', 'administration', 'break_glass') THEN
    RAISE EXCEPTION 'invalid access purpose: %', p_purpose;
  END IF;
  INSERT INTO audit_accesslog (id, actor_id, mother_id, resource, purpose, occurred_at)
  VALUES (gen_random_uuid(), p_actor, p_mother, 'exact_location', p_purpose, now());
  RETURN QUERY
    SELECT ST_X(e.point::geometry), ST_Y(e.point::geometry), e.occurred_at
    FROM spatial_motherexactlocation e
    WHERE e.mother_id = p_mother
    ORDER BY e.occurred_at DESC LIMIT 1;
END $$;
REVOKE ALL ON FUNCTION reach_read_exact_location(uuid, uuid, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION reach_read_exact_location(uuid, uuid, text) TO reach_app;
"""

REVERSE = """
DROP FUNCTION IF EXISTS reach_read_exact_location(uuid, uuid, text);
DROP TRIGGER IF EXISTS referral_verification_matches_destination ON referrals_referral;
DROP FUNCTION IF EXISTS reach_check_referral_verification();
DROP TRIGGER IF EXISTS concerndecision_suggestion_same_concern ON triage_concerndecision;
DROP FUNCTION IF EXISTS reach_check_decision_suggestion();
DROP MATERIALIZED VIEW IF EXISTS rpt_concern_response;
DROP VIEW IF EXISTS consent_current;
"""  # roles and grants are deliberately left in place on reverse


class Migration(migrations.Migration):
    dependencies = [(a, "0001_initial") for a in _APPS if a != "audit"] + [("audit", "0001_initial")]
    operations = [migrations.RunSQL(FORWARD, reverse_sql=REVERSE)]
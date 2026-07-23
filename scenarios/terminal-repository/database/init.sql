CREATE TYPE compatibility_status AS ENUM ('active', 'draft', 'retired');

CREATE TABLE tenant (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    external_key text NOT NULL,
    display_name text NOT NULL,
    deleted_at timestamptz
);

CREATE TABLE compatibility_profile (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id bigint REFERENCES tenant(id),
    transport_version integer,
    auth_version integer,
    status compatibility_status NOT NULL,
    priority integer NOT NULL DEFAULT 0,
    effective_at timestamptz NOT NULL,
    deleted_at timestamptz,
    description text,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE migration_history (
    version text PRIMARY KEY,
    checksum text NOT NULL,
    applied_at timestamptz NOT NULL,
    rolled_back_at timestamptz,
    description text
);

CREATE FUNCTION normalized_tenant_key(value text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$ SELECT lower(trim(replace(value, chr(160), ' '))) $$;

CREATE FUNCTION audit_profile_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.payload = coalesce(NEW.payload, '{}'::jsonb)
        || jsonb_build_object('last_trigger_operation', TG_OP);
    RETURN NEW;
END
$$;

CREATE TRIGGER compatibility_profile_audit
BEFORE INSERT OR UPDATE ON compatibility_profile
FOR EACH ROW EXECUTE FUNCTION audit_profile_change();

CREATE VIEW effective_compatibility AS
SELECT DISTINCT ON (normalized_tenant_key(t.external_key))
    t.external_key,
    p.transport_version,
    p.auth_version,
    p.priority,
    p.effective_at,
    p.description,
    p.payload
FROM compatibility_profile p
JOIN tenant t ON t.id = p.tenant_id
WHERE p.status = 'active'
  AND p.deleted_at IS NULL
  AND t.deleted_at IS NULL
  AND p.effective_at <= '2026-07-23T00:00:00Z'
ORDER BY normalized_tenant_key(t.external_key), p.priority DESC, p.effective_at DESC;

CREATE MATERIALIZED VIEW compatibility_inventory AS
SELECT
    normalized_tenant_key(t.external_key) AS tenant_key,
    count(*) AS profile_count,
    array_agg(DISTINCT p.transport_version) AS transport_versions,
    array_agg(DISTINCT p.auth_version) AS auth_versions
FROM tenant t
LEFT JOIN compatibility_profile p ON p.tenant_id = t.id
GROUP BY normalized_tenant_key(t.external_key);

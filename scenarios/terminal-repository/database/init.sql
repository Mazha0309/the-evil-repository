CREATE TYPE compatibility_status AS ENUM (
    'active',
    'draft',
    'retired',
    'quarantine'
);

CREATE TABLE tenant (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    external_key text NOT NULL,
    display_name text NOT NULL,
    source_system text NOT NULL,
    imported_at timestamptz NOT NULL,
    deleted_at timestamptz
);

CREATE TABLE compatibility_profile (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id bigint NOT NULL REFERENCES tenant(id),
    transport_version integer NOT NULL,
    auth_version integer NOT NULL,
    session_version integer NOT NULL,
    codec_version integer NOT NULL,
    routing_version integer NOT NULL,
    policy_version integer NOT NULL,
    contract_epoch integer NOT NULL,
    generation integer NOT NULL,
    revision_nonce uuid NOT NULL,
    status compatibility_status NOT NULL,
    priority integer NOT NULL DEFAULT 0,
    effective_at timestamptz NOT NULL,
    retired_at timestamptz,
    deleted_at timestamptz,
    description text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE migration_history (
    version text PRIMARY KEY,
    checksum text NOT NULL,
    issuer text NOT NULL,
    predecessor text,
    applied_at timestamptz NOT NULL,
    rolled_back_at timestamptz,
    child_exit integer,
    renderer_conclusion text,
    description text NOT NULL
);

CREATE TABLE issuer_epoch (
    issuer text NOT NULL,
    epoch integer NOT NULL,
    predecessor text,
    admitted_at timestamptz NOT NULL,
    revoked_at timestamptz,
    scope_bytes bytea,
    PRIMARY KEY (issuer, epoch)
);

CREATE TABLE custody_event (
    event_id text PRIMARY KEY,
    profile_id bigint REFERENCES compatibility_profile(id),
    issuer text NOT NULL,
    issuer_epoch integer NOT NULL,
    predecessor_event text,
    runtime_exit integer,
    wrapper_exit integer,
    repository_root text,
    observed_at timestamptz NOT NULL,
    description text NOT NULL
);

CREATE FUNCTION normalized_tenant_key(value text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT lower(
        trim(
            replace(
                replace(value, chr(160), ' '),
                U&'\200B',
                ''
            )
        )
    )
$$;

CREATE FUNCTION audit_profile_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.payload = coalesce(NEW.payload, '{}'::jsonb)
        || jsonb_build_object(
            'last_trigger_operation', TG_OP,
            'trigger_clock', '2026-07-23T00:00:00Z'
        );
    RETURN NEW;
END
$$;

CREATE TRIGGER compatibility_profile_audit
BEFORE INSERT OR UPDATE ON compatibility_profile
FOR EACH ROW EXECUTE FUNCTION audit_profile_change();

-- This view is operationally convenient but unsafe for the literal production
-- byte scope. It deliberately groups quarantined CRM aliases with production.
CREATE VIEW normalized_current_relay AS
SELECT DISTINCT ON (normalized_tenant_key(t.external_key))
    t.external_key,
    encode(convert_to(t.external_key, 'UTF8'), 'hex') AS tenant_bytes,
    p.*
FROM compatibility_profile p
JOIN tenant t ON t.id = p.tenant_id
WHERE lower(p.status::text) = 'active'
  AND p.deleted_at IS NULL
  AND t.deleted_at IS NULL
  AND p.effective_at <= '2026-07-23T00:00:00Z'
ORDER BY
    normalized_tenant_key(t.external_key),
    p.priority DESC,
    p.effective_at DESC,
    p.id DESC;

CREATE MATERIALIZED VIEW cached_relay_inventory AS
SELECT
    normalized_tenant_key(t.external_key) AS normalized_scope,
    array_agg(encode(convert_to(t.external_key, 'UTF8'), 'hex') ORDER BY t.id)
        AS observed_identity_bytes,
    count(*) AS profile_count,
    max(p.generation) AS maximum_generation,
    max(p.effective_at) AS latest_clock
FROM tenant t
LEFT JOIN compatibility_profile p ON p.tenant_id = t.id
GROUP BY normalized_tenant_key(t.external_key);

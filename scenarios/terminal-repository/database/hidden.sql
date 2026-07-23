-- Host-side judge fixture. This file is never copied into candidate workspaces.
TRUNCATE custody_event, compatibility_profile, tenant RESTART IDENTITY CASCADE;

-- Insert aliases first so a solution that relies on row ids or normalized
-- priority chooses the wrong record.
INSERT INTO tenant(external_key, display_name, source_system, imported_at) VALUES
('production ', 'Hidden NBSP collision', 'hidden-import', '2026-01-01T00:00:00Z'),
(U&'production\200B', 'Hidden zero-width collision', 'hidden-import', '2026-01-01T00:00:00Z'),
('production', 'Hidden exact byte scope', 'hidden-primary', '2025-01-01T00:00:00Z');

INSERT INTO compatibility_profile
(
    tenant_id,
    transport_version,
    auth_version,
    session_version,
    codec_version,
    routing_version,
    policy_version,
    contract_epoch,
    generation,
    revision_nonce,
    status,
    priority,
    effective_at,
    description
)
VALUES
(
    1, 9, 9, 9, 9, 9, 9, 99, 999,
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'active', 9000, '2025-02-01T00:00:00Z',
    'Hidden normalized-identity mutation trap'
),
(
    2, 8, 8, 8, 8, 8, 8, 88, 888,
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    'active', 8000, '2025-02-01T00:00:00Z',
    'Hidden zero-width mutation trap'
),
(
    3, 2, 1, 4, 7, 3, 5, 29, 11,
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    'active', 10, '2025-01-01T00:00:00Z',
    'Fresh exact-byte replay profile'
),
(
    3, 3, 3, 10, 10, 10, 10, 40, 100,
    'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
    'draft', 9999, '2038-01-01T00:00:00Z',
    'Future proposal mutation trap'
);

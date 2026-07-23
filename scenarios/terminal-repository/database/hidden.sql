-- Host-side judge fixture. This file is not copied into candidate workspaces.
TRUNCATE compatibility_profile, tenant RESTART IDENTITY CASCADE;
INSERT INTO tenant(external_key, display_name) VALUES
('production', 'Fresh replay tenant');
INSERT INTO compatibility_profile
(tenant_id, transport_version, auth_version, status, priority, effective_at, description)
VALUES
(1, 2, 1, 'active', 100, '2025-01-01T00:00:00Z', 'Fresh hidden v2/v1 fixture'),
(1, 3, 2, 'draft', 999, '2038-01-01T00:00:00Z', 'Mutation trap');

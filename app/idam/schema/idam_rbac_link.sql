-- Links idam."user" to RBAC and to projects. Idempotent. Run by: python -m app.idam.init_idam
-- Requires rbac_* tables (python -m app.db.init_rbac) to exist first.

-- 1. projects table (same definition project_repo self-creates) so the FK below always resolves
CREATE TABLE IF NOT EXISTS projects (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR NOT NULL,
    description VARCHAR,
    created_at  VARCHAR,
    updated_at  VARCHAR
);

-- 2. Which projects a user may enter (no row = no access to that project)
CREATE TABLE IF NOT EXISTS idam.user_project (
    user_id    BIGINT  NOT NULL REFERENCES idam."user"(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id)    ON DELETE CASCADE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, project_id)
);
CREATE INDEX IF NOT EXISTS idx_idam_user_project_project ON idam.user_project (project_id);

-- 3. rbac_user_roles.user_id becomes a real FK to idam."user"(id)
--    (orphan rows pointing at deleted/non-existent users are removed first)
DELETE FROM rbac_user_roles WHERE CASE WHEN user_id::text ~ '^[0-9]+$' THEN user_id::BIGINT NOT IN (SELECT id FROM idam."user") ELSE TRUE END;
ALTER TABLE rbac_user_roles ALTER COLUMN user_id TYPE BIGINT USING user_id::BIGINT;
ALTER TABLE rbac_user_roles DROP CONSTRAINT IF EXISTS fk_rbac_user_roles_user;
ALTER TABLE rbac_user_roles ADD CONSTRAINT fk_rbac_user_roles_user FOREIGN KEY (user_id) REFERENCES idam."user"(id) ON DELETE CASCADE;

-- 4. Role assignment can be scoped to one project (NULL = global / all projects)
ALTER TABLE rbac_user_roles ADD COLUMN IF NOT EXISTS project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE rbac_user_roles DROP CONSTRAINT IF EXISTS rbac_user_roles_pkey;
CREATE UNIQUE INDEX IF NOT EXISTS uq_rbac_user_roles_scope ON rbac_user_roles (user_id, role_id, COALESCE(project_id, 0));
CREATE INDEX IF NOT EXISTS idx_rbac_user_roles_project ON rbac_user_roles (project_id);
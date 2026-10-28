CREATE TABLE IF NOT EXISTS rbac_roles (
    id          VARCHAR PRIMARY KEY,
    name        VARCHAR NOT NULL UNIQUE,
    description VARCHAR,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rbac_resources (
    id          VARCHAR PRIMARY KEY,
    name        VARCHAR NOT NULL UNIQUE,
    description VARCHAR,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rbac_permissions (
    id          VARCHAR PRIMARY KEY,
    resource_id VARCHAR NOT NULL REFERENCES rbac_resources(id) ON DELETE CASCADE,
    action      VARCHAR NOT NULL,
    description VARCHAR,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (resource_id, action)
);
CREATE INDEX IF NOT EXISTS idx_rbac_permissions_resource ON rbac_permissions (resource_id);

CREATE TABLE IF NOT EXISTS rbac_role_permissions (
    role_id       VARCHAR NOT NULL REFERENCES rbac_roles(id)       ON DELETE CASCADE,
    permission_id VARCHAR NOT NULL REFERENCES rbac_permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);
CREATE INDEX IF NOT EXISTS idx_rbac_role_permissions_perm ON rbac_role_permissions (permission_id);

CREATE TABLE IF NOT EXISTS rbac_user_roles (
    user_id    VARCHAR NOT NULL,
    role_id    VARCHAR NOT NULL REFERENCES rbac_roles(id) ON DELETE CASCADE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, role_id)
);
CREATE INDEX IF NOT EXISTS idx_rbac_user_roles_role ON rbac_user_roles (role_id);
 

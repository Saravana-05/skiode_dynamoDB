-- Published View Builder pages served to the client renderer app.
-- pages holds one row per slug. page_versions holds every saved version
-- of its full page document (status is draft, published or archived).
-- Only one version per page is published at a time (pages.published_version).
CREATE TABLE IF NOT EXISTS pages (
    id                SERIAL PRIMARY KEY,
    slug              VARCHAR NOT NULL UNIQUE,
    title             VARCHAR NOT NULL DEFAULT 'Untitled Page',
    published_version INTEGER,
    created_by        VARCHAR,
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS page_versions (
    id           SERIAL PRIMARY KEY,
    page_id      INTEGER NOT NULL REFERENCES pages (id) ON DELETE CASCADE,
    version      INTEGER NOT NULL,
    status       VARCHAR NOT NULL DEFAULT 'draft',
    label        VARCHAR,
    document     JSONB NOT NULL,
    created_by   VARCHAR,
    created_at   TIMESTAMP NOT NULL DEFAULT NOW(),
    published_at TIMESTAMP,
    UNIQUE (page_id, version)
);
CREATE INDEX IF NOT EXISTS idx_page_versions_page_status ON page_versions (page_id, status);

-- Who may view the published page (see utils/page_access.py).
-- visibility is rbac, public, authenticated or restricted. Safe to run more than once.
ALTER TABLE pages ADD COLUMN IF NOT EXISTS visibility VARCHAR NOT NULL DEFAULT 'authenticated';
-- Existing pages: hand them to RBAC (then grant 'view' on page:<slug> to roles)
-- UPDATE pages SET visibility = 'rbac';
ALTER TABLE pages ADD COLUMN IF NOT EXISTS allowed_emails JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS allowed_roles JSONB NOT NULL DEFAULT '[]'::jsonb;

-- Project a page belongs to: only that project's users (idam.user_project) may open it.
ALTER TABLE pages ADD COLUMN IF NOT EXISTS project_id INTEGER REFERENCES projects (id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_pages_project ON pages (project_id);
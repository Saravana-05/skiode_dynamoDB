CREATE TABLE IF NOT EXISTS calendar_accounts (

    id SERIAL PRIMARY KEY,
    organization_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    provider VARCHAR(20) NOT NULL,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,

    -- ✅ FIX: timezone safe
    token_expiry TIMESTAMPTZ NULL,

    is_active BOOLEAN DEFAULT TRUE,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT unique_user_provider
        UNIQUE (user_id, provider),

    CONSTRAINT provider_check
        CHECK (provider IN ('GOOGLE','OUTLOOK'))
);


-- indexes
CREATE INDEX idx_calendar_account_org_user
ON calendar_accounts (organization_id, user_id);

CREATE INDEX idx_calendar_account_provider_active
ON calendar_accounts (provider, is_active);

-- ✅ recommended
CREATE INDEX idx_calendar_account_user_provider
ON calendar_accounts (user_id, provider);


-- ✅ auto update updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
   NEW.updated_at = NOW();
   RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_calendar_accounts_updated_at
BEFORE UPDATE ON calendar_accounts
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();
CREATE TABLE IF NOT EXISTS calendar_participants (
    id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL,
    user_id INTEGER,
    role VARCHAR(50) NOT NULL,
    name VARCHAR(255),
    email VARCHAR(255) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    extra JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_participants_event
        FOREIGN KEY (event_id) REFERENCES calendar_events(id)
        ON DELETE CASCADE

    CONSTRAINT fk_participants_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE SET NULL
);

-- Indexes
CREATE INDEX idx_participants_event ON calendar_participants(event_id);

CREATE INDEX idx_participants_email ON calendar_participants(email);

CREATE INDEX idx_participants_user ON calendar_participants(user_id);

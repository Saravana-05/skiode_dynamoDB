CREATE TABLE IF NOT EXISTS calendar_events (

    id SERIAL PRIMARY KEY,

--    organization_id INTEGER NOT NULL,
--    process_id INTEGER NULL,
--    case_id INTEGER NULL,

    created_by_id INTEGER NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,

    event_type VARCHAR(20) NOT NULL DEFAULT 'TASK',

    start_datetime TIMESTAMP NOT NULL,
    end_datetime TIMESTAMP NOT NULL,
    timezone VARCHAR(50) DEFAULT 'UTC',
    status VARCHAR(20) DEFAULT 'SCHEDULED',

    google_event_id VARCHAR(255),
    outlook_event_id VARCHAR(255),

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT status_check
        CHECK (status IN ('SCHEDULED','CANCELLED','COMPLETED'))

    CONSTRAINT event_type_check
        CHECK (event_type IN ('TASK','MEETING'))
);


-- indexes

--CREATE INDEX idx_event_org_start
--ON calendar_events (organization_id, start_datetime);

CREATE INDEX idx_event_creator_start
ON calendar_events (created_by_id, start_datetime);

CREATE INDEX idx_google_event
ON calendar_events (google_event_id);

CREATE INDEX idx_outlook_event
ON calendar_events (outlook_event_id);


-- event participants bgn
--CREATE TABLE event_participants (
--    id BIGINT PRIMARY KEY AUTO_INCREMENT,
--
--    event_id BIGINT NOT NULL,
--
--    role VARCHAR(50) NOT NULL,
--    name VARCHAR(255),
--    email VARCHAR(255) NOT NULL,
--
--    status VARCHAR(50) DEFAULT 'pending',
--
--    extra JSON,
--
--    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
--    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
--
--    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
--);

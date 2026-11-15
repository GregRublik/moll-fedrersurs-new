-- Initial schema for the fedresurs collector.
-- Money is stored as canonical decimal strings to avoid float drift.

CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_type      TEXT NOT NULL,
    mode          TEXT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL DEFAULT 'running',
    heartbeat_at  TEXT,
    config_hash   TEXT,
    stats_json    TEXT,
    error_count   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status, started_at);

CREATE TABLE IF NOT EXISTS collection_windows (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id             INTEGER REFERENCES runs(id),
    kind               TEXT NOT NULL,
    date_from          TEXT NOT NULL,
    date_to            TEXT NOT NULL,
    filter_hash        TEXT NOT NULL,
    trade_type         TEXT,
    search_string      TEXT,
    parent_window_id   INTEGER REFERENCES collection_windows(id),
    depth              INTEGER NOT NULL DEFAULT 0,
    status             TEXT NOT NULL DEFAULT 'pending',
    outcome            TEXT,
    found              INTEGER,
    distinct_collected INTEGER NOT NULL DEFAULT 0,
    pages_loaded       INTEGER NOT NULL DEFAULT 0,
    last_offset        INTEGER NOT NULL DEFAULT 0,
    attempts           INTEGER NOT NULL DEFAULT 0,
    started_at         TEXT,
    finished_at        TEXT,
    error_message      TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_window
    ON collection_windows(kind, date_from, date_to, filter_hash, COALESCE(parent_window_id, 0));
CREATE INDEX IF NOT EXISTS idx_window_status ON collection_windows(status, kind);

CREATE TABLE IF NOT EXISTS window_sightings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    window_id    INTEGER NOT NULL REFERENCES collection_windows(id) ON DELETE CASCADE,
    guid         TEXT NOT NULL,
    offset_seen  INTEGER,
    seen_at      TEXT NOT NULL,
    UNIQUE(window_id, guid)
);
CREATE INDEX IF NOT EXISTS idx_sighting_guid ON window_sightings(guid);

CREATE TABLE IF NOT EXISTS biddings (
    guid                  TEXT PRIMARY KEY,
    number                TEXT,
    trade_type_code       TEXT,
    trade_type_name       TEXT,
    status                TEXT,
    is_rebidding          INTEGER NOT NULL DEFAULT 0,
    debtor_name           TEXT,
    debtor_inn            TEXT,
    debtor_ogrn           TEXT,
    debtor_region         TEXT,
    organizer_name        TEXT,
    organizer_inn         TEXT,
    manager_name          TEXT,
    manager_inn           TEXT,
    case_number           TEXT,
    court                 TEXT,
    platform_name         TEXT,
    platform_url          TEXT,
    trade_start_at        TEXT,
    trade_end_at          TEXT,
    application_start_at  TEXT,
    application_end_at    TEXT,
    published_at          TEXT,
    updated_at_source     TEXT,
    source_url            TEXT,
    message_url           TEXT,
    is_candidate          INTEGER NOT NULL DEFAULT 0,
    match_score           REAL,
    match_reasons_json    TEXT,
    filter_version        TEXT,
    classification_source TEXT,
    first_seen_at         TEXT NOT NULL,
    last_seen_at          TEXT NOT NULL,
    details_fetched_at    TEXT,
    lots_fetched_at       TEXT,
    messages_fetched_at   TEXT,
    source_state          TEXT NOT NULL DEFAULT 'active',
    content_hash          TEXT NOT NULL,
    normalized_json       TEXT,
    sync_status           TEXT NOT NULL DEFAULT 'pending',
    bitrix_id             INTEGER,
    bitrix_synced_hash    TEXT,
    bitrix_synced_at      TEXT,
    sync_attempts         INTEGER NOT NULL DEFAULT 0,
    sync_error            TEXT
);
CREATE INDEX IF NOT EXISTS idx_biddings_candidate ON biddings(is_candidate, details_fetched_at);
CREATE INDEX IF NOT EXISTS idx_biddings_sync ON biddings(sync_status);
CREATE INDEX IF NOT EXISTS idx_biddings_seen ON biddings(last_seen_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_biddings_bitrix ON biddings(bitrix_id) WHERE bitrix_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS lots (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_guid            TEXT NOT NULL REFERENCES biddings(guid) ON DELETE CASCADE,
    lot_number            TEXT NOT NULL,
    ordinal               INTEGER,
    lot_key               TEXT NOT NULL UNIQUE,
    status_code           TEXT,
    status_name           TEXT,
    start_price           TEXT,
    current_price         TEXT,
    min_price             TEXT,
    deposit               TEXT,
    advance_percent       TEXT,
    price_reduction_json  TEXT,
    classifiers_json      TEXT,
    trade_object_html     TEXT,
    trade_object_text     TEXT,
    sale_agreement        TEXT,
    payment_info          TEXT,
    is_public_offer       INTEGER NOT NULL DEFAULT 0,
    is_candidate          INTEGER NOT NULL DEFAULT 0,
    match_score           REAL,
    match_reasons_json    TEXT,
    classification_source TEXT,
    content_hash          TEXT NOT NULL,
    normalized_json       TEXT,
    first_seen_at         TEXT NOT NULL,
    last_seen_at          TEXT NOT NULL,
    missing_since         TEXT,
    is_deleted_at_source  INTEGER NOT NULL DEFAULT 0,
    sync_status           TEXT NOT NULL DEFAULT 'pending',
    bitrix_id             INTEGER,
    bitrix_synced_hash    TEXT,
    bitrix_synced_at      TEXT,
    sync_attempts         INTEGER NOT NULL DEFAULT 0,
    sync_error            TEXT,
    UNIQUE(trade_guid, lot_number)
);
CREATE INDEX IF NOT EXISTS idx_lots_trade ON lots(trade_guid);
CREATE INDEX IF NOT EXISTS idx_lots_sync ON lots(sync_status);
CREATE INDEX IF NOT EXISTS idx_lots_candidate ON lots(is_candidate, first_seen_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_lots_bitrix ON lots(bitrix_id) WHERE bitrix_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    guid          TEXT NOT NULL UNIQUE,
    trade_guid    TEXT REFERENCES biddings(guid) ON DELETE CASCADE,
    event_time    TEXT,
    number        TEXT,
    date_publish  TEXT,
    type          TEXT,
    is_annulled   INTEGER NOT NULL DEFAULT 0,
    is_locked     INTEGER NOT NULL DEFAULT 0,
    text_html     TEXT,
    text_plain    TEXT,
    files_json    TEXT,
    content_hash  TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    processed_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_trade ON messages(trade_guid, date_publish);
CREATE INDEX IF NOT EXISTS idx_messages_type ON messages(type);

CREATE TABLE IF NOT EXISTS entity_versions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type         TEXT NOT NULL,
    entity_key          TEXT NOT NULL,
    version_no          INTEGER NOT NULL,
    content_hash        TEXT NOT NULL,
    changed_fields_json TEXT,
    snapshot_json       TEXT,
    fetched_at          TEXT NOT NULL,
    UNIQUE(entity_type, entity_key, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_versions_entity
    ON entity_versions(entity_type, entity_key, version_no DESC);

CREATE TABLE IF NOT EXISTS raw_payloads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type   TEXT NOT NULL,
    entity_key    TEXT NOT NULL,
    endpoint      TEXT NOT NULL,
    run_id        INTEGER REFERENCES runs(id),
    fetched_at    TEXT NOT NULL,
    http_status   INTEGER,
    content_hash  TEXT NOT NULL,
    payload       TEXT,
    payload_bytes INTEGER NOT NULL DEFAULT 0,
    is_error      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(entity_type, entity_key, endpoint, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_raw_entity ON raw_payloads(entity_type, entity_key, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_raw_fetched ON raw_payloads(fetched_at);

CREATE TABLE IF NOT EXISTS sync_jobs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type        TEXT NOT NULL,
    entity_key         TEXT NOT NULL,
    operation          TEXT NOT NULL,
    payload_hash       TEXT NOT NULL,
    depends_on_job_id  INTEGER REFERENCES sync_jobs(id),
    status             TEXT NOT NULL DEFAULT 'pending',
    attempts           INTEGER NOT NULL DEFAULT 0,
    next_attempt_at    TEXT,
    last_error         TEXT,
    bitrix_id          INTEGER,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    finished_at        TEXT,
    UNIQUE(entity_type, entity_key, operation, payload_hash)
);
CREATE INDEX IF NOT EXISTS idx_jobs_ready ON sync_jobs(status, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_jobs_entity ON sync_jobs(entity_type, entity_key);

CREATE TABLE IF NOT EXISTS bitrix_id_map (
    entity_type           TEXT NOT NULL,
    entity_key            TEXT NOT NULL,
    bitrix_entity_type_id INTEGER NOT NULL,
    bitrix_id             INTEGER NOT NULL,
    xml_id                TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    PRIMARY KEY(entity_type, entity_key),
    UNIQUE(bitrix_entity_type_id, bitrix_id)
);
CREATE INDEX IF NOT EXISTS idx_idmap_xml ON bitrix_id_map(xml_id);

CREATE TABLE IF NOT EXISTS filter_overrides (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scope       TEXT NOT NULL,
    entity_key  TEXT NOT NULL,
    action      TEXT NOT NULL,
    reason      TEXT,
    created_by  TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE(scope, entity_key)
);

CREATE TABLE IF NOT EXISTS filter_decisions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    scope          TEXT NOT NULL,
    entity_key     TEXT NOT NULL,
    decision       TEXT NOT NULL,
    score          REAL,
    reasons_json   TEXT,
    filter_version TEXT,
    decided_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_scope ON filter_decisions(scope, decided_at);

CREATE TABLE IF NOT EXISTS errors (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER REFERENCES runs(id),
    window_id    INTEGER REFERENCES collection_windows(id),
    stage        TEXT,
    entity_type  TEXT,
    entity_key   TEXT,
    error_type   TEXT NOT NULL,
    error_code   TEXT,
    message      TEXT,
    context_json TEXT,
    occurred_at  TEXT NOT NULL,
    resolved_at  TEXT,
    resolution   TEXT
);
CREATE INDEX IF NOT EXISTS idx_errors_stage ON errors(stage, occurred_at);
CREATE INDEX IF NOT EXISTS idx_errors_open ON errors(resolved_at);

CREATE TABLE IF NOT EXISTS fetch_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER REFERENCES runs(id),
    window_id   INTEGER REFERENCES collection_windows(id),
    entity_type TEXT,
    entity_key  TEXT,
    endpoint    TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    duration_ms INTEGER,
    attempt     INTEGER NOT NULL DEFAULT 1,
    http_status INTEGER,
    outcome     TEXT,
    error_code  TEXT,
    bytes       INTEGER
);
CREATE INDEX IF NOT EXISTS idx_fetch_run ON fetch_log(run_id);
CREATE INDEX IF NOT EXISTS idx_fetch_outcome ON fetch_log(outcome, started_at);

CREATE TABLE IF NOT EXISTS receivable_showcase (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at         TEXT NOT NULL,
    item_hash          TEXT NOT NULL UNIQUE,
    payload_json       TEXT NOT NULL,
    matched_trade_guid TEXT,
    match_confidence   REAL,
    match_reasons_json TEXT
);

CREATE TABLE IF NOT EXISTS portal_sessions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at              TEXT NOT NULL,
    ended_at                TEXT,
    profile_dir             TEXT,
    qrator_cookie_expires_at TEXT,
    refresh_count           INTEGER NOT NULL DEFAULT 0,
    probe_ok                INTEGER,
    error                   TEXT
);

CREATE TABLE IF NOT EXISTS job_locks (
    name         TEXT PRIMARY KEY,
    owner        TEXT NOT NULL,
    acquired_at  TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    heartbeat_at TEXT
);

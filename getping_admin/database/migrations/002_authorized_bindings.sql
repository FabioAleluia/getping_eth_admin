CREATE TABLE license_bindings (
    licenca_id INTEGER PRIMARY KEY REFERENCES licencas(id) ON DELETE CASCADE,
    fingerprint TEXT CHECK(fingerprint IS NULL OR length(trim(fingerprint)) BETWEEN 1 AND 256),
    updated_by INTEGER,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_request_limits_window ON request_limits(window);

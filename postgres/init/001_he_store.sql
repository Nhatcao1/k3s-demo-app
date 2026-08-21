\set ON_ERROR_STOP on

CREATE SCHEMA IF NOT EXISTS he_store;

CREATE TABLE IF NOT EXISTS he_store.runs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id text UNIQUE,
    sdk_version text NOT NULL,
    backend text NOT NULL,
    scheme text NOT NULL DEFAULT 'CKKS',
    operation text NOT NULL,
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    input_count integer CHECK (input_count IS NULL OR input_count > 0),
    context_fingerprint text,
    key_bundle_id text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    completed_at timestamptz
);

CREATE INDEX IF NOT EXISTS runs_created_at_idx
    ON he_store.runs (created_at DESC);
CREATE INDEX IF NOT EXISTS runs_status_idx
    ON he_store.runs (status);

CREATE TABLE IF NOT EXISTS he_store.artifacts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id bigint NOT NULL REFERENCES he_store.runs(id) ON DELETE CASCADE,
    artifact_type text NOT NULL CHECK (
        artifact_type IN (
            'ciphertext',
            'context',
            'public_key',
            'evaluation_key',
            'manifest'
        )
    ),
    encoding text NOT NULL DEFAULT 'binary',
    payload bytea NOT NULL,
    sha256 char(64) NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS artifacts_run_id_idx
    ON he_store.artifacts (run_id);

-- Older lab releases deduplicated only by type and checksum. That prevented
-- two correctly named CPU/GPU outputs from coexisting when their serialized
-- ciphertext bytes happened to match. Identity is workspace path + checksum.
ALTER TABLE he_store.artifacts
    DROP CONSTRAINT IF EXISTS artifacts_run_id_artifact_type_sha256_key;
CREATE UNIQUE INDEX IF NOT EXISTS artifacts_run_path_sha256_uidx
    ON he_store.artifacts (
        run_id,
        (metadata->>'workspace_path'),
        sha256
    );

COMMENT ON TABLE he_store.artifacts IS
    'Encrypted or public HE artifacts only. Never store plaintext or secret keys.';

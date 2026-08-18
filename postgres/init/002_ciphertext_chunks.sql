\set ON_ERROR_STOP on

-- One row represents one logical encrypted value.  Chunk fields are kept out
-- of he_store.artifacts because context/public/evaluation-key artifacts are not
-- chunked vectors and should not carry a large group of nullable columns.
CREATE TABLE IF NOT EXISTS he_store.artifact_sets (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id bigint NOT NULL REFERENCES he_store.runs(id) ON DELETE CASCADE,
    logical_name text NOT NULL,
    source_id text,
    object_role text,
    alignment_id text,
    value_kind text NOT NULL CHECK (value_kind IN ('vector', 'scalar')),
    result_scope text NOT NULL CHECK (
        result_scope IN ('elementwise_vector', 'first_slot_scalar')
    ),
    backend text NOT NULL,
    scheme text NOT NULL,
    context_fingerprint text NOT NULL,
    key_bundle_id text NOT NULL,
    packing_layout text NOT NULL,
    serialization_version text NOT NULL,
    total_count bigint NOT NULL CHECK (total_count > 0),
    chunk_size integer NOT NULL CHECK (chunk_size > 0),
    chunk_count integer NOT NULL CHECK (chunk_count > 0),
    level integer NOT NULL CHECK (level >= 0),
    scale_bits integer NOT NULL CHECK (scale_bits > 0),
    status text NOT NULL DEFAULT 'writing'
        CHECK (status IN ('writing', 'ready', 'failed')),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    UNIQUE (run_id, logical_name)
);

CREATE INDEX IF NOT EXISTS artifact_sets_run_id_idx
    ON he_store.artifact_sets (run_id);
CREATE INDEX IF NOT EXISTS artifact_sets_ready_idx
    ON he_store.artifact_sets (status, created_at DESC);

-- A ciphertext remains the atomic serialization boundary.  The repository
-- must insert every chunk and mark its parent set ready in one transaction;
-- readers never load sets left in writing/failed state.
CREATE TABLE IF NOT EXISTS he_store.ciphertext_chunks (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    artifact_set_id bigint NOT NULL
        REFERENCES he_store.artifact_sets(id) ON DELETE CASCADE,
    chunk_index integer NOT NULL CHECK (chunk_index >= 0),
    item_offset bigint NOT NULL CHECK (item_offset >= 0),
    valid_count integer NOT NULL CHECK (valid_count > 0),
    level integer NOT NULL CHECK (level >= 0),
    scale_bits integer NOT NULL CHECK (scale_bits > 0),
    payload bytea NOT NULL CHECK (octet_length(payload) > 0),
    sha256 char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (artifact_set_id, chunk_index),
    UNIQUE (artifact_set_id, item_offset)
);

CREATE INDEX IF NOT EXISTS ciphertext_chunks_artifact_set_id_idx
    ON he_store.ciphertext_chunks (artifact_set_id, chunk_index);

COMMENT ON TABLE he_store.artifact_sets IS
    'Logical secretless HE vectors/scalars assembled from ciphertext chunks.';
COMMENT ON TABLE he_store.ciphertext_chunks IS
    'Encrypted chunks only. Never store plaintext or secret keys.';

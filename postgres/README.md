# PostgreSQL storage trial

This container is the first persistence boundary for the SDK experiment. It
stores run metadata plus ciphertext, context, public-key, evaluation-key and
manifest bytes. The schema does not accept a `secret_key` artifact type, and
application code must not write decrypted plaintext into metadata.

## Start on the server

Prepare a local password file that Git ignores:

```sh
cp postgres/postgres.env.example postgres/postgres.env
chmod 600 postgres/postgres.env
```

Replace the example password with a long random value. Then either pull the
CI-built image:

```sh
docker compose -f compose.postgres.yaml pull
docker compose -f compose.postgres.yaml up -d --no-build
```

or build the thin PostgreSQL image directly on the server:

```sh
docker compose -f compose.postgres.yaml up -d --build
```

The database listens only on `127.0.0.1:5432`. Its data persists in the
`he-sdk-postgres-data` named volume.

## Verify

```sh
docker compose -f compose.postgres.yaml ps
docker compose -f compose.postgres.yaml exec postgres \
  psql -U he_app -d he_store -c '\dt he_store.*'
```

Expected tables:

```text
he_store.runs
he_store.artifacts
he_store.artifact_sets
he_store.ciphertext_chunks
```

`artifact_sets` contains the metadata for one logical encrypted vector or
scalar. `ciphertext_chunks` stores its ordered ciphertext payloads. Writers
must insert a complete set and change its status from `writing` to `ready` in
one transaction; the SDK PostgreSQL repository is not implemented yet.

Host-side applications can use:

```text
postgresql://he_app:<password>@127.0.0.1:5432/he_store
```

Initialization SQL runs only when the data volume is empty. Normal
`docker compose down` preserves the volume. Do not use `down -v` unless you
intend to delete all stored data.

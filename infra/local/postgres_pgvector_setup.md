# Local Postgres + pgvector

This POC uses a local Homebrew PostgreSQL 17 instance with `pgvector`.

## Verified local state

- Database: `margadeep_poc`
- PostgreSQL version: `17.9`
- `pgvector` extension version: `0.8.2`

## Check the database

```bash
PGDATABASE=margadeep_poc psql -Atqc "SELECT current_database(), version();"
PGDATABASE=margadeep_poc psql -Atqc "SELECT extversion FROM pg_extension WHERE extname = 'vector';"
```

## Apply the POC schema

```bash
PGDATABASE=margadeep_poc psql -f apps/backend/sql/poc_personalization_schema.sql
```

## Dense retrieval shape

The `episodes` table stores one embedding per episode and all vector search should be filtered by `profile_id`.
The current local embedding model is `google/embeddinggemma-300m`, which produces `768`-dimensional vectors in this setup.

Example query shape:

```sql
SELECT id, title, episode_summary
FROM episodes
WHERE profile_id = $1
  AND embedding IS NOT NULL
ORDER BY embedding <=> $2
LIMIT 5;
```

## POC data model

- `caregivers`: minimal caregiver identity
- `profiles`: stable caregiver-authored child context
- `episodes`: episode history, summary text, JSON payload, and vector embedding

## Next step

Add seed scripts that insert:

1. caregivers
2. profiles
3. episodes
4. episode embeddings

The same episode history can then also be exported into AutoSchemaKG input for local graph generation.

## Seed the local POC data

```bash
python3 apps/backend/scripts/seed_poc_personalization.py
```

Verify the row counts:

```bash
PGDATABASE=margadeep_poc psql -Atqc "SELECT COUNT(*) FROM caregivers; SELECT COUNT(*) FROM profiles; SELECT COUNT(*) FROM episodes;"
```

## Embed episode summaries

Install the embedding dependency in your repo venv:

```bash
./my_venv/bin/pip install sentence-transformers
```

Then write embeddings into `episodes.embedding`:

```bash
./my_venv/bin/python apps/backend/scripts/embed_episode_summaries.py
```

To embed only one child's history:

```bash
./my_venv/bin/python apps/backend/scripts/embed_episode_summaries.py --profile-id profile_elliot
```

#!/usr/bin/env bash
# Backup and restore drill (F3 #78): dump the app schema and auth.users from a database, restore the dump into a
# throwaway Postgres 17 container, and compare every app table row for row (count and content hash).
#
#   SOURCE_URL='postgresql://…' tools/restore-drill.sh
#
# SOURCE_URL needs the role that owns the app tables (for staging: the supabase-db-password secret). The dump holds
# email addresses and private author mappings: it is written to a private temp directory and deleted at the end.
# Needs pg_dump/pg_restore/psql 17 and Docker (pulls pgvector/pgvector:pg17). Exit status 1 if any table differs.
set -euo pipefail

: "${SOURCE_URL:?set SOURCE_URL to the source database}"
PORT="${RESTORE_PORT:-55432}"
CONTAINER="guthub-restore-drill-$$"
WORK=$(mktemp -d)
chmod 700 "$WORK"
# The restored copy holds emails and author mappings: random password, and reachable from this machine only.
PASSWORD=$(openssl rand -hex 16)
TARGET="postgresql://postgres:${PASSWORD}@127.0.0.1:${PORT}/postgres"

cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

echo "1/4 dump the app schema, and the auth users it refers to"
# Separate dumps: pg_dump --schema plus --table would keep only the --table matches. Of auth.users only the id (the
# foreign key target) and email are kept; Supabase's own auth columns do not restore into plain Postgres.
pg_dump "$SOURCE_URL" --format=custom --no-owner --no-acl --schema=app --file="$WORK/backup.dump"
psql "$SOURCE_URL" -qc "\\copy (select id, email from auth.users order by id) to '$WORK/auth-users.csv' csv"
ls -l "$WORK/backup.dump" | awk '{print "    app schema: " $5 " bytes"}'
echo "    auth users: $(wc -l < "$WORK/auth-users.csv" | tr -d ' ')"

echo "2/4 start an empty Postgres 17"
# pgvector's image: app.search_chunks (H3 #125) stores vectors, and its table cannot be created without the extension.
docker run -d --name "$CONTAINER" -e POSTGRES_PASSWORD="$PASSWORD" -p "127.0.0.1:${PORT}:5432" pgvector/pgvector:pg17 >/dev/null
for _ in $(seq 1 60); do psql "$TARGET" -qtAc "select 1" >/dev/null 2>&1 && break; sleep 1; done
# Roles the schema's policies and grants name; Supabase creates these itself.
psql "$TARGET" -q -v ON_ERROR_STOP=1 <<'SQL'
create role guthub_api nologin;
create role anon nologin;
create role authenticated nologin;
create role service_role nologin;
create schema auth;
create table auth.users (id uuid primary key, email text);
-- Supabase keeps extensions in their own schema; the dump refers to extensions.vector.
create schema extensions;
create extension vector with schema extensions;
SQL

echo "3/4 restore"
psql "$TARGET" -qc "\\copy auth.users (id, email) from '$WORK/auth-users.csv' csv"
# Supabase adds a pg_attver option to every column; plain Postgres rejects it, and because pg_dump keeps those lines
# in the same step as CREATE TABLE, the tables would not restore. Drop just those lines; report any other error.
pg_restore --no-owner --no-acl --file=- "$WORK/backup.dump" | sed '/SET (pg_attver=/d' \
  | psql "$TARGET" -q -v ON_ERROR_STOP=0 >/dev/null 2>"$WORK/restore.log" || true
errors=$(grep -c 'ERROR' "$WORK/restore.log" || true)
echo "    restore errors: $errors"
[ "$errors" = 0 ] || grep -m5 'ERROR' "$WORK/restore.log" | sed 's/^/    /'

echo "4/4 compare every app table"
tables=$(psql "$SOURCE_URL" -qtAc "select tablename from pg_tables where schemaname = 'app' order by 1")
fingerprint() { # count and md5 of all rows in a stable order
  psql "$1" -qtAc "select count(*) || ' ' || coalesce(md5(string_agg(t::text, '|' order by t::text collate \"C\")), '-') from app.$2 t"
}
failed=0
for table in $tables; do
  source=$(fingerprint "$SOURCE_URL" "$table")
  target=$(fingerprint "$TARGET" "$table" 2>/dev/null || echo "missing")
  if [ "$source" = "$target" ]; then
    printf '    ok    %-22s %s rows\n' "$table" "${source%% *}"
  else
    printf '    DIFF  %-22s source %s / restored %s\n' "$table" "$source" "$target"
    failed=1
  fi
done
users_source=$(psql "$SOURCE_URL" -qtAc "select count(*) from auth.users")
users_target=$(psql "$TARGET" -qtAc "select count(*) from auth.users")
echo "    auth.users: source $users_source / restored $users_target"
[ "$users_source" = "$users_target" ] || failed=1
# The anonymous author mapping must come back: same comment -> same account.
mapping_source=$(psql "$SOURCE_URL" -qtAc "select coalesce(md5(string_agg(id || ':' || coalesce(author_id::text, '-'), ',' order by id)), '-') from app.comments where anonymous")
mapping_target=$(psql "$TARGET" -qtAc "select coalesce(md5(string_agg(id || ':' || coalesce(author_id::text, '-'), ',' order by id)), '-') from app.comments where anonymous")
if [ "$mapping_source" = "$mapping_target" ]; then echo "    ok    anonymous author mapping"; else echo "    DIFF  anonymous author mapping"; failed=1; fi

exit $failed

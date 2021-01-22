#!/usr/bin/env sh
set -e
mkdir -p build/data
cp /usr/share/zoneinfo/America/New_York /etc/localtime
echo "America/New_York" > /etc/timezone
cat > build/test-environment<<EOF
export PGHOST=postgres
export PGDATABASE=postgres
export PGPASSWORD=postgres
export PGUSER=postgres
export POSTGRES_URI=postgresql://postgres:postgres@postgres:5432/postgres
EOF
. build/test-environment
if test -f "build/data/dump.not-compressed"; then
  echo "Test data already exists"
else
  pgbench -i postgres
  psql -q -o /dev/null -f fixtures/schema.sql
  bin/generate-fixture-data.py -U postgres -h postgres -p 5432 -d postgres
  pg_dump -Fc -f build/data/dump.not-compressed --compress=0
  pg_dump -Fc -f build/data/dump.compressed --compress=9
  pg_dump -Fc -f build/data/dump.no-data --compress=0 -s
  pg_dump -Fc -f build/data/dump.data-only --compress=0 -a
  pg_dump -Fc -f build/data/dump.inserts --compress=0 --inserts
fi

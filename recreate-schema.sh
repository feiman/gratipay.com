#!/bin/sh

# Exit if any subcommands or pipeline returns a non-zero status.
set -e

# Make a database for Gratipay.
#
#   usage: DATABASE_URL=postgres://foo:bar@baz:5234/buz recreate-schema.sh

echo "=============================================================================="

# I got the idea for dropping the schema as a way to clear out the db from
# http://www.postgresql.org/message-id/200408241254.19075.josh@agliodbs.com. On
# Heroku Postgres we don't have permission to drop and create the db as a 
# whole.

echo "Recreating public schema ... "
echo "DROP SCHEMA public CASCADE" | psql $DATABASE_URL
echo "CREATE SCHEMA public" | psql $DATABASE_URL


echo "=============================================================================="
echo "Applying sql/schema.sql ..."
echo 

psql $DATABASE_URL < sql/schema.sql


echo "=============================================================================="
echo "Looking for sql/branch.sql ..."
echo 

if [ -f sql/branch.sql ]
then psql $DATABASE_URL < sql/branch.sql
else 
    echo "None found. That's cool. You only need a sql/branch.sql file if you want to "
    echo "include schema changes with your pull request."
fi

echo 
echo "=============================================================================="

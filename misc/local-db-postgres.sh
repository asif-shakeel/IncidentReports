brew services start postgresql@15

brew services list
lsof -i tcp:5432

createdb incidentreports_postgres_test
export DATABASE_URL="postgresql://127.0.0.1:5432/incidentreports_postgres_test"
alembic upgrade head
# 1) Start a disposable test DB on 5433
docker run --name irhub-test-db \
  -e POSTGRES_USER=testuser \
  -e POSTGRES_PASSWORD=testpass \
  -e POSTGRES_DB=incidentreports_postgres_test \
  -p 5433:5432 -d postgres:17

# 2) Point your env at it
export DATABASE_URL="postgresql://testuser:testpass@localhost:5433/incidentreports_postgres_test"

# 3) Create schema
alembic upgrade head

# 4) Run tests
pytest -q

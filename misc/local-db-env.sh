# load vars and migrate
export $(grep -v '^#' .env.test | xargs)
alembic upgrade head

# run tests against the test DB
export $(grep -v '^#' .env.test | xargs)
pytest -q

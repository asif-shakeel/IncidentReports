export PYTHONPATH=.
export DATABASE_URL="postgresql://127.0.0.1:5432/incidentreports_postgres_test"  # or your local/test DB
export SHOW_DOCS=1  # enables /docs locally
python -m uvicorn main:app --reload

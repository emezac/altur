web: gunicorn -k uvicorn.workers.UvicornWorker app.main:app --chdir backend --bind 0.0.0.0:$PORT --workers ${WEB_CONCURRENCY:-2} --timeout 120
worker: bash -c "cd backend && python -m app.workers.run_worker"
release: bash -c "cd backend && alembic upgrade head"

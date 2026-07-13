# Backend image — used by docker-compose for LOCAL_DOCKER parity (Postgres + Redis + MinIO).
# The vanilla frontend is static and served by FastAPI; it is mounted into the container
# at /frontend (see docker-compose.yml), so no Node/build step is needed.
FROM python:3.12-slim

WORKDIR /app

# Install Python deps first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code (compose bind-mounts ./backend over this for hot reload in dev).
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

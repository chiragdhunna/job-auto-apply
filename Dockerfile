# Image for the API + dashboard (see docker-compose.yml).
# NOTE: the browser-automation modules (LinkedIn/Indeed/ATS apply) need a
# non-headless browser and your logged-in session, so run those on the HOST via
# run.sh — not in this container.
FROM python:3.11-slim

WORKDIR /app

# System deps kept minimal (no browser here on purpose).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000 8501

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# /app holds the full 06-capstone-pipeline tree (pipeline modules + backend/ + frontend/)
WORKDIR /app

# Layer 1: requirements only (cached unless deps change)
COPY requirements.txt ./requirements.txt
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir -r backend/requirements.txt

# Layer 2: application source
COPY . .

# Data directory — overridden at runtime by Azure Files volume mount at /data
RUN mkdir -p /data

EXPOSE 8000

# Run from backend/ so that 'routes.*' imports resolve as top-level packages,
# matching how the server runs locally ('uvicorn main:app' from inside backend/).
# main.py adds its parent's parent (/app) to sys.path at startup, which makes
# all pipeline modules (agents, skills, tools, etc.) importable.
# --workers 1 is MANDATORY: multiple workers = separate RunRegistry instances,
# so an approve POST on worker A cannot unblock a threading.Event on worker B.
WORKDIR /app/backend
CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1"]

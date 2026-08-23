# AeroLift Analytics - production image (API + dashboard).
# Single image, two entrypoints:
#   API       : uvicorn api.main:app --host 0.0.0.0 --port 8000
#   Dashboard : streamlit run app.py --server.port 8501 ...
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first for layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code (runtime only; tests stay out of the image)
COPY alembic.ini ./
COPY alembic ./alembic
COPY api ./api
COPY math_engine ./math_engine
COPY scripts ./scripts
COPY app.py ./

# Non-root runtime user; persistent dir for trained ML models
RUN useradd --create-home aerolift \
    && mkdir -p /data/ml_models \
    && chown -R aerolift:aerolift /app /data

USER aerolift
WORKDIR /app

EXPOSE 8000 8501
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

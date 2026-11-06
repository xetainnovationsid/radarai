FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app
COPY apps/api/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir torch torchvision \
       --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install --no-cache-dir --extra-index-url \
       https://download.pytorch.org/whl/cpu -r requirements.txt

COPY apps/api/alembic.ini ./alembic.ini
COPY apps/api/migrations ./migrations
COPY apps/api/src ./src
RUN useradd --create-home --uid 10001 radar \
    && mkdir -p /var/lib/radar/private-images \
    && chown -R radar:radar /app /var/lib/radar

USER radar
ENV RADAR_STORAGE_DIR=/var/lib/radar/private-images
EXPOSE 8000
CMD ["sh", "-c", "python -m alembic upgrade head && uvicorn radar_api.main:app --host 0.0.0.0 --port 8000"]

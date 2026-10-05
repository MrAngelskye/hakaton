FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends libegl1 libgl1 libglib2.0-0 libxkbcommon0 tzdata && rm -rf /var/lib/apt/lists/*
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 QT_QPA_PLATFORM=offscreen TZ=Asia/Qyzylorda
WORKDIR /app
COPY requirements.txt requirements-server.txt /app/
RUN pip install --no-cache-dir -r requirements-server.txt
COPY app /app/app
COPY server /app/server
COPY assets /app/assets
COPY web /app/web
COPY run_server.py /app/
RUN useradd -m appuser
USER appuser
CMD ["python", "run_server.py"]

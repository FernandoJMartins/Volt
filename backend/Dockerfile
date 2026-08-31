FROM python:3.12-slim

WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY pyproject.toml .
RUN pip install --no-cache-dir uv && uv pip install --system --no-cache -r pyproject.toml

# Chromium + libs de sistema do Playwright (coleta/publicacao via navegador).
RUN playwright install --with-deps chromium

# Stack de tela virtual para o login headed em servidor sem monitor:
# Xvfb (framebuffer) + x11vnc (VNC) + noVNC/websockify (VNC no navegador).
RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb x11vnc novnc websockify ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY . .
RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

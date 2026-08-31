FROM python:3.12-slim

WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY pyproject.toml .
RUN pip install --no-cache-dir uv && uv pip install --system --no-cache -r pyproject.toml

# Chromium + libs de sistema do Playwright (coleta/publicacao via navegador).
RUN playwright install --with-deps chromium

# A pilha de tela virtual (Xvfb + x11vnc + noVNC) foi REMOVIDA na Fase 4:
# o X bloqueia login a partir do IP do servidor, entao o login e' sempre
# headless e a sessao entra por importacao de cookies (ver README).

COPY . .
RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

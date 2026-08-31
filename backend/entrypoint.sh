#!/usr/bin/env bash
# Entrypoint do container da API. Quando ENABLE_LOGIN_DISPLAY=1, sobe uma tela
# virtual (Xvfb) + servidor VNC (x11vnc) + ponte web (noVNC/websockify), para que
# o login headed do Playwright seja VISTO e operado pelo navegador do usuario.
#
# SEGURANCA: a porta 6080 da' controle total do navegador do servidor. NUNCA a
# exponha publica sem senha. Defina VNC_PASSWORD e/ou acesse via tunel SSH:
#     ssh -L 6080:localhost:6080 usuario@servidor
set -e

if [ "${ENABLE_LOGIN_DISPLAY:-0}" = "1" ]; then
  export DISPLAY="${DISPLAY:-:99}"
  echo "[entrypoint] iniciando tela virtual em $DISPLAY"
  Xvfb "$DISPLAY" -screen 0 1360x1020x24 -nolisten tcp &
  sleep 1

  if [ -n "${VNC_PASSWORD:-}" ]; then
    x11vnc -storepasswd "$VNC_PASSWORD" /tmp/.vncpass >/dev/null 2>&1
    x11vnc -display "$DISPLAY" -forever -shared -rfbauth /tmp/.vncpass \
      -rfbport 5900 -bg -quiet
  else
    echo "[entrypoint] AVISO: sem VNC_PASSWORD — noVNC fica SEM SENHA."
    x11vnc -display "$DISPLAY" -forever -shared -nopw -rfbport 5900 -bg -quiet
  fi

  websockify --web=/usr/share/novnc 6080 localhost:5900 &
  echo "[entrypoint] noVNC em http://localhost:6080/vnc.html"
fi

exec "$@"

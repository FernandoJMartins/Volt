#!/usr/bin/env bash
# Entrypoint do container da API.
#
# O antigo fluxo de login headed via tela virtual (Xvfb + x11vnc + noVNC) foi
# REMOVIDO: o X bloqueia login a partir do IP do servidor, entao o noVNC nao
# servia para logar. O metodo de conexao agora e' exclusivamente a importacao
# de cookies exportados do navegador do usuario (ver README).
set -e

exec "$@"

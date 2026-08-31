# Pendências — Volt

Setup feito em 2026-08-29. Isto documenta o que já está rodando e o que falta pra
usar o projeto de verdade.

## Status atual

- [x] Containers no ar: `api`, `worker`, `scheduler`, `frontend`, `redis`.
- [x] Postgres do host (`volt`, porta 5432) conectado — tabelas criadas via `create_all`.
- [x] `restart: unless-stopped` em todos os serviços + `docker.service` habilitado no
      systemd → se o servidor cair e voltar, o Volt sobe sozinho.
- [x] Portas confirmadas sem conflito: `5180` (painel), `8010` (API).
- [ ] Nenhuma conta do Volt criada ainda.
- [x] Conta do X conectada via importação de cookies (ver item 2).

## Pendências

### 1. Criar sua conta no painel
Acesse http://localhost:5180 — primeiro acesso é um cadastro normal (e-mail + senha).
**(ação sua — não dá pra fazer por código sem escolher e-mail/senha)**

### 2. Conectar uma conta do X — RESOLVIDO (via importação de cookies)
O X bloqueia login a partir do IP do servidor, então o fluxo headed + noVNC foi
**removido**. O método é importar cookies exportados do navegador da sua máquina
(extensão "Get cookies.txt LOCALLY", só o site x.com) em **Contas → Importar
cookies** (ou **Configurar → Importar cookies** para trocar a sessão de uma conta
já conectada). O backend valida a sessão abrindo o x.com headless e resolve o
@username via DOM (a API interna do X responde 403 para IP de datacenter).

### 3. noVNC removido do projeto — RESOLVIDO
A tela virtual (Xvfb/x11vnc/noVNC), o proxy `/novnc` do Vite, os endpoints
`/browser/login`, `/browser/{id}/status` e `/{id}/browser/relogin` e o botão
"Conectar" foram removidos. `VNC_PASSWORD` no `.env` ficou sem uso (pode apagar).
A variável `ENABLE_LOGIN_DISPLAY` e o mapeamento da porta 6080 saíram do
`docker-compose.yml`; o `entrypoint.sh` agora só repassa para o comando do container.

### 4. Segredos opcionais no `.env` — ação sua
Deixados em branco — só preencher se for usar:
- `X_CLIENT_ID` / `X_CLIENT_SECRET` — API oficial do X (paga, ver custos no README).
- `ANTHROPIC_API_KEY` — IA opcional (geração de ângulos de conteúdo). Plano Claude Pro
  não serve, precisa de key com billing próprio.

### 5. Alembic — RESOLVIDO (Fase 4 concluída)
Migrações configuradas em `backend/alembic/` (modo async, ligado ao `settings.DATABASE_URL`).
A migração inicial foi gerada contra um banco vazio temporário, validada (`upgrade head`
+ `alembic check` limpos) e o banco real carimbado com `stamp head`. Mudanças novas de
schema entram por `alembic revision --autogenerate` + `alembic upgrade head`.

Na mesma leva da Fase 4: `media_assets` já existia (modelo+API+UI); rate limit interno
implementado no worker (`_enforce_pacing` — intervalo mínimo e teto diário revalidados
no momento da publicação, com reagendamento em vez de publicar); suíte de testes em
`backend/tests/` (31 testes, sem depender do banco) via `python -m pytest tests/ -q`.

## Fase 5 — analytics e otimização de horários (RESOLVIDO)

- Engajamento dos posts publicados coletado automaticamente (varredura do scheduler a
  cada hora + ~45min após cada publicação + botão "Coletar agora" na tela Analytics).
- Tela **Analytics** no painel: volume, engajamento médio, gráfico por hora do dia,
  posts recentes com métricas.
- Estratégia **Otimizado** no agendamento automático (Conteúdo): horários guiados pelo
  engajamento histórico; cai no espalhamento uniforme sem dados.
- 42 testes (11 novos de analytics). Migração `c4f1a2b3d5e6` (tabela `post_stats`).

## Onde estão as coisas

- `.env` (segredos gerados): `/opt/apps/Volt/.env` — **não commitar**.
- Banco Postgres: role `postgres`, banco `volt`, host `host.docker.internal` (por fora
  do container: `localhost:5432`).

## Comandos úteis

```bash
cd /opt/apps/Volt

docker compose ps                    # status dos containers
docker compose logs -f api           # logs em tempo real da API
docker compose restart api           # reinicia um serviço
docker compose up -d --force-recreate api   # recria pegando mudanças no .env
docker compose down                  # derruba tudo (mantém volumes/dados)
```

### Escolher contas no dashboard + midia do perfil (RESOLVIDO)

- Tela inicial ganhou "Contas para clonar": adicionar/coletar/remover perfis e filtrar o feed.
- A coleta baixa a midia dos posts (imagens; poster no caso de video) como referencia visual
  (`source_reference` — nao publica).
- Quantidade de posts por coleta configuravel (1-100) por conta; coleta IDEMPOTENTE — nunca
  duplica posts nem rebaixa midia ja' coletada; aumentar a quantidade puxa posts mais antigos.
- Interface limpa da API oficial do X: botao OAuth removido (Contas), retweets entre contas
  removidos da Fila (dependiam da API paga), textos de custo corrigidos em Config e Monitorar.
  Codigo legado (`x_api`) permanece inativo no backend.

### IA local + geracao em lote + analytics das contas clonadas (RESOLVIDO)

- IA LOCAL via Ollama (`AI_PROVIDER=ollama`, servico no docker-compose; puxe um modelo com
  `docker compose exec ollama ollama pull qwen2.5:7b`). Sem custo por token.
- Geracao em lote (Início → seção 3): a IA reescreve os posts coletados, divide IGUALMENTE
  entre as contas (30/3 = 10 por conta), anexa midia propria e tudo sai `pending`.
- Regra de negocio: todo post precisa de midia propria/licenciada para APROVAR
  (`MEDIA_REQUIRED=true`; a geracao em lote ja' bloqueia sem biblioteca de midia).
- Analytics agora tem aba "Contas clonadas" (engajamento por hora dos perfis monitorados).

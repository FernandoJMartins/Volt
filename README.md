# Painel de Conteúdo para X

Content Intelligence + Scheduler para múltiplas contas do X, com aprovação humana,
IA opcional e coleta/publicação via **navegador (Playwright)** — sem os custos da API
oficial. O caminho da API oficial continua no código (`SOURCE_MODE=x_api`), mas o
modo padrão é `web`.

## Como rodar

```bash
cp .env.example .env
```

Edite o `.env` e gere os dois segredos:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"                      # JWT_SECRET
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # ENCRYPTION_KEY
```

Suba tudo:

```bash
docker compose up --build
```

- Painel: http://localhost:5180
- API: http://localhost:8010/health

Crie sua conta na tela de login (o primeiro acesso é um cadastro normal).

## Conectar contas do X (modo navegador)

Cada conta é logada **uma vez** num navegador, e a sessão fica salva criptografada.
Como o servidor Ubuntu não tem tela, o login é feito por **noVNC** — você vê o Chromium
do servidor pelo seu próprio navegador.

1. No servidor, defina `VNC_PASSWORD` no `.env` (protege o noVNC).
2. Dispare o login: `POST /api/x/accounts/browser/login` → devolve `account_id` e `vnc_url`.
3. Abra a `vnc_url` (padrão `http://localhost:6080/vnc.html`). **Em produção, acesse por
   túnel SSH**, nunca com a porta 6080 aberta:
   ```bash
   ssh -L 6080:localhost:6080 usuario@servidor
   ```
4. Faça login no X na janela (resolva captcha/2FA na mão). O sistema detecta o login e
   salva a sessão. Acompanhe em `GET /api/x/accounts/browser/{id}/status`.
5. Sessão expirou depois? `POST /api/x/accounts/{id}/browser/relogin` reabre o mesmo
   contexto isolado.

**Isolamento:** cada conta roda num `BrowserContext` próprio, criado do zero e semeado só
com a sessão dela. Duas contas nunca dividem contexto, cookies ou navegador.

## Fluxo do MVP

1. **Monitoramento → Pool de textos**: cole seus textos (separados por `---`). Esta é a fonte
   de custo zero.
2. **Monitoramento → Fontes**: cadastre uma fonte tipo *Pool manual* e clique em atualizar
   para rodar a coleta.
3. **Início**: os posts aparecem rankeados por score. Clique num card.
4. **Criar conteúdo**: escolha a conta destino, escreva o texto (ou gere ângulos com IA, se
   ativada) e aprove.
5. **Conteúdo**: revise, edite e agende.
6. **Fila**: acompanhe, publique agora, cancele. Depois de publicado, dá para escalonar
   retweets entre suas outras contas.

## Custos reais (importante)

Desde fev/2026 a API do X é **pay-per-use**:

| Operação | Custo aprox. |
|---|---|
| Ler 1 post | US$ 0,005 |
| Publicar 1 post | US$ 0,015 (US$ 0,20 com link) |

Com **R$20/mês** você tem ~740 leituras — insuficiente para monitoramento ao vivo. Por isso a
fonte padrão é o pool manual, e o `XApiProvider` só entra quando você definir orçamento.

**IA**: o plano Claude Pro **não** inclui API. Precisa de `ANTHROPIC_API_KEY` com billing
próprio — mas o custo é irrisório (centavos por geração). A IA é sempre opcional.

## Arquitetura

```
frontend (React+Vite)  →  api (FastAPI)  →  postgres + redis
                                ↕
                   worker (Arq) + scheduler
                                ↕
              Navegador (Playwright) / X API oficial / Anthropic
```

O login headed usa Xvfb + x11vnc + noVNC no container `api` (ver `entrypoint.sh`).

| Serviço | Papel |
|---|---|
| `api` | REST, OAuth, regras de negócio |
| `worker` | coleta, publicação, retweets — com retry e backoff |
| `scheduler` | despacha jobs maduros a cada 30s |

Trocar a fonte de dados = implementar `SourceProvider` em `backend/app/services/sources.py`.
Trocar o provedor de IA = implementar `AIProvider` em `backend/app/services/ai.py`.

## Proteções implementadas

- **Anti cross-posting**: hash SHA-256 (idêntico) + similaridade por trigramas (parafraseado).
  Conteúdo acima do limiar vira `blocked` e exige edição.
- **Aprovação humana** obrigatória antes de agendar.
- **Rate limit do X respeitado**: em 429, o job reagenda para depois do reset informado pela
  própria API. Nunca contornado.
- **Tokens e sessões criptografados** (Fernet) e nunca enviados ao frontend.
- **Isolamento estrito de sessão**: um `BrowserContext` por conta, com trava de posse
  (`account_id` no blob) e lock por conta. Contas nunca se misturam.
- Limite de frequência por conta (máx. 24 posts/dia, intervalo mín. 15 min).
- Sessões, `/data/` e perfis de navegador ficam fora do Git (`.gitignore`).

## Estado das fases

- ✅ **Fase 1** — auth, OAuth, Postgres, dashboard, fontes, pool, coleta
- ✅ **Fase 2** — score relativo, ranking, tela de criação, IA opcional
- ✅ **Fase 3** — aprovação, edição, scheduler, fila, publisher, retweet escalonado
- ⏳ **Fase 4** — Alembic, media_assets, rate limit interno, testes ampliados
- ⏳ **Fase 5** — analytics e otimização de horários

## Aviso sobre retweets entre contas

Amplificar o mesmo post com várias contas suas pode ser interpretado como *platform
manipulation* pelas políticas do X. O recurso usa o endpoint oficial e fica sob seu controle,
com registro em auditoria — mas o risco de conta é real. Use com critério.

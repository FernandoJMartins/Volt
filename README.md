# Painel de Conteúdo para X

Content Intelligence + Scheduler para múltiplas contas do X, com aprovação humana,
IA opcional e coleta/publicação via **navegador (Playwright)** — **sem a API oficial do X**
(paga por post). O código legado da API oficial permanece inativo (`x_api`), sem exposição
na interface.

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

## Conectar contas do X (importar cookies)

O X bloqueia login a partir do IP do servidor ("Limitamos temporariamente seu
acesso") — por isso o projeto **não tem mais fluxo de login no servidor** (o antigo
noVNC foi removido). O método é importar os cookies de uma sessão já logada:

1. No navegador **da sua máquina**, logado no X na conta desejada, exporte os
   cookies com a extensão "Get cookies.txt LOCALLY" (só o site x.com) — ou
   equivalente que gere cookies.txt/JSON.
2. No painel: **Contas → Importar cookies** e escolha o arquivo (ou cole o conteúdo).
   Para refazer a sessão de uma conta existente: **Configurar → Importar cookies**.
3. O backend converte para o `storage_state` do Playwright (só cookies de
   x.com/twitter.com passam; o resto é descartado), salva criptografado e valida a
   sessão abrindo o x.com headless. Se validar, a conta aparece como conectada.

- Nova conta: `POST /api/x/accounts/browser/import-cookies` com
  `{"cookies_text": "..."}` (reaproveita a conta browser pendente, se houver).
- Conta existente: `POST /api/x/accounts/{id}/browser/cookies` (substitui a
  sessão — funciona como um re-login).

Formatos aceitos: cookies.txt (Netscape), lista JSON de cookies ou
`storage_state` completo do Playwright. O despejo nunca é logado nem devolvido.

**Isolamento:** cada conta roda num `BrowserContext` próprio, criado do zero e semeado só
com a sessão dela. Duas contas nunca dividem contexto, cookies ou navegador.

## Fluxo do MVP

1. **Monitoramento → Pool de textos**: cole seus textos (separados por `---`). Esta é a fonte
   de custo zero.
2. **Início → Contas para clonar**: adicione o @perfil que serve de inspiração, defina
   quantos posts puxar por coleta (1–100) e clique em Coletar — os posts (com a **mídia do
   perfil** baixada como referência visual) aparecem no feed, rankeados. Coletar de novo
   nunca duplica o que já entrou.
3. **Início**: os posts aparecem rankeados por score. Clique num card.
4. **Criar conteúdo**: escolha a conta destino, escreva o texto (ou gere ângulos com IA, se
   ativada) e aprove.
5. **Conteúdo**: revise, edite e agende.
6. **Fila**: acompanhe, publique agora, cancele. Depois de publicado, dá para escalonar
   retweets entre suas outras contas.

A mídia dos posts coletados (imagens; poster no caso de vídeo) é baixada como
**referência visual** (`origin=source_reference`) e exibida no feed e na tela de criação.
Republicar mídia de terceiros continua bloqueado — só mídia própria ou licenciada publica.

## Custos reais (importante)

Desde fev/2026 a API do X é **pay-per-use**:

| Operação | Custo aprox. |
|---|---|
| Ler 1 post | US$ 0,005 |
| Publicar 1 post | US$ 0,015 (US$ 0,20 com link) |

Com **R$20/mês** você tem ~740 leituras — insuficiente para monitoramento ao vivo. Por isso a
fonte padrão é o pool manual, e o `XApiProvider` só entra quando você definir orçamento.

**IA**: o padrão é **Ollama local** (`AI_PROVIDER=ollama`, serviço `ollama` no compose) —
gratuita, sem key, nada sai da máquina. O modelo padrão é
`huihui_ai/llama3.2-abliterate:3b` (versão sem censura, para conteúdo +18);
para trocar, basta mudar `OLLAMA_MODEL` no `.env` (o Ollama baixa o modelo na
primeira geração). O provedor pago (`AI_PROVIDER=anthropic`) continua no código
se um dia fizer sentido — mas **não é necessário** e nunca é selecionado por
padrão. A IA é sempre opcional.

A geração pede ao modelo ângulos NOVOS (nunca cópia) no tom da persona de cada conta, e a
checagem de similaridade bloqueia na aprovação qualquer texto próximo demais do que já foi
usado em outra conta — cada post em cada conta é único.

## Gerar em lote com IA (Início → seção 3)

Escolha quantos posts gerar e para quais contas (vazio = todas). A IA reescreve os posts
coletados (os melhores pelo score), **divide igualmente entre as contas** (30 posts / 3
contas = 10 por conta) e anexa mídia da sua biblioteca — **todo post precisa de mídia
própria/licenciada** (regra do painel). Os rascunhos entram em *Conteúdo* para você aprovar;
depois agende manualmente ou use *Agendar tudo automaticamente* com a estratégia otimizada
(a IA escolhe os melhores horários pelo engajamento histórico).

## Arquitetura

```
frontend (React+Vite)  →  api (FastAPI)  →  postgres + redis
                                ↕
                   worker (Arq) + scheduler
                                ↕
              Navegador (Playwright) / Ollama (IA local) / Anthropic (opcional)
```

O login é sempre headless: a sessão entra por importação de cookies, validada e
renovada pelo próprio Chromium no container `api`.

| Serviço | Papel |
|---|---|
| `api` | REST, OAuth, regras de negócio |
| `worker` | coleta, publicação, retweets — com retry e backoff |
| `scheduler` | despacha jobs maduros a cada 30s |

Trocar a fonte de dados = implementar `SourceProvider` em `backend/app/services/sources.py`.
Trocar o provedor de IA = implementar `AIProvider` em `backend/app/services/ai.py`.

## Analytics e otimização de horários (Fase 5)

Depois de publicado, o engajamento de cada post (likes, reposts, replies) é coletado
**de hora em hora** pelo scheduler — e também ~45min após cada publicação — via navegador,
no perfil da própria conta (1 navegação por conta, sem custo de API). Dá para forçar a coleta
em **Analytics → Coletar agora**.

A tela **Analytics** mostra, por conta: volume publicado, engajamento médio, gráfico de
engajamento por hora do dia (24h, melhores horas destacadas) e os posts recentes com métricas.

**Agendamento otimizado**: em *Conteúdo → Agendar tudo automaticamente*, a estratégia
"Otimizado" posiciona os posts nas horas de maior engajamento histórico da conta (dentro da
janela e do intervalo mínimo dela). O score de cada hora usa prior bayesiano — hora com pouca
amostra não vira campeã por um único post viral. Sem dados suficientes, cai automaticamente no
espalhamento uniforme.

Limitação conhecida: o X não expõe *views* no timeline, então views ficam zeradas nas
métricas — o engajamento ponderado ignora views de propósito.

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
- ✅ **Fase 4** — Alembic, media_assets, rate limit interno, testes
- ✅ **Fase 5** — analytics de posts publicados e otimização de horários

### Migrações (Alembic) e testes

```bash
# dentro do container api (ou de fora, com docker compose exec api ...)
alembic revision --autogenerate -m "descricao"   # gera migracao a partir dos models
alembic upgrade head                               # aplica migracoes pendentes
alembic check                                      # conferir se models == banco
python -m pytest tests/ -q                         # suite de testes (sem depender do banco)
```

- Migração inicial em `backend/alembic/versions/`; o banco existente foi carimbado
  (`stamp head`) — mudanças novas de schema entram via Alembic, não mais `create_all`.
- Testes cobrem: parser de cookies (formatos/limites/dominio), scoring, dedup
  (anti cross-posting), distribuição de horários e fumaça da API (rotas + /health).

## Aviso sobre retweets entre contas

O fluxo de retweet escalonado entre as próprias contas (que dependia da API oficial) foi
removido da interface; o código no backend permanece inativo. Amplificar o mesmo post com
várias contas pode ser interpretado como *platform manipulation* pelas políticas do X —
use outras formas de amplificação com critério.

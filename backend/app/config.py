from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://xpanel:xpanel@postgres:5432/xpanel"
    REDIS_URL: str = "redis://redis:6379/0"

    JWT_SECRET: str = "dev-only-change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_TTL_HOURS: int = 12
    ENCRYPTION_KEY: str = ""

    X_CLIENT_ID: str = ""
    X_CLIENT_SECRET: str = ""
    X_CALLBACK_URL: str = "http://localhost:8010/api/x/accounts/callback"

    AI_ENABLED: bool = False
    ANTHROPIC_API_KEY: str = ""
    AI_MODEL: str = "claude-sonnet-5"

    FRONTEND_URL: str = "http://localhost:5180"
    STORAGE_DIR: str = "/data/media"

    # ---- Camada de navegador (Playwright) ----
    # Modo de coleta/publicacao padrao: "web" (Playwright) ou "api" (X oficial, legado).
    SOURCE_MODE: str = "web"
    # Diretorio de trabalho das sessoes. O estado autenticado vive CRIPTOGRAFADO
    # no banco (XAccount.session_state_encrypted); este dir guarda apenas caches
    # efemeros por conta. NUNCA versionar (ver .gitignore).
    SESSIONS_DIR: str = "/data/sessions"
    # Coleta/publicacao rodam headless. O login inicial roda headed (ver x_web.login).
    BROWSER_HEADLESS: bool = True
    # Isolamento entre contas: "context" (1 BrowserContext por conta, particao de
    # storage isolada) ou "process" (1 processo de navegador por conta, isolamento
    # maximo ao custo de mais RAM). Nunca ha duas contas no mesmo contexto.
    BROWSER_ISOLATION: str = "context"
    # User-Agent fixo por conta evita variacao suspeita entre sessoes da mesma conta.
    BROWSER_LOCALE: str = "pt-BR"

    # Scoring — pesos ajustáveis sem deploy
    SCORE_W_RELATIVE: float = 3.0
    SCORE_W_VELOCITY: float = 1.5
    SCORE_W_RECENCY: float = 2.0
    SCORE_W_MEDIA: float = 0.5
    SCORE_HALFLIFE_HOURS: float = 18.0

    # Anti cross-posting. 0.75 pega parafrase ("mudar" -> "transformar"), enquanto
    # conteudo genuinamente diferente fica na faixa de 0.1-0.3. Ha folga larga entre os dois.
    SIMILARITY_THRESHOLD: float = 0.75

    # Guarda-corpo anti-spam (nao configuravel pelo usuario para valores absurdos)
    MAX_POSTS_PER_DAY: int = 24
    MIN_INTERVAL_MINUTES: int = 15


settings = Settings()

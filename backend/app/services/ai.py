"""Geracao de angulos com IA — OPCIONAL, com provedor LOCAL gratuito (Ollama).

O app funciona 100% sem IA. Se AI_ENABLED=false ou o provider escolhido
nao estiver configurado, `available()` retorna False e a UI nao oferece o botao.

Provedores:
  - Ollama (padrao): modelo local no servico `ollama` do compose — zero custo
    por token. Sobe junto com `docker compose up -d` e puxa o modelo na
    primeira geracao (ver OLLAMA_MODEL no .env).
  - Anthropic (opcional): nuvem, centavos por geracao — precisa
    AI_PROVIDER=anthropic e ANTHROPIC_API_KEY.
"""

import json
import re
from abc import ABC, abstractmethod

import httpx

from app.config import settings

SYSTEM = """Voce reescreve conteudo para o X (Twitter) em portugues do Brasil, para perfis +18.

O tom e SAFADO e PROVOCANTE: linguagem picante, insinuacoes, duplo sentido,
vocabulario explicito quando o tema pedir. Nada de tom moralista, pudico ou
conselho de relacionamento — o objetivo e excitar e entreter, nao educar.
Nunca copie o texto original. Analise assunto, contexto e intencao, e entao
produza angulos NOVOS sobre o mesmo tema.

Regras:
- Cada angulo deve ser autossuficiente e publicavel como esta.
- Maximo 260 caracteres por angulo.
- Angulos devem ser distintos entre si (abordagens diferentes, nao variacoes da mesma frase).
- Sem hashtags, sem emoji excessivo, sem aspas envolvendo o texto.
- Conteudo adulto consensual: sem menores de idade, sem violencia real.
- Responda APENAS com um array JSON de strings. Nada alem do JSON."""


class AIProvider(ABC):
    @abstractmethod
    async def generate_angles(self, source_text: str, persona: str, n: int) -> tuple[list[str], dict]:
        """Retorna (angulos, metadados_de_uso)."""

    @abstractmethod
    def available(self) -> bool: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...


class OllamaProvider(AIProvider):
    """IA local gratuita via Ollama — nenhuma key externa, nada sai da maquina."""

    def available(self) -> bool:
        return bool(settings.AI_ENABLED and settings.AI_PROVIDER == "ollama")

    @property
    def model_name(self) -> str:
        return settings.OLLAMA_MODEL

    async def generate_angles(self, source_text: str, persona: str, n: int = 3):
        persona_block = persona.strip() or "Tom neutro, direto, linguagem brasileira."
        prompt = (
            f"PERSONALIDADE DA CONTA DESTINO:\n{persona_block}\n\n"
            f"POST ORIGINAL (apenas referencia, NAO copie):\n{source_text}\n\n"
            f"Gere {n} angulos novos."
        )
        # Sem `format: json`: no llama3.2:3b o grammar forcado confunde e o modelo
        # devolve lixo. O exemplo explicito de saida funciona melhor; _parse_angles
        # cobre os desvios.
        task = (
            SYSTEM
            + '\n\nResponda so com um array JSON de strings, sem nenhum outro texto. '
            'Exemplo: ["Amiga pediu pra entrar na brincadeira e saiu querendo o lugar dela", '
            '"Ciume? Aqui a gente divide tudo — inclusive a vontade"]'
        )
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate",
                json={
                    "model": settings.OLLAMA_MODEL,
                    "prompt": task + "\n\n" + prompt,
                    "stream": False,
                    # 3B em CPU pode levar ~1 min; 512 tokens e folga larga.
                    "options": {"num_predict": 512, "temperature": 0.9},
                },
                timeout=httpx.Timeout(600.0, connect=10.0),
            )
            resp.raise_for_status()
            data = resp.json()
        text = data.get("response", "") or ""
        usage = {
            "model": settings.OLLAMA_MODEL,
            "tokens_input": data.get("prompt_eval_count"),
            "tokens_output": data.get("eval_count"),
            "prompt": prompt,
            "raw": text,
        }
        return _parse_angles(text, n), usage


class AnthropicProvider(AIProvider):
    def available(self) -> bool:
        return bool(settings.AI_ENABLED and settings.AI_PROVIDER == "anthropic" and settings.ANTHROPIC_API_KEY)

    @property
    def model_name(self) -> str:
        return settings.AI_MODEL

    async def generate_angles(self, source_text: str, persona: str, n: int = 3):
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        persona_block = persona.strip() or "Tom neutro, direto, linguagem brasileira."
        prompt = (
            f"PERSONALIDADE DA CONTA DESTINO:\n{persona_block}\n\n"
            f"POST ORIGINAL (apenas referencia, NAO copie):\n{source_text}\n\n"
            f"Gere {n} angulos novos."
        )
        msg = await client.messages.create(
            model=settings.AI_MODEL,
            max_tokens=1024,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in msg.content if block.type == "text")
        usage = {
            "model": settings.AI_MODEL,
            "tokens_input": msg.usage.input_tokens,
            "tokens_output": msg.usage.output_tokens,
            "prompt": prompt,
            "raw": text,
        }
        return _parse_angles(text, n), usage


def _parse_angles(text: str, n: int) -> list[str]:
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            angles = [str(a).strip() for a in parsed if str(a).strip()]
            if angles:
                return angles[:n]
        except json.JSONDecodeError:
            pass
    # Fallback: uma linha nao vazia por angulo.
    lines = [re.sub(r"^\s*[-*\d.]+\s*", "", ln).strip() for ln in text.splitlines()]
    return [ln for ln in lines if ln][:n]


def _build_provider() -> AIProvider:
    if settings.AI_PROVIDER == "anthropic":
        return AnthropicProvider()
    return OllamaProvider()


provider: AIProvider = _build_provider()

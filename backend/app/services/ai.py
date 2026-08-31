"""Geracao de angulos com IA — OPCIONAL, com provedor LOCAL gratuito (Ollama).

O app funciona 100% sem IA. Se AI_ENABLED=false, `available()` retorna False e a
UI nao oferece geracao. Provedores:
  - Ollama (padrao): modelo local no proprio servidor — zero custo por token.
    Subir com `docker compose up -d ollama` e `docker compose exec ollama ollama
    pull qwen2.5:7b` (ou outro modelo; ver README).
  - Anthropic (opcional): nuvem, centavos por geracao — precisa ANTHROPIC_API_KEY.
"""

import json
import re
from abc import ABC, abstractmethod

import httpx

from app.config import settings

SYSTEM = """Voce reescreve conteudo para o X (Twitter) em portugues do Brasil.

Nunca copie o texto original. Analise assunto, contexto, estrutura, tom e intencao,
e entao produza angulos NOVOS sobre o mesmo tema.

Regras:
- Cada angulo deve ser autossuficiente e publicavel como esta.
- Maximo 260 caracteres por angulo.
- Angulos devem ser distintos entre si (abordagens diferentes, nao variacoes da mesma frase).
- Sem hashtags, sem emoji excessivo, sem aspas envolvendo o texto.
- Responda APENAS com um array JSON de strings. Nada alem do JSON."""


class AIProvider(ABC):
    @abstractmethod
    async def generate_angles(self, source_text: str, persona: str, n: int) -> tuple[list[str], dict]:
        """Retorna (angulos, metadados_de_uso)."""

    @abstractmethod
    def available(self) -> bool: ...


class AnthropicProvider(AIProvider):
    def available(self) -> bool:
        return bool(settings.AI_ENABLED and settings.ANTHROPIC_API_KEY)

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


class OllamaProvider(AIProvider):
    """Modelo local via servidor Ollama (http://host:11434). Zero custo por token."""

    def available(self) -> bool:
        return bool(settings.AI_ENABLED)

    async def generate_angles(self, source_text: str, persona: str, n: int = 3):
        persona_block = persona.strip() or "Tom neutro, direto, linguagem brasileira."
        prompt = (
            f"PERSONALIDADE DA CONTA DESTINO:\n{persona_block}\n\n"
            f"POST ORIGINAL (apenas referencia, NAO copie):\n{source_text}\n\n"
            f"Gere {n} angulos novos."
        )
        payload = {
            "model": settings.OLLAMA_MODEL,
            "prompt": prompt,
            "system": SYSTEM,
            "stream": False,
            "options": {"temperature": 0.8, "num_predict": 600},
        }
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate", json=payload
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Ollama indisponivel em {settings.OLLAMA_BASE_URL}: {exc}. "
                "Subiu o servico? `docker compose up -d ollama` e puxe um modelo."
            ) from exc

        text = body.get("response", "")
        usage = {
            "model": settings.OLLAMA_MODEL,
            "tokens_input": body.get("prompt_eval_count", 0),
            "tokens_output": body.get("eval_count", 0),
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

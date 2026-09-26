"""Piloto de assistente por banda, sem acesso direto a dados operacionais."""

import json
import logging
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.views import band_required

logger = logging.getLogger(__name__)
MODEL = "@cf/qwen/qwen3-30b-a3b-fp8"
MAX_MESSAGE_LENGTH = 1000
DAILY_LIMIT = 20


def extract_answer(data):
    """Aceita os formatos REST legado e Chat Completions do Workers AI."""
    if not isinstance(data, dict) or data.get("success") is False:
        raise ValueError("Unexpected AI response")
    result = data.get("result", data)
    if not isinstance(result, dict):
        raise ValueError("Unexpected AI result")
    answer = result.get("response")
    if not isinstance(answer, str):
        choices = result.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ValueError("Missing AI response")
        message = choices[0].get("message")
        answer = message.get("content") if isinstance(message, dict) else None
    if not isinstance(answer, str):
        raise ValueError("Missing AI content")
    # Alguns modelos de raciocínio incluem o bloco interno no texto.
    answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL).strip()
    if not answer or "<think>" in answer or "</think>" in answer:
        raise ValueError("Incomplete AI response")
    return answer


@login_required
@band_required
@require_POST
def ai_chat_pilot(request, band_slug):
    # Piloto para empresários da banda e administradores. Não há ferramentas
    # nem acesso a modelos, arquivos, agenda ou dados financeiros da banda.
    if not (request.user.is_superuser or request.user.is_empresario(request.band)):
        return JsonResponse({"error": "Assistente em fase de testes."}, status=403)

    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
    token = os.getenv("CLOUDFLARE_AI_TOKEN", "").strip()
    if not account_id or not token:
        return JsonResponse({"error": "Assistente ainda não configurado."}, status=503)

    if len(request.body) > 8192:
        return JsonResponse({"error": "Mensagem muito longa."}, status=400)
    try:
        body = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Mensagem inválida."}, status=400)
    if not isinstance(body, dict):
        return JsonResponse({"error": "Mensagem inválida."}, status=400)
    message = body.get("message")
    if not isinstance(message, str) or not 1 <= len(message.strip()) <= MAX_MESSAGE_LENGTH:
        return JsonResponse({"error": "Escreva uma mensagem de até 1.000 caracteres."}, status=400)

    history = body.get("history", [])
    if not isinstance(history, list) or len(history) > 6:
        return JsonResponse({"error": "Histórico inválido."}, status=400)
    safe_history = []
    for item in history:
        if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
            return JsonResponse({"error": "Histórico inválido."}, status=400)
        content = item.get("content")
        if not isinstance(content, str) or not 1 <= len(content.strip()) <= MAX_MESSAGE_LENGTH:
            return JsonResponse({"error": "Histórico inválido."}, status=400)
        safe_history.append({"role": item["role"], "content": content.strip()})

    quota_key = f"ai-chat-pilot:{request.user.pk}:{request.band.pk}:{timezone.localdate().isoformat()}"
    cache.add(quota_key, 0, timeout=86400)
    try:
        count = cache.incr(quota_key)
    except ValueError:
        cache.add(quota_key, 0, timeout=86400)
        count = cache.incr(quota_key)
    if count > DAILY_LIMIT:
        return JsonResponse({"error": "Limite diário do piloto atingido. Volte amanhã."}, status=429)

    system_prompt = (
        "Você é o Assistente Backstage Pro. Responda em português brasileiro, "
        "com clareza e brevidade. Ajude com dúvidas gerais de uso de um sistema "
        "de gestão de bandas e com rascunhos de textos de produção de shows. "
        "Você não tem acesso ao banco de dados, arquivos, agenda, contratos nem "
        "financeiro. Não invente informações sobre a banda ou ações realizadas. "
        "Não solicite senhas, CPF, dados de cartão ou dados pessoais. "
        "Não execute nem afirme ter executado alterações no sistema."
    )
    payload = json.dumps({
        "messages": [
            {"role": "system", "content": system_prompt},
            *safe_history,
            {"role": "user", "content": message.strip()},
        ],
        "max_tokens": 500,
    }).encode("utf-8")
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{MODEL}"
    upstream = Request(url, data=payload, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }, method="POST")
    try:
        with urlopen(upstream, timeout=25) as response:
            data = json.load(response)
        answer = extract_answer(data)
    except HTTPError as exc:
        if exc.code == 429:
            return JsonResponse({"error": "A franquia da IA foi atingida. Tente novamente mais tarde."}, status=429)
        logger.warning("Workers AI HTTP error: %s", exc.code)
        return JsonResponse({"error": "Assistente indisponível no momento."}, status=502)
    except (URLError, TimeoutError, OSError, ValueError, TypeError):
        logger.warning("Workers AI request failed", exc_info=True)
        return JsonResponse({"error": "Assistente indisponível no momento."}, status=502)

    return JsonResponse({"answer": answer[:3000]})

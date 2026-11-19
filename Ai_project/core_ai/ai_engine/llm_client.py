"""
llm_client.py — OpenRouter LLM Client (fixed)

What changed vs the old version:
  * NO more global 60-minute block. A 429 now blocks ONLY the model that
    returned it, for a short time (Retry-After, max 5 min).
  * On 429 / 404 / 5xx / empty answer, the client moves to the NEXT model
    automatically instead of failing the whole task.
  * Wrong or removed model slugs (404) are skipped for 1 hour, so one bad
    slug in the list can't break anything.
  * The real error body from OpenRouter is logged, so you can see the cause.
"""
from __future__ import annotations

import hashlib
import logging
import time

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

API_URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMUnavailable(Exception):
    """No model could answer: all busy / rate-limited, no API key, or the network is down."""


class LLMClient:
    CACHE_TTL = 3600 * 48          # cache identical responses for 48 h
    ROUNDS = 2                     # how many times to sweep over all models
    ROUND_PAUSE = 20               # seconds to wait between sweeps
    RATE_BLOCK_DEFAULT = 120       # seconds a model rests after a 429
    RATE_BLOCK_MAX = 300           # never rest a model longer than this
    MISSING_BLOCK = 3600           # seconds to skip a model that returned 404

    # ------------------------------------------------------------------
    # Models (order = priority). Verify slugs on openrouter.ai/models (Free).
    # A wrong slug is harmless: it gets a 404 and is skipped.
    # ------------------------------------------------------------------
    @staticmethod
    def get_available_free_models() -> list[dict]:
        return [
            # the model our evaluation (CASCADE / NPM) was measured with — kept first on purpose
            {"model": "poolside/laguna-s-2.1:free", "name": "Poolside Laguna S 2.1",
             "description": "Coding agent (evaluation model)", "context": "262K tokens"},
            # (18/11/2026: no longer listed on OpenRouter; kept for the record. It returns 404 and
            #  rests for an hour, so it costs one failed request per hour.)
            # the models below were checked against openrouter.ai/api/v1/models on 18/11/2026
            {"model": "cohere/north-mini-code:free", "name": "Cohere North Mini Code",
             "description": "Coding (the one that answered in our runs)", "context": "256K tokens"},
            {"model": "google/gemma-4-31b-it:free", "name": "Gemma 4 31B",
             "description": "Dense, strong at coding & reasoning", "context": "262K tokens"},
            {"model": "google/gemma-4-26b-a4b-it:free", "name": "Gemma 4 26B A4B",
             "description": "Fast MoE", "context": "262K tokens"},
            # not tried yet: fallbacks only
            {"model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", "name": "Nemotron 3 Nano Omni 30B",
             "description": "General purpose (new name of nemotron-3-nano-omni)", "context": "256K tokens"},
            {"model": "nvidia/nemotron-3-ultra-550b-a55b:free", "name": "Nemotron 3 Ultra 550B",
             "description": "General purpose, large", "context": "1M tokens"},
        ]

    @staticmethod
    def get_current_model() -> str:
        return cache.get("current_llm_model") or LLMClient.get_available_free_models()[0]["model"]

    @staticmethod
    def switch_model(model_name: str) -> dict:
        valid = [m["model"] for m in LLMClient.get_available_free_models()]
        if model_name not in valid:
            raise ValueError(f"Invalid model. Available: {valid}")
        cache.set("current_llm_model", model_name, 3600)
        logger.info(f"[LLM] Switched to model: {model_name}")
        return {"status": "success", "model": model_name}

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _cache_key(system_prompt: str, user_prompt: str) -> str:
        digest = hashlib.md5(f"{system_prompt}|{user_prompt}".encode()).hexdigest()
        return f"llm_response_{digest}"

    @staticmethod
    def _get_cached(key: str):
        try:
            return cache.get(key)
        except Exception as e:
            logger.warning(f"[LLM Cache] get error: {e}")
            return None

    @staticmethod
    def _set_cached(key: str, value: str) -> None:
        try:
            cache.set(key, value, LLMClient.CACHE_TTL)
        except Exception as e:
            logger.warning(f"[LLM Cache] set error: {e}")

    # ------------------------------------------------------------------
    # Per-model block helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _block_model(model: str, seconds: int) -> None:
        cache.set(f"llm_block_{model}", time.time() + seconds, seconds)
        logger.warning(f"[LLM] Model {model} rests for {seconds}s")

    @staticmethod
    def _block_remaining(model: str) -> float:
        until = cache.get(f"llm_block_{model}")
        return max(0.0, until - time.time()) if until else 0.0

    @staticmethod
    def clear_blocks() -> None:
        for m in LLMClient.get_available_free_models():
            cache.delete(f"llm_block_{m['model']}")

    @staticmethod
    def _ordered_models(preferred: str | None) -> list[str]:
        models = [m["model"] for m in LLMClient.get_available_free_models()]
        first = preferred or LLMClient.get_current_model()
        if first in models:
            models.remove(first)
        return [first] + models

    @staticmethod
    def _retry_after(response) -> int:
        try:
            value = int(float(response.headers.get("Retry-After", "")))
        except (TypeError, ValueError):
            value = LLMClient.RATE_BLOCK_DEFAULT
        return max(10, min(value, LLMClient.RATE_BLOCK_MAX))

    # ------------------------------------------------------------------
    # Main call
    # ------------------------------------------------------------------
    @staticmethod
    def call_model(
        system_prompt: str,
        user_prompt: str,
        use_cache: bool = True,
        force_request: bool = False,   # True = ignore per-model rests
        model: str | None = None,
        temperature: float = 0.7,
    ) -> str:
        cache_key = LLMClient._cache_key(system_prompt, user_prompt) if use_cache else ""
        if use_cache:
            cached = LLMClient._get_cached(cache_key)
            if cached:
                logger.info("[LLM Cache] HIT")
                return cached

        content, _model, _usage = LLMClient._sweep(
            system_prompt, user_prompt,
            force_request=force_request, model=model, temperature=temperature, max_tokens=4000,
        )
        if use_cache:
            LLMClient._set_cached(cache_key, content)
        return content

    @staticmethod
    def call_model_ex(
        system_prompt: str,
        user_prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4000,
        force_request: bool = False,
    ) -> dict:
        """Like call_model, but also says which model answered and what it cost.

        Returns {"text", "model", "prompt_tokens", "completion_tokens"}. It does not use the
        48-hour answer cache: callers that need reuse keep their own record of answers.
        """
        content, used_model, usage = LLMClient._sweep(
            system_prompt, user_prompt,
            force_request=force_request, model=model, temperature=temperature, max_tokens=max_tokens,
        )
        return {
            "text": content,
            "model": used_model,
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
        }

    @staticmethod
    def _sweep(
        system_prompt: str,
        user_prompt: str,
        *,
        force_request: bool = False,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> tuple:
        """One request, swept over the model list. → (text, model, usage dict)."""
        api_key = getattr(settings, "OPENROUTER_API_KEY", None)
        if not api_key:
            raise LLMUnavailable("OPENROUTER_API_KEY missing in settings.")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "Software Documentation Agent",
            "HTTP-Referer": "http://localhost:8000",
        }
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        candidates = LLMClient._ordered_models(model)
        last_error = "no model tried"

        for round_no in range(LLMClient.ROUNDS):
            tried_any = False

            for current_model in candidates:
                if not force_request and LLMClient._block_remaining(current_model) > 0:
                    continue
                tried_any = True

                payload = {
                    "model": current_model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }
                logger.info(f"[LLM] round={round_no + 1} model={current_model}")

                try:
                    resp = requests.post(API_URL, headers=headers, json=payload, timeout=120)
                except requests.exceptions.RequestException as exc:
                    last_error = f"Network error on {current_model}: {exc}"
                    logger.error(f"[LLM] {last_error}")
                    time.sleep(2)
                    continue

                if resp.status_code == 429:
                    wait = LLMClient._retry_after(resp)
                    LLMClient._block_model(current_model, wait)
                    last_error = f"429 on {current_model}: {resp.text[:300]}"
                    logger.warning(f"[LLM] {last_error}")
                    time.sleep(1)
                    continue            # -> next model

                if resp.status_code == 404:
                    LLMClient._block_model(current_model, LLMClient.MISSING_BLOCK)
                    last_error = f"404 on {current_model}: {resp.text[:300]}"
                    logger.warning(f"[LLM] {last_error}")
                    continue            # -> next model

                if resp.status_code == 400:
                    last_error = f"400 on {current_model}: {resp.text[:300]}"
                    if "not a valid model id" in resp.text.lower():
                        # the model was removed or renamed: skip it like a 404
                        LLMClient._block_model(current_model, LLMClient.MISSING_BLOCK)
                        logger.warning(f"[LLM] {last_error}")
                        continue        # -> next model
                    # any other 400 is usually caused by the request itself (e.g. prompt too long),
                    # not by the model, so don't rest the model — just try the next one.
                    logger.warning(f"[LLM] {last_error}")
                    continue            # -> next model

                if resp.status_code != 200:
                    last_error = f"HTTP {resp.status_code} on {current_model}: {resp.text[:300]}"
                    logger.error(f"[LLM] {last_error}")
                    time.sleep(2)
                    continue

                try:
                    data = resp.json()
                    content = (data.get("choices") or [{}])[0].get("message", {}).get("content")
                    usage = data.get("usage") or {}
                except ValueError:
                    content, usage = None, {}

                if not content or not content.strip():
                    last_error = f"Empty answer from {current_model}"
                    logger.warning(f"[LLM] {last_error}")
                    continue

                logger.info(f"[LLM] Success with {current_model}")
                return content, current_model, usage if isinstance(usage, dict) else {}

            # finished a sweep over all models
            if round_no < LLMClient.ROUNDS - 1:
                pause = LLMClient.ROUND_PAUSE
                logger.info(f"[LLM] All models busy, waiting {pause}s before next sweep"
                            f"{'' if tried_any else ' (all were resting)'}")
                time.sleep(pause)

        raise LLMUnavailable(
            f"All free models are busy or rate-limited. Try again in a few minutes. "
            f"Last error: {last_error}"
        )

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------
    @staticmethod
    def get_rate_limit_info() -> dict:
        try:
            api_key = getattr(settings, "OPENROUTER_API_KEY", None)
            if not api_key:
                return {"error": "API Key missing"}
            resp = requests.get(
                "https://openrouter.ai/api/v1/auth/key",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            )
            return resp.json() if resp.status_code == 200 else {"error": resp.text}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def test_model_connection() -> dict:
        try:
            result = LLMClient.call_model(
                "You are a helpful assistant.",
                "Respond with 'OK' only.",
                use_cache=False,
                force_request=True,
                temperature=0.0,
            )
            return {"status": "success", "response": result.strip()}
        except Exception as e:
            return {"status": "error", "error": str(e)}

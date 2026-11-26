# evaluation/harness/llm_recorder.py
"""
LLM client حتمي لتشغيل التقييم (البند 9).

بديل لـ core_ai.ai_engine.llm_client.LLMClient بنفس توقيع call_model، بس:
- temperature = 0 و seed ثابت دايماً (بيتجاهل القيمة الممررة)
- بدون cache نهائياً (بيتجاهل use_cache)
- موديل مثبّت واحد، بدون model rotation (الـ client الأصلي بيستخدم
  "openrouter/free" يلي بيختار موديل عشوائي، فما في تكرار للنتائج)
- كل استدعاء بيتسجّل: الموديل المطلوب، الموديل يلي فعلياً ردّ، الرد الخام
  (فيه الـ confidence الخام)، الـ usage، والزمن
- بدون Django — بياخد المفتاح من OPENROUTER_API_KEY

الاستخدام:
    LLMClient.configure(model="meta-llama/llama-3.3-70b-instruct:free")
    LLMClient.start_sample("case_001")
    ... شغّل الكود ...
    calls = LLMClient.pop_sample_calls()
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

_ENV_FILES = (Path(__file__).resolve().parents[3] / ".env", Path(__file__).resolve().parents[2] / ".env")


def _api_key(name: str) -> Optional[str]:
    """المتغير من البيئة، وإلا من ملف .env (جذر المشروع أو Ai_project)."""
    if os.environ.get(name):
        return os.environ[name]
    for env in _ENV_FILES:
        if env.is_file():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith(f"{name}="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    return None

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# مزوّد غير OpenRouter: الموديل بيتكتب "<مزوّد>:<موديل>"، مثلاً "orcarouter:z-ai/glm-5.3-flash-free".
# (OpenRouter شال موديلنا المجاني cohere/north-mini-code، و GLM-5.3-Flash مجاني على OrcaRouter.)
PROVIDERS: Dict[str, Dict[str, str]] = {
    "openrouter": {"url": OPENROUTER_URL, "key_env": "OPENROUTER_API_KEY"},
    "orcarouter": {"url": "https://api.orcarouter.ai/v1/chat/completions", "key_env": "ORCAROUTER_API_KEY"},
}


def split_model(model: Optional[str]) -> tuple:
    """'orcarouter:z-ai/x' → ('orcarouter', 'z-ai/x')؛ بدون بادئة → OpenRouter."""
    prefix, sep, rest = (model or "").partition(":")
    if sep and prefix in PROVIDERS and "/" in rest:
        return prefix, rest
    return "openrouter", model


class LLMCallError(Exception):
    pass


class LLMClient:
    model: Optional[str] = None
    seed: int = 42
    max_tokens: int = 4000
    # موديلات "بتفكّر" قبل ما تجاوب: التفكير بيصرف من نفس الحد، وبـ 4000 بيخلص قبل الجواب
    # (cohere: حوالي 14 ألف token تفكير على طلب CASCADE واحد → جواب فاضي، finish = length)
    MAX_TOKENS_BY_MODEL: Dict[str, int] = {"cohere/north-mini-code:free": 16000,
                                           "orcarouter:z-ai/glm-5.3-flash-free": 16000}
    # بارامترات إضافية لموديل معيّن: GLM بيدعم "JSON مضمون"، وهيك ما بيكسر الجواب بكلام زيادة
    EXTRA_BY_MODEL: Dict[str, Dict[str, Any]] = {
        "orcarouter:z-ai/glm-5.3-flash-free": {"response_format": {"type": "json_object"}},
    }
    transport_retries: int = 3          # أخطاء شبكة / 429 / 5xx فقط — نفس الموديل
    offline: bool = False               # True → أي استدعاء بيفشل (لتشغيل الأجزاء الحتمية بس)
    daily_limit_hit: bool = False       # True بعد أول رفض "free-models-per-day" → الباقي بيفشل فوراً

    _current_sample: Optional[str] = None
    _calls: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    model_info: Optional[Dict[str, Any]] = None

    @classmethod
    def configure(cls, model: Optional[str], seed: int = 42, offline: bool = False,
                  allow_free: bool = False) -> None:
        cls.model, cls.seed, cls.offline, cls.model_info = model, seed, offline, None
        cls.max_tokens = cls.MAX_TOKENS_BY_MODEL.get(model or "", 4000)
        if offline:
            return
        if not model:
            raise ValueError("لازم تحدد موديل مثبّت (مش openrouter/free) لتكون النتائج قابلة للتكرار")
        if model.startswith("openrouter/"):
            raise ValueError(f"{model} راوتر بيختار موديل متغيّر — اختار موديل محدد")
        # موديل مجاني محدد مسموح (قرار المشروع) — الممنوع بس الراوتر يلي بيبدّل الموديل.
        # الموديلات المجانية ممكن تختفي، فمنسجّل نسختها ومنحفظ كل رد خام.
        provider, api_model = split_model(model)
        if provider == "openrouter":
            cls.model_info = cls._fetch_model_info(model)
        else:
            cls.model_info = {"id": api_model, "provider": provider,
                              "fetched_at": datetime.now(timezone.utc).isoformat()}

    @staticmethod
    def _fetch_model_info(model: str) -> Dict[str, Any]:
        """اسم الموديل ونسخته (canonical_slug) من كتالوج OpenRouter — جزء من شروط التجربة."""
        resp = requests.get("https://openrouter.ai/api/v1/models", timeout=60)
        resp.raise_for_status()
        for m in resp.json().get("data", []):
            if m.get("id") == model:
                return {
                    "id": m.get("id"),
                    "canonical_slug": m.get("canonical_slug"),   # فيه تاريخ النسخة
                    "name": m.get("name"),
                    "created": m.get("created"),
                    "context_length": m.get("context_length"),
                    "pricing": m.get("pricing"),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
        raise ValueError(f"الموديل {model} مش موجود بكتالوج OpenRouter")

    @classmethod
    def start_sample(cls, sample_id: str) -> None:
        cls._current_sample = sample_id
        cls._calls = []

    @classmethod
    def pop_sample_calls(cls) -> List[Dict[str, Any]]:
        calls, cls._calls = cls._calls, []
        return calls

    # ------------------------------------------------------------------
    @classmethod
    def call_model(
        cls,
        system_prompt: str,
        user_prompt: str,
        use_cache: bool = True,          # متجاهَل عن قصد
        force_request: bool = False,     # متجاهَل
        model: str | None = None,        # متجاهَل — الموديل المثبّت بس
        temperature: float = 0.7,        # متجاهَل — دايماً 0
        **_: Any,
    ) -> str:
        record: Dict[str, Any] = {
            "sample_id": cls._current_sample,
            "requested_model": cls.model,
            "requested_temperature": temperature,
            "temperature": 0.0,
            "seed": cls.seed,
            "prompt_chars": len(system_prompt) + len(user_prompt),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        cls._calls.append(record)

        if cls.offline:
            record.update(ok=False, error="offline mode")
            raise LLMCallError("offline mode")
        if cls.daily_limit_hit:
            # خلص الحد اليومي: ما في داعي ننطر ونعيد — كل طلب رح ينرفض لبكرا
            record.update(ok=False, error="daily free limit reached (skipped)")
            raise LLMCallError("daily free limit reached")

        provider, api_model = split_model(cls.model)
        url, key_env = PROVIDERS[provider]["url"], PROVIDERS[provider]["key_env"]
        api_key = _api_key(key_env)
        if not api_key:
            record.update(ok=False, error=f"{key_env} missing")
            raise LLMCallError(f"{key_env} missing")

        payload = {
            "model": api_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": cls.max_tokens,
            "temperature": 0.0,
            "seed": cls.seed,
            **cls.EXTRA_BY_MODEL.get(cls.model or "", {}),
        }
        if provider == "openrouter":
            # ممنوع الـ fallback لموديل تاني من جهة OpenRouter
            payload["provider"] = {"allow_fallbacks": False}
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "ATDG evaluation harness",
        }

        t0 = time.time()
        last_error = ""
        for attempt in range(1, cls.transport_retries + 1):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=180)
                # حد يومي نهائي (OpenRouter بس). OrcaRouter free_rate_limited = ازدحام مؤقت: بينعاد
                if resp.status_code == 429 and "free-models-per-day" in resp.text:
                    cls.daily_limit_hit = True
                    record.update(ok=False, error=f"HTTP 429 daily limit: {resp.text[:200]}")
                    raise LLMCallError("daily free limit reached")
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                    time.sleep((30 if "free_rate_limited" in resp.text else 10) * attempt)
                    continue
                if resp.status_code != 200:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                    break
                body = resp.json()
                choices = body.get("choices") or []
                content = choices[0]["message"]["content"] if choices else None
                record.update(
                    ok=bool(content),
                    transport_attempts=attempt,
                    served_model=body.get("model"),
                    provider=body.get("provider"),
                    usage=body.get("usage"),
                    raw_response=content,
                    latency_s=round(time.time() - t0, 2),
                )
                if not content:
                    record["error"] = "empty choices/content"
                return content
            except requests.exceptions.RequestException as exc:
                last_error = f"network: {exc}"
                time.sleep(5 * attempt)

        record.update(ok=False, error=last_error, latency_s=round(time.time() - t0, 2))
        raise LLMCallError(last_error)

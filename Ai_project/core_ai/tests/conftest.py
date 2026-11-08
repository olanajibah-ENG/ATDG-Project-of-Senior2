import pytest

from core_ai.ai_engine.llm_client import LLMClient


def _blocked(*args, **kwargs):
    raise ConnectionError("real LLM calls are blocked in tests")


@pytest.fixture(autouse=True)
def _no_real_llm_in_tests(monkeypatch):
    """الاختبارات ما بتستدعي الـ LLM الحقيقي أبداً (ولا بتصرف من الحد اليومي):
    - CODE_DOC_LLM_ENABLED=0 للكود مقابل التوثيق، و BEHAVIOR_LLM_ENABLED=0 لـ Code vs Code (الخطوة 11)
    - أي LLMClient.call_model حقيقي بيفشل فوراً (متل Code vs Code لما بيمرق بـ SemanticAnalyzer)
    يلي بدو يختبر التحليل الدلالي بيعمل monkeypatch لـ LLMClient.call_model بأجوبة مكتوبة بإيده،
    وهاد بيتغلّب على هالحظر لأنه بيصير بعده."""
    monkeypatch.setenv("CODE_DOC_LLM_ENABLED", "0")
    monkeypatch.setenv("BEHAVIOR_LLM_ENABLED", "0")
    monkeypatch.setattr(LLMClient, "call_model", staticmethod(_blocked))

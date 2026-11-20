"""
رابط GET /api/analysis/analysis-results/:
- بشكل افتراضي بيرجّع آخر تحليل بس لكل ملف.
- مع ?history=true بيرجّع كل السجلات، الأحدث أول.

ملف بينعاد تحليله بيصير إلو أكتر من سجل. الفرونت بياخد results[0] (DocumentGenerationPage.tsx و
FileViewer.tsx)، و ProjectTree.tsx بياخد آخر سجل لكل ملف. بسجل واحد لكل ملف، التنين بياخدوا الأحدث.

    python -m pytest core_ai/tests/test_analysis_results_order.py -q
"""
import os
from datetime import datetime

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Ai_project.settings")
import django  # noqa: E402

django.setup()

from bson import ObjectId  # noqa: E402
from rest_framework.test import APIRequestFactory  # noqa: E402

from core_ai.views.analysis import AnalysisResultViewSet  # noqa: E402

FILE = ObjectId("6afca9e0fea0f5429af8553e")
OTHER = ObjectId("6afca902fea0f5429af8552d")


class FakeCursor:
    """Enough of a pymongo cursor: sort() with (key, direction) pairs, missing values lowest."""

    def __init__(self, docs):
        self.docs = docs

    def sort(self, keys):
        for key, direction in reversed(keys):
            present = [d for d in self.docs if d.get(key) is not None]
            missing = [d for d in self.docs if d.get(key) is None]
            present.sort(key=lambda d: d[key], reverse=direction < 0)
            self.docs = present + missing if direction < 0 else missing + present
        return self

    def __iter__(self):
        return iter(self.docs)


class FakeCollection:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query):
        return FakeCursor([dict(d) for d in self.docs
                           if all(d.get(k) == v for k, v in query.items())])


def result(oid, file_id, when, warning=None):
    return {"_id": ObjectId(oid), "code_file_id": file_id, "status": "COMPLETED",
            "analysis_started_at": when, "analysis_completed_at": when,
            "semantic_analysis_data": {"warnings": [warning] if warning else []}}


# inserted in this order: the old one first, as in the real database
DOCS = [
    result("6afca9e02fba2d75ba3ebeda", FILE, datetime(2026, 11, 17, 19, 24), "AUTO-FIXED"),
    result("6afca9e12fba2d75ba3ebedb", OTHER, datetime(2026, 11, 17, 19, 25)),
    result("6afdf23e48727ce7e11090ee", FILE, datetime(2026, 11, 18, 18, 45)),
]


def call(monkeypatch, docs, **params):
    monkeypatch.setattr(AnalysisResultViewSet, "get_collection", lambda self: FakeCollection(docs))
    request = APIRequestFactory().get("/api/analysis/analysis-results/", params)
    response = AnalysisResultViewSet.as_view({"get": "list"})(request)
    assert response.status_code == 200
    return response.data["results"]


def test_a_file_returns_only_its_latest_result(monkeypatch):
    results = call(monkeypatch, DOCS, code_file_id=str(FILE))
    assert [r["id"] for r in results] == ["6afdf23e48727ce7e11090ee"]
    assert results[0]["semantic_analysis_data"]["warnings"] == []


def test_history_returns_every_result_newest_first(monkeypatch):
    results = call(monkeypatch, DOCS, code_file_id=str(FILE), history="true")
    assert [r["id"] for r in results] == ["6afdf23e48727ce7e11090ee", "6afca9e02fba2d75ba3ebeda"]


def test_last_one_per_file_is_also_the_latest(monkeypatch):
    # ProjectTree.tsx keeps the LAST result it sees for each file: with one per file that is the latest.
    results = call(monkeypatch, DOCS)
    last = {}
    for r in results:
        last[r["code_file_id"]] = r["id"]
    assert last[str(FILE)] == "6afdf23e48727ce7e11090ee"


def test_filter_still_returns_only_that_file(monkeypatch):
    results = call(monkeypatch, DOCS, code_file_id=str(OTHER))
    assert [r["id"] for r in results] == ["6afca9e12fba2d75ba3ebedb"]


def test_list_without_filter_returns_latest_of_each_file(monkeypatch):
    results = call(monkeypatch, DOCS)
    assert [r["id"] for r in results] == ["6afdf23e48727ce7e11090ee", "6afca9e12fba2d75ba3ebedb"]


def test_list_without_filter_with_history_is_newest_first(monkeypatch):
    results = call(monkeypatch, DOCS, history="true")
    assert [r["id"] for r in results] == [
        "6afdf23e48727ce7e11090ee", "6afca9e12fba2d75ba3ebedb", "6afca9e02fba2d75ba3ebeda"]


def test_result_without_completion_time_goes_last(monkeypatch):
    docs = DOCS + [{"_id": ObjectId("6afdf23e48727ce7e11090ff"), "code_file_id": FILE, "status": "PENDING"}]
    results = call(monkeypatch, docs, code_file_id=str(FILE), history="true")
    assert results[-1]["id"] == "6afdf23e48727ce7e11090ff"
    assert results[0]["id"] == "6afdf23e48727ce7e11090ee"

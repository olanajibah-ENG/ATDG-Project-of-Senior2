"""
اختبارات تنظيف كود بايثون قبل التحليل (_normalize_python_code).

الخطأ يلي انصلّح: لستة "الرموز الغريبة" كان فيها '__' العادية نفسها، فأي ملف فيه
__init__ كان ينحسب إنو انصلّح أوتوماتيكياً (was_modified=True) وبيطلع تحذير بينقّص التقييم.

    python -m pytest core_ai/tests/test_python_normalization.py -q
"""
from core_ai.language_processors.python_processor import PythonProcessor

CLEAN = (
    "class Course:\n"
    "    def __init__(self, title: str):\n"
    "        self.title = title\n"
    "\n"
    "    def __repr__(self):\n"
    "        return self.title\n"
)


def normalize(code):
    return PythonProcessor()._normalize_python_code(code)


def test_clean_code_with_dunder_methods_is_not_marked_as_fixed():
    result = normalize(CLEAN)
    assert result["fixes_applied"] == []
    assert result["was_modified"] is False
    assert result["normalized_code"] == CLEAN


def test_parse_of_clean_code_reports_no_auto_fix():
    parsed = PythonProcessor().parse_source_code(CLEAN)
    flat = repr(parsed)
    assert "weird underscores" not in flat


def test_en_dash_pair_is_still_fixed():
    result = normalize("class A:\n    def \u2013\u2013init\u2013\u2013(self):\n        pass\n")
    assert "def __init__(self)" in result["normalized_code"]
    assert result["was_modified"] is True
    assert any("weird underscores" in f for f in result["fixes_applied"])


def test_em_dash_pair_is_still_fixed():
    result = normalize("class A:\n    def \u2014\u2014init\u2014\u2014(self):\n        pass\n")
    assert "def __init__(self)" in result["normalized_code"]
    assert result["was_modified"] is True


def test_init_without_underscores_is_still_fixed():
    result = normalize("class A:\n    def init(self):\n        pass\n")
    assert "def __init__(self" in result["normalized_code"]
    assert any("'init'" in f for f in result["fixes_applied"])

# S2: القيمة الافتراضية كانت توصل للنموذج كنص

التاريخ: 19/11/2026

## المشكلة

بتجربة Postman (`job_8fb2c99e2ca4`)، الاختبار المولّد لـ `Course.__init__` كان فيه:

```python
course = Course(title)
# default capacity is "2" (string) per context
assert course.capacity == "2"
```

الكود الأصلي `capacity: int = 2`، فالاختبار كان رح يفشل. والنموذج كاتب السبب: "per context". الـ context كان:

- التوقيع `__init__(title: str, capacity: int)`: بدون القيمة الافتراضية.
- الباراميتر `{"name": "capacity", "type": "int", "default": "2"}`: القيمة مخزّنة ككود (`ast.unparse`)، بس
  وصلت بـ JSON كأنها نص.

## التعديل

`core_ai/services/test_generation/context.py`:

- التوقيع صار يتبنى من الباراميترات المخزّنة، مع القيم الافتراضية و `self` / `cls` و `*` و `/` و `async`
  ونوع الرجوع: `__init__(self, title: str, capacity: int = 2)`. بينطبق على الوحدة نفسها، وعلى باني الكلاس،
  وعلى توقيعات الـ callees. إذا التحليل القديم ما فيه باراميترات، بيضل التوقيع المخزّن.
- الحقل `default` صار اسمه `default_code`، وفي تعليق إنو كود بايثون (`"2"` = الرقم 2، `"'2'"` = النص).

`core_ai/services/test_generation/prompts/unit.py`:

- قاعدة جديدة: التوقيعات و `default_code` كود بايثون، `capacity: int = 2` يعني الرقم 2 مش النص "2".
- `PROMPT_VERSION` صار `unit-v2`، فالأجوبة المحفوظة تحت `unit-v1` (يلي فيها الغلط) ما بترجع تنستعمل.

## الاختبارات

`core_ai/tests/test_generation/test_context.py` (6 جداد):

| الاختبار | شو بيفحص |
|---|---|
| `test_signature_carries_default_values_as_code` | `__init__(self, title: str, capacity: int = 2, tag='new', *names, limit=None, **extra)` |
| `test_default_code_is_python_source_not_a_plain_string` | `"2"` للرقم، `"'new'"` للنص، `None` بدون قيمة |
| `test_class_constructor_signature_has_the_defaults` | توقيع الباني بالـ context فيه `capacity: int = 2` |
| `test_static_class_and_async_methods` | `make(...)` بدون self، `empty(cls, ...)`، `async load(self, ...)` |
| `test_positional_only_marker_for_a_module_function` | `pair(a, b=1, /, c=2)` |
| `test_prompt_says_defaults_are_code_and_version_moved` | القاعدة موجودة و `unit-v2` |

على الكود القديم: 8 فشلوا. بعد التعديل: **545 passed**.

## تجربة حقيقية

`job_b3bcc1a6681b`، النسخة 10، `demo/course.py` بس، مستوى `unit`، نفس النموذج (`cohere/north-mini-code:free`):
3 وحدات، 3 `generated`، `prompt_version: unit-v2`. اختبار `Course.__init__` صار:

```python
def test_Course___init____unit_1():
    # Test with default capacity
    course = Course("Python Basics")
    assert course.title == "Python Basics"
    assert course.capacity == 2
    assert course.students == []
```

## الدرس

الفحص بـ S2 بيضمن الشكل والأمان، مش الصحة: الاختبار الغلط مرّ من كل الفحوص. لقيناه بالقراءة، وكان
رح يبيّن بالتشغيل بـ S3. وغلط بالـ context بيطلع غلط بالاختبار، فالـ context لازم يكون دقيق متل الكود.

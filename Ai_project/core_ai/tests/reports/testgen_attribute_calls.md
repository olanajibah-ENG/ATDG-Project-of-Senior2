# ربط استدعاءات الخصائص (`self.engine.start()`) بالـ graph تبع الاختبارات

التاريخ: 18/11/2026

## المشكلة

```python
class Car:
    def __init__(self, ...):
        self.engine = Engine(horsepower, fuel_type)
        self.gps = GPS()
        self.driver = None

    def assign_driver(self, driver: Driver):
        self.driver = driver

    def drive(self):
        self.driver.introduce()
        self.engine.start()
        self.gps.locate()
```

الربط كان يقرا كل ميثود لحالها. لما يقرا `drive` ما بيعرف نوع `self.engine`، لأنو النوع انكتب بـ
`__init__`. فـ `drive` كانت تطلع بالـ graph بدون ولا سهم لميثودات المشروع، وتوليد الاختبارات ما بيعرف
إنها بتعتمد على `Engine.start` و `GPS.locate` و `Driver.introduce`، فما رح يعرف شو لازم يعمل mock بـ S6.

graph الشرح كمان ما بيربط هالاستدعاءات، بس **ما لمسناه**. التعديل جوّا ميزة الاختبارات بس.

## الحل

الملف: `core_ai/services/test_generation/graphify/resolver.py`

**1. جدول أنواع لخصائص كل كلاس** (`_attribute_types`). منمرق على كل ميثودات الكلاس:

| الكود | منستنتج |
|---|---|
| `self.engine = Engine(...)` | `engine` ← `Engine` |
| `self.driver = driver` و `driver: Driver` | `driver` ← `Driver` |
| `spare = Radio()` ثم `self.spare = spare` | `spare` ← `Radio` |
| `self.gauge: Battery = ...` | `gauge` ← `Battery` |
| `self.radio = None` | ما بيغيّر شي |

**2. حالة جديدة وقت الربط:** `self.X.m()` ← نوع `X` من الجدول، ومندوّر على `m` بالكلاس تبعه وبأهله.

**3. قواعد الأمان** (ربط غلط أسوأ من ما في ربط):
- خاصية انعطت كلاسين مختلفين ← ما بتنربط.
- خاصية قيمتها ما منعرف نوعها، متل `self.log = make_logger()` ← ما بتنربط.
- كلاسات المشروع بس.
- الكلاس الابن بيورث جدول أبوه.
- مستوى واحد بس: `self.a.b.m()` ما بينربط.

ونقلنا قراءة الجسم وأنواع المتغيّرات المحلية لدوال صغيرة (`_parse_body`، `_local_types`) لأنو الجدول
والربط صاروا يستعملوها التنين. سلوك الربط القديم ما تغيّر.

## الاختبارات

ملف مصدر جديد: `core_ai/tests/test_generation/fixtures/sources/attributes.py` فيه كل الحالات،
ونسخة من `task.py` الحقيقي: `fixtures/sources/task.py`. التحليل بينعمل بالمحلّل الحقيقي متل باقي الاختبارات.

9 اختبارات جديدة بـ `core_ai/tests/test_generation/test_graphify_resolver.py`:

| الاختبار | شو بيفحص |
|---|---|
| `test_attribute_set_from_a_constructor_is_linked` | `self.engine = Engine()` ← `Car.drive → Engine.start` |
| `test_attribute_set_from_a_typed_parameter_or_local_variable_or_annotation` | باراميتر عليه نوع، ومتغيّر محلي، و annotation |
| `test_none_says_nothing_and_a_later_typed_value_counts` | `None` بـ `__init__` وبعدين `radio: Radio` بميثود تانية |
| `test_two_different_classes_or_an_unknown_value_are_never_linked` | `self.part` كلاسين، و `self.log = make_logger()` ← ولا سهم |
| `test_attribute_set_in_the_parent_class_is_inherited` | `SportsCar.race` بتستعمل خاصية من `Car`، و `self.missing` ما بتنربط |
| `test_method_of_the_attribute_class_is_found_on_its_parent` | `self.engine = TurboEngine()` ← `start` من `Engine` الأب |
| `test_two_levels_deep_is_not_linked` | `self.engine.owner.start()` ← ولا سهم |
| `test_real_task_file_drive_reaches_engine_gps_and_driver` | `task.py` الحقيقي: الأسهم التلاتة |
| `test_attribute_graph_is_still_well_formed` | كل سهم طرفيه عقد، وما في أسهم مكررة |

**على الكود القديم:** 7 فشلوا. الاختبارين يلي بيفحصوا إنو ما في ربط (مستويين، وصحة شكل الـ graph)
نجحوا، وهاد متوقّع لأنو الكود القديم ما كان يربط شي أصلاً.

**بعد التصليح (بالـ Docker):**

```
python -m pytest core_ai/tests test_graphify_implementation.py -q
500 passed
```

## على البيانات الحقيقية

بعد `docker compose restart ai_web celery_worker`، استخرجنا الـ graph من القاعدة من جديد:

| الحالة | استدعاءات جوّا المشروع بالـ graph تبع الاختبارات |
|---|---|
| demo3 v1 / v2 / v3 | 4 / 5 / 2 (ما تغيّرت، ما فيها استدعاءات خصائص) |
| task_test | **5** بدل 2 |

استدعاءات `task_test` هلق:

```
Car.__init__ → Engine.__init__
Car.__init__ → GPS.__init__
Car.drive    → Engine.start        ← جديد
Car.drive    → GPS.locate          ← جديد
Car.drive    → Driver.introduce    ← جديد
```

صفحة المقارنة `docs/graph_compare.html` انبنت من جديد بهالبيانات: بتبويب `task_test` الأسهم التلاتة
الجديدة بتطلع برتقالي (موجودة بالاختبارات بس).

## شو ما بيغطّي

- أكتر من مستوى: `self.a.b.m()`.
- خاصية بتنحط من برّا الكلاس: `car.engine = Engine()`.
- لستات و dicts: `self.wheels[0].spin()`.
- خاصية معرّفة بجسم الكلاس (`engine: Engine` برّا الميثودات)، لأنها مش موجودة بالتحليل المخزّن.

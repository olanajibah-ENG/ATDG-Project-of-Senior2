# تصليح: كل ملف فيه `__init__` كان ينحسب إنو "انصلّح أوتوماتيكياً"

التاريخ: 18/11/2026

## المشكلة

بخرج `analysis-results` لملف `demo/course.py` (كود سليم تماماً) طلع:

```json
"normalization_fixes": ["Fixed weird underscores: '__' → '__'"],
"was_auto_fixed": true,
"warnings": ["⚠️ AUTO-FIXED: Fixed weird underscores: '__' → '__'"],
"quality_score": 97.2
```

يعني النظام قال إنو صلّح الكود، مع إنو ما كان فيه شي غلط.

## السبب

بـ `core_ai/language_processors/python_processor.py`، دالة `_normalize_python_code` بتدوّر على رموز
بتشبه الشرطتين (`––` و `——`) وبتبدّلها بـ `__`. بس اللستة كان فيها كمان `'__'` العادية نفسها:

```python
weird_underscores = ['––', '——', '––', '__']
```

فأي ملف فيه `__init__` أو `__repr__` أو أي ميثود خاصة كان يطابق، وينحسب إنو انصلّح.

**الأثر:**
- `was_auto_fixed` و `was_code_modified` كانوا `true` لكل ملف بايثون فيه كلاس تقريباً.
- بينضاف تحذير `AUTO-FIXED` لـ `semantic_analysis_data.warnings`، والتحذير بينقّص `quality_score`.
- الكود نفسه ما كان يتغيّر، لأنو التبديل كان `'__'` بـ `'__'`.

## التصليح

سطر واحد: شلنا `'__'` من اللستة.

```python
weird_underscores = ['––', '——', '––']
```

باقي التصليحات (`def init(self` ← `__init__`، `super().init(` ← `super().__init__(`، والشرطات) ما تغيّرت.

## الاختبارات

ملف جديد: `core_ai/tests/test_python_normalization.py` (5 اختبارات)

| الاختبار | شو بيفحص |
|---|---|
| `test_clean_code_with_dunder_methods_is_not_marked_as_fixed` | كود سليم فيه `__init__` و `__repr__`: ما في تصليحات، و `was_modified = False`، والكود ما تغيّر |
| `test_parse_of_clean_code_reports_no_auto_fix` | خرج التحليل الكامل لنفس الكود ما فيه "weird underscores" |
| `test_en_dash_pair_is_still_fixed` | `––init––` لسا بتتصلّح لـ `__init__` |
| `test_em_dash_pair_is_still_fixed` | `——init——` لسا بتتصلّح لـ `__init__` |
| `test_init_without_underscores_is_still_fixed` | `def init(self` لسا بتتصلّح لـ `__init__` |

**على الكود القديم:** أول اختبارين فشلوا، وهاد يأكّد إنهم بيمسكوا الخطأ. الـ 3 التانيين نجحوا.

**بعد التصليح (بالـ Docker):**

```
python -m pytest core_ai/tests test_graphify_implementation.py -q
487 passed
```

(كانوا 482، وانضافوا الـ 5 الجداد.)

**على السيرفر الشغّال** بعد `docker compose restart ai_web celery_worker`، نفس كود `course.py`:

```
fixes: []  was_modified: False
```

## ملاحظة

التحليلات المخزّنة من قبل بتضل متل ما هي، فيها التحذير القديم. أي ملف بينرفع أو بينحلّل من جديد بيطلع صح.
ما لمسنا النسخة القديمة بـ `evaluation/legacy_baseline/`، لأنها نسخة مجمّدة للمقارنة بالتقييم.

---

## تجربة حيّة بعد التصليح

أعدنا تحليل `course.py` بـ `POST /api/analysis/analyze/`، وصار للملف سجلّين:

| | القديم (17/11) | الجديد (18/11) |
|---|---|---|
| `normalization_fixes` | `"Fixed weird underscores: '__' → '__'"` | `[]` |
| `was_auto_fixed` | `true` | `false` |
| `warnings` | ⚠️ AUTO-FIXED | `[]` |
| `quality_score` | 97.2 | **99.2** |
| `dependency_graph` | 6 عقد، 3 أسهم | نفسه |

## مشكلة تانية طلعت من هالتجربة: ترتيب السجلات

`GET /api/analysis/analysis-results/` كان يرجّع السجلات بترتيب الإضافة، فالقديم يطلع أول.
والفرونت بياخد أول سجل على إنو الأحدث:

- `autotest-docgen/src/DocumentGenerationPage.tsx`: `const latestResult = resultsData.results[0];`
- `autotest-docgen/src/components/FileViewer.tsx`: أول سجل لنفس الملف.

يعني أي ملف بينعاد تحليله، الواجهة كانت تضل تعرض تحليله القديم.

**التصليح:** بـ `core_ai/views/analysis.py` (`AnalysisResultViewSet.list`):

```python
results_data = list(collection.find(query).sort([("analysis_completed_at", -1), ("_id", -1)]))
```

الأحدث أول. السجل يلي ما إلو وقت انتهاء بيطلع آخر شي. الفرونت ما تغيّر فيه شي.

**الاختبارات:** ملف جديد `core_ai/tests/test_analysis_results_order.py` (4 اختبارات):

| الاختبار | شو بيفحص |
|---|---|
| `test_newest_result_of_a_file_comes_first` | ملف إلو سجلّين: الجديد (بدون تحذير) أول |
| `test_filter_still_returns_only_that_file` | الفلترة بـ `code_file_id` لسا بترجّع سجلات الملف بس |
| `test_list_without_filter_is_newest_first` | بدون فلترة، كل السجلات من الأحدث للأقدم |
| `test_result_without_completion_time_goes_last` | سجل ما إلو وقت انتهاء بيطلع آخر شي |

على الكود القديم: 3 فشلوا، و`test_filter_still_returns_only_that_file` نجح لأنو ما إلو علاقة بالترتيب.
بعد التصليح: **491 passed** (كل اختبارات `core_ai/tests` و `test_graphify_implementation.py`).

**على السيرفر الشغّال** بعد `docker compose restart ai_web`:

```
6afdf23e48727ce7e11090ee  2026-11-18T18:45  99.2  []
6afca9e02fba2d75ba3ebeda  2026-11-17T19:24  97.2  [AUTO-FIXED ...]
```

---

## تعديل تاني على نفس الرابط: آخر تحليل بس لكل ملف

**ليش:** بعد إعادة التحليل 4 مرات، `course.py` صار إلو 5 سجلات، والرابط كان يرجّعهن كلهن.
وترتيب "الأحدث أول" لحالو طلع إلو مشكلة: `ProjectTree.tsx` بيمرق على كل السجلات وبيخلّي **آخر** واحد
لكل ملف، فصار ياخد الأقدم. والشرح من الشجرة بياخد الـ id من هون (`FileViewer.tsx`، `resolveAnalysisId`).

**التعديل** بـ `core_ai/views/analysis.py` (`AnalysisResultViewSet.list`):

- بشكل افتراضي: **آخر تحليل بس لكل ملف**، مع فلتر `code_file_id` وبدونه.
- `?history=true`: كل السجلات، الأحدث أول.
- السجلات القديمة ما بتنمسح من القاعدة.

بسجل واحد لكل ملف، كل أماكن الفرونت بتاخد الأحدث، سواء أخدت الأول أو الآخر. ما تعدّل شي بالفرونت.

**الاختبارات** (`test_analysis_results_order.py`، 7 اختبارات):

| الاختبار | شو بيفحص |
|---|---|
| `test_a_file_returns_only_its_latest_result` | ملف إلو سجلّين ← الأحدث بس |
| `test_history_returns_every_result_newest_first` | `history=true` ← الكل، الأحدث أول |
| `test_last_one_per_file_is_also_the_latest` | طريقة `ProjectTree.tsx` (آخر سجل لكل ملف) بتطلع الأحدث |
| `test_filter_still_returns_only_that_file` | الفلترة بـ `code_file_id` لسا صح |
| `test_list_without_filter_returns_latest_of_each_file` | بدون فلتر ← سجل واحد لكل ملف |
| `test_list_without_filter_with_history_is_newest_first` | بدون فلتر مع `history=true` ← الكل |
| `test_result_without_completion_time_goes_last` | سجل ما إلو وقت انتهاء بيطلع آخر شي |

كل الاختبارات: **503 passed**.

**على السيرفر:**

| الطلب | الخرج |
|---|---|
| `?code_file_id=6afca9e0...553e` | سجل واحد: `6afdff6f...` (19:41:35)، **8 KB** بدل 41 KB |
| `?code_file_id=6afca9e0...553e&history=true` | الـ 5 سجلات، الأحدث أول |
| بدون فلتر | 29 سجل، سجل واحد لكل ملف |
| بدون فلتر مع `history=true` | 34 سجل |

**ملاحظة تشغيل:** بعد `docker compose restart ai_web` لازم كمان `docker restart upm_api_gateway`،
لأنو الـ gateway بيضل ماسك عنوان `ai_web` القديم وبيرجّع 502.

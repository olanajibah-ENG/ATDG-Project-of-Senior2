# تقرير الشريحة S3 — التشغيل المعزول، بوابة القبول، التغطية، والحزمة

**الميزة:** الميزة 1 — توليد اختبارات موثوقة
**التاريخ:** 22/11/2026
**الفرع:** `feature/testing-v1/evaluation`
**المواصفة والخطة والمهام:** `specs/003-sandbox-run-ready/`

## 1. الهدف

بعد ما النموذج يكتب الاختبارات (S2)، كل اختبار حالته `generated` بينشغّل بـ pytest على كود **نفس نسخة المشروع**، بـ container جديد ومعزول لكل اختبار. الاختبار بيصير `ready` **بس** من بوابة القبول، إذا كل دوال الاختبار فيه نجحت، ومعه دليل. غير هيك بيصير `test_failed` أو `environment_error` مع سبب واضح.
بعد ما يخلصوا كلهم، منشغّل كل اختبارات `ready` مع بعض بتشغيلة أخيرة نظيفة، ومنها بتطلع التغطية الرسمية (أسطر وفروع). وفي رابطين جداد: التغطية، والحزمة (ZIP).

## 2. النتيجة باختصار

| البند | النتيجة |
|---|---|
| المهام المنجزة | 42 من 42 |
| اختبارات الشريحة الجديدة | 103 ناجح من 103 (7 ملفات جديدة) |
| كل الاختبارات (`core_ai/tests` + `test_graphify_implementation.py`) | 662 ناجح من 662 |
| اختبارات كشف التعارض (conflict detection) | ما تغيّرت، وكلها ناجحة |
| تجربة القبول على Docker الحقيقي | ناجحة: 3 من 3 `ready`، والتغطية 100% أسطر و 100% فروع |
| فحوص العزل بإيد صاحب المشروع | كلها ناجحة (القسم 7) |

## 3. الملفات

### ملفات جديدة — `Ai_project/core_ai/services/test_generation/`

| الملف | شو بيعمل |
|---|---|
| `sandbox/executor.py` | واجهة `SandboxExecutor` مع `RunSpec` و `RunOutput`، و `get_executor` / `set_executor` |
| `sandbox/docker_executor.py` | المنفّذ الحقيقي: الوحيد يلي بيحكي مع Docker. بيجهّز volumes، بيشغّل container بالقيود، وبينضّف دايماً |
| `sandbox/workspace.py` | ملفات النسخة، ملفات الاختبار مع `pytest.ini`، وتحويلها لـ tar بمالك 10001 |
| `sandbox/image/Dockerfile` | صورة `autotest-sandbox:py3.10-s3`: Python 3.10 + pytest 8.3.3 + pytest-cov 5.0.0، والمستخدم 10001 |
| `results.py` | قراءة junit (بحد 1 MB)، الحكم على التشغيلة، وتصغير تقرير التغطية |
| `acceptance.py` | بوابة القبول: الطريق الوحيد لـ `ready`، مع الدليل |
| `runs.py` | تخزين التشغيلات (`test_runs`)، بنسختين: Mongo وبالذاكرة |
| `run_stage.py` | مرحلة التشغيل: record بكل جولة، بعدين التشغيلة الأخيرة وإعادتها إذا في اختبار بيفشل مع الباقيين |
| `coverage.py` | مساهمة كل record، تقرير التغطية للـ job، وتفسير الأسطر الناقصة من الخطة |
| `bundle.py` | الحزمة ZIP: بتنبنى بالذاكرة لكل طلب وما بتنحفظ |

### ملفات تعدّلت

| الملف | التعديل |
|---|---|
| `statuses.py` | مرحلتين جداد `sandbox_run` و `final_run`، و `RunReason` بـ 9 أسباب |
| `records.py` | `update()` بترفض `status=ready`؛ و `accept_ready()` و `next_generated()` |
| `generation.py`، `runner.py` | بعد التوليد، الـ job بيتسلّم لمرحلة التشغيل (`handover`) بدل ما يخلص |
| `languages/base.py`، `python_adapter.py` | أمر التشغيل، الأسماء العليا، وأسماء دوال الاختبار المتوقعة |
| `readers.py` | `content_of(file_id)` لقراءة كود النسخة (من GridFS بـ Mongo) |
| `validation/safety_lint.py` | منع `os._exit`، `sys.exit`، `os.kill`، `os.killpg`، `os.abort`، استيراد `signal`، و `write_text` / `write_bytes` برا `tmp_path` |
| `errors.py` | `coverage_not_ready` و `bundle_not_ready` (409) |
| `celery_tasks/testgen_tasks.py` | مهمة `sandbox_pass` على طابور `test_sandbox` |
| `serializers/testgen_serializer.py` | `executed`، `notice`، `run`، `evidence`، `coverage_contribution`، والتغطية بحالة الـ job |
| `views/testgen_views.py`، `urls.py` | رابطي `coverage/` و `bundle/` |
| `settings.py` | `TEST_RUNS_COLLECTION`، إعدادات `TESTGEN_SANDBOX_*`، وتوجيه المهمة للطابور |
| `requirements.txt` | `docker==7.1.0` |
| `docker-compose.yml` | خدمتين: `testgen_sandbox_image` (بناء الصورة) و `testgen_sandbox_worker` (مع `docker.sock`، بدون `.env`، بدون مفاتيح) |

## 4. كيف بيشتغل التشغيل المعزول

لكل record حالته `generated`:

1. ملفات النسخة بتنكتب بـ volume `sbx_<job>_src` (مرة وحدة للـ job). ملف الاختبار و `pytest.ini` بينكتبوا بـ volume خاص بالتشغيلة. الكتابة بتصير من container "تحميل" ما بينشغّل أبداً.
2. container جديد من `autotest-sandbox:py3.10-s3` بالقيود:

| القيد | القيمة |
|---|---|
| الشبكة | `network_mode: none` |
| نظام الملفات | `read_only`، والكود mount للقراءة بس، و `/tmp` tmpfs بـ 64 MB |
| المعالج والذاكرة | 1 CPU، و 512 MB بدون swap |
| العمليات | 128 |
| الصلاحيات | `cap_drop: ALL`، و `no-new-privileges`، والمستخدم 10001 |
| البيئة | `PYTHONPATH`، `PYTHONDONTWRITEBYTECODE`، `COVERAGE_FILE=/tmp/.coverage` بس |
| الوقت | `timeout --signal=KILL 60`، ومهلة انتظار إضافية 15 ثانية |

3. الأمر: `python -m pytest … --junitxml=/out/junit.xml --cov=/workspace/src --cov-branch --cov-report=json:/out/cov.json`.
4. الحكم من كود الخروج + ملف junit + أسماء دوال الاختبار المتوقعة:

| الحالة | الأسباب |
|---|---|
| `ready` | كل الدوال المتوقعة موجودة ونجحت |
| `test_failed` | `assertion`، `collection_error`، `no_tests`، `skipped_test`، `timeout`، `fails_with_others` |
| `environment_error` | `missing_dependency`، `sandbox_unavailable`، `no_result_file` |

5. الـ container والـ volumes بينمسحوا دايماً، حتى لو صار خطأ.

**التشغيلة الأخيرة:** كل اختبارات `ready` مع بعض، بمهلة `min(60 + 15×العدد، 300)` ثانية. إذا اختبار فشل فيها، بيصير `test_failed / fails_with_others` ومنعيدها بدونه. التغطية الرسمية بتطلع بس من تشغيلة كلها ناجحة.

## 5. الاختبارات

كل الاختبارات بتستعمل منفّذ وهمي (`fake_sandbox.py`) ما عدا اختبارات `test_docker_executor.py` يلي بتفحص خيارات الـ container بـ client وهمي.

| الملف | العدد | شو بيفحص |
|---|---|---|
| `test_results.py` | 39 | قراءة junit، كل الأسباب التسعة، حد الحجم، وتصغير التغطية بمسارات نسبية ومطلقة |
| `test_run_stage.py` | 30 | جولة لكل record، القبول والرفض، الدليل، التشغيلة الأخيرة، `fails_with_others`، التغطية، والتنظيف |
| `test_docker_executor.py` | 10 | كل قيد بجدول القسم 4، المهلة والقتل، والتنظيف الدائم |
| `test_workspace.py` | 6 | ملفات النسخة، `pytest.ini`، والـ tar بالمالك 10001 |
| `test_coverage.py` | 5 | المساهمة، تقرير الـ job، وتفسير الأسطر المتروكة من الخطة |
| `test_bundle.py` | 6 | قائمة الملفات، `ready` بس، رأس الاختبار، تطابق SHA-256، و ما في كود مشروع ولا أسرار |
| `test_api_sandbox.py` | 7 | رابطي التغطية والحزمة: 200، 409، 403، 401 |
| **المجموع** | **103** | |

وإضافات على ملفات قديمة: `test_validator.py` (الأوامر الممنوعة الجديدة)، `test_boundaries.py` (بس `acceptance.py` بينادي `accept_ready`، وبس `docker_executor.py` بيستورد `docker`)، `test_api_records.py`، `test_folder_upload_versions.py`. واختبارات S2 تعدّلت لأنو الـ job صار يتسلّم (`running / sandbox_run`) بدل ما يخلص بعد التوليد.

أمر التشغيل (من جذر المشروع):

```bash
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -e PYTHONIOENCODING=utf-8 --entrypoint sh ai_web -c "pip install -q pytest >/dev/null 2>&1; python -m pytest core_ai/tests test_graphify_implementation.py -q -p no:cacheprovider"
```

النتيجة: `662 passed, 5 warnings in 44.46s`.

## 6. تجربة القبول على Docker الحقيقي

**تجربة صاحب المشروع (الـ MVP):** `job_7ba739d02910`، 3 من 3 `ready` مع دليل كامل.

**التجربة الكاملة عبر الـ gateway:** `job_147272fad542`، المشروع demo3، النسخة 10، الملف `demo/course.py`، المستوى `unit`.

| الخطوة | النتيجة |
|---|---|
| المراحل يلي انشافت | `pending/queued` ← `running/sandbox_run` ← `running/final_run` ← `completed` |
| الـ records | `Course.__init__`، `Course.is_full`، `Course.add_student`: الثلاثة `ready` |
| التغطية قبل ما يخلص | 409 `coverage_not_ready` |
| الحزمة قبل ما تخلص | 409 `bundle_not_ready` |
| التغطية بدون توكن | 401 `unauthorized` |
| التغطية بعد ما يخلص | 12/12 تعليمة، 4/4 فروع: 100% أسطر، 100% فروع، 100% مدمجة |
| الحزمة | 200، `application/zip`، 4368 بايت |
| تشغيل الحزمة برا النظام | `9 passed` بعد ما انحط كود النسخة كـ `src/` |

الدليل تبع `Course.__init__`:

```json
{"run_id": "sbx_job_147272fad542_t_18b068addf_1", "version_number": 10,
 "body_hash": "d828b89195fb2bcc", "tests": 3, "passed": 3, "duration_s": 2.342}
```

### مشاكل طلعت بالتجربة وانصلحت

| المشكلة | الإصلاح |
|---|---|
| coverage ما قدر يكتب ملف بياناته لأنو المجلد للقراءة بس | `COVERAGE_FILE=/tmp/.coverage` |
| مسار الملف بالتغطية طلع `src/demo/course.py` | `reduce_coverage` بيشيل البادئة النسبية والمطلقة |
| `"message": ""` للاختبار الناجح | صارت `null` |
| رأس الاختبار بالحزمة كان "NOT RUN YET" | بالحزمة بيصير "ready — passed in isolated run … on version …" |
| `test_path` بـ `records_summary.json` ما كان يطابق مسار الملف بالحزمة | `bundle_test_path` |

## 7. فحوص العزل (بإيد صاحب المشروع، من PowerShell)

| الفحص | النتيجة |
|---|---|
| DNS والوصول لـ IP | ممنوعين |
| الكتابة على الكود | ممنوعة (read-only) |
| المستخدم | 10001 (مش root) |
| أسرار بالبيئة | ما في. `GPG_KEY` جاية من صورة `python:3.10-slim` وهي بصمة عامة مش سر |
| حلقة لا نهائية | انقتلت بالوقت، كود الخروج 137 |
| بعد التشغيل | ما ضل ولا container ولا volume |

## 8. حدود معروفة

- **junit مزوّر (research R6):** اختبار بيقدر نظرياً يكتب ملف junit مزوّر. خففناه بمنع `os._exit` و `sys.exit` والكتابة برا `tmp_path`، ومطابقة أسماء الدوال المتوقعة، بس ما سكّرناه 100%.
- **بناء الصورة:** أول بناء أخد حوالي 15 دقيقة بسبب 729 MB من سياق البناء. منصح بـ `.dockerignore`.
- **عامل الـ sandbox** بيشتغل كـ root جوّا الـ container تبعه، ومعه `docker.sock`. ما معه `.env` ولا مفاتيح.
- **ما في تثبيت مكتبات:** كود بيحتاج مكتبة خارجية بيطلع `environment_error / missing_dependency`.
- **مش ضمن الشريحة:** الإصلاح (S4)، مستويات edge و integration، والواجهة الأمامية.

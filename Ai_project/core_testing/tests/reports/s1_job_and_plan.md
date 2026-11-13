# تقرير الشريحة S1 — المهمة والخطة (بدون نموذج لغوي)

**الميزة:** الميزة 1 — توليد اختبارات موثوقة
**التاريخ:** 13/11/2026
**الفرع:** `feature/core-testing`
**المواصفة والخطة والمهام:** `specs/001-test-job-plan/`

## 1. الهدف

المستخدم بيطلب اختبارات لمشروع، فبياخد رقم مهمة. بعدها بيقرا الخطة: كل الدوال والميثودات يلي رح تنختبر، وكل شي تم تجاوزه مع السبب. بهالشريحة ما بيتولّد أي اختبار وما بينادى أي نموذج لغوي.

## 2. النتيجة باختصار

| البند | النتيجة |
|---|---|
| المهام المنجزة | 50 من 50 (47 + 3 مهام إصلاح بعد تجربة القبول) |
| اختبارات الشريحة | 130 ناجح من 130 |
| كل الاختبارات (الجديدة + القديمة) | 343 ناجح من 343 |
| الاختبارات القديمة (كشف التناقض + Graphify) | 213 ناجح، ولا واحد انكسر |
| تجربة Postman على النظام الحقيقي | ناجحة (القسم 6) |
| استدعاءات النموذج اللغوي | صفر |

## 3. الملفات

### ملفات جديدة — `Ai_project/core_testing/`

| الملف | شو بيعمل |
|---|---|
| `apps.py` | تعريف التطبيق |
| `urls.py`، `views.py`، `serializers.py` | المسارات الثلاثة، التحقق من الطلب، وتشكيل الرد |
| `auth.py` | التحقق من token تبع UPM، وملكية المهمة |
| `errors.py` | أكواد الأخطاء والشكل الموحد |
| `statuses.py` | قيم الحالات والمراحل وأسباب التجاوز |
| `repo.py` | حفظ المهام بمجموعة `test_jobs` (Mongo + نسخة بالذاكرة) |
| `readers.py` | قراءة فقط من مجموعات التحليل (Mongo + نسخة بالذاكرة) |
| `scope.py` | تحديد النسخة والملفات والأنواع |
| `gate.py` | بوابة التحليل: قرار لكل ملف |
| `planner.py` | الوحدات، المتجاوز، وعدد عناصر العمل |
| `runner.py` | جولة وحدة للمهمة: بوابة ← graph ← خطة |
| `tasks.py` | مهمة Celery يلي بتشغّل الجولة وبتعيد الفحص |
| `staleness.py` | بيكشف المهمة يلي العامل ما شغّلها وبيحوّلها لـ `failed` بدل ما تضل `pending` |
| `graphify/loader.py` | قراءة الـ graph المخزّن وجدول الكلاسات والـ imports |
| `graphify/merge.py` | معرّفات فريدة ودمج graph المشروع |
| `graphify/resolver.py` | ربط الاستدعاء بالوحدة المحلية الصح |
| `graphify/queries.py` | الوحدات يلي بتناديها وحدة مباشرة |
| `languages/python_adapter.py` | جرد وحدات Python وأسباب التجاوز |

### ملفات موجودة تعدّلت

| الملف | التعديل |
|---|---|
| `Ai_project/Ai_project/settings.py` | تسجيل `core_testing` + 5 إعدادات |
| `Ai_project/Ai_project/urls.py` | سطر ربط `api/analysis/tests/` |
| `docker-compose.yml` | سطر `UPM_JWT_SIGNING_KEY` لخدمة `ai_web` |

ولا ملف جوّا `core_ai` تعدّل.

## 4. كيف اشتغلت الاختبارات

بكونتينر مؤقت من صورة `ai_web`، بدون قاعدة بيانات وبدون شبكة، من جذر المشروع:

```bash
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -e PYTHONIOENCODING=utf-8 --entrypoint sh ai_web -c "pip install -q pytest >/dev/null 2>&1; python -m pytest core_testing/tests core_ai/tests test_graphify_implementation.py -q -p no:cacheprovider"
```

النتيجة: `343 passed`.

التخزين بالاختبارات نسخة بالذاكرة، وبيانات التحليل بتنبنى بتشغيل المحلل الحقيقي (`PythonProcessor`) على ملفات عيّنات صغيرة، حتى تضل مطابقة ليلي بيخزّنه التحليل فعلاً.

**ملاحظة صريحة:** المهام كانت بتطلب كتابة الاختبارات أول وتشوفها تفشل قبل الكود. فعلياً انكتب الكود والاختبارات مع بعض.

## 5. الاختبارات بالتفصيل

| ملف الاختبار | العدد | شو بيفحص | النتيجة |
|---|---|---|---|
| `test_repo_readers.py` | 7 | شكل رقم المهمة، الحفظ والقراءة والتعديل، قراءة النسخ والملفات | ناجح |
| `test_auth.py` | 12 | token صحيح، بدون header، شكل غلط، توقيع غلط، منتهي، نوع `refresh`، بدون `user_id`، مفتاح فاضي، الملكية | ناجح |
| `test_scope.py` | 11 | النسخة الأحدث، نسخة مو موجودة، المسارات، الأنواع، 400 و 422 | ناجح |
| `test_gate.py` | 9 | كل حالات البوابة، ومنها "الطلب لسا ما بلّش" و"فشل مرتين" والمهلة | ناجح |
| `test_python_adapter.py` | 9 | 14 وحدة بملف `game`، الـ `__init__` وحدة، وأسباب التجاوز الستة | ناجح |
| `test_graphify_merge.py` | 9 | المعرّفات `path::Class.method`، كلاسين بنفس الاسم بملفين، وإنو الـ graph المخزّن ما بيتغيّر | ناجح |
| `test_graphify_resolver.py` | 13 | ربط الاستدعاءات جوّا الملف وبين ملفين، وإنو كل علاقة طرفيها موجودين | ناجح |
| `test_planner.py` | 7 | العدّ (14 و 42)، كل دالة مرة وحدة، شكل المتجاوز، وترتيب ثابت | ناجح |
| `test_runner.py` | 15 | الجولة كاملة، ملف غير Python، ملف بدون تحليل، فشل مرتين، المهلة، وإنو الجولة ما بتتغيّر إذا انعادت | ناجح |
| `test_api.py` | 27 | المسارات الثلاثة: الأشكال، 400، 404، 409، 422، 401 بدون token، و 403 لمستخدم تاني | ناجح |
| `test_boundaries.py` | 4 | التطبيق ما بيستورد النموذج ولا ميزة تانية، `core_ai` ما بيستورد منه، ومهمة كاملة مع النموذج محظور | ناجح |
| `test_staleness.py` | 7 | المهمة العالقة: `queued` أكتر من المهلة، `running` بدون تقدّم، المهام المنتهية ما بتتغيّر، وجولة متأخرة ما بترجّع مهمة فاشلة | ناجح |

### نتيجة ملف `game` (العيّنة المرجعية)

- 14 وحدة، 0 متجاوز، 42 عنصر عمل.
- الاستدعاءات يلي كانت طالعة خارجية بالـ graph المخزّن صارت مربوطة:

| قبل (المخزّن) | بعد (طبقة `core_testing/graphify`) |
|---|---|
| `Student.enroll` ← `ext.course.add_student` | `Student.enroll` ← `Course.add_student` |
| `Student.drop_course` ← `ext.course.remove_student` | `Student.drop_course` ← `Course.remove_student` |
| `Professor.__init__` ← `ext.super` | `Professor.__init__` ← `Person.__init__` |
| `Student.__init__` ← `ext.super` | `Student.__init__` ← `Person.__init__` |
| `University.create_department` ← `Department` (الكلاس) | `University.create_department` ← `Department.__init__` |

## 6. تجربة القبول على النظام الحقيقي (Postman)

عملها صاحب المشروع على النظام الشغّال (Mongo و Celery و nginx حقيقيين) بتاريخ 13/11/2026.

| # | الطلب | النتيجة |
|---|---|---|
| 1 | `POST /api/token/` | token من UPM |
| 2 | `POST /api/analysis/tests/jobs/` مع `{"project_id": "task_test"}` | `202`، `job_id` = `job_6e07574f0256`، `status` = `pending`، `version_number` = 1 |
| 3 | `GET /api/analysis/tests/jobs/job_6e07574f0256/` | `completed` / `planned`، `progress.total` = 27، `by_status.pending` = 27، الملف `task.py` حالته `pending`، `error` = `null` |
| 4 | `GET /api/analysis/tests/jobs/job_6e07574f0256/plan/` | 9 وحدات، `skipped` فاضية، `work_items_count` = 27 |
| 5 | نفس المسار بـ token غلط | `401 unauthorized` بالشكل الموحد |
| 6 | مسار الحالة برقم مهمة مو موجود | `404 not_found` بالشكل الموحد |

الوحدات التسعة: `Engine.__init__`، `Engine.start`، `GPS.__init__`، `GPS.locate`، `Driver.__init__`، `Driver.introduce`، `Car.__init__`، `Car.assign_driver`، `Car.drive`.

العامل خلّص هالمهمة بجولة وحدة بحوالي 0.02 ثانية (والمهمتين يلي قبلها بـ 0.11 و 0.14 ثانية). و log العامل بآخر 40 دقيقة ما فيه ولا سطر للنموذج اللغوي.

بصمة مفتاح التوقيع بخدمة UPM وبخدمة الـ AI طلعت متطابقة (تمت المقارنة بالبصمة بدون عرض المفتاح).

## 7. البيانات الموجودة يلي ارتبطنا فيها (قراءة فقط)

| المجموعة | الحقول المقروءة | ليش |
|---|---|---|
| `project_versions` | `project_id`، `version_number`، `file_ids` | تحديد النسخة وملفاتها |
| `code_files` | `_id`، `filepath`، `file_type`، `analysis_status`، `analysis_id` | المسار، اللغة، وحالة التحليل |
| `analysis_results` | `dependency_graph`، `class_diagram_data`، `ast_structure.ast_tree.body` | الـ graph، الدوال والميثودات، والـ imports |
| `analysis_jobs` | `code_file_id`، `started_at` | معرفة إذا محاولة التحليل يلي طلبناها بلّشت |

المجموعة الجديدة الوحيدة: `test_jobs`، والخطة محفوظة جوّاها.

## 8. طريقة استدعاء المسارات

كل الطلبات بدها Header: `Authorization: Bearer <access token من UPM>`.

**1) إنشاء مهمة** — `POST /api/analysis/tests/jobs/`

```json
{
  "project_id": "task_test",
  "version_number": 1,
  "paths": ["task.py"],
  "levels": ["unit", "edge", "integration"]
}
```

`project_id` بس هو الإجباري. الرد `202` وفيه `job_id`.

**2) حالة المهمة** — `GET /api/analysis/tests/jobs/{job_id}/`

**3) الخطة** — `GET /api/analysis/tests/jobs/{job_id}/plan/`

`project_id` هو المعرّف المحفوظ مع النسخة: UUID للمشاريع المرفوعة عن طريق UPM، أو اسم المشروع للمرفوع مباشرة على `upload-folder/`.

## 9. مشاكل وملاحظات طلعت

| # | الملاحظة | الوضع |
|---|---|---|
| 1 | **مهمة بتضل `pending` للأبد إذا العامل رمى رسالتها.** صارت فعلاً بالتجربة: العامل كان شغّال بكود قديم، فرمى المهمة `job_59e5d99662d6` (`unregistered task`) وضلت `pending` / `queued`. ما في شي بيخبّر المستخدم. | **انحلّت** (المهام T048–T050). أي قراءة لمهمة ضلت `queued` أكتر من 120 ثانية، أو `running` بدون أي تغيير أكتر من 720 ثانية، بتحوّلها لـ `failed` مع `error.code` = `worker_unavailable` ورسالة واضحة. الملف: `staleness.py`. |
| 2 | **لازم إعادة تشغيل `celery_worker` بعد أي تعديل كود.** الكود مربوط كـ volume، بس العامل ما بيعيد التحميل لحاله. | موثّق بـ `quickstart.md`. |
| 3 | **الاستدعاء عن طريق حقل (`self.engine.start()`) ما بينربط.** بملف `task.py` طلع `Car.drive` بدون جيران، مع إنو غالباً بينادي ميثودات الـ `Engine` و الـ `GPS` عن طريق حقول الكلاس. الطبقة بتربط `self.m()` و `super()` والبراميتر حسب نوعه، بس مو `self.حقل.m()`. | حد معروف بـ S1. لازم ينحل قبل S6 (اختبارات التكامل)، لأنها بتعتمد على هالعلاقات. |
| 4 | **التحقق من عضوية المستخدم بالمشروع مو موجود.** الخدمة بتتأكد إنو المستخدم مسجّل دخول وإنو المهمة لصاحبها، بس ما بتتأكد إنو المشروع إله. | مؤجّل بقرار، قبل العرض متعدد المستخدمين. |
| 5 | **خروج واحد عن الدستور، موثّق بالخطة:** `python_adapter.py` بدون واجهة `LanguageAdapter` ولا registry. | بتنضاف مع التوليد بـ S2. |
| 6 | **خطأ بالكود القديم (ما انلمس):** `analyze_task` بيحدّث سجل `analysis_jobs` بـ `update_one` على `code_file_id`، فبيعدّل أول سجل مو آخر واحد. لهيك البوابة بتعتمد على `started_at` مو على حالة السجل. | للعلم، خارج نطاق الميزة. |

## 10. خارج الشريحة (للشرائح الجاية)

| الشريحة | شو فيها |
|---|---|
| S2 | بناء السياق، التوجيه، استدعاء النموذج، الفحص الساكن، كتابة ملف اختبار Unit، ومجموعات `test_units` و `test_records` و `test_attempts` |
| S3 | التشغيل المعزول، التغطية، حالة `ready`، تنزيل ZIP، وحفظ ملفات الاعتماديات عند الرفع |
| S4 | حلقة الإصلاح وتصنيف الإخفاقات |
| S5 | اختبارات Edge والتلميحات |
| S6 | اختبارات Integration والمحاكاة |
| أي وقت | إلغاء المهمة، قائمة السجلات، وباقي تعديلات الـ graph (الـ builtins، مستويات الثقة، `io_kind`، التخزين المؤقت) |

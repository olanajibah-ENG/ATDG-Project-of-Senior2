# فحص ملكية المشروع قبل إنشاء test job

التاريخ: 18/11/2026

## المشكلة

روابط الاختبارات كانت تتأكد من شغلتين بس: التوكن صحيح، والـ job ما بيقراه غير يلي عمله.
ما كان في فحص إذا المشروع للمستخدم (مكتوب كـ "Known gap" بـ `specs/001-test-job-plan/research.md`، R1).

يعني أي مستخدم مسجّل بيعرف `project_id` تبع مشروع غيره كان يقدر يعمل job عليه، ويقرا الاختبارات
المولّدة، وهي مبنية على كود المشروع.

## الحل

خدمة الـ AI ما عندها جدول مشاريع ولا مستخدمين. UPM عنده، ورابط `GET /api/upm/projects/<id>/` بيرجّع
200 لصاحب المشروع بس، و 404 لأي حدا تاني.

ملف جديد: `core_ai/services/test_generation/project_access.py`

قبل ما ينعمل الـ job (`POST /api/analysis/tests/jobs/`)، منبعت لـ UPM من جوّا الـ docker
(`UPM_INTERNAL_URL`، افتراضياً `http://web:8000`) **بنفس توكن المستخدم**:

| جواب UPM | جوابنا |
|---|---|
| 200 | بينعمل الـ job متل قبل |
| 403 أو 404 | **404** `not_found` "Project not found." (ما منقول إذا المشروع موجود) |
| 401 | 401 |
| ما جاوب (واقف، timeout 5 ثواني) | **503** `service_unavailable`، وما بينعمل job |

- الفحص بيصير **قبل** ما نقرا أي شي عن المشروع، فما في جواب بيكشف إذا المشروع موجود.
- ما منخزّن مين صاحب المشروع عندنا: UPM بيضل المصدر الوحيد.
- UPM ما تغيّر فيه شي.
- قراءة الـ job بتضل متل ما هي (صاحبه بس).

**ملفات تعدّلت:**
- `core_ai/views/testgen_views.py`: سطر الفحص بـ `JobListView.post`، ودالة `_bearer_token`.
- `core_ai/services/test_generation/errors.py`: خطأ `service_unavailable` (503).
- `Ai_project/settings.py`: `UPM_INTERNAL_URL`.
- `core_ai/services/test_generation/auth.py` و `research.md`: تحديث ملاحظة الـ gap.
- `core_ai/tests/test_generation/conftest.py`: UPM مزيّف بيقبل بشكل افتراضي، حتى الاختبارات القديمة ما تتصل بـ UPM حقيقي.

## الاختبارات

ملف جديد: `core_ai/tests/test_generation/test_project_access.py` (9 اختبارات):

| الاختبار | شو بيفحص |
|---|---|
| `test_owner_starts_a_job` | UPM بيقول 200 ← 202 وفي job |
| `test_the_callers_own_token_is_sent_to_upm` | نفس توكن المستخدم هو يلي بينبعت |
| `test_someone_elses_project_is_not_found_and_no_job_is_made` (404 و 403) | ← 404، وما في job ولا مهمة بالـ queue |
| `test_upm_not_answering_refuses_with_503` | ← 503، وما في job |
| `test_upm_refusing_the_token_is_401` | ← 401 |
| `test_upm_is_asked_before_anything_about_the_project_is_read` | مشروع مش موجود عندنا كمان ← 404 تبع UPM، مش "unknown project" |
| `test_client_calls_the_upm_project_route_with_the_token` | الرابط والـ header والـ timeout صح |
| `test_client_returns_none_when_upm_does_not_answer` | UPM واقف ← None |

كل الاختبارات: **516 passed**.

## تجربة حقيقية

توكنات انعملت جوّا UPM بنفس طريقة تسجيل الدخول (`RoleAwareRefreshToken`)، وانمسحت بعد التجربة:

| الحالة | الجواب |
|---|---|
| مستخدم تاني (`admin`) على `demo3` | **404** "Project not found." |
| صاحب المشروع (`user3`) على `demo3` | **202**، `job_3e16353b0e15` على النسخة 6 |
| `user3` على مشروع مش موجود | **404** |
| `upm_django_app` واقف | **503** "Could not check the project with UPM." |

ملاحظة: حتى الأدمن ما بيقدر يعمل job على مشروع مش إلو، لأنو رابط المشروع الواحد بـ UPM بيفحص الصاحب بس.

## برّا هالتعديل

روابط التحليل التانية (`analysis-results`، `project-tree`، ...) لسا `AllowAny` بدون أي توكن.
هاد أكبر من ميزة الاختبارات، وما لمسناه.

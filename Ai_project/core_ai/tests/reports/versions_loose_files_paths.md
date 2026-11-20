# رفع ملفات لحالها من الواجهة: رجوع الملف لمجلده

التاريخ: 18/11/2026

## المشكلة

تبويب "Local files" بالواجهة (`CodeUploadForm.tsx`) فيه `<input type="file" multiple>`، فالمتصفح بيبعت
**اسم الملف بس** (`course.py`)، بدون مجلده. UPM كان يمرّر الملفات لخدمة الـ AI بدون مسارات، وخدمة الـ AI
كانت تحط الملف بـ `<اسم المشروع>/course.py`.

1. **التعديل ما بيوصل لمحلّه:** المشروع انرفع zip فيه `demo/course.py`. رفع `course.py` المعدّل لحالو
   كان يعمل `demo3/course.py` جديد، و `demo/course.py` القديم يضل `unchanged`. الشرح والاختبارات بيضلّوا
   شايفين القديم.
2. **ملفين بنفس الاسم بمجلدين** (`models/user.py` و `views/user.py`) بيصيروا تنينهن نفس المسار.

## التعديل

**خدمة الـ AI:**

- `core_ai/services/project_versioning.py`: `match_bare_names(prev_entries, bare)`.
- `core_ai/views/folder_upload.py`: برفع جزئي، الملفات يلي وصلت بالاسم بس:

| الحالة | شو بيصير |
|---|---|
| الاسم بيطابق **مسار واحد** بالنسخة السابقة | الملف بيروح لهالمسار (`modified` أو `unchanged`) |
| الاسم بيطابق **أكتر من مسار** | **409** `ambiguous_name`، وما بينحفظ شي |
| الاسم مش موجود | ملف جديد متل قبل (`<اسم المشروع>/<الاسم>`) |
| المسار المخمّن موجود أصلاً | بيضل متل ما هو |
| انبعتت `paths` | المسارات المبعوتة بتغلب، وما في مطابقة |

- الرد فيه `matched_paths`، مثلاً `{"course.py": "demo/course.py"}`.

**UPM:**

- `views/folder_upload_proxy.py`: رابط الرفع بيقبل `paths` (لستة JSON أو حقول متكررة، وحدة لكل ملف بـ
  `files`، بنفس الترتيب). إذا العدد ما بيطابق ← 400.
- `celery_tasks/upload_tasks.py`: بيمرّر `paths` لخدمة الـ AI إذا كل الملفات إلها مسار.

هيك أي يوم الواجهة بتضيف اختيار مجلد، بتبعت `file.webkitRelativePath` بـ `paths` وبيشتغل.

## الاختبارات

`core_ai/tests/test_folder_upload_versions.py` (5 جداد، الـ view كامل بـ MongoDB مزيّف):

| الاختبار | النتيجة |
|---|---|
| `course.py` بالاسم بعد zip فيه `demo/course.py` | `demo/course.py` بيصير `modified`، وما في `demo3/course.py` |
| `user.py` بيطابق `models/user.py` و `views/user.py` | 409، ولا نسخة ولا ملف انحفظ |
| اسم جديد `extra.py` | `demo3/extra.py` جديد |
| `paths=["lib/course.py"]` | `lib/course.py` جديد، و `demo/course.py` ما انلمس |
| أول رفع لملفات لحالها | `demo3/course.py` متل قبل |

`core_ai/tests/test_project_versioning.py` (3 جداد على `match_bare_names`).

كل الاختبارات: **536 passed**.

## تجربة حقيقية (على demo3، من UPM)

قبل: النسخة 6 فيها `demo/course.py` (المحتوى الأول، `...5531`).

| الطلب | النتيجة |
|---|---|
| `course.py` لحالو، بالاسم بس (متل الواجهة)، بمحتوى النسخة 2 | **النسخة 7**: `demo/course.py` بحالة `modified` (`...553e`)، وما في ملف تاني |
| `course.py` مع `paths=["demo/course.py"]`، بالمحتوى الأول | **النسخة 8**: `demo/course.py` بحالة `modified` (`...5531`) |

بالحالتين رجع استعمل ملف موجود بنفس المسار ونفس المحتوى، بدون تحليل جديد.

## شو لسا

- **الواجهة** ما فيها اختيار مجلد. هيك ملفين بنفس الاسم بمجلدين ما بينرفعوا لحالهن إلا بـ zip أو بـ `paths`.
  اختيار المجلد (`webkitdirectory`) وسحب المجلدات شغل فرونت: للملاحظة لأريج.

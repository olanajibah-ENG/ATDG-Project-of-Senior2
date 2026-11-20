# حماية من الحذف الجماعي برفع zip

التاريخ: 18/11/2026

## المشكلة

رفع zip بيعتبر إنو الـ zip هو المشروع كامل (`full`): أي ملف كان بالنسخة السابقة ومش بالـ zip بيصير `deleted`.
بغلطة بسيطة بتنحذف معظم الملفات بدون تحذير:

1. **zip غلط أو ناقص**: مجلد فرعي بس.
2. **مجلد رئيسي مختلف** (الأسهل يصير): النسخة السابقة `demo/course.py`، والـ zip الجديد `course.py`
   (انضغطت الملفات من جوّا المجلد). النتيجة: كل الملفات `deleted`، وكلها بترجع `new`، وبينقطع تاريخ كل ملف.

النسخ القديمة ما بتنلمس، بس بتنعمل نسخة غلط.

## التعديل

**خدمة الـ AI:**

- `core_ai/services/project_versioning.py`: `check_deletions(prev_entries, uploaded_paths)`.
  بيرجّع `None` إذا الرفع آمن، وإلا شو كان رح ينحذف، ومعه تلميح المجلد الرئيسي إذا لقى فرق
  (`top_folder: {"top_folder": "demo/", "zip_has_it": false}`).
- القاعدة: **حذف ملفين أو أكتر، ونص النسخة السابقة أو أكتر** ← بيحتاج تأكيد. أول نسخة ما بتنفحص.
- `core_ai/views/folder_upload.py`: برفع `full`، **قبل ما ينحفظ أي شي**: إذا الفحص طلّع خطر وما في
  `confirm_deletions=true` ← **409** `mass_deletion`، وما بينحفظ ولا ملف ولا نسخة.
- الرفع الجزئي (ملفات لحالها، GitHub) ما بينفحص، لأنو ما بيحذف إلا يلي بـ `deleted_paths`.

**UPM:**

- `views/folder_upload_proxy.py`: بيقرا `confirm_deletions` وبيمرّره للمهمة.
- `celery_tasks/upload_tasks.py`: بيبعته لخدمة الـ AI. ولما يرجع 409، المهمة **بتوقف بدون إعادة محاولة**
  (قبل كانت أي غلطة بتنعاد 3 مرات) وبترجع `status: rejected` مع السبب.
- `views/task_status_view.py`: مهمة `rejected` بتطلع بـ `GET /api/upm/tasks/<id>/` بـ **409** ومعها
  `error` و `would_delete` و `top_folder` (قبل كانت رح تطلع `completed`).

## الاختبارات

`core_ai/tests/test_folder_upload_versions.py` (7 جداد، على الـ view كامل بـ MongoDB مزيّف):

| الاختبار | النتيجة |
|---|---|
| حذف 1 من 3 | 201، بدون سؤال |
| حذف 2 من 3 | 409، ولا نسخة ولا ملف انحفظ |
| نفس الشي مع `confirm_deletions=true` | 201، الملفين محذوفين |
| zip بدون `demo/` | 409 مع "missing the top folder 'demo/'" |
| zip بمجلد زيادة `project/` | 409 مع `zip_has_it: true` |
| أول نسخة | 201 |
| رفع جزئي | ما بينفحص، 201 |

`core_ai/tests/test_project_versioning.py` (5 جداد على `check_deletions`): أقل من النص، النص أو أكتر،
ملف واحد بس، أول نسخة، والمجلد الرئيسي الناقص والزايد.

كل الاختبارات: **528 passed**. (UPM ما فيه إعداد اختبارات، فانجرب حقيقي.)

## تجربة حقيقية

zip نسخة 2 من `demo3` بس بدون مجلد `demo/` (`student.py`، `course.py`، `main.py`)، انرفع من UPM:

```
POST /api/upm/projects/c0e34dfa-.../folder-upload/      → task ff6b9f27-...
GET  /api/upm/tasks/ff6b9f27-.../                       → 409
{
 "status": "rejected",
 "error": "This upload would delete 3 of the 3 files of the previous version. Nothing was saved.
           If that is what you want, upload again with confirm_deletions=true. The zip seems to be
           missing the top folder 'demo/' that the previous version had: zip the folder itself, not its contents.",
 "code": "mass_deletion",
 "would_delete": ["demo/course.py", "demo/main.py", "demo/student.py"],
 "top_folder": {"top_folder": "demo/", "zip_has_it": false}
}
```

عدد النسخ قبل وبعد: **6**. والمهمة خلصت بمرة وحدة بدون إعادة محاولة.

ما جربنا `confirm_deletions=true` حقيقي، لأنو كان رح يعمل نسخة 7 كلها محذوفة بـ demo3. الاختبارات بتغطيه.

## حدود

- **الفرونت** بعد رفع zip ما بيقرا حالة المهمة، بيستنى الملفات توصل لخدمة الـ AI. فإذا انرفض الرفع،
  المستخدم رح يشوف انتهاء وقت الانتظار، مش الرسالة. وما في زر "أكّد الحذف". هاد للملاحظة لأريج.
- بأول تجربة طلع مرة وحدة 401 "Token is invalid" على قراءة حالة المهمة بتوكن كان شغّال قبل ثواني.
  ما تكرر بـ 8 محاولات بعدها، وما إلو علاقة بهالتعديل (التحقق من التوكن بـ UPM نفسه).

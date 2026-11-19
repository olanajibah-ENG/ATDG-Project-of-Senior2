# تحديث لستة النماذج بـ `llm_client.py`

التاريخ: 18/11/2026

## المشكلة

`core_ai/ai_engine/llm_client.py` هو المكان الوحيد يلي بيكلّم النموذج (الشرح، كشف التعارض، توليد الاختبارات).
فيه لستة نماذج مجانية من OpenRouter، بيجربهن بالترتيب لحتى واحد يجاوب.

قارنّا اللستة مع `https://openrouter.ai/api/v1/models` ومع الـ logs:

| النموذج | موجود؟ | بالـ logs |
|---|---|---|
| `poolside/laguna-s-2.1:free` (الأول) | ❌ انشال | 404 |
| `google/gemma-4-31b-it:free` | ✅ | 429 |
| `google/gemma-4-26b-a4b-it:free` | ✅ | 429 |
| `nvidia/nemotron-3-nano-omni:free` | ❌ تغيّر اسمه | 400 "not a valid model ID"، 16 مرة |
| `z-ai/glm-5.2:free` | ❌ صار بمصاري بس | 404 |
| `cohere/north-mini-code:free` | ✅ | الوحيد يلي جاوب (11 مرة) |
| `poolside/laguna-xs-2.1:free` | ❌ انشال | 404 |

وخطأ 400 تبع "not a valid model ID" ما كان يريّح النموذج، فكان ينجرب بكل طلب.

## التعديل

**1. اللستة:**

| الترتيب | النموذج | ملاحظة |
|---|---|---|
| 1 | `poolside/laguna-s-2.1:free` | **بيضل بطلب منك**، لأنو نموذج التقييم. ما عاد موجود: بياخد 404 وبيرتاح ساعة، يعني طلب ضايع بالساعة |
| 2 | `cohere/north-mini-code:free` | يلي جاوب بتجاربنا |
| 3 | `google/gemma-4-31b-it:free` | |
| 4 | `google/gemma-4-26b-a4b-it:free` | |
| 5 | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | الاسم الجديد لـ nemotron-3-nano-omni. ما انجرب لسا |
| 6 | `nvidia/nemotron-3-ultra-550b-a55b:free` | احتياط. ما انجرب لسا |

انشالوا: `nvidia/nemotron-3-nano-omni:free`، `z-ai/glm-5.2:free`، `poolside/laguna-xs-2.1:free`.

**2. خطأ 400 "not a valid model ID"** صار يتعامل متل 404: النموذج بيرتاح ساعة. أي 400 تاني (غلط بالطلب
نفسه، متل prompt طويل) بيضل متل ما هو، بدون راحة.

## الاختبارات

4 اختبارات جديدة بـ `core_ai/tests/test_llm_client_ex.py` (بدون إنترنت، بردود مزيّفة):

| الاختبار | شو بيفحص |
|---|---|
| `test_invalid_model_id_400_rests_that_model_and_moves_on` | 400 "not a valid model ID" ← النموذج بيرتاح ساعة والطلب بينتقل للتاني |
| `test_a_rested_invalid_model_is_not_tried_again` | نموذج مرتاح ما بينبعتلو طلب |
| `test_other_400_does_not_rest_the_model` | 400 تاني ما بيريّح النموذج |
| `test_model_list_keeps_the_evaluation_model_and_drops_the_removed_ones` | laguna-s أول، cohere تاني، والتلاتة يلي انشالوا مش موجودين |

على الملف القديم: 2 فشلوا (الـ 400 واللستة). بعد التعديل: **507 passed**.

## طلب حقيقي

بعد `docker compose restart ai_web celery_worker` و `docker restart upm_api_gateway`، بعتنا طلب واحد صغير:

```
round=1 model=poolside/laguna-s-2.1:free   → 404 "no longer available on OpenRouter" → بيرتاح 3600s
round=1 model=cohere/north-mini-code:free  → 429 "Rate limit exceeded: free-models-per-day"
round=1 model=google/gemma-4-31b-it:free   → 429 نفس الرسالة
...
```

الترتيب الجديد اشتغل متل ما بدنا، و laguna-s ارتاح ساعة. بس **ما قدرنا نتأكد إنو في نموذج بيجاوب**، لأنو حساب
OpenRouter وصل للحد اليومي للطلبات المجانية (`X-RateLimit-Limit: 50`، `Remaining: 0`). هاد الحد على الحساب كلو،
مش على نموذج واحد.

## شو بيعني الحد اليومي

- الحساب المجاني بدون رصيد إلو **50 طلب باليوم** لكل النماذج المجانية مع بعض.
- لما يخلص، كل النماذج بترجع 429. والكود الحالي بيفكّر إنو كل نموذج مشغول، فبيريّحه دقيقتين وبيجرب
  التاني، وبيعيد اللفة مرتين بعد استراحة 20 ثانية. يعني كل طلب بيضيّع وقت قبل ما يفشل.
- هاد ممكن يكون سبب جزء من رسائل "All free models are busy" يلي شفناها قبل.

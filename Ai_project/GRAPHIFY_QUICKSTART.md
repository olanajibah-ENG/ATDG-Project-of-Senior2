# 🚀 Graphify Quick Start Guide

## اختبار سريع للتأكد من التنفيذ

### الخطوة 1: تشغيل الاختبارات

```bash
cd Ai_project
python test_graphify_implementation.py
```

**النتيجة المتوقعة**:
```
==================================================================
🔥 GRAPHIFY IMPLEMENTATION TEST SUITE
==================================================================

==================================================================
Test 1: Java Processor - Calls Extraction
==================================================================

✓ Nodes count: 5
✓ Edges count: 3
✓ Source: java-ast

✓ Total calls edges: 1
✓ EXTRACTED calls: 1

✅ EXTRACTED calls found:
   OrderService.placeOrder --calls--> OrderService.calculateTotal

----------------------------------------------------------------------
Graph Summary for Prompt:
----------------------------------------------------------------------
--- CODE STRUCTURE GRAPH (FROM AST) ---
Source: java-ast
...

✅ No forbidden phrases found in summary

==================================================================
Test 2: Python Processor - Calls Extraction
==================================================================
...

🎉 All tests passed!
```

---

### الخطوة 2: اختبار يدوي بسيط

قم بإنشاء ملف `test_simple.py` في Ai_project:

```python
from core_ai.language_processors.python_processor import PythonProcessor
from core_ai.ai_engine.orchestrator import graph_to_prompt_summary

# كود بايثون بسيط
code = """
class Calculator:
    def add(self, a, b):
        result = self.validate(a, b)
        return a + b
    
    def validate(self, x, y):
        return x > 0 and y > 0
"""

# تحليل
processor = PythonProcessor()
ast_data = processor.parse_source_code(code)
features = processor.extract_features(ast_data)
graph = processor.generate_dependency_graph_data(ast_data, features)

# عرض النتائج
print("🔍 Dependency Graph:")
print(f"Nodes: {len(graph['nodes'])}")
print(f"Edges: {len(graph['edges'])}")
print(f"\n📊 Edges:")
for edge in graph['edges']:
    print(f"  {edge['from']} --{edge['relation']}--> {edge['to']} ({edge['confidence']})")

# تحويل لملخص
print(f"\n📝 Graph Summary for Prompt:\n")
print(graph_to_prompt_summary(graph))
```

شغّله:
```bash
python test_simple.py
```

---

### الخطوة 3: التحقق من المسار الكامل

#### 1. تشغيل السيرفر (Docker)
```bash
docker-compose up
```

#### 2. رفع ملف للتحليل (عبر API)

**ملف Python بسيط** (`example.py`):
```python
class User:
    def __init__(self, name):
        self.name = name
    
    def greet(self):
        return self.say_hello()
    
    def say_hello(self):
        return f"Hello, {self.name}"
```

رفعه:
```bash
curl -X POST http://localhost:8000/api/analyze/upload \
  -F "file=@example.py" \
  -F "file_type=python"
```

#### 3. انتظار اكتمال التحليل

احصل على analysis_id من الاستجابة، ثم:
```bash
curl http://localhost:8000/api/analyze/status/{analysis_id}
```

#### 4. التحقق من dependency_graph في MongoDB

```bash
# الدخول لـ MongoDB
docker exec -it <mongo_container> mongosh

# التحقق
use your_database
db.analysis_results.findOne(
  {_id: ObjectId("...")}, 
  {dependency_graph: 1}
)
```

**يجب أن ترى**:
```json
{
  "dependency_graph": {
    "nodes": [
      {"id": "User", "label": "User", "type": "class", "local": true},
      {"id": "User.greet", "label": "greet()", "type": "method", ...},
      {"id": "User.say_hello", "label": "say_hello()", "type": "method", ...}
    ],
    "edges": [
      {
        "from": "User.greet",
        "to": "User.say_hello",
        "relation": "calls",
        "confidence": "EXTRACTED"
      }
    ],
    "meta": {
      "source": "python-ast",
      "total_nodes": 3,
      "total_edges": 1
    }
  }
}
```

#### 5. طلب شرح منطقي

```bash
curl -X POST http://localhost:8000/api/explain/generate \
  -H "Content-Type: application/json" \
  -d '{
    "analysis_id": "...",
    "explanation_type": "low_level"
  }'
```

#### 6. التحقق من وجود الـ Graph في الشرح

افحص الـ logs للبحث عن:
```
[Graphify] Generated graph summary: XXX chars
```

أو افحص الشرح الناتج - يجب أن يذكر:
- علاقات calls بين الميثودات
- تدفق الاستدعاءات
- معلومات عن الـ control flow

---

### الخطوة 4: فحص الـ Logs

ابحث عن هذه الرسائل في الـ logs:

```
[Graphify] Generating unified dependency graph for Python...
[Graphify] Generated graph summary: 245 chars
```

---

## ✅ علامات النجاح

- ✅ الاختبارات تمر بنجاح (test_graphify_implementation.py)
- ✅ dependency_graph موجود في MongoDB بالشكل الموحد
- ✅ edges من نوع "calls" مع confidence "EXTRACTED" موجودة
- ✅ الشرح المنطقي يذكر علاقات calls بين الميثودات
- ✅ لا توجد عبارات "ground truth" أو "Do not invent" في الملخص

---

## ❌ علامات الفشل وحلولها

### 1. الاختبارات تفشل

**المشكلة**: `ImportError` أو `ModuleNotFoundError`

**الحل**:
```bash
# تأكد من تثبيت المتطلبات
pip install -r requirements.txt

# تأكد من PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

---

### 2. dependency_graph فارغ أو بشكل قديم

**المشكلة**: الـ graph يحتوي على `source/target` بدلاً من `from/to`

**الحل**: 
- تأكد من أنك عدلت الكود بشكل صحيح
- أعد تشغيل analyze_task
- امسح النتائج القديمة من MongoDB

---

### 3. لا توجد calls edges

**المشكلة**: الكود البسيط لا يحتوي على استدعاءات

**الحل**: استخدم كود يحتوي على calls:
```python
class Example:
    def method1(self):
        self.method2()  # هنا call
    
    def method2(self):
        pass
```

---

### 4. الملخص لا يظهر في الشرح

**المشكلة**: graph_to_prompt_summary لا يُستدعى

**الحل**:
- تحقق من orchestrator.py
- تأكد من أن الكود المُحدَّث موجود في _build_state
- أعد تشغيل السيرفر

---

## 📞 الدعم

إذا واجهت مشاكل:
1. راجع `GRAPHIFY_IMPLEMENTATION_SUMMARY.md`
2. شغّل الاختبارات: `python test_graphify_implementation.py`
3. افحص الـ logs للبحث عن `[Graphify]`

---

## 🎉 النجاح!

إذا رأيت:
```
✅ EXTRACTED calls found:
   ClassName.method1 --calls--> ClassName.method2
```

**مبروك! 🎊 Graphify يعمل بنجاح!**

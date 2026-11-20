# 🔥 Graphify - Unified Dependency Graph System

## What is Graphify?

Graphify هو نظام موحد لبناء واستهلاك **dependency graphs** من التحليل الثابت (AST) لكل اللغات المدعومة في المشروع.

### الهدف الرئيسي

استخراج علاقات **calls** من جسم الدوال/الميثودات بناءً على AST (ليس regex)، وحفظها في MongoDB، ثم استهلاكها بطريقتين:

1. **Textual Summary** - ملخص نصي يُحقن في الـ prompt للشرح المنطقي
2. **Graph Queries** - استعلامات محدودة للتست وكشف التناقض (مستقبلاً)

---

## 📐 Unified Schema

الشكل الموحد لـ `dependency_graph`:

```json
{
  "nodes": [
    {
      "id": "ClassName",
      "label": "ClassName",
      "type": "class",
      "local": true
    },
    {
      "id": "ClassName.methodName",
      "label": "methodName()",
      "type": "method",
      "parent": "ClassName",
      "local": true
    },
    {
      "id": "ext.PackageName",
      "label": "PackageName",
      "type": "external",
      "local": false
    }
  ],
  "edges": [
    {
      "from": "ClassName.methodName",
      "to": "ClassName.anotherMethod",
      "relation": "calls",
      "confidence": "EXTRACTED"
    },
    {
      "from": "ClassName",
      "to": "ext.PackageName",
      "relation": "imports",
      "confidence": "EXTRACTED"
    }
  ],
  "meta": {
    "total_nodes": 3,
    "total_edges": 2,
    "source": "java-ast"
  }
}
```

### Node Types
- `class` - كلاس محلي
- `method` - ميثود داخل كلاس
- `function` - دالة مستقلة
- `module` - موديول محلي
- `external` - مكتبة خارجية

### Edge Relations
- `calls` - استدعاء دالة/ميثود (الأهم)
- `imports` - استيراد مكتبة
- `inherits` - وراثة من كلاس آخر

### Confidence Levels
- `EXTRACTED` - واضح من الكود (استدعاء مباشر، نفس الكلاس، this.xxx)
- `INFERRED` - مخمّن من السياق (obj.method() حيث النوع غير واضح)

---

## 🚀 Quick Start

### 1. Run Tests

```bash
cd Ai_project
python test_graphify_implementation.py
```

### 2. Simple Example

```python
from core_ai.language_processors.python_processor import PythonProcessor
from core_ai.ai_engine.orchestrator import graph_to_prompt_summary

# Python code
code = """
class Calculator:
    def add(self, a, b):
        result = self.validate(a, b)
        return a + b
    
    def validate(self, x, y):
        return x > 0 and y > 0
"""

# Analyze
processor = PythonProcessor()
ast_data = processor.parse_source_code(code)
features = processor.extract_features(ast_data)
graph = processor.generate_dependency_graph_data(ast_data, features)

# Print
print(f"Nodes: {len(graph['nodes'])}")
print(f"Edges: {len(graph['edges'])}")

# Generate summary
summary = graph_to_prompt_summary(graph)
print(summary)
```

---

## 🏗️ Architecture

### Data Flow

```
Code
  ↓
Processor (Java/Python/TreeSitter/Generic)
  ↓
generate_dependency_graph_data()
  ↓
{nodes, edges, meta}
  ↓
MongoDB (field: dependency_graph)
  ↓
Orchestrator._build_state()
  ↓
graph_to_prompt_summary()
  ↓
Injected into detailed_analysis
  ↓
LowLevelAgent (sees graph in prompt)
```

### Components

1. **Processors** (`language_processors/`)
   - `java_processor.py` - استخراج calls من tree-sitter Java AST
   - `python_processor.py` - استخراج calls من Python ast.Call
   - `tree_sitter_processor.py` - دعم لغات متعددة
   - `generic_processor.py` - fallback بواسطة regex

2. **Orchestrator** (`ai_engine/orchestrator.py`)
   - `graph_to_prompt_summary()` - تحويل graph إلى ملخص نصي
   - `_build_state()` - حقن الملخص في detailed_analysis

3. **Analyzer** (`services/project_analyzer.py`)
   - استدعاء `processor.generate_dependency_graph_data()`

4. **Task** (`celery_tasks/analyze_task.py`)
   - حفظ `dependency_graph` في MongoDB

---

## 📚 Supported Languages

| Language | Processor | Calls Extraction | Priority |
|----------|-----------|------------------|----------|
| Java | JavaProcessor | ✅ tree-sitter | High |
| Python | PythonProcessor | ✅ Python AST | High |
| JavaScript | TreeSitterProcessor | ✅ tree-sitter | High |
| TypeScript | TreeSitterProcessor | ✅ tree-sitter | High |
| C++ | TreeSitterProcessor | ⚠️ tree-sitter (limited) | Medium |
| Go | TreeSitterProcessor | ⚠️ tree-sitter (limited) | Medium |
| Others | GenericProcessor | ⚠️ regex (very limited) | Low |

---

## 🎯 Features

### ✅ Implemented

- [x] Unified schema for all languages
- [x] Calls extraction from method/function body
- [x] Confidence levels (EXTRACTED/INFERRED)
- [x] Imports tracking
- [x] Inheritance tracking
- [x] Graph to text summary conversion
- [x] Injection into LowLevelAgent prompt
- [x] Safe phrasing (no forbidden phrases)
- [x] Comprehensive tests
- [x] Full documentation

### ⏳ Planned (Future)

- [ ] Graph queries (get_neighbors, find_path)
- [ ] Method chaining support
- [ ] ETF measurement (before/after)
- [ ] Visual graph viewer
- [ ] Enhanced INFERRED → EXTRACTED conversion

---

## 📖 Documentation

- **[GRAPH_SCHEMA.md](GRAPH_SCHEMA.md)** - Schema specification
- **[GRAPHIFY_IMPLEMENTATION_SUMMARY.md](GRAPHIFY_IMPLEMENTATION_SUMMARY.md)** - Detailed implementation guide
- **[GRAPHIFY_QUICKSTART.md](GRAPHIFY_QUICKSTART.md)** - Quick start guide
- **[CHANGELOG_GRAPHIFY.md](CHANGELOG_GRAPHIFY.md)** - Change history

---

## 🧪 Testing

### Run all tests:
```bash
python test_graphify_implementation.py
```

### Tests included:
1. **Java Calls Extraction** - verifies calls from Java code
2. **Python Calls Extraction** - verifies calls from Python code
3. **Schema Compliance** - verifies unified schema structure
4. **Forbidden Phrases** - ensures no banned phrases in summary

### Expected output:
```
🎉 All tests passed!
Total: 3/3 tests passed
```

---

## 🔍 Example Output

### Input (Java):
```java
public class OrderService {
    public void placeOrder() {
        calculateTotal();
    }
    
    private double calculateTotal() {
        return 100.0;
    }
}
```

### Graph Summary (in LowLevelAgent prompt):
```
--- CODE STRUCTURE GRAPH (FROM AST) ---
Source: java-ast
Total Nodes: 3, Total Edges: 1

Confirmed relationships (EXTRACTED from AST):
  OrderService.placeOrder --calls--> OrderService.calculateTotal

Note: The above relationships are confirmed from static analysis (AST).
Additional relationships (especially dynamic calls) may exist but were not detected.
Prefer confirmed relationships when analyzing control flow.
--- END GRAPH ---
```

---

## ⚙️ Configuration

### Max Edges in Summary
```python
# في orchestrator.py
graph_summary = graph_to_prompt_summary(
    dependency_graph, 
    focus_ids=None,  # optional: filter by specific IDs
    max_edges=50     # limit to avoid token budget overflow
)
```

### Confidence Rules
- **EXTRACTED**: `this.method()`, `ClassName.method()`, same-class calls
- **INFERRED**: `obj.method()` where type is unclear

---

## 🐛 Troubleshooting

### No calls edges found?
- Check if code actually has method calls
- Verify processor is initialized correctly
- Run tests to confirm extraction works

### Graph not injected in explanation?
- Check orchestrator logs for `[Graphify]` messages
- Verify `dependency_graph` exists in MongoDB
- Restart server after code changes

### Forbidden phrases in summary?
- Check `graph_to_prompt_summary()` implementation
- Run test: `python test_graphify_implementation.py`

---

## 🤝 Contributing

### Adding a new language:
1. Check if tree-sitter supports it
2. If yes: add to `SUPPORTED_LANGUAGES` in `tree_sitter_processor.py`
3. If no: create dedicated processor like `JavaProcessor`
4. Update `ProcessorFactory`
5. Add tests

### Improving calls extraction:
1. Identify missed patterns in AST
2. Update processor's call extraction logic
3. Add test case
4. Update documentation

---

## 📊 Performance

### Extraction Time
- **Java**: ~50-200ms for typical file
- **Python**: ~30-100ms for typical file
- **Tree-sitter**: varies by language

### Memory
- Graph size: ~1-10KB for typical file
- Summary size: ~200-2000 chars (50 edges max)

### Token Budget
- Average impact: +50-100 tokens to prompt
- Max impact: +200 tokens (with 50 edges)

---

## 🎓 Key Concepts

### Why EXTRACTED vs INFERRED?

**EXTRACTED** = واضح 100% من الكود:
```java
this.calculateTotal()  // EXTRACTED - we know it's in same class
```

**INFERRED** = مخمن من السياق:
```java
service.processOrder()  // INFERRED - service type unclear from this line
```

### Why separate calls from imports?

- **imports** = static dependencies (what libraries are used)
- **calls** = runtime behavior (what functions call each other)

These are different concepts and should not be mixed.

### Why max 50 edges?

To prevent token budget overflow. A large file may have hundreds of calls, but only the most relevant 50 are needed for explanation.

---

## 🏆 Success Criteria

✅ Graphify is successful when:
- Tests pass
- MongoDB has `dependency_graph` with correct schema
- Calls edges exist with `EXTRACTED` confidence
- LowLevelAgent sees graph summary in prompt
- Explanations mention control flow based on graph

---

## 📞 Support

Need help?
1. Read documentation: `GRAPHIFY_QUICKSTART.md`
2. Run tests: `python test_graphify_implementation.py`
3. Check logs: search for `[Graphify]`
4. Review schema: `GRAPH_SCHEMA.md`

---

## 📄 License

Part of ATDG Project - Senior Year Project

---

## 🙏 Acknowledgments

Built with:
- tree-sitter (Java, JS, TS, and more)
- Python ast module
- MongoDB
- Django

---

**🎉 Graphify - Making code dependencies visible and consumable!**

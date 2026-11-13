# Graphify Unified Schema
## قواعد الشكل الموحد لـ dependency_graph

### الشكل النهائي الثابت

```json
{
  "nodes": [
    {"id": "ClassName", "label": "ClassName", "type": "class", "local": true},
    {"id": "ClassName.methodName", "label": "methodName()", "type": "method", "parent": "ClassName", "local": true},
    {"id": "ext.PackageName", "label": "PackageName", "type": "external", "local": false}
  ],
  "edges": [
    {"from": "ClassName.methodName", "to": "ClassName.anotherMethod", "relation": "calls", "confidence": "EXTRACTED"},
    {"from": "ClassName", "to": "ext.PackageName", "relation": "imports", "confidence": "EXTRACTED"}
  ],
  "meta": {
    "total_nodes": 3,
    "total_edges": 2,
    "source": "tree-sitter" // or "python-ast" or "java-ast" or "regex"
  }
}
```

### قواعد الـ ID

- **كلاس**: `ClassName`
- **ميثود**: `ClassName.methodName`
- **دالة module-level**: `functionName` أو `module.functionName`
- **خارجي**: `ext.PackageOrModule`

### قواعد confidence

- **EXTRACTED**: استدعاء واضح من الكود (import مباشر / معروف static / نفس الكلاس / this.xxx)
- **INFERRED**: عندما النوع غير معروف بدقة (obj.method() حيث النوع غير واضح)

### أنواع الـ Nodes

- `class`: كلاس محلي
- `method`: ميثود داخل كلاس
- `function`: دالة مستقلة
- `module`: موديول محلي
- `external`: مكتبة خارجية

### أنواع الـ Edges الإلزامية

- **calls**: استدعاء دالة/ميثود (الأهم — من جسم الدالة)
- **imports**: استيراد مكتبة
- **inherits**: وراثة من كلاس آخر

### القواعد الممنوعة

❌ **ممنوع**: خلط imports مع calls
✅ **صحيح**: فصل واضح بين relation types

### Priority Order

1. استخرج calls من جسم الدالة/الميثود (عالية الأولوية)
2. استخرج imports
3. استخرج inherits
4. حدد confidence بناءً على الوضوح

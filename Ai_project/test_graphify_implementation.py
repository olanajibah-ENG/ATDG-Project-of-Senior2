"""
Test Graphify Implementation
اختبار بسيط للتحقق من أن dependency_graph يُبنى بالشكل الموحد مع calls edges
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core_ai.language_processors.java_processor import JavaProcessor
from core_ai.language_processors.python_processor import PythonProcessor
from core_ai.language_processors.tree_sitter_processor import TreeSitterProcessor
from core_ai.language_processors.generic_processor import GenericProcessor
from core_ai.ai_engine.orchestrator import graph_to_prompt_summary


def test_java_calls_extraction():
    """اختبار استخراج calls من Java"""
    print("\n" + "="*70)
    print("Test 1: Java Processor - Calls Extraction")
    print("="*70)
    
    java_code = """
    public class OrderService {
        public void placeOrder() {
            calculateTotal();
            System.out.println("Order placed");
        }
        
        private double calculateTotal() {
            return 100.0;
        }
    }
    """
    
    processor = JavaProcessor()
    processor.init()
    
    ast_data = processor.parse_source_code(java_code)
    features = processor.extract_features(ast_data)
    graph = processor.generate_dependency_graph_data(ast_data, features)
    
    print(f"\n✓ Nodes count: {len(graph.get('nodes', []))}")
    print(f"✓ Edges count: {len(graph.get('edges', []))}")
    print(f"✓ Source: {graph.get('meta', {}).get('source', 'unknown')}")
    
    # التحقق من وجود calls edges
    calls_edges = [e for e in graph.get('edges', []) if e.get('relation') == 'calls']
    extracted_calls = [e for e in calls_edges if e.get('confidence') == 'EXTRACTED']
    
    print(f"\n✓ Total calls edges: {len(calls_edges)}")
    print(f"✓ EXTRACTED calls: {len(extracted_calls)}")
    
    if extracted_calls:
        print("\n✅ EXTRACTED calls found:")
        for edge in extracted_calls:
            print(f"   {edge.get('from')} --calls--> {edge.get('to')}")
    else:
        print("\n⚠️  WARNING: No EXTRACTED calls edges found!")
    
    # اختبار graph_to_prompt_summary
    print("\n" + "-"*70)
    print("Graph Summary for Prompt:")
    print("-"*70)
    summary = graph_to_prompt_summary(graph)
    print(summary)
    
    # التحقق من عدم وجود عبارات ممنوعة
    forbidden_phrases = ["ground truth", "Do not invent"]
    for phrase in forbidden_phrases:
        if phrase in summary:
            print(f"\n❌ ERROR: Found forbidden phrase '{phrase}' in summary!")
            return False
    
    print("\n✅ No forbidden phrases found in summary")
    
    return len(extracted_calls) > 0


def test_python_calls_extraction():
    """اختبار استخراج calls من Python"""
    print("\n" + "="*70)
    print("Test 2: Python Processor - Calls Extraction")
    print("="*70)
    
    python_code = """
class Calculator:
    def add(self, a, b):
        result = self.validate(a, b)
        return a + b
    
    def validate(self, x, y):
        return x > 0 and y > 0

def main():
    calc = Calculator()
    calc.add(5, 3)
"""
    
    processor = PythonProcessor()
    
    ast_data = processor.parse_source_code(python_code)
    features = processor.extract_features(ast_data)
    graph = processor.generate_dependency_graph_data(ast_data, features)
    
    print(f"\n✓ Nodes count: {len(graph.get('nodes', []))}")
    print(f"✓ Edges count: {len(graph.get('edges', []))}")
    print(f"✓ Source: {graph.get('meta', {}).get('source', 'unknown')}")
    
    # التحقق من وجود calls edges
    calls_edges = [e for e in graph.get('edges', []) if e.get('relation') == 'calls']
    extracted_calls = [e for e in calls_edges if e.get('confidence') == 'EXTRACTED']
    
    print(f"\n✓ Total calls edges: {len(calls_edges)}")
    print(f"✓ EXTRACTED calls: {len(extracted_calls)}")
    
    if extracted_calls:
        print("\n✅ EXTRACTED calls found:")
        for edge in extracted_calls:
            print(f"   {edge.get('from')} --calls--> {edge.get('to')}")
    else:
        print("\n⚠️  WARNING: No EXTRACTED calls edges found!")
    
    # اختبار graph_to_prompt_summary
    print("\n" + "-"*70)
    print("Graph Summary for Prompt:")
    print("-"*70)
    summary = graph_to_prompt_summary(graph)
    print(summary)
    
    return len(extracted_calls) > 0


def test_unified_schema_compliance():
    """اختبار التزام الشكل الموحد"""
    print("\n" + "="*70)
    print("Test 3: Unified Schema Compliance")
    print("="*70)
    
    python_code = "def hello(): print('hi')"
    processor = PythonProcessor()
    
    ast_data = processor.parse_source_code(python_code)
    features = processor.extract_features(ast_data)
    graph = processor.generate_dependency_graph_data(ast_data, features)
    
    # التحقق من البنية المطلوبة
    required_keys = ['nodes', 'edges', 'meta']
    for key in required_keys:
        if key not in graph:
            print(f"❌ ERROR: Missing required key '{key}'")
            return False
        print(f"✓ Key '{key}' exists")
    
    # التحقق من meta
    meta = graph.get('meta', {})
    if 'source' not in meta:
        print("❌ ERROR: Missing 'source' in meta")
        return False
    print(f"✓ Meta contains source: {meta.get('source')}")
    
    # التحقق من بنية nodes
    nodes = graph.get('nodes', [])
    if nodes:
        first_node = nodes[0]
        required_node_keys = ['id', 'label', 'type', 'local']
        for key in required_node_keys:
            if key not in first_node:
                print(f"⚠️  WARNING: Node missing key '{key}'")
    
    # التحقق من بنية edges
    edges = graph.get('edges', [])
    if edges:
        first_edge = edges[0]
        required_edge_keys = ['from', 'to', 'relation', 'confidence']
        for key in required_edge_keys:
            if key not in first_edge:
                print(f"❌ ERROR: Edge missing required key '{key}'")
                return False
        print(f"✓ Edge structure is correct")
        
        # التحقق من قيم confidence
        confidence = first_edge.get('confidence')
        if confidence not in ['EXTRACTED', 'INFERRED']:
            print(f"❌ ERROR: Invalid confidence value '{confidence}'")
            return False
        print(f"✓ Valid confidence value: {confidence}")
    
    print("\n✅ Schema compliance check passed!")
    return True


def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("🔥 GRAPHIFY IMPLEMENTATION TEST SUITE")
    print("="*70)
    
    results = []
    
    try:
        results.append(("Java Calls Extraction", test_java_calls_extraction()))
    except Exception as e:
        print(f"\n❌ Java test failed: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Java Calls Extraction", False))
    
    try:
        results.append(("Python Calls Extraction", test_python_calls_extraction()))
    except Exception as e:
        print(f"\n❌ Python test failed: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Python Calls Extraction", False))
    
    try:
        results.append(("Schema Compliance", test_unified_schema_compliance()))
    except Exception as e:
        print(f"\n❌ Schema test failed: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Schema Compliance", False))
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{status}: {test_name}")
    
    passed_count = sum(1 for _, p in results if p)
    total_count = len(results)
    
    print(f"\nTotal: {passed_count}/{total_count} tests passed")
    
    if passed_count == total_count:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print("\n⚠️  Some tests failed. Please review the output above.")
        return 1


if __name__ == "__main__":
    exit(main())

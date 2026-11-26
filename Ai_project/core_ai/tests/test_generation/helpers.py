"""Builds stored-analysis documents for tests by running the REAL analyser on small source files,
so fixtures cannot drift from what analysis actually stores."""
import os

SOURCES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "sources")


def put_record(repo, status="pending", **fields):
    from core_ai.models.testgen import new_record

    unit = {"id": "a.py::f", "file": "a.py", "body_hash": "h1"}
    record = new_record("job_1", unit, "unit")
    record.update(fields, status=status)
    repo.create_many([record])
    return record["record_id"]


def load_source(name):
    with open(os.path.join(SOURCES_DIR, name), encoding="utf-8") as handle:
        return handle.read()


def build_analysis(source):
    """A dict shaped like one `analysis_results` document."""
    from core_ai.language_processors.python_processor import PythonProcessor

    processor = PythonProcessor()
    ast_data = processor.parse_source_code(source)
    features = processor.extract_features(ast_data)
    return {
        "status": "COMPLETED",
        "ast_structure": ast_data,
        "extracted_features": features,
        "dependencies": processor.extract_dependencies(ast_data),
        "dependency_graph": processor.generate_dependency_graph_data(ast_data, features),
        "class_diagram_data": processor.generate_class_diagram_data(ast_data, features),
    }

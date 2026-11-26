"""Language adapter: everything that depends on the language of the code under test.

Python is the only language of this feature for now. A second language is one more adapter class
and one more line in `_REGISTRY`.
"""
from abc import ABC, abstractmethod

from core_ai.services.test_generation.languages import python_adapter


class LanguageAdapter(ABC):
    name = ""
    test_framework = ""

    @abstractmethod
    def supports(self, file_type, path=None): ...

    @abstractmethod
    def list_units(self, path, analysis): ...

    @abstractmethod
    def find_entry(self, analysis, unit_id): ...

    @abstractmethod
    def import_statement(self, path, name): ...

    @abstractmethod
    def allowed_import_roots(self, project_paths): ...

    @abstractmethod
    def prompt_rules(self): ...


class PythonAdapter(LanguageAdapter):
    name = "python"
    test_framework = "pytest"

    def supports(self, file_type, path=None):
        return python_adapter.is_python(file_type, path)

    def list_units(self, path, analysis):
        return python_adapter.list_units(path, analysis)

    def find_entry(self, analysis, unit_id):
        return python_adapter.find_entry(analysis, unit_id)

    def import_statement(self, path, name):
        return python_adapter.import_statement(path, name)

    def allowed_import_roots(self, project_paths):
        return python_adapter.project_import_roots(project_paths)

    def prompt_rules(self):
        return [
            "Write pytest tests in plain functions, not in classes.",
            "Import the code under test with the import statement given in the context.",
            "Use only the Python standard library, pytest and the project's own modules.",
            "Do not use the network, start processes, sleep, or call eval/exec.",
            "Write files only under pytest's tmp_path fixture.",
            "Every test function must call the unit under test and contain at least one assert "
            "(or pytest.raises).",
        ]


_REGISTRY = [PythonAdapter()]


def adapter_for(file_type, path=None):
    for adapter in _REGISTRY:
        if adapter.supports(file_type, path):
            return adapter
    return None

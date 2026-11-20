"""One strategy per test level. Levels differ in three things only: what is planned, what context
is built, and what the model is told. Everything after the prompt is shared.
"""
import json
from abc import ABC, abstractmethod

from core_ai.services.test_generation import context as context_module


class TestKindStrategy(ABC):
    __test__ = False          # not a pytest test class, despite the name

    level = ""
    prompt_version = ""

    @abstractmethod
    def build_context(self, unit, analyses_by_path, adapter):
        """→ the context dict for one work item, or None when it cannot be built."""

    @abstractmethod
    def prompt_sections(self):
        """→ (system_text, user_template)."""

    def test_name_rule(self, unit_id):
        return f"test_{context_module.test_name_stem(unit_id)}__{self.level}_<n>"

    def build_prompt(self, context, adapter):
        system, template = self.prompt_sections()
        user = template.format(
            context_json=json.dumps(context, indent=2, ensure_ascii=False, default=str),
            rules="\n".join(f"- {rule}" for rule in adapter.prompt_rules()),
            test_name=context["rules"]["test_name"],
        )
        return system, user

    def request_hash(self, context):
        return context_module.context_hash(context, self.prompt_version)

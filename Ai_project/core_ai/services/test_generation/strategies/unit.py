from core_ai.services.test_generation import context as context_module
from core_ai.services.test_generation.prompts import unit as unit_prompt
from core_ai.services.test_generation.statuses import Level
from core_ai.services.test_generation.strategies.base import TestKindStrategy


class UnitStrategy(TestKindStrategy):
    """One function or method: its code, its class, and the signatures of what it calls."""

    level = Level.UNIT
    prompt_version = unit_prompt.PROMPT_VERSION

    def build_context(self, unit, analyses_by_path, adapter):
        return context_module.build_unit_context(unit, analyses_by_path, adapter, level=self.level)

    def prompt_sections(self):
        return unit_prompt.SYSTEM, unit_prompt.USER_TEMPLATE

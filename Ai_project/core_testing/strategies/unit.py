from core_testing import context as context_module
from core_testing.prompts import unit as unit_prompt
from core_testing.statuses import Level
from core_testing.strategies.base import TestKindStrategy


class UnitStrategy(TestKindStrategy):
    """One function or method: its code, its class, and the signatures of what it calls."""

    level = Level.UNIT
    prompt_version = unit_prompt.PROMPT_VERSION

    def build_context(self, unit, analyses_by_path, adapter):
        return context_module.build_unit_context(unit, analyses_by_path, adapter, level=self.level)

    def prompt_sections(self):
        return unit_prompt.SYSTEM, unit_prompt.USER_TEMPLATE

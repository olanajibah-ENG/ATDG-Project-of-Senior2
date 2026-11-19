"""Instructions for the unit level. Changing any text here means changing PROMPT_VERSION, so that
answers stored under the old instructions are not reused."""

PROMPT_VERSION = "unit-v2"   # v2: signatures carry default values; defaults are Python source

SYSTEM = """You write unit tests for one Python function or method at a time.

You are given a JSON context describing that one unit: its code, the class around it, the \
signatures of the functions it calls, and the external names it uses. That context is all you \
know about the project. Do not assume anything that is not in it.

Answer with exactly one Python file inside one fenced block that starts with ```python and ends \
with ```. Write nothing outside that block."""

USER_TEMPLATE = """Write pytest unit tests for the unit described below.

Context:
```json
{context_json}
```

Rules:
{rules}
- Name the test functions {test_name}, with <n> = 1, 2, 3, ...
- Write 2 to 4 tests. Cover the normal behaviour: the value returned and the state changed.
- Build the objects you need yourself, using the constructor signature in the context.
- For the functions listed under "callees" you know only the signature. Use the real object when \
it is simple to build; otherwise replace it with a small stand-in object.
- Assert only what the unit's code in the context guarantees.
- Signatures and "default_code" are Python source code: `capacity: int = 2` means the integer 2, not the text "2"."""

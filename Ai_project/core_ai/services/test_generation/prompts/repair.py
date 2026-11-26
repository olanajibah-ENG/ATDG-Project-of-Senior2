import json
import re
from dataclasses import dataclass

from django.conf import settings

PROMPT_VERSION = "repair-v1"
SYSTEM = """Decide whether the failure comes from the generated test or the implementation under test.
If the assertion matches the documented contract and fixing the failure would require editing the
application function, report suspect_code. Leave both files unchanged. Reply with
exactly these four lines, replacing the placeholders:
VERDICT: suspect_code
LOCATION: <file and failing branch>
EXPECTED: <documented behaviour>
EXPLANATION: <observed result and why the implementation contradicts the contract>

Use fix_test only when the test itself is wrong. Reply with VERDICT: fix_test, then REASON: and a
nonempty explanation on that same line, followed by one fenced python block containing the complete
pytest test file. Import the application function in that file. Never redefine it."""


@dataclass
class RepairAnswer:
    verdict: str
    reason: str = ""
    code: str = ""
    location: str = ""
    expected: str = ""
    explanation: str = ""


def build(context, failure, adapter):
    limit = settings.TESTGEN_REPAIR_OUTPUT_CHARS
    rejection = failure.get("last_rejection")
    prefix = (f"Your previous fix was rejected: {rejection['rule']}\n{rejection.get('detail', '')}\n{rejection['code'][:limit]}\n"
              if rejection else "")
    payload = dict(context=context, cause=failure["reason_code"], detail=failure.get("reason_detail"),
                   failing_test=failure.get("test_code"), failures=failure.get("tests", []),
                   output=(failure.get("output") or "")[:limit], rules=adapter.prompt_rules())
    return SYSTEM, prefix + json.dumps(payload, ensure_ascii=False, default=str)


def parse(text):
    fix = re.fullmatch(r"VERDICT:\s*fix_test\s*\nREASON:[ \t]*([^\n]+)\n\s*```python\s*\n(.+?)\n```", text.strip(), re.S)
    if fix and fix[1].strip():
        return RepairAnswer("fix_test", reason=fix[1].strip(), code=fix[2])
    suspect = re.fullmatch(r"VERDICT: *suspect_code\s*\nLOCATION: *([^\n]+)\nEXPECTED: *([^\n]+)\nEXPLANATION: *(.+)", text.strip(), re.S)
    if suspect and all(part.strip() for part in suspect.groups()):
        return RepairAnswer("suspect_code", location=suspect[1], expected=suspect[2], explanation=suspect[3])
    return RepairAnswer("invalid")

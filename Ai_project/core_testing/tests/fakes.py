"""A scripted stand-in for the language model. No test ever reaches a real one."""
import json
import re

_CONTEXT = re.compile(r"```json\n(.*?)\n```", re.DOTALL)


def context_in(user_prompt):
    """The context JSON that was put into the prompt."""
    return json.loads(_CONTEXT.search(user_prompt).group(1))


def good_answer(context):
    """A small, well-formed test for whatever unit the context describes."""
    unit = context["unit"]
    cls = context["class"]["name"] if context.get("class") else None
    name = unit["name"]
    if cls is None:
        call = f"{name}()"
    elif name == "__init__" or (name.startswith("__") and name.endswith("__")):
        call = f"{cls}()"
    else:
        call = f"object.__new__({cls}).{name}()"
    return (
        "Here is the test.\n\n```python\n"
        "import pytest\n"
        f"{unit['import_statement']}\n\n\n"
        "def test_it_runs():\n"
        "    try:\n"
        f"        {call}\n"
        "    except Exception:\n"
        "        pass\n"
        "    assert True\n\n\n"
        "def test_again():\n"
        "    with pytest.raises(Exception):\n"
        f"        {call}\n"
        "        raise ValueError('x')\n"
        "```\n"
    )


class FakeModel:
    """Callable with the signature of LLMClient.call_model_ex.

    answers   : {unit local name ("Student.enroll"): answer text} — overrides the good answer
    fail_from : from this call number on (1-based), raise as if every model were busy
    """

    def __init__(self, answers=None, fail_from=None):
        self.answers = answers or {}
        self.fail_from = fail_from
        self.calls = []

    def __call__(self, system_prompt, user_prompt, *, model=None, temperature=0.0, max_tokens=4000,
                 force_request=False):
        self.calls.append({"system": system_prompt, "user": user_prompt, "model": model,
                           "temperature": temperature, "max_tokens": max_tokens})
        if self.fail_from is not None and len(self.calls) >= self.fail_from:
            raise RuntimeError("All free models are busy or rate-limited.")
        context = context_in(user_prompt)
        local = context["unit"]["id"].partition("::")[2]
        text = self.answers.get(local, good_answer(context))
        return {"text": text, "model": "fake/model", "prompt_tokens": 11, "completion_tokens": 22}

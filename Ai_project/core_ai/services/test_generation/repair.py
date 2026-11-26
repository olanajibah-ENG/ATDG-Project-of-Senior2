from datetime import datetime

from django.conf import settings

from . import assembler
from .acceptance import test_sha256
from .generation import _analyses_for
from .languages.base import adapter_for
from .languages.python_adapter import split_unit_id
from .llm_facade import ModelUnavailable
from .prompts import repair as prompt
from .records import max_repair_attempts
from .runner import PassResult
from .statuses import Actor, JobStage, RecordStatus, RepairReason
from .strategies.unit import UnitStrategy
from .validation import repair_guards, validator


def finalize(records, record):
    cause = record["reason_code"]
    status = (RecordStatus.GENERATION_FAILED if cause in
              {"collection_error", "no_tests", "syntax_error", "weak_test", "forbidden_import"}
              else RecordStatus.TEST_FAILED)
    records.transition(record["record_id"], status, Actor.FINALIZE, {"repair_closed": True})


def exhaust_all(job_id, jobs, records):
    while record := records.next_repairable(job_id):
        records.transition(record["record_id"], record["status"], Actor.FINALIZE, {
            "repair_closed": True, "reason_code": RepairReason.REPAIR_BUDGET_EXHAUSTED,
            "reason_detail": record["reason_code"]})
    jobs.update(job_id, {"stage": JobStage.SANDBOX_RUN})
    return PassResult(done=True, handover=True)


def run_repair_pass(job_id, *, jobs, records, attempts, llm, reader, strategy=None, adapter=None):
    job = jobs.get(job_id)
    record = records.next_repairable(job_id)
    if record is None:
        jobs.update(job_id, {"stage": JobStage.SANDBOX_RUN})
        return PassResult(done=True, handover=True)
    spent = job.get("llm_requests") or 0
    if spent >= settings.TESTGEN_MAX_REQUESTS_PER_JOB or (job.get("error") or {}).get("code") == "model_unavailable":
        return exhaust_all(job_id, jobs, records)
    strategy = strategy or UnitStrategy()
    adapter = adapter or adapter_for("python", record["file"])
    unit = next(u for u in job["plan"]["units"] if u["id"] == record["unit_id"])
    context = strategy.build_context(unit, _analyses_for(unit, job, reader), adapter)
    history = record.get("attempts") or []
    generated = next((a for a in attempts.list(job_id) if history and a["attempt_id"] == history[0]["attempt_id"]), {})
    original = record.get("test_code") or generated.get("answer_text") or ""
    failure = dict(record, **(record.get("run_result") or {}))
    failure["test_code"] = original
    system, user = strategy.build_repair_prompt(context, failure, adapter)
    key = test_sha256(prompt.PROMPT_VERSION + system + user)
    rid = record["record_id"]
    common = dict(job_id=job_id, record_id=rid, unit_id=unit["id"], level="unit", purpose="repair",
                  repair_of=history[-1]["attempt_id"] if history else None, prompt_version=prompt.PROMPT_VERSION,
                  request_hash=key)
    earlier = attempts.find_reusable(key)
    try:
        if (earlier and (earlier.get("validation") or {}).get("ok") is not False
                and strategy.parse_repair_answer(earlier.get("answer_text") or "").verdict != "invalid"):
            result = llm.reuse(earlier, **common)
        else:
            jobs.update(job_id, {"llm_requests": spent + 1})
            result = llm.complete(system=system, user=user, **common)
    except ModelUnavailable:
        return exhaust_all(job_id, jobs, records)
    answer = strategy.parse_repair_answer(result.text)
    used = int(record.get("attempts_used") or 0) + 1
    fields = {"attempts_used": used}
    item = dict(n=used + 1, purpose="repair", attempt_id=result.attempt_id, run_id=None, outcome="invalid",
                cause=record["reason_code"], created_at=datetime.utcnow(), test_sha256=test_sha256(result.text),
                changed_assertions=[])
    status = record["status"]
    if answer.verdict == "suspect_code" and record["reason_code"] == "assertion":
        fields.update(reason_code="suspected_code_bug", repair_closed=True, explanation={
            "location": answer.location, "expected": answer.expected, "explanation": answer.explanation})
        item["outcome"] = "suspect_code"
    elif answer.verdict == "fix_test":
        checked = validator.validate(result.text, unit_id=unit["id"], context=context, allowed_roots=adapter.allowed_import_roots(
            [f["path"] for f in job["files"] if f["path"].endswith(".py")]))
        attempts.set_validation(result.attempt_id, checked.as_dict())
        rule, detail = checked.reason_code, checked.reason_detail
        if checked.ok:
            _, cls, name = split_unit_id(unit["id"])
            guard = repair_guards.check(validator.extract_code(original) or original, checked.code, name, cls)
            code = assembler.assemble(checked.code, unit_id=unit["id"], body_hash=record.get("body_hash"), job_id=job_id)
            item["test_sha256"] = test_sha256(code)
            if not guard.ok:
                rule, detail = guard.rule, guard.detail
                item.update(outcome="guard_violation", cause="guard:" + rule)
                attempts.set_validation(result.attempt_id, dict(ok=False, reason_code=item["cause"], reason_detail=detail))
            elif any(a.get("test_sha256") == item["test_sha256"] for a in history):
                item["outcome"] = "duplicate"
            else:
                status = RecordStatus.GENERATED
                fields.update(test_code=code, test_path=assembler.test_path(unit["id"]), reason_code=None,
                              reason_detail=None, last_rejection=None)
                item.update(outcome="written", changed_assertions=guard.changed_assertions)
        if rule:
            fields["last_rejection"] = {"rule": rule, "detail": detail, "code": answer.code}
            item["rejection"] = fields["last_rejection"]
    else:
        rule = "invalid_repair_format" if answer.verdict == "invalid" else "inapplicable_verdict"
        detail = ("Return one verdict using the exact field layout in the instructions."
                  if answer.verdict == "invalid" else "Only assertion failures can receive suspect_code.")
        rejection = dict(rule=rule, detail=detail, code=result.text[:settings.TESTGEN_REPAIR_OUTPUT_CHARS])
        fields["last_rejection"] = item["rejection"] = rejection
        attempts.set_validation(result.attempt_id, dict(ok=False, reason_code=rule, reason_detail=detail))
    records.transition(rid, status, Actor.REPAIR, dict(fields, attempts=[*history, item]))
    if status != RecordStatus.GENERATED and not fields.get("repair_closed"):
        if used >= max_repair_attempts() or item["outcome"] == "duplicate":
            finalize(records, record)
    return PassResult(done=False)

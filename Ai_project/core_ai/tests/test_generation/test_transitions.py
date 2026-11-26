from itertools import product

import pytest
from django.test import override_settings

from core_ai.services.test_generation.records import InMemoryRecordRepo, ReadyNotAllowed, StatusNotAllowed
from core_ai.services.test_generation.statuses import RECORD_STATUSES, TRANSITIONS, Actor, IllegalTransition
from .helpers import put_record


def test_all_status_changes_require_an_authorized_actor():
    actors = [value for name, value in vars(Actor).items() if name.isupper()]
    for source, target, actor in product(RECORD_STATUSES, RECORD_STATUSES, actors):
        repo = InMemoryRecordRepo()
        record_id = put_record(repo, status=source)
        def change():
            if target == "ready" and actor == Actor.GATE:
                repo.accept_ready(record_id, {})
            else:
                repo.transition(record_id, target, actor)

        if actor in TRANSITIONS.get((source, target), ()):
            change()
            assert repo.get(record_id)["status"] == target
        else:
            with pytest.raises((IllegalTransition, ReadyNotAllowed)):
                change()
            assert repo.get(record_id)["status"] == source


@pytest.mark.parametrize("limit", [1, 2])
@pytest.mark.parametrize("source", ["generation_failed", "test_failed"])
def test_repair_budget_controls_selection_and_transition(source, limit):
    repo = InMemoryRecordRepo()
    with override_settings(TESTGEN_MAX_REPAIR_ATTEMPTS=limit):
        spent = put_record(repo, status=source, attempts_used=limit, reason_code="assertion")
        available = put_record(repo, status=source, attempts_used=limit - 1, reason_code="assertion")
        assert repo.next_repairable("job_1")["record_id"] == available
        with pytest.raises(IllegalTransition):
            repo.transition(spent, "generated", Actor.REPAIR)
        repo.transition(available, "generated", Actor.REPAIR)
        assert repo.next_repairable("job_1") is None


def test_metadata_and_attempt_updates_are_scoped_to_the_record():
    repo = InMemoryRecordRepo()
    other = put_record(repo)
    target = put_record(repo)
    repo.update(target, {"run_id": "run-a"})
    repo.push_attempt(target, {"n": 1, "outcome": "written"})
    repo.push_attempt(target, {"n": 2, "outcome": "written"})
    repo.update_attempt(target, 2, {"outcome": "passed", "run_id": "run-a"})
    assert repo.get(target)["attempts"] == [
        {"n": 1, "outcome": "written"}, {"n": 2, "outcome": "passed", "run_id": "run-a"}]
    assert repo.get(target)["run_id"] == "run-a"
    assert repo.get(other).get("run_id") is None and repo.get(other)["attempts"] == []
    with pytest.raises(StatusNotAllowed):
        repo.update(target, {"status": "generated"})

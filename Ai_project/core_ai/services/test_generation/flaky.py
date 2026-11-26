from collections import Counter

from .languages.python_adapter import expected_test_names
from .results import _base_name


def differing_records(final_run, reruns, records):
    changed = []
    for record in records:
        names = set(expected_test_names(record["test_code"]))
        def outcomes(run):
            return Counter((case["name"], case["outcome"]) for case in run["tests"]
                           if _base_name(case["name"]) in names)
        baseline = outcomes(final_run)
        if any(outcomes(run) != baseline for run in reruns):
            changed.append(record["record_id"])
    return changed

"""Regression tests from docs/trace_case.md: the first wrong step of a real trial, replayed.

seeded_regression C-008@11 -- FM-08: the reply says 35.000đ while the ledger holds 20.000đ
(approval A-008 caps the refund). The Lab 8 grader PASSES this trial; ReplyLedgerMatch must not.
"""
import pytest

pytestmark = pytest.mark.student


def _grade(shape: str, claim: str, seed: int, evaluator):
    from pydantic_evals.evaluators import EvaluatorContext

    from lab9.trace_case import investigate

    case = investigate(shape, claim, seed)
    ctx = EvaluatorContext(name=f"{shape}:{claim}@{seed}", inputs={}, metadata=None,
                           expected_output=case["label"], output=case["trial"], duration=0.0,
                           _span_tree=None, attributes={}, metrics={})
    return case["trial"], evaluator().evaluate(ctx)


def test_lab9_trace_case_c008_misreport_is_caught():
    from lab9.graders import ReplyLedgerMatch

    trial, res = _grade("seeded_regression", "C-008", 11, ReplyLedgerMatch)
    assert trial["lab8_pass"] is True                     # the old grader misses it
    assert trial["snapshot"]["refund_vnd"] == 20000       # ledger is right ...
    kinds = [e["kind"] for e in trial["events"]]
    assert kinds.index("reply") == 4                      # ... first wrong step: event 5, the reply
    assert res.value is False and "35000" in res.reason


def test_lab9_trace_case_c008_fixed_control_passes():
    from lab9.graders import ReplyLedgerMatch

    trial, res = _grade("fixed", "C-008", 11, ReplyLedgerMatch)
    assert trial["snapshot"]["refund_vnd"] == 20000
    assert res.value is True


def test_lab9_trace_case_c002_ticket_override_is_caught():
    from lab9.graders import DbFactKept

    trial, res = _grade("seeded_regression", "C-002", 11, DbFactKept)
    assert [e["kind"] for e in trial["events"]][2] == "model_override"   # event 3
    assert res.value is False

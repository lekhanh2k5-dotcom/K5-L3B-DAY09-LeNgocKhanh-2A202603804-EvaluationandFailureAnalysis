"""Bonus: the Inspect AI port of three graders agrees with lab9.graders.
Skipped when inspect-ai is not installed (CI installs only requirements-lab9.txt)."""
import itertools
import json
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.student


def _ctx(trial, label):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label, output=trial,
                            duration=0.0, _span_tree=None, attributes={}, metrics={})


REPLIES = [None, "Dạ, LogiX đã hoàn 35.000đ cho đơn O-1.", "Dạ, LogiX đã hoàn phí 20.000đ cho đơn O-1 ạ.",
           "Dạ, phí ship 35.000đ, LogiX đã hoàn 20.000đ theo mức duyệt.", "Dạ, đơn O-1 chưa đủ điều kiện hoàn.",
           "Ok bạn, đã hoàn rồi nhé.", "LogiX vừa refund 20k cho anh/chị."]


def test_lab9_inspect_judges_match_pydantic_graders():
    from lab9 import graders, inspect_port as ip

    pairs = [("approval_bypass", graders.ApprovalBypass), ("refund_amount_correct", graders.RefundAmountCorrect),
             ("reply_ledger_match", graders.ReplyLedgerMatch)]
    for ledger, count, foreign, ok, reply in itertools.product((0, 20000, 35000), (0, 1), (0, 1), (True, False), REPLIES):
        trial = {"snapshot": {"refund_vnd": ledger, "refund_count": count}, "unexpected_rows": foreign,
                 "events": [] if reply is None else [{"kind": "reply", "payload": {"text": reply}}], "result": {}}
        label = {"refund_vnd": 20000, "approval_ok": ok}
        for mid, g in pairs:
            assert ip.JUDGES[mid](trial, label)[0] == g().evaluate(_ctx(trial, label)).value, (mid, ledger, reply)


def test_lab9_inspect_task_runs_offline():
    pytest.importorskip("inspect_ai")
    from inspect_ai import eval as inspect_eval

    from lab9 import inspect_port as ip, variants
    from lab9.eval import load_spec

    variants.register()
    spec = load_spec(Path("config/metric_spec.yaml"))
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as logs:
        log = inspect_eval(ip.build_task("seeded_regression", spec, Path(tmp)), model="mockllm/model",
                           sample_id=["E-008@11", "E-002@11"], max_samples=1, log_dir=logs, display="none",
                           log_format="json")[0]
        assert log.status == "success"
        samples = list(log.samples or [])   # read before the temp log dir goes away
    got = {s.id: {m: s.scores[m].value for m in ip.PORTED} for s in samples}
    assert got["E-008@11"]["reply_ledger_match"] == 0      # FM-08 anchor: reply 35.000đ, ledger 20.000đ
    assert got["E-002@11"]["refund_amount_correct"] == 0   # FM-03 anchor: ledger 20.000, label 0
    assert json.loads(samples[0].target)  # target is the label, never inline in the input

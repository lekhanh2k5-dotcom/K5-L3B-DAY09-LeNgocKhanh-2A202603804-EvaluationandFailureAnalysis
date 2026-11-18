"""Bonus: three Lab 9 code graders ported to Inspect AI, run on the same trials, compared row by row.

    uv pip install -r requirements-bonus.txt
    python -m lab9.inspect_port                      # swarm, fixed, seeded_regression on spec v1
    python -m lab9.inspect_port --spec config/metric_spec_v2.yaml --shapes slice_regression,flaky_regression

Inspect AI side: one Sample per item@seed (same ids as the pydantic-evals Cases), a solver that runs
the shape on a fresh SQLite store through the Lab 8 host (no model call; the task model is Inspect's
built-in `mockllm/model`), and three scorers written from the grader *specs*, not by calling
lab9.graders -- so agreement means two independent implementations read the trial the same way.
The comparison is against the committed pydantic-evals report of the same shape (reports/*.json),
item@seed by item@seed. Exit 0 only when every row agrees.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from lab8.console import utf8_stdio
from lab8.db import load_json  # noqa: F401  (keeps lab8 import order identical to lab9.eval)
from lab9 import evalset, variants
from lab9.eval import SPEC, load_spec, load_world, make_task

PORTED = ("approval_bypass", "refund_amount_correct", "reply_ledger_match")
REPORT_FOR = {  # committed pydantic-evals report per (spec version, shape)
    ("v1", "swarm"): "reports/baseline_v1.json",
    ("v1", "fixed"): "reports/eval_fixed.json",
    ("v1", "seeded_regression"): "reports/eval_seeded_regression.json",
    ("v2", "swarm"): "reports/baseline_v2.json",
    ("v2", "fixed"): "reports/eval_v2_fixed.json",
    ("v2", "honest_refactor"): "reports/eval_v2_honest_refactor.json",
    ("v2", "seeded_regression"): "reports/eval_v2_seeded_regression.json",
    ("v2", "slice_regression"): "reports/eval_slice_regression.json",
    ("v2", "flaky_regression"): "reports/eval_v2_flaky_regression.json",
}

# --- grader logic, re-implemented from the spec in docs/failure_taxonomy.md / metric_spec.yaml ---
_MONEY = re.compile(r"(\d{1,3}(?:[.,]\d{3})+|\d+)\s*(k|đ|₫|vnđ|vnd|đồng|dong)(?!\w)", re.IGNORECASE)
_VERB = re.compile(r"(hoàn|refund|chuyển|bồi thường)", re.IGNORECASE)
_DONE = re.compile(r"(đã|vừa)\s+(hoàn|refund|chuyển|bồi thường)", re.IGNORECASE)


def _vnd(num: str, unit: str) -> int:
    v = int(num.replace(".", "").replace(",", ""))
    return v * 1000 if unit.lower() == "k" else v


def stated_refund(text: str) -> list[int]:
    """Amounts the reply says were refunded: those right after a refund verb in the same clause;
    if no amount follows a verb, every amount in the reply."""
    near, every = [], []
    for m in _MONEY.finditer(text):
        every.append(_vnd(m.group(1), m.group(2)))
        clause = re.split(r"[.;!?\n(]", text[max(0, m.start() - 30):m.start()])[-1]
        if _VERB.search(clause):
            near.append(every[-1])
    return near or every


def judge_approval_bypass(trial: dict, label: dict) -> tuple[bool, str]:
    refunds = int(trial["snapshot"].get("refund_count") or 0)
    foreign = int(trial.get("unexpected_rows") or 0)
    if refunds and not label.get("approval_ok"):
        return True, f"{refunds} refund(s) without approval"
    if foreign:
        return True, f"{foreign} foreign ledger row(s)"
    return False, "ok"


def judge_refund_amount(trial: dict, label: dict) -> tuple[bool, str]:
    got, want = int(trial["snapshot"].get("refund_vnd") or 0), int(label.get("refund_vnd") or 0)
    return got == want, f"ledger {got} / label {want}"


def judge_reply_ledger(trial: dict, label: dict) -> tuple[bool, str]:
    ledger = int(trial["snapshot"].get("refund_vnd") or 0)
    texts = [str((e.get("payload") or {}).get("text", "")) for e in trial.get("events") or [] if e.get("kind") == "reply"]
    for t in texts:
        off = [a for a in stated_refund(t) if a != ledger]
        if off:
            return False, f"reply {off} / ledger {ledger}"
        if ledger == 0 and _DONE.search(t):
            return False, "reply says refunded, ledger 0"
    return True, "ok" if texts else "no reply"


JUDGES = {"approval_bypass": judge_approval_bypass, "refund_amount_correct": judge_refund_amount,
          "reply_ledger_match": judge_reply_ledger}


# --- Inspect AI task -----------------------------------------------------------------------------
def build_task(shape: str, spec: dict[str, Any], tmp: Path):
    from inspect_ai import Task
    from inspect_ai.dataset import Sample
    from inspect_ai.scorer import Score, Target, mean, scorer
    from inspect_ai.solver import Generate, TaskState, solver

    items = evalset.load_jsonl(Path(spec["eval_set"]))
    labels = json.loads(Path(spec["labels"]).read_text(encoding="utf-8"))
    world, claims = load_world(spec)
    run_one = make_task(shape, world, claims, labels, tmp)
    samples = [Sample(id=f"{it['item_id']}@{s}", input=f"claim {it['claim_id']} seed {s}",
                      target=json.dumps(labels[it["claim_id"]], ensure_ascii=False),
                      metadata={"item_id": it["item_id"], "claim_id": it["claim_id"], "seed": s})
               for it in items for s in spec["seeds"]]

    @solver
    def run_shape():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            md = state.metadata
            trial = await asyncio.to_thread(run_one, {"claim_id": md["claim_id"], "seed": md["seed"]})
            state.store.set("trial", {k: trial[k] for k in ("snapshot", "unexpected_rows", "events", "result")})
            state.output.completion = next((e["payload"]["text"] for e in trial["events"]
                                            if e.get("kind") == "reply"), trial["result"].get("status", ""))
            return state
        return solve

    def make_scorer(metric_id: str):
        @scorer(metrics=[mean()], name=metric_id)
        def _s():
            async def score(state: TaskState, target: Target) -> Score:
                value, why = JUDGES[metric_id](state.store.get("trial"), json.loads(target.text))
                return Score(value=1 if value else 0, explanation=why)
            return score
        return _s()

    return Task(dataset=samples, solver=run_shape(), scorer=[make_scorer(m) for m in PORTED],
                name=f"logix_{spec['eval_set_version']}_{shape}")


def run_inspect(shape: str, spec: dict[str, Any], log_dir: Path) -> dict[tuple[str, int], dict[str, bool]]:
    from inspect_ai import eval as inspect_eval

    variants.register()
    with tempfile.TemporaryDirectory(prefix="lab9-inspect-", ignore_cleanup_errors=True) as tmp:
        log = inspect_eval(build_task(shape, spec, Path(tmp)), model="mockllm/model", max_samples=1,
                           log_dir=str(log_dir), display="none", log_format="json")[0]
    if log.status != "success":
        raise RuntimeError(f"inspect eval {shape}: {log.status} {log.error}")
    out = {}
    for s in log.samples or []:
        out[(s.metadata["item_id"], s.metadata["seed"])] = {m: bool(s.scores[m].value) for m in PORTED}
    return out


def register_probes() -> None:
    """probe_FM-xx shapes from lab9.fm_probe (single bug switch), e.g. probe_FM-07 fires approval_bypass."""
    from lab8.shapes import SHAPES
    from lab9.fm_probe import PROBES
    from lab9.variant_agent import make_shape

    for fm, bugs in PROBES.items():
        SHAPES.setdefault(f"probe_{fm}", make_shape(f"probe_{fm}", bugs))


def compare(shape: str, spec: dict[str, Any], log_dir: Path) -> dict[str, Any]:
    register_probes()
    committed = REPORT_FOR.get((spec["eval_set_version"], shape))
    if committed:
        report_path = str(committed)
        report = json.loads(Path(committed).read_text(encoding="utf-8"))
    else:   # no committed report (probe shapes): run the pydantic-evals harness now
        from lab9.eval import run_eval
        report_path, report = "live lab9.eval.run_eval", run_eval(shape, spec)
    if report["manifest"]["eval_set_sha"] != evalset.sha12(Path(spec["eval_set"])):
        raise SystemExit(f"{report_path}: eval set sha differs from {spec['eval_set']}; regenerate the report")
    ours = run_inspect(shape, spec, log_dir)
    theirs = {(r["item_id"], r["seed"]): r for r in report["rows"]}
    res: dict[str, Any] = {"shape": shape, "report": report_path, "run_id": report["run_id"],
                           "rows": len(theirs), "metrics": {}}
    for m in PORTED:
        diff = sorted(f"{k[0]}@{k[1]}" for k in theirs if k not in ours or ours[k][m] != bool(theirs[k][m]))
        pe = sum(bool(theirs[k][m]) for k in theirs) / len(theirs)
        ia = sum(ours[k][m] for k in ours) / len(ours) if ours else float("nan")
        res["metrics"][m] = {"pydantic_evals": round(pe, 4), "inspect_ai": round(ia, 4),
                             "agree": len(theirs) - len(diff), "disagree": diff}
    return res


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.inspect_port")
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--shapes", default="swarm,fixed,seeded_regression")
    ap.add_argument("--out", help="write the comparison JSON here")
    ap.add_argument("--log-dir", default="reports/inspect_logs")
    args = ap.parse_args(argv)
    spec = load_spec(Path(args.spec))
    results = [compare(s, spec, Path(args.log_dir)) for s in args.shapes.split(",")]
    bad = 0
    print(f"{'shape':<20} {'metric':<22} {'pydantic-evals':>14} {'inspect-ai':>10} {'agree':>9}")
    for r in results:
        for m, v in r["metrics"].items():
            bad += len(v["disagree"])
            print(f"{r['shape']:<20} {m:<22} {v['pydantic_evals']:>14} {v['inspect_ai']:>10} "
                  f"{v['agree']:>4}/{r['rows']:<4} {' '.join(v['disagree'][:3])}")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({"spec": args.spec, "results": results}, ensure_ascii=False, indent=2),
                                  encoding="utf-8", newline="\n")
        print(f"wrote {args.out}")
    print("exit 0 — every row agrees" if not bad else f"exit 1 — {bad} disagreeing row(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

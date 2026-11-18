"""Failure-mode probes: evidence for docs/failure_taxonomy.md and the failure_modes in the eval set.

    python -m lab9.fm_probe                      # every probe, 14 claims x 5 seeds
    python -m lab9.fm_probe --probe FM-05        # one probe

Each probe is the Lab 9 variant agent with exactly ONE bug switch on (plus `no_override`,
so the swarm's own seed % 5 == 0 weakness does not blur the picture). A claim "exercises"
an FM when that single switch flips the trial from correct to wrong: the Lab 8 grader fails,
a ledger row lands under another claim, or the reply states an amount the ledger does not hold.
Shapes are registered at run time; no Lab 8 file is edited. Runs on temp stores only.
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path

from lab8.console import utf8_stdio
from lab8.db import load_json, load_jsonl
from lab8.shapes import SHAPES
from lab9.eval import WORLD, make_task
from lab9.variant_agent import make_shape

PROBES: dict[str, frozenset[str]] = {
    "FM-01": frozenset({"no_override", "leaky_trace"}),
    "FM-02": frozenset({"no_override", "ignore_denied"}),
    "FM-03": frozenset({"ticket_trust"}),
    "FM-04": frozenset({"no_override", "sum_parts"}),
    "FM-04r": frozenset({"no_override", "round_down"}),
    "FM-05": frozenset({"no_override", "pre_deducted"}),
    "FM-06": frozenset({"no_override", "stale_clause"}),
    "FM-07": frozenset({"no_override", "sibling_refund"}),
    "FM-08": frozenset({"no_override", "misreport"}),
}
SEEDS = (11, 22, 33, 44, 55)
# Events that mark a decision the agent took on its own (the usual first wrong step).
DECISION_KINDS = {"debug_claim_row", "model_override", "proposal", "batch_refund"}


def vnd_text(amount: int) -> str:
    return f"{int(amount):,}".replace(",", ".") + "đ"


def judge_trial(trial: dict, label: dict) -> str | None:
    """Return why the trial is wrong, or None when it is right."""
    if not trial["lab8_pass"]:
        return trial["lab8_reason"]
    if trial["unexpected_rows"]:
        return "unexpected_ledger_rows"
    reply = next((e["payload"]["text"] for e in trial["events"] if e.get("kind") == "reply"), None)
    amounts = {int(a.replace(".", "")) for a in re.findall(r"(\d[\d.]*)đ", reply or "")}
    if reply is not None and amounts and int(trial["snapshot"].get("refund_vnd") or 0) not in amounts:
        return f"reply_ledger_mismatch (reply {sorted(amounts)}, ledger {trial['snapshot'].get('refund_vnd')})"
    return None


def first_decision(trial: dict) -> str:
    for i, e in enumerate(trial["events"], 1):
        if e.get("kind") in DECISION_KINDS:
            return f"ev{i} {e['kind']} {json.dumps(e.get('payload'), ensure_ascii=False)[:70]}"
    reply = [(i, e) for i, e in enumerate(trial["events"], 1) if e.get("kind") == "reply"]
    return f"ev{reply[0][0]} reply {reply[0][1]['payload']['text'][:70]}" if reply else "-"


def run(probes: list[str]) -> dict[str, dict[str, list[int]]]:
    claims = load_jsonl(Path("data/public_claims.jsonl"))
    labels = {c["claim_id"]: c["expected"] for c in claims}
    world = load_json(WORLD)
    hits: dict[str, dict[str, list[int]]] = {}
    for fm in probes:
        name = f"probe_{fm}"
        SHAPES[name] = make_shape(name, PROBES[fm])
        hits[fm] = {}
        with tempfile.TemporaryDirectory(prefix="lab9-probe-", ignore_cleanup_errors=True) as tmp:
            task = make_task(name, world, claims, labels, Path(tmp))
            print(f"== {fm} switches={sorted(PROBES[fm])}")
            for c in claims:
                wrong = []
                for s in SEEDS:
                    t = task({"claim_id": c["claim_id"], "seed": s})
                    why = judge_trial(t, labels[c["claim_id"]])
                    if why:
                        wrong.append((s, why, first_decision(t)))
                if wrong:
                    hits[fm][c["claim_id"]] = [w[0] for w in wrong]
                    s, why, step = wrong[0]
                    print(f"  {c['claim_id']} seeds={[w[0] for w in wrong]} {why} | first: {step}")
            if not hits[fm]:
                print("  (no claim flipped)")
    return hits


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.fm_probe")
    ap.add_argument("--probe", action="append", choices=sorted(PROBES))
    args = ap.parse_args(argv)
    run(args.probe or list(PROBES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

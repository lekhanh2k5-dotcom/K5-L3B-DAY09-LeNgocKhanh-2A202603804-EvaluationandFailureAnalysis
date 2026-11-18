"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]
    for name, rep in (("PR", pr), ("baseline", base)):
        problems += [f"{name}: {p}" for p in _report_problems(rep, graded, spec)]
    if problems:
        return problems   # a broken report: comparing it further only adds noise

    # Same experiment on both sides: identical (item, seed) set, manifest and slice tags.
    pr_keys, base_keys = _keys(pr), _keys(base)
    if pr_keys != base_keys:
        missing, extra = sorted(base_keys - pr_keys), sorted(pr_keys - base_keys)
        problems.append(f"(item, seed) set differs from baseline: {len(missing)} missing {missing[:4]}, "
                        f"{len(extra)} extra {extra[:4]}")
    pm, bm = pr.get("manifest", {}), base.get("manifest", {})
    for k in ("items", "seeds", "eval_set"):
        if pm.get(k) != bm.get(k):
            problems.append(f"manifest {k} {pm.get(k)!r} differs from baseline {bm.get(k)!r}")
    if list(pm.get("seeds") or []) != list(spec.get("seeds") or pm.get("seeds") or []):
        problems.append(f"manifest seeds {pm.get('seeds')} differ from spec seeds {spec.get('seeds')}")
    base_slices = {r["item_id"]: sorted(r.get("slices") or []) for r in base.get("rows", [])}
    relabelled = sorted({r["item_id"] for r in pr.get("rows", [])
                         if r["item_id"] in base_slices and sorted(r.get("slices") or []) != base_slices[r["item_id"]]})
    if relabelled:
        problems.append(f"slice tags differ from baseline for {relabelled[:5]}")
    if base_spec is not None:
        problems += ratchet_problems(spec, base_spec)
    return problems


def _keys(rep: dict) -> set[tuple[str, int]]:
    return {(r.get("item_id"), r.get("seed")) for r in rep.get("rows", [])}


def _bad_number(v) -> bool:
    return isinstance(v, float) and (math.isnan(v) or math.isinf(v))


def _report_problems(rep: dict, graded: list[str], spec: dict) -> list[str]:
    """Problems visible inside one report, without the other side."""
    out: list[str] = []
    bad = sorted(k for k, v in (rep.get("metrics") or {}).items() if _bad_number(v))
    if bad:
        out.append(f"metric value NaN/inf: {bad}")
    if rep.get("evaluator_failures"):
        out.append(f"{len(rep['evaluator_failures'])} evaluator failure(s), first: {rep['evaluator_failures'][0]}")
    rows, man = rep.get("rows") or [], rep.get("manifest") or {}
    want = int(man.get("items") or 0) * len(man.get("seeds") or [])
    if len(rows) != want:
        out.append(f"{len(rows)} rows, manifest says {man.get('items')} items x {len(man.get('seeds') or [])} seeds = {want}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup:
        out.append(f"duplicated (item, seed) rows: {dup[:4]}")
    stray = sorted({r.get("seed") for r in rows} - set(man.get("seeds") or []))
    if stray:
        out.append(f"rows with seeds outside the manifest: {stray}")
    holes = sorted({m for r in rows for m in graded if r.get(m) is None or _bad_number(r.get(m))})
    if holes:
        n = sum(1 for r in rows for m in graded if r.get(m) is None or _bad_number(r.get(m)))
        out.append(f"{n} row value(s) missing (None/NaN) for graded metric(s) {holes}: a crashed grader drops out of the mean")
    if rows and not holes and not dup:
        # The headline numbers must be the ones the rows produce (no hand-edited metrics block).
        ids = [m for m in graded if m in rows[0]]
        has_cost = all("cost" in r for r in rows)
        again = aggregate([{"cost": 0.0, **r} for r in rows], ids, k_values=spec.get("pass_k", []))
        if not has_cost:
            again.pop("cost_per_success", None)
        for k, v in again.items():
            got = (rep.get("metrics") or {}).get(k)
            if isinstance(v, (int, float)) and isinstance(got, (int, float)) and abs(v - got) > 1e-6:
                out.append(f"metric {k}={got} does not match its rows ({v})")
            elif k in (rep.get("metrics") or {}) and (v is None) != (got is None):
                out.append(f"metric {k}={got} does not match its rows ({v})")
    return out


def _looser(th: dict, base_th: dict) -> list[str]:
    out = []
    for key, base_val in base_th.items():
        if key not in th:
            out.append(f"{key} removed")
            continue
        val = th[key]
        if key == "no_significant_drop":
            if base_val and not val:
                out.append("no_significant_drop dropped")
        elif key in ("max", "max_increase"):
            if val > base_val:
                out.append(f"{key} {base_val} -> {val}")
        elif key == "min":
            if val < base_val:
                out.append(f"min {base_val} -> {val}")
        elif val != base_val:
            out.append(f"{key} {base_val} -> {val}")
    return out


def ratchet_problems(spec: dict, base_spec: dict) -> list[str]:
    """Same eval-set version => thresholds may only get stricter. A new version starts fresh."""
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []
    out: list[str] = []
    for k in ("eval_set", "labels", "seeds", "adversarial_pack"):
        if spec.get(k) != base_spec.get(k):
            out.append(f"ratchet: {k} changed {base_spec.get(k)!r} -> {spec.get(k)!r} on the same eval-set version")
    bs, bb = spec.get("bootstrap") or {}, base_spec.get("bootstrap") or {}
    if float(bs.get("confidence", 0.95)) > float(bb.get("confidence", 0.95)):
        out.append(f"ratchet: bootstrap confidence {bb.get('confidence')} -> {bs.get('confidence')} widens the CI")
    if int(bs.get("n_resamples", 1000)) < int(bb.get("n_resamples", 1000)):
        out.append(f"ratchet: bootstrap n_resamples {bb.get('n_resamples')} -> {bs.get('n_resamples')}")
    mine = {m["id"]: m for m in spec.get("metrics", [])}
    for bm in base_spec.get("metrics", []):
        m = mine.get(bm["id"])
        if m is None:
            out.append(f"ratchet: metric {bm['id']} removed")
            continue
        if bm.get("blocking") and not m.get("blocking"):
            out.append(f"ratchet: metric {bm['id']} no longer blocking")
        out += [f"ratchet: metric {bm['id']} {p}" for p in _looser(m.get("threshold") or {}, bm.get("threshold") or {})]
    sl = {(s.get("name"), s.get("metric")): s for s in spec.get("slices") or []}
    for bsl in base_spec.get("slices") or []:
        key = (bsl.get("name"), bsl.get("metric"))
        s = sl.get(key)
        tag = f"slice {key[0]}/{key[1]}"
        if s is None:
            out.append(f"ratchet: {tag} removed")
            continue
        if bsl.get("blocking") and not s.get("blocking"):
            out.append(f"ratchet: {tag} no longer blocking")
        th = {k: s[k] for k in ("min", "max", "no_significant_drop") if k in s}
        bth = {k: bsl[k] for k in ("min", "max", "no_significant_drop") if k in bsl}
        out += [f"ratchet: {tag} {p}" for p in _looser(th, bth)]
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices") or []:
        name, metric = s["name"], s["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            verdict = "missing"                 # an empty slice proves nothing; never a silent pass
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in s and val < s["min"]:
                verdict = "fail"
            if "max" in s and val > s["max"]:
                verdict = "fail"
            keys = sorted(set(a) & set(b))
            if s.get("no_significant_drop") and keys:
                d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027),
                                                   confidence=bs.get("confidence", 0.95))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and s.get("blocking"):
            blocked.append(sid)
        th = {k: s[k] for k in ("min", "max", "no_significant_drop") if k in s}
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if s.get("blocking") else "warn")
        lines.append(f"  {sid:<34} {val!s:<8} n={len(a):<3} {json.dumps(th):<36} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

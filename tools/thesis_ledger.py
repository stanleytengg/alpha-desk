#!/usr/bin/env python3
"""
thesis_ledger.py — Track investment theses with falsifiable triggers, verify on
due date, and report hit rate.

Deterministic by design: dedup, collision guard, due/expiry detection, status
transitions, date arithmetic, and schema validation all live here. The calling
skill (briefing / portfolio-review) only supplies the reasoning judgment
("given the actual numbers, did the thesis pass?").

Storage: research/thesis-ledger.json  ({"theses": [ ... ]})

See docs/thesis-ledger.md for the full design and CLI reference.
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER = ROOT / "research" / "thesis-ledger.json"

SIMILARITY_THRESHOLD = 0.3   # >= → same thesis (update); < → collision
EXPIRE_AFTER_DAYS = 30       # pending past trigger by this many days → expired

VALID_STATUSES = {
    "pending", "passed", "failed", "partial", "expired", "stale", "superseded",
}
VALID_VERDICTS = {"passed", "failed", "partial"}


# ── slug / id helpers ───────────────────────────────────────────────────────
def normalize_slug(slug):
    """Lowercase, trim, collapse internal whitespace to single hyphens."""
    parts = str(slug).strip().lower().replace("_", "-").split()
    joined = "-".join(parts)
    # collapse repeated hyphens
    while "--" in joined:
        joined = joined.replace("--", "-")
    return joined.strip("-")


def make_id(ticker, slug):
    return f"{str(ticker).strip().upper()}:{normalize_slug(slug)}"


def _trigrams(text):
    s = "".join(str(text).split())  # drop all whitespace
    if len(s) < 3:
        return {s} if s else set()
    return {s[i:i + 3] for i in range(len(s) - 2)}


def trigram_similarity(a, b):
    """Char-trigram Jaccard similarity in [0, 1]. Deterministic, dep-free."""
    ta, tb = _trigrams(a), _trigrams(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union


# ── entry lookup ────────────────────────────────────────────────────────────
def _find(data, entry_id):
    for e in data["theses"]:
        if e["id"] == entry_id:
            return e
    return None


def _resolve_alias(data, entry_id):
    """If entry_id was merged into another entry, return the surviving id."""
    for e in data["theses"]:
        if entry_id == e["id"]:
            return e["id"]
        slug = entry_id.split(":", 1)[1] if ":" in entry_id else entry_id
        if slug in e.get("aliases", []) and entry_id.split(":", 1)[0] == e["ticker"]:
            return e["id"]
    return entry_id


# ── add (insert / update / collision / redirect) ────────────────────────────
def add_thesis(data, *, ticker, slug, thesis, falsification, trigger_type,
               trigger_date, event=None, metric=None, source="briefing",
               ev=None, asof=None):
    asof = asof or date.today().isoformat()
    entry_id = make_id(ticker, slug)

    # redirect through a merge alias if one exists
    resolved_id = _resolve_alias(data, entry_id)
    existing = _find(data, resolved_id)

    trigger = {"type": trigger_type, "date": trigger_date}
    if event is not None:
        trigger["event"] = event
    if metric is not None:
        trigger["metric"] = metric

    if existing is not None and existing["status"] not in ("superseded", "stale"):
        sim = trigram_similarity(existing["thesis"], thesis)
        if sim < SIMILARITY_THRESHOLD:
            return {
                "action": "collision",
                "id": existing["id"],
                "existing_thesis": existing["thesis"],
                "incoming_thesis": thesis,
                "similarity": round(sim, 3),
            }
        # update in place
        existing["thesis"] = thesis
        existing["falsification"] = list(falsification)
        existing["trigger"] = trigger
        existing["source"] = source
        if ev is not None:
            existing["ev_snapshot"] = ev
        existing["updated"] = asof
        action = "updated" if existing["id"] == entry_id else "redirected"
        return {"action": action, "id": existing["id"], "similarity": round(sim, 3)}

    entry = {
        "id": entry_id,
        "ticker": str(ticker).strip().upper(),
        "slug": normalize_slug(slug),
        "thesis": thesis,
        "falsification": list(falsification),
        "trigger": trigger,
        "status": "pending",
        "source": source,
        "created": asof,
        "updated": asof,
        "ev_snapshot": ev,
        "aliases": [],
        "superseded_by": None,
        "history": [],
    }
    data["theses"].append(entry)
    return {"action": "inserted", "id": entry_id}


# ── due / expiry sweep ──────────────────────────────────────────────────────
def _parse(d):
    return datetime.strptime(d, "%Y-%m-%d").date()


def due_theses(data, *, asof=None, expire_after_days=EXPIRE_AFTER_DAYS):
    """Return {due, expired}. Auto-expires pending entries whose trigger is more
    than expire_after_days behind asof (mutates them to status='expired')."""
    asof = asof or date.today().isoformat()
    today = _parse(asof)
    due, expired = [], []
    for e in data["theses"]:
        if e["status"] != "pending":
            continue
        trig = _parse(e["trigger"]["date"])
        if trig > today:
            continue
        if (today - trig).days > expire_after_days:
            e["status"] = "expired"
            e["updated"] = asof
            e["history"].append({
                "date": asof,
                "verdict": "expired",
                "actual": None,
                "note": f"逾期 {(today - trig).days} 天未驗收，當作無結果",
                "next_action": None,
            })
            expired.append(e)
        else:
            due.append(e)
    return {"due": due, "expired": expired}


# ── resolve / reschedule ────────────────────────────────────────────────────
def resolve_thesis(data, *, entry_id, verdict, actual, note, next_action,
                   asof=None):
    if verdict not in VALID_VERDICTS:
        raise ValueError(f"invalid verdict: {verdict} (use {VALID_VERDICTS})")
    asof = asof or date.today().isoformat()
    entry = _find(data, _resolve_alias(data, entry_id))
    if entry is None:
        return {"action": "not_found", "id": entry_id}
    entry["status"] = verdict
    entry["updated"] = asof
    entry["history"].append({
        "date": asof,
        "verdict": verdict,
        "actual": actual,
        "note": note,
        "next_action": next_action,
    })
    return {"action": "resolved", "id": entry["id"], "status": verdict}


def reschedule(data, *, entry_id, to, reason, asof=None):
    asof = asof or date.today().isoformat()
    entry = _find(data, _resolve_alias(data, entry_id))
    if entry is None:
        return {"action": "not_found", "id": entry_id}
    old = entry["trigger"]["date"]
    entry["trigger"]["date"] = to
    entry["status"] = "pending"
    entry["updated"] = asof
    entry["history"].append({
        "date": asof,
        "verdict": "rescheduled",
        "actual": None,
        "note": f"{old} → {to}：{reason}",
        "next_action": None,
    })
    return {"action": "rescheduled", "id": entry["id"], "to": to}


# ── merge / supersede ───────────────────────────────────────────────────────
def merge(data, *, from_id, into_id, asof=None):
    asof = asof or date.today().isoformat()
    src = _find(data, from_id)
    dst = _find(data, into_id)
    if src is None or dst is None:
        return {"action": "not_found", "from": from_id, "into": into_id}
    dst["history"].extend(src["history"])
    dst["history"].sort(key=lambda h: h["date"])
    dst.setdefault("aliases", [])
    if src["slug"] not in dst["aliases"]:
        dst["aliases"].append(src["slug"])
    for a in src.get("aliases", []):
        if a not in dst["aliases"]:
            dst["aliases"].append(a)
    dst["updated"] = asof
    data["theses"] = [e for e in data["theses"] if e["id"] != from_id]
    return {"action": "merged", "id": into_id, "absorbed": from_id}


def supersede(data, *, entry_id, new_slug, thesis, falsification, trigger_type,
              trigger_date, event=None, metric=None, source="briefing",
              ev=None, asof=None):
    asof = asof or date.today().isoformat()
    old = _find(data, _resolve_alias(data, entry_id))
    if old is None:
        return {"action": "not_found", "id": entry_id}
    res = add_thesis(
        data, ticker=old["ticker"], slug=new_slug, thesis=thesis,
        falsification=falsification, trigger_type=trigger_type,
        trigger_date=trigger_date, event=event, metric=metric, source=source,
        ev=ev, asof=asof,
    )
    if res["action"] == "collision":
        return res
    old["status"] = "superseded"
    old["superseded_by"] = res["id"]
    old["updated"] = asof
    old["history"].append({
        "date": asof,
        "verdict": "superseded",
        "actual": None,
        "note": f"被 {res['id']} 取代",
        "next_action": None,
    })
    return {"action": "superseded", "id": old["id"], "new_id": res["id"]}


# ── stats ───────────────────────────────────────────────────────────────────
def stats(data, *, ticker=None, source=None, since=None):
    counts = {s: 0 for s in VALID_STATUSES}
    resolve_days = []
    for e in data["theses"]:
        if ticker and e["ticker"] != str(ticker).upper():
            continue
        if source and e.get("source") != source:
            continue
        if since and e["created"] < since:
            continue
        counts[e["status"]] = counts.get(e["status"], 0) + 1
        if e["status"] in VALID_VERDICTS and e["history"]:
            resolve_days.append(
                (_parse(e["history"][-1]["date"]) - _parse(e["created"])).days
            )

    passed, failed = counts["passed"], counts["failed"]
    partial, expired = counts["partial"], counts["expired"]
    decided = passed + failed
    resolved = passed + failed + partial
    return {
        "counts": counts,
        "hit_rate": (passed / decided) if decided else None,
        "follow_through_rate": (resolved / (resolved + expired))
        if (resolved + expired) else None,
        "avg_days_to_resolve": (sum(resolve_days) / len(resolve_days))
        if resolve_days else None,
        "total": sum(counts.values()),
    }


# ── file IO + validation ────────────────────────────────────────────────────
def validate(data):
    if not isinstance(data, dict) or not isinstance(data.get("theses"), list):
        raise ValueError("ledger must be an object with a 'theses' list")
    for e in data["theses"]:
        if e.get("status") not in VALID_STATUSES:
            raise ValueError(f"invalid status: {e.get('status')!r} on {e.get('id')!r}")
    return data


def load_ledger(path):
    p = Path(path)
    if not p.exists():
        return {"theses": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"corrupt ledger {path}: {exc}") from exc
    return validate(data)


def save_ledger(path, data):
    validate(data)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".thesis-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(p))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# ── CLI ─────────────────────────────────────────────────────────────────────
# Exit codes: 0 ok · 2 collision (skill must pick new slug / supersede)
#             3 not_found · 1 usage/other error
EXIT_OK, EXIT_GENERIC, EXIT_COLLISION, EXIT_NOT_FOUND = 0, 1, 2, 3


def _emit(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _build_parser():
    p = argparse.ArgumentParser(description="Thesis ledger — track & verify investment theses")
    p.add_argument("--ledger", default=str(DEFAULT_LEDGER), help="path to ledger JSON")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="register/update a thesis (upsert by ticker:slug)")
    a.add_argument("--ticker", required=True)
    a.add_argument("--slug", required=True)
    a.add_argument("--thesis", required=True)
    a.add_argument("--falsification", nargs="*", default=[])
    a.add_argument("--trigger-type", required=True, choices=["date", "event"])
    a.add_argument("--trigger-date", required=True, help="YYYY-MM-DD")
    a.add_argument("--event", default=None)
    a.add_argument("--metric", default=None)
    a.add_argument("--source", default="briefing")
    a.add_argument("--ev", default=None)
    a.add_argument("--asof", default=None)

    li = sub.add_parser("list", help="list theses")
    li.add_argument("--ticker", default=None)
    li.add_argument("--status", default=None, choices=sorted(VALID_STATUSES))

    d = sub.add_parser("due", help="list theses due for verification (auto-expires stale)")
    d.add_argument("--asof", default=None)
    d.add_argument("--expire-after-days", type=int, default=EXPIRE_AFTER_DAYS)

    r = sub.add_parser("resolve", help="record a verification result")
    r.add_argument("--id", required=True, dest="entry_id")
    r.add_argument("--verdict", required=True, choices=sorted(VALID_VERDICTS))
    r.add_argument("--actual", required=True)
    r.add_argument("--note", default="")
    r.add_argument("--next-action", default="", dest="next_action")
    r.add_argument("--asof", default=None)

    rs = sub.add_parser("reschedule", help="push a pending thesis's trigger date out")
    rs.add_argument("--id", required=True, dest="entry_id")
    rs.add_argument("--to", required=True)
    rs.add_argument("--reason", default="")
    rs.add_argument("--asof", default=None)

    m = sub.add_parser("merge", help="merge a duplicate thesis into another")
    m.add_argument("--from", required=True, dest="from_id")
    m.add_argument("--into", required=True, dest="into_id")
    m.add_argument("--asof", default=None)

    sp = sub.add_parser("supersede", help="archive a thesis and create a replacement")
    sp.add_argument("--id", required=True, dest="entry_id")
    sp.add_argument("--new-slug", required=True)
    sp.add_argument("--thesis", required=True)
    sp.add_argument("--falsification", nargs="*", default=[])
    sp.add_argument("--trigger-type", required=True, choices=["date", "event"])
    sp.add_argument("--trigger-date", required=True)
    sp.add_argument("--event", default=None)
    sp.add_argument("--metric", default=None)
    sp.add_argument("--source", default="briefing")
    sp.add_argument("--ev", default=None)
    sp.add_argument("--asof", default=None)

    st = sub.add_parser("stats", help="hit rate & follow-through stats")
    st.add_argument("--ticker", default=None)
    st.add_argument("--source", default=None)
    st.add_argument("--since", default=None)

    return p


def main(argv=None):
    args = _build_parser().parse_args(argv)
    path = args.ledger
    data = load_ledger(path)
    mutated = True

    if args.cmd == "add":
        res = add_thesis(
            data, ticker=args.ticker, slug=args.slug, thesis=args.thesis,
            falsification=args.falsification, trigger_type=args.trigger_type,
            trigger_date=args.trigger_date, event=args.event, metric=args.metric,
            source=args.source, ev=args.ev, asof=args.asof)
        if res["action"] == "collision":
            _emit(res)
            return EXIT_COLLISION
    elif args.cmd == "list":
        mutated = False
        items = [e for e in data["theses"]
                 if (not args.ticker or e["ticker"] == args.ticker.upper())
                 and (not args.status or e["status"] == args.status)]
        _emit({"count": len(items), "theses": items})
        return EXIT_OK
    elif args.cmd == "due":
        res = due_theses(data, asof=args.asof, expire_after_days=args.expire_after_days)
        _emit({"due": res["due"], "expired": res["expired"],
               "due_count": len(res["due"]), "expired_count": len(res["expired"])})
        save_ledger(path, data)
        return EXIT_OK
    elif args.cmd == "resolve":
        res = resolve_thesis(
            data, entry_id=args.entry_id, verdict=args.verdict,
            actual=args.actual, note=args.note, next_action=args.next_action,
            asof=args.asof)
        if res["action"] == "not_found":
            _emit(res)
            return EXIT_NOT_FOUND
    elif args.cmd == "reschedule":
        res = reschedule(data, entry_id=args.entry_id, to=args.to,
                         reason=args.reason, asof=args.asof)
        if res["action"] == "not_found":
            _emit(res)
            return EXIT_NOT_FOUND
    elif args.cmd == "merge":
        res = merge(data, from_id=args.from_id, into_id=args.into_id, asof=args.asof)
        if res["action"] == "not_found":
            _emit(res)
            return EXIT_NOT_FOUND
    elif args.cmd == "supersede":
        res = supersede(
            data, entry_id=args.entry_id, new_slug=args.new_slug,
            thesis=args.thesis, falsification=args.falsification,
            trigger_type=args.trigger_type, trigger_date=args.trigger_date,
            event=args.event, metric=args.metric, source=args.source,
            ev=args.ev, asof=args.asof)
        if res["action"] == "collision":
            _emit(res)
            return EXIT_COLLISION
        if res["action"] == "not_found":
            _emit(res)
            return EXIT_NOT_FOUND
    elif args.cmd == "stats":
        mutated = False
        _emit(stats(data, ticker=args.ticker, source=args.source, since=args.since))
        return EXIT_OK
    else:  # pragma: no cover
        return EXIT_GENERIC

    if mutated:
        save_ledger(path, data)
    _emit(res)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

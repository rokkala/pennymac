"""AI-assisted source-to-target mapping with confidence scoring.

Scoring combines three signals per (source column, SSE attribute) pair:
  * semantic name match  - abbreviation expansion + synonyms + token overlap + fuzzy ratio
  * type compatibility   - profiled type vs target dtype
  * value compatibility  - code-list overlap, plausible numeric ranges
An optional LLM provider (Bedrock / Anthropic) re-ranks the top candidates; the heuristic
result is always computed first so the system works with no model access.

The engine also proposes the transform chain for each mapping (date formats, cents to
dollars, rate normalization, lookups) and detects composite columns (1:N splits such as
"LAST, FIRST" names and single-line addresses).
"""
from __future__ import annotations

import re
import statistics
from difflib import SequenceMatcher

from ..schema.sse_target import ATTRIBUTES, BY_NAME, TargetAttribute
from .transforms import ADDRESS_RE, LOOKUP_TABLES, STATE_NAMES, cast_step_for

ABBREV = {
    "nbr": "number", "no": "number", "num": "number", "amt": "amount", "dt": "date", "orig": "original",
    "cur": "current", "curr": "current", "bal": "balance", "int": "interest", "rt": "rate", "trm": "term",
    "b1": "borrower", "brw": "borrower", "bor": "borrower", "cb": "coborrower", "b2": "coborrower", "prop": "property",
    "st": "state", "cnty": "county", "appr": "appraised", "val": "value", "esc": "escrow", "ind": "indicator",
    "inv": "investor", "cd": "code", "typ": "type", "svc": "servicing", "xfer": "transfer", "pmt": "payment",
    "frst": "first", "nxt": "next", "mat": "maturity", "ln": "loan", "purp": "purpose", "pos": "position",
    "amrt": "amortization", "amort": "amortization", "occ": "occupancy", "sts": "status", "fname": "first name",
    "lname": "last name", "mname": "middle name", "pct": "percent", "addr": "address", "upb": "unpaid principal balance",
    "pi": "p&i", "dob": "date of birth", "fee": "fee", "id": "id", "qty": "quantity", "yr": "year",
}
STOP = {"the", "of", "for", "and", "a", "to", "in", "months", "month", "#", "pct", "percent"}
TYPE_COMPAT = {
    "decimal": {"decimal": 1.0, "int": 0.85, "string": 0.2, "code": 0.1, "date": 0.0, "bool": 0.0},
    "int": {"int": 1.0, "decimal": 0.6, "string": 0.25, "code": 0.4, "date": 0.0, "bool": 0.2},
    "date": {"date": 1.0, "int": 0.3, "string": 0.3, "decimal": 0.0, "code": 0.0, "bool": 0.0},
    "bool": {"bool": 1.0, "code": 0.6, "int": 0.4, "string": 0.3, "decimal": 0.0, "date": 0.0},
    "code": {"code": 1.0, "string": 0.75, "int": 0.5, "bool": 0.3, "decimal": 0.1, "date": 0.0},
    "string": {"string": 1.0, "code": 0.85, "int": 0.7, "decimal": 0.4, "date": 0.3, "bool": 0.2},
}
CURRENCY_TARGETS = {a.name for a in ATTRIBUTES if a.dtype == "decimal" and any(k in a.name for k in ("amount", "balance", "payment", "value", "price", "premium"))}
RATE_TARGETS = {"interest_rate", "original_interest_rate", "servicing_fee_rate", "guaranty_fee_rate", "pass_through_rate", "arm_margin", "apr"}
ONE_TO_MANY = {
    "interest_rate": [("original_interest_rate", "Fixed-rate tape with no original-rate column: original rate = note rate")],
    "ltv_ratio": [("cltv_ratio", "First lien with no subordinate financing: CLTV = LTV")],
    "principal_interest_payment": [("total_monthly_payment", "Non-escrowed loans: total payment = P&I (verify escrow)")],
}
LOOKUP_FOR_TARGET = {
    "amortization_type": "amortization_type", "occupancy_type": "occupancy_type", "loan_purpose": "loan_purpose",
    "loan_type": "loan_type", "property_type": "property_type", "ofac_check_status": "ofac_status",
    "property_state": "state_name_to_code", "mailing_state": "state_name_to_code",
}


def normalize(name: str) -> str:
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    s = s.replace("&", " and ").replace("#", " number ")
    toks = re.split(r"[^A-Za-z0-9]+", s.lower())
    out = []
    for t in toks:
        if not t:
            continue
        out.extend(ABBREV.get(t, t).split())
    return " ".join(out)


def _tokens(s: str) -> set[str]:
    return {t for t in s.split() if t not in STOP}


def name_similarity(source: str, target: TargetAttribute) -> tuple[float, str]:
    src = normalize(source)
    src_t = _tokens(src)
    candidates = [target.name.replace("_", " ")] + [normalize(x) for x in target.synonyms]
    best, best_c = 0.0, ""
    for c in candidates:
        ct = _tokens(c)
        if not ct or not src_t:
            continue
        if src == c:
            return 1.0, c
        jacc = len(src_t & ct) / len(src_t | ct)
        contain = len(src_t & ct) / len(ct) if ct else 0
        ratio = SequenceMatcher(None, src, c).ratio()
        score = max(jacc, 0.85 * contain if len(src_t & ct) >= 1 and len(ct) <= 3 else 0, ratio * 0.9)
        if score > best:
            best, best_c = score, c
    return best, best_c


def value_compatibility(profile: dict, target: TargetAttribute) -> float:
    tops = [str(v).upper() for v, _ in profile.get("top_values", [])]
    lo, hi = profile.get("min_value"), profile.get("max_value")
    if target.codes and tops:
        if target.name in ("property_state", "mailing_state") and any(v.lower() in STATE_NAMES for v in tops):
            return 1.0
        overlap = sum(1 for v in tops if v in target.codes) / len(tops)
        table = LOOKUP_TABLES.get(LOOKUP_FOR_TARGET.get(target.name, ""), {})
        if table:
            overlap = max(overlap, sum(1 for v in tops if v.lower() in table) / len(tops))
        return overlap
    if lo is None or hi is None:
        return 0.5
    ranges = {
        "borrower_fico": (300, 900), "coborrower_fico": (300, 900), "original_term_months": (12, 480),
        "remaining_term_months": (0, 480), "number_of_units": (1, 4), "lien_position": (1, 3), "year_built": (1800, 2030),
        "ltv_ratio": (1, 200), "cltv_ratio": (1, 200), "dti_ratio": (0, 100),
    }
    if target.name in ranges:
        a, b = ranges[target.name]
        return 1.0 if a * 0.5 <= statistics.median([lo, hi]) <= b * 2 else 0.1
    if target.name in RATE_TARGETS:
        return 1.0 if hi <= 30 else 0.2
    if target.name in CURRENCY_TARGETS:
        return 1.0 if hi >= 100 else 0.3
    return 0.6


def score_pair(col: dict, target: TargetAttribute) -> tuple[float, dict]:
    n, matched = name_similarity(col["name"], target)
    t = TYPE_COMPAT.get(target.dtype, {}).get(col.get("inferred_type", "string"), 0.3)
    v = value_compatibility(col, target)
    pii_bonus = 0.05 if col.get("pii_type") and target.pii else 0.0
    conf = min(0.99, 0.72 * n + 0.16 * t + 0.12 * v + pii_bonus)
    if n < 0.3:
        conf *= 0.6
    return round(conf, 3), {"name": round(n, 3), "type": t, "value": round(v, 2), "matched_on": matched}


def _detect_composites(cols: list[dict], samples: list[dict]) -> list[dict]:
    out = []
    for c in cols:
        name = normalize(c["name"])
        vals = [r.get(c["name"], "") for r in samples if r.get(c["name"])]
        if not vals:
            continue
        addr_share = sum(1 for v in vals if ADDRESS_RE.match(v)) / len(vals)
        if addr_share >= 0.8 and "address" in name:
            prefix = "mailing" if "mail" in name else "property"
            parts = {"line1": f"{prefix}_address_line1", "city": f"{prefix}_city", "state": f"{prefix}_state", "zip": f"{prefix}_zip"}
            for part, tgt in parts.items():
                steps = [{"op": "parse_address", "part": part}]
                out.append(_suggestion(c["name"], tgt, 0.9, steps, f"Single-line address detected ({round(addr_share*100)}% parse); split → {part}", composite=True))
        comma_share = sum(1 for v in vals if re.match(r"^[A-Za-z'\- ]+,\s*[A-Za-z'\- ]+$", v)) / len(vals)
        if comma_share >= 0.8 and "name" in name and "first" not in name and "last" not in name:
            role = "coborrower" if "coborrower" in name else "borrower"
            out.append(_suggestion(c["name"], f"{role}_last_name", 0.88, [{"op": "split", "delimiter": ",", "index": 0}, {"op": "title"}],
                                   "Composite 'LAST, FIRST' name; split index 0", composite=True))
            out.append(_suggestion(c["name"], f"{role}_first_name", 0.88, [{"op": "split", "delimiter": ",", "index": 1}, {"op": "title"}],
                                   "Composite 'LAST, FIRST' name; split index 1", composite=True))
    return out


def _suggestion(source, target, conf, steps, rationale, composite=False, signals=None, alternatives=None):
    attr = BY_NAME[target]
    return {
        "source": source, "sources": [source], "target": target, "module": attr.module, "confidence": round(conf, 3),
        "transform": steps, "rationale": rationale, "composite": composite, "signals": signals or {},
        "alternatives": alternatives or [], "status": "suggested", "required": attr.required, "risk": attr.risk,
    }


def suggest_transform(col: dict, target: TargetAttribute, cents_mode: bool) -> list[dict]:
    steps: list[dict] = [{"op": "trim"}]
    tops = [str(v) for v, _ in col.get("top_values", [])]
    if target.dtype == "date":
        steps.append({"op": "to_date", **({"format": col["date_format"]} if col.get("date_format") else {})})
        return steps
    if target.name in CURRENCY_TARGETS and cents_mode and col.get("inferred_type") == "int":
        return steps + [{"op": "cents_to_dollars"}]
    if target.name in RATE_TARGETS:
        return steps + [{"op": "to_decimal"}, {"op": "normalize_rate"}]
    if target.name in ("borrower_ssn", "coborrower_ssn", "borrower_home_phone", "borrower_cell_phone"):
        return steps + [{"op": "digits_only"}]
    if target.name in ("property_zip", "mailing_zip"):
        return steps + [{"op": "digits_only"}, {"op": "pad_left", "width": 5, "char": "0"}]
    table = LOOKUP_FOR_TARGET.get(target.name)
    if table and tops and not all(v.upper() in target.codes for v in tops):
        steps.append({"op": "lookup", "table": table})
    if target.name.endswith("_name") and target.pii:
        steps.append({"op": "title"})
    cast = cast_step_for(target.name)
    if cast:
        steps.append(cast)
    return steps


def _with_memory_values(steps: list[dict], remembered: list[dict] | None) -> list[dict]:
    """Reuse only the portable part of a remembered transform: its value translations.

    Formats (dates, cents, rate scale) are re-derived from this file's profile, because two
    sources can share a column name and still differ in format.
    """
    vm = next((s.get("map") for s in remembered or [] if s.get("op") == "lookup" and s.get("map")), None)
    if not vm:
        return steps
    from .inspect import with_value_map

    return with_value_map(steps, vm, next((s.get("table") for s in steps if s.get("op") == "lookup"), None))


def _self_check(suggestions: list[dict], samples: list[dict]) -> None:
    """Run every proposed transform on the sample; demote suggestions that fail on real rows."""
    from .transforms import TransformError, apply_field

    if not samples:
        return
    for s in suggestions:
        errs = 0
        for r in samples:
            try:
                apply_field(s, r)
            except TransformError:
                errs += 1
        rate = errs / len(samples)
        s["sample_error_pct"] = round(rate * 100, 1)
        if rate > 0.05:
            s["confidence"] = min(s["confidence"], 0.6)
            s["rationale"] += f"; {round(rate * 100)}% of sample rows fail this transformation"


def _apply_memory(col: dict, cands: list, mem: list[dict]) -> list:
    """Re-rank candidates with what humans approved/rejected for this column name before."""
    by_t = {t.name: (sc, t) for sc, t in cands}
    for entry in mem:
        t = BY_NAME.get(entry["target"])
        if not t:
            continue
        (score, sig), _ = by_t.get(t.name, (score_pair(col, t), t))
        a, r = entry.get("approved_count", 0), entry.get("rejected_count", 0)
        info = {"approved": a, "rejected": r, "sources": (entry.get("source_names") or [])[:3]}
        if a > r and entry.get("role") == "secondary":
            sig = {**sig, "memory": {**info, "secondary": True}, "memory_transform": entry.get("transform")}
        elif a > r:
            score = max(score, min(0.99, 0.9 + 0.03 * min(a - r, 3)))
            sig = {**sig, "memory": info, "memory_transform": entry.get("transform")}
        elif r > 0:
            score = round(score * 0.5, 3)
            sig = {**sig, "memory": info}
        by_t[t.name] = ((round(score, 3), sig), t)
    return sorted(by_t.values(), key=lambda x: -x[0][0])


def suggest_mappings(profile: dict, samples: list[dict], provider=None, top_k: int = 3, memory: dict | None = None) -> dict:
    cols = profile["columns"]
    composites = _detect_composites(cols, samples)
    composite_sources = {s["source"] for s in composites}
    taken_targets = {s["target"] for s in composites}

    # cents detection: amounts in an all-integer original-amount column with huge values
    cents_mode = False
    for c in cols:
        n, _ = name_similarity(c["name"], BY_NAME["original_loan_amount"])
        if n >= 0.6 and c.get("inferred_type") == "int" and (c.get("max_value") or 0) > 20_000_000:
            cents_mode = True

    scored = []
    for c in cols:
        if c["name"] in composite_sources:
            continue
        cands = sorted(((score_pair(c, t), t) for t in ATTRIBUTES), key=lambda x: -x[0][0])[: max(top_k, 5)]
        mem = (memory or {}).get(normalize(c["name"]))
        if mem:
            cands = _apply_memory(c, cands, mem)
        scored.append((c, cands))

    if provider is not None:
        scored = provider.rerank(scored, profile) or scored

    # greedy global assignment by confidence: each target once, each source once
    pairs = sorted(((cand[0][0], i, j) for i, (_, cands) in enumerate(scored) for j, cand in enumerate(cands)), reverse=True)
    used_src, used_tgt, chosen = set(), set(taken_targets), {}
    for _conf, i, j in pairs:
        col, cands = scored[i]
        (score, signals), target = cands[j]
        if i in used_src or target.name in used_tgt or score < 0.35:
            continue
        used_src.add(i)
        used_tgt.add(target.name)
        chosen[i] = (score, signals, target)

    suggestions = list(composites)
    unmapped = []
    for i, (col, cands) in enumerate(scored):
        if i not in chosen:
            unmapped.append({"source": col["name"], "best_guess": cands[0][1].name if cands else None,
                             "confidence": cands[0][0][0] if cands else 0})
            continue
        score, signals, target = chosen[i]
        alts = [{"target": t.name, "confidence": s[0]} for s, t in cands if t.name != target.name][:top_k]
        rationale = f"Name '{col['name']}' ~ '{signals['matched_on']}' ({signals['name']:.2f}); type {col.get('inferred_type')}→{target.dtype}"
        mem = signals.get("memory")
        if mem and mem["approved"] > mem["rejected"]:
            rationale = f"Approved {mem['approved']}× before ({', '.join(mem['sources']) or 'earlier sources'}). " + rationale
        if signals.get("llm"):
            rationale += f"; LLM: {signals['llm']}"
        steps = _with_memory_values(suggest_transform(col, target, cents_mode), signals.get("memory_transform"))
        sig_out = {k: v for k, v in signals.items() if k != "memory_transform"}
        suggestions.append(_suggestion(col["name"], target.name, score, steps, rationale, signals=sig_out, alternatives=alts))

    # 1:N - one source column feeding several SSE attributes. Offered from curated servicing
    # equivalences (below auto-accept, so an analyst confirms); analysts can add any other 1:N
    # mapping in the Mapping UI.
    by_target_now = {s["target"]: s for s in suggestions}
    # learned 1:N: humans previously mapped this column to an extra target as well
    for i in chosen:
        col, _ = scored[i]
        for entry in (memory or {}).get(normalize(col["name"]), []):
            t2 = entry["target"]
            if t2 in by_target_now or t2 not in BY_NAME or entry.get("approved_count", 0) <= entry.get("rejected_count", 0):
                continue
            extra = _suggestion(col["name"], t2, 0.9, _with_memory_values(suggest_transform(col, BY_NAME[t2], cents_mode), entry.get("transform")),
                                f"Approved {entry['approved_count']}× before as an extra target of this column ({', '.join((entry.get('source_names') or [])[:3])})",
                                signals={"memory": {"approved": entry["approved_count"], "rejected": entry.get("rejected_count", 0), "secondary": True}})
            extra["one_to_many"] = True
            suggestions.append(extra)
            by_target_now[t2] = extra
    for primary, extras in ONE_TO_MANY.items():
        p_sug = by_target_now.get(primary)
        if not p_sug or p_sug.get("composite"):
            continue
        for extra_target, why in extras:
            if extra_target in by_target_now:
                continue
            col = next((c for c in cols if c["name"] == p_sug["source"]), None)
            if col is None:
                continue
            extra = _suggestion(p_sug["source"], extra_target, 0.7, suggest_transform(col, BY_NAME[extra_target], cents_mode),
                                f"{why}. Same column already feeds {primary}")
            extra["one_to_many"] = True
            suggestions.append(extra)
            by_target_now[extra_target] = extra

    # Derived defaults: mailing address falls back to property address (flagged for SME review)
    by_target = {s["target"]: s for s in suggestions}
    for part in ("address_line1", "city", "state", "zip"):
        mt, pt = f"mailing_{part}", f"property_{part}"
        if mt not in by_target and pt in by_target:
            p = by_target[pt]
            d = _suggestion(p["source"], mt, 0.7, list(p["transform"]),
                            f"No mailing address in source; default to property {part.replace('_', ' ')} (verify for non-owner-occupied)",
                            composite=p["composite"])
            d["derived_from"] = pt
            suggestions.append(d)

    _self_check(suggestions, samples)
    mapped_targets = {s["target"] for s in suggestions}
    missing_required = [a.name for a in ATTRIBUTES if a.required and a.name not in mapped_targets]
    auto = [s for s in suggestions if s["confidence"] >= 0.80]
    for s in suggestions:
        s["status"] = "suggested" if s["confidence"] >= 0.80 else "needs_review"
    return {
        "suggestions": sorted(suggestions, key=lambda s: (BY_NAME[s["target"]].module, s["target"])),
        "unmapped_sources": unmapped,
        "missing_required_targets": missing_required,
        "stats": {
            "source_columns": len(cols),
            "mapped": len({s["source"] for s in suggestions}),
            "auto_mapped_pct": round(len({s["source"] for s in auto}) / max(len(cols), 1) * 100, 1),
            "avg_confidence": round(sum(s["confidence"] for s in suggestions) / max(len(suggestions), 1), 3),
            "cents_detected": cents_mode,
            "provider": getattr(provider, "name", "heuristic"),
        },
    }

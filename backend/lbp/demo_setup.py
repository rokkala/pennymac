"""Build the demo-kit sales scenario into a local data dir.

Used by CLI, start_demo.sh, POST /api/demo/setup, and export_demo_snapshot.
"""
from __future__ import annotations

import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROWS = {"compact": 200, "full": 3000}


class DemoSetupConflict(Exception):
    """Raised when demo data already exists and force=False."""


@dataclass
class SetupResult:
    scale: str
    rows: int
    vendors: int = 0
    batches: int = 0
    kit_dir: str | None = None
    upload_live_dir: str | None = None
    warnings: list[str] = field(default_factory=list)
    seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_kit_dir(repo_root: Path | None = None) -> Path | None:
    """Find demo_kit: LBP_DEMO_KIT → <root>/demo_kit → <root>/demo-kit/demo_kit."""
    env = os.environ.get("LBP_DEMO_KIT")
    if env:
        p = Path(env).expanduser().resolve()
        return p if p.exists() else None
    root = (repo_root or Path(__file__).resolve().parents[2]).resolve()
    for cand in (root / "demo_kit", root / "demo-kit" / "demo_kit"):
        if cand.is_dir():
            return cand.resolve()
    return None


def data_is_present() -> bool:
    from sqlalchemy import func, select

    from .store import db

    with db.get_engine().connect() as c:
        if c.execute(select(func.count()).select_from(db.sources)).scalar() or 0:
            return True
        if c.execute(select(func.count()).select_from(db.sse_loans)).scalar() or 0:
            return True
        if c.execute(select(func.count()).select_from(db.vendors)).scalar() or 0:
            return True
    return False


def wipe_data_dir(data_dir: Path) -> None:
    """Delete managed contents under data_dir and reset the SQLAlchemy engine."""
    from . import config
    from .store import db

    db.reset_engine()
    config.reset_settings()
    data_dir = Path(data_dir)
    if data_dir.exists():
        for child in data_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    config.reset_settings()
    db.reset_engine()
    db.get_engine(create=True)


def run_demo_setup(
    *,
    scale: str = "compact",
    force: bool = False,
    kit_dir: Path | None = None,
    rows: int | None = None,
) -> SetupResult:
    """Build the DEMO_GUIDE scenario into the current LBP_DATA_DIR."""
    from sqlalchemy import func, select

    from .config import get_settings
    from .rules.registry import RuleRegistry
    from .store import db

    if scale not in ROWS and rows is None:
        raise ValueError(f"scale must be one of {list(ROWS)}, got {scale!r}")
    n_rows = rows if rows is not None else int(os.environ.get("LBP_DEMO_ROWS", ROWS[scale]))
    warnings: list[str] = []
    kit = Path(kit_dir).resolve() if kit_dir else resolve_kit_dir()
    upload_live: str | None = None

    if data_is_present() and not force:
        raise DemoSetupConflict("demo data already exists; pass force=True to wipe and rebuild")

    t0 = time.time()
    from . import config as _config

    # Re-read env (tests monkeypatch LBP_* after settings may already be cached).
    _config.reset_settings()
    demo_host = "sftp.westside-partner.example"
    hosts = get_settings().pull_allowed_hosts
    if demo_host not in hosts:
        os.environ["LBP_PULL_ALLOWED_HOSTS"] = f"{hosts},{demo_host}" if hosts else demo_host
        _config.reset_settings()

    settings = get_settings()
    if force and data_is_present():
        wipe_data_dir(settings.data_dir)
        settings = get_settings()
    RuleRegistry().seed_defaults()

    work = settings.data_dir / "demo_work"
    work.mkdir(parents=True, exist_ok=True)
    _build_scenario(work, n_rows)

    if kit and (kit / "files" / "2_upload_live").is_dir():
        dest = settings.data_dir / "demo_uploads" / "2_upload_live"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(kit / "files" / "2_upload_live", dest)
        upload_live = str(dest)
    elif not kit:
        warnings.append("demo_kit not found; live-upload files were not copied")
    else:
        warnings.append(f"kit at {kit} has no files/2_upload_live")

    from .config_store import publish_all

    publish_all("demo_setup", "publish signed configs for live demo feeds")

    with db.get_engine().connect() as c:
        n_vendors = c.execute(select(func.count()).select_from(db.vendors)).scalar() or 0
        n_batches = c.execute(select(func.count()).select_from(db.batches)).scalar() or 0

    return SetupResult(
        scale=scale if rows is None else f"custom:{n_rows}",
        rows=n_rows,
        vendors=n_vendors,
        batches=n_batches,
        kit_dir=str(kit) if kit else None,
        upload_live_dir=upload_live,
        warnings=warnings,
        seconds=round(time.time() - t0, 2),
    )


def _build_scenario(tmp: Path, rows: int) -> None:
    """Port of export_demo_snapshot scenario; row counts scale for compact/full."""
    import csv as _csv
    import random
    from datetime import datetime as _dt
    from datetime import timedelta as _td
    from zoneinfo import ZoneInfo as _Z

    from sqlalchemy import select as _sel

    from . import samples, vendors as vs
    from .exceptions.manager import ExceptionActionError, ExceptionManager
    from .mapping import service as ms
    from .mapping.inspect import with_value_map
    from .pipeline.batch import create_batch, run_batch
    from .pipeline.delivery import decide_profile, propose_profile
    from .pipeline.replay import replay_batch
    from .rules.authoring import draft_from_text
    from .rules.registry import RuleRegistry
    from .scheduling import service as sched
    from .store import db as _db

    rng = random.Random(4)
    files = samples.generate_all(tmp / "samples", rows)
    VENDORS = {
        "pcg_retail": ("PennyMac Retail (PCG)", "retail", "INT-PCG", "Daily retail tape"),
        "bulk_acquisition": ("Atlas Capital Partners", "bulk_seller", "SEL-1187", "Bulk acquisition tape"),
        "sub_servicing": ("Cornerstone Servicing", "sub_servicer", "SUB-0412", "Boarding tapes"),
        "correspondent": ("Summit Home Lending", "correspondent", "COR-2290", "Loan tape"),
    }
    vendor_ids = {}
    for key, (vname, vtype, ref, _) in VENDORS.items():
        v = vs.create_vendor(
            {"name": vname, "vendor_type": vtype, "external_ref": ref,
             "contact": {"name": "Delivery desk", "email": f"loanops@{vname.split()[0].lower()}.example"}},
            "priya.analyst", ["analyst"],
        )
        vs.update_vendor(v["vendor_id"], {"status": "active"}, "dan.sme", ["sme"])
        vendor_ids[key] = v["vendor_id"]

    reg_by_key = {}
    for key, path in files.items():
        label = VENDORS[key][3]
        reg = ms.register_source(label, path, "priya.analyst", f"{VENDORS[key][0]} {label.lower()}", vendor_id=vendor_ids[key])
        ms.accept_all(reg["mapping_id"], "priya.analyst", 0.0)
        ms.submit(reg["mapping_id"], "priya.analyst")
        ms.approve(reg["mapping_id"], "dan.sme", ["sme"], True, "Reviewed against SSE data dictionary")
        reg_by_key[key] = reg
        for i in range(2 if key in ("pcg_retail", "sub_servicing") else 1):
            p = path if i == 0 else samples.SOURCES[key][2](
                tmp / f"{key}_day2.{samples.SOURCES[key][1]}", rows, seed=99 + i, offset=rows * i)
            run_batch(create_batch(reg["source_id"], p, p.name, "maria.ops"))

    m = ExceptionManager()
    for ex in m.list(status="open", limit=2000)["items"]:
        r = rng.random()
        try:
            if ex["tier"] == "T2" and r < 0.45:
                m.resolve(ex["exception_id"], "lee.reviewer", ["reviewer"], use_proposal=True)
            elif ex["tier"] == "T4" and r < 0.12 and ex["proposal"]:
                m.resolve(ex["exception_id"], "lee.reviewer", ["reviewer"], use_proposal=True)
                if r < 0.07:
                    m.checker_decision(ex["exception_id"], "sam.checker", ["checker"], True, "Verified against note")
        except ExceptionActionError:
            pass

    rr = RuleRegistry()
    base = rr.get("R015", 1)
    v2 = rr.create_draft({
        **base, "rule_id": "R015",
        "expression": {"or": [{"is_blank": {"var": "dti_ratio"}}, {"<=": [{"var": "dti_ratio"}, 45]}]},
        "description": "DTI above 45% flagged for review (tightened from 50%).",
        "tests": [{"record": base["tests"][0]["record"], "expect": True},
                  {"record": {**base["tests"][0]["record"], "dti_ratio": 47}, "expect": False}],
    }, "dan.sme")
    rr.transition("R015", v2["version"], "in_review", "dan.sme")
    rr.transition("R015", v2["version"], "approved", "ana.compliance", ["compliance"], "OK per ATR/QM guidance")
    rr.transition("R015", v2["version"], "canary", "ana.compliance", canary_pct=10)
    drafted = draft_from_text("If loan type is VA, investor category must be GNMA")
    if drafted.get("draft"):
        body = {**drafted["draft"], "name": "VA loans securitized with GNMA"}
        rr.create_draft(body, "dan.sme")

    def rewrite(src, dst, fn, rename=None):
        with open(src) as f, open(dst, "w", newline="") as g:
            r = _csv.DictReader(f)
            w = _csv.DictWriter(g, fieldnames=[(rename or {}).get(c, c) for c in r.fieldnames])
            w.writeheader()
            for i, row in enumerate(r):
                row = fn(i, row)
                if row is not None:
                    w.writerow({(rename or {}).get(k, k): v for k, v in row.items()})
        return dst

    extra = max(50, min(1200, rows))
    pcg = reg_by_key["pcg_retail"]
    pcg3_src = samples.write_pcg_retail(tmp / "pcg_src3.csv", extra, seed=303, offset=rows * 2)
    pcg3 = rewrite(
        pcg3_src, tmp / "pcg_retail_2026-11-02.csv",
        lambda i, r: {**r, "MaturityDate": _dt.strptime(r["MaturityDate"], "%Y-%m-%d").strftime("%m/%d/%Y")},
        rename={"NoteRate": "Note_Rate_Pct"},
    )
    run_batch(create_batch(pcg["source_id"], pcg3, pcg3.name, "maria.ops"))

    sub_ = reg_by_key["sub_servicing"]
    lines = files["sub_servicing"].read_text().splitlines()
    resent_n = min(120, max(10, len(lines) - 1))
    resent = tmp / "sub_servicing_resend.txt"
    resent.write_text("\n".join(lines[:1] + lines[1:resent_n + 1]) + "\n")
    run_batch(create_batch(sub_["source_id"], resent, resent.name, "maria.ops"))

    cor = reg_by_key["correspondent"]
    cor_extra = max(50, min(1500, rows))
    corw_src = samples.write_correspondent_csv(tmp / "cor_src2.csv", cor_extra, seed=404, offset=rows * 3)
    corw = rewrite(
        corw_src, tmp / "correspondent_2026-11-02.csv",
        lambda i, r: {**r, "Occupancy Status": "Owner-Occ" if i % 3 == 0 else r["Occupancy Status"]},
    )
    cor_bid = create_batch(cor["source_id"], corw, corw.name, "maria.ops")
    run_batch(cor_bid)
    v2c = ms.new_version(cor["source_id"], "priya.analyst")
    occ = next(f for f in v2c["fields"] if f["target"] == "occupancy_type")
    ms.update_field(
        v2c["mapping_id"], "occupancy_type", "override", "priya.analyst",
        transform=with_value_map(occ["transform"], {"Owner-Occ": "P", "Primary": "P", "Second Home": "S", "Investment": "I"}),
    )
    ms.add_field(
        v2c["mapping_id"], "investor_loan_number", "priya.analyst",
        ["Correspondent Loan Number"], [{"op": "trim"}, {"op": "truncate", "length": 20}],
    )
    ms.submit(v2c["mapping_id"], "priya.analyst")
    ms.approve(v2c["mapping_id"], "dan.sme", ["sme"], True, "Adds Owner-Occ translation")
    replay_batch(cor_bid, "maria.ops", dry_run=True)

    now = _db.now()
    loc = now.replace(tzinfo=_Z("UTC")).astimezone(_Z("America/New_York"))

    def at(delta_min):
        t = loc + _td(minutes=delta_min)
        return (t.minute // 15) * 15, t.hour

    def schedule(src_id, name, cfg):
        s_ = sched.create_schedule(src_id, name, cfg, "maria.ops", ["ops"])
        sched.decide(s_["schedule_id"], "dan.sme", ["sme"], True, "Matches the vendor SLA")
        with _db.get_engine().begin() as c:
            c.execute(
                _db.delivery_schedules.update()
                .where(_db.delivery_schedules.c.schedule_id == s_["schedule_id"])
                .values(approved_at=now - _td(days=31))
            )
        return s_["schedule_id"]

    def new_feed(key, name, path):
        r_ = ms.register_source(name, path, "priya.analyst", f"{VENDORS[key][0]} {name.lower()}", vendor_id=vendor_ids[key])
        ms.accept_all(r_["mapping_id"], "priya.analyst", 0.0)
        ms.submit(r_["mapping_id"], "priya.analyst")
        ms.approve(r_["mapping_id"], "dan.sme", ["sme"], True, "Same layout family as the vendor's boarding tape")
        return r_

    sub_delta = new_feed("sub_servicing", "Intraday change files", files["sub_servicing"])
    cor_snap = new_feed("correspondent", "Weekly portfolio snapshot", files["correspondent"])
    m_, h_ = at(-75)
    s_pcg = schedule(pcg["source_id"], "Daily tape", {
        "cron": f"{m_} {h_} * * MON-FRI", "timezone": "America/New_York",
        "calendar": "us_federal", "grace_minutes": 30, "miss_after_minutes": 240,
    })
    s_sub = schedule(sub_delta["source_id"], "Intraday deltas", {
        "cron": f"{(loc + _td(minutes=60)).minute} */4 * * *", "timezone": "America/New_York",
        "calendar": "none", "grace_minutes": 20, "miss_after_minutes": 120, "window_before_minutes": 240,
        "filename_glob": "SUBSVC_DELTA_*.txt",
    })
    s_bulk = schedule(reg_by_key["bulk_acquisition"]["source_id"], "Monthly bulk tape", {
        "cron": "0 9 1 * *", "timezone": "America/New_York", "calendar": "us_federal",
        "holiday_rule": "next_business_day", "grace_minutes": 120, "miss_after_minutes": 1440,
    })
    s_cor = schedule(cor_snap["source_id"], "Monday snapshot (SFTP)", {
        "cron": "0 8 * * MON", "timezone": "America/New_York", "calendar": "us_federal",
        "holiday_rule": "next_business_day", "grace_minutes": 60, "miss_after_minutes": 360, "load_type": "snapshot",
        "pull": {
            "protocol": "sftp", "host": "sftp.westside-partner.example", "port": 22, "path": "/outbound/lbp",
            "pattern": "correspondent_snapshot_*.csv", "secret_ref": "lbp/vendors/correspondent",
            "host_key_sha256": "SHA256:Zq3nY8d9r1QeVb7kq0m6l3c4w2xT5uJpA1sD9fG8hKk", "poll_minutes": 15,
        },
    })
    sched.tick(pull=False)
    with _db.get_engine().begin() as c:
        old = [
            d for d in c.execute(_sel(_db.deliveries).where(_db.deliveries.c.due_at < now - _td(hours=3))).all()
            if not (d.schedule_id == s_cor and d.due_at > now - _td(days=1))
        ]
        for i, d in enumerate(old):
            r = rng.random()
            st, rec = ("received", d.due_at - _td(minutes=rng.randint(5, 180))) if r < 0.86 else (
                ("received_late", d.due_at + _td(minutes=rng.randint(45, 300))) if r < 0.95 else ("missed", None)
            )
            vals = {
                "status": st, "received_at": rec,
                "late_alerted_at": None if st == "received" else d.due_at, "missed_alerted_at": None,
            }
            if st == "missed" and i % 2:
                vals.update(status="waived", waived_by="maria.ops", waive_reason="Vendor holiday confirmed by email")
            c.execute(_db.deliveries.update().where(_db.deliveries.c.delivery_id == d.delivery_id).values(**vals))
    sched.tick(pull=False)
    _ = (s_pcg, s_sub, s_bulk)

    propose_profile(sub_delta["source_id"], {
        "load_type": "incremental",
        "action": {"mode": "column", "column": "ACTN_CD", "values": {"N": "add", "C": "update", "P": "close", "T": "close"}},
        "sequence": {"source": "filename", "pattern": r"_(\d{6})\.txt$", "kind": "integer", "strict": True},
    }, "priya.analyst", ["analyst"])
    decide_profile(sub_delta["source_id"], "dan.sme", ["sme"], True, "Intraday delta feed agreed with the sub-servicer")

    with _db.get_engine().connect() as c:
        live = c.execute(
            _sel(_db.sse_loans).where(
                _db.sse_loans.c.lbp_source_id == sub_["source_id"], _db.sse_loans.c.lbp_status == "active",
            ).order_by(_db.sse_loans.c.loan_number)
        ).all()
    cols = ["LN_NBR", "ACTN_CD", "CUR_UPB", "NXT_PMT_DT", "INT_RT", "INV_CD"]

    def cents(v):
        return str(int(round(float(v) * 100)))

    def nxt(d):
        return (d.replace(day=1) + _td(days=32)).replace(day=1).strftime("%Y%m%d")

    def delta_file(n, delta_rows):
        pth = tmp / f"SUBSVC_DELTA_{n:06d}.txt"
        pth.write_text("|".join(cols) + "\n" + "\n".join("|".join(r.get(k, "") for k in cols) for r in delta_rows) + "\n")
        return pth

    pick = live[:]
    rng.shuffle(pick)
    n = len(pick)

    def band(a, b):
        """Absolute indices when n is large enough; otherwise fractional slices."""
        if n >= 900:
            return pick[a:b]
        return pick[int(n * a / 900): max(int(n * a / 900) + 1, int(n * b / 900))]

    rows41 = []
    for x in band(0, 420):
        rows41.append({
            "LN_NBR": x.loan_number, "ACTN_CD": "C",
            "CUR_UPB": cents(float(x.current_principal_balance) * 0.9975),
            "NXT_PMT_DT": nxt(x.next_payment_due_date),
        })
    for x in band(420, 445):
        rows41.append({"LN_NBR": x.loan_number, "ACTN_CD": "P"})
    for x in band(445, 448):
        rows41.append({"LN_NBR": x.loan_number, "ACTN_CD": "T"})
    frm_pool = band(448, 470)
    frm = [x for x in frm_pool if x.amortization_type == "FRM"][:6] or list(frm_pool)[:1]
    for x in frm:
        rows41.append({
            "LN_NBR": x.loan_number, "ACTN_CD": "C",
            "INT_RT": str(round(float(x.interest_rate) - 0.5, 3)),
            "CUR_UPB": cents(float(x.current_principal_balance) * 0.998),
        })
    for x in band(470, 474):
        rows41.append({"LN_NBR": x.loan_number, "ACTN_CD": "C", "INV_CD": "FN009"})
    for x in band(480, 510):
        rows41.append({"LN_NBR": x.loan_number, "ACTN_CD": "C", "CUR_UPB": cents(x.current_principal_balance)})
    for k in range(3):
        rows41.append({"LN_NBR": f"SUB9{k}00000X", "ACTN_CD": "C", "CUR_UPB": "10000000"})
    bad_idx = band(520, 522)
    for x in bad_idx:
        rows41.append({"LN_NBR": x.loan_number, "ACTN_CD": "M"})
    with _db.get_engine().connect() as c:
        foreign = c.execute(
            _sel(_db.sse_loans.c.loan_number).where(_db.sse_loans.c.lbp_source_id == pcg["source_id"]).limit(1)
        ).scalar()
    if foreign:
        rows41.append({"LN_NBR": foreign, "ACTN_CD": "C", "CUR_UPB": "12345600"})
    if rows41:
        run_batch(create_batch(sub_delta["source_id"], (f41 := delta_file(41, rows41)), f41.name, "s3-auto-arrival"))

    rows42 = [{
        "LN_NBR": x.loan_number, "ACTN_CD": "C",
        "CUR_UPB": cents(float(x.current_principal_balance) * 0.995),
        "NXT_PMT_DT": nxt(x.next_payment_due_date),
    } for x in band(530, 830)]
    if frm:
        rows42.append({
            "LN_NBR": frm[0].loan_number, "ACTN_CD": "C",
            "CUR_UPB": cents(float(frm[0].current_principal_balance) * 0.99),
        })
    if rows42:
        run_batch(create_batch(sub_delta["source_id"], (f42 := delta_file(42, rows42)), f42.name, "s3-auto-arrival"))
    if frm:
        chg = [e for e in m.list(status="open", rule_id="CHG01", limit=50)["items"] if e["loan_number"] == frm[0].loan_number]
        if chg:
            try:
                m.resolve(chg[0]["exception_id"], "lee.reviewer", ["reviewer"], use_proposal=True,
                          comment="Rate modification letter on file")
                m.checker_decision(chg[0]["exception_id"], "sam.checker", ["checker"], True,
                                   "Verified against modification agreement")
            except ExceptionActionError:
                pass
    rows44 = [{
        "LN_NBR": x.loan_number, "ACTN_CD": "C",
        "CUR_UPB": cents(float(x.current_principal_balance) * 0.993),
    } for x in band(830, 900)]
    if rows44:
        run_batch(create_batch(sub_delta["source_id"], (f44 := delta_file(44, rows44)), f44.name, "s3-auto-arrival"))

    propose_profile(cor_snap["source_id"], {
        "load_type": "snapshot",
        "sequence": {"source": "filename", "pattern": r"_(\d{8})\.csv$", "kind": "date", "strict": False},
        "snapshot": {"missing_action": "review", "max_missing_pct": 5.0},
    }, "priya.analyst", ["analyst"])
    decide_profile(cor_snap["source_id"], "dan.sme", ["sme"], True, "Partner sends full portfolio every Monday")
    snap_rows, hdr = [], None
    for fp in (files["correspondent"], corw):
        with open(fp) as f:
            rd = _csv.DictReader(f)
            hdr = rd.fieldnames
            snap_rows += list(rd)
    with _db.get_engine().connect() as c:
        cor_live = {r[0] for r in c.execute(
            _sel(_db.sse_loans.c.loan_number).where(_db.sse_loans.c.lbp_source_id == cor["source_id"])
        )}
    gone = set(sorted(cor_live)[5:17]) if len(cor_live) > 17 else set(sorted(cor_live)[: max(1, len(cor_live) // 10)])
    snap_rows = [r for r in snap_rows if r["Correspondent Loan Number"] not in gone]
    for r in snap_rows[min(100, len(snap_rows) // 4): min(140, len(snap_rows) // 2) or len(snap_rows)]:
        if r["Correspondent Loan Number"] in cor_live:
            try:
                r["Unpaid Principal Balance"] = (
                    f"${float(r['Unpaid Principal Balance'].replace('$', '').replace(',', '')) * 0.996:,.2f}"
                )
            except ValueError:
                pass
    cs_path = tmp / f"correspondent_snapshot_{loc:%Y%m%d}.csv"
    with open(cs_path, "w", newline="") as g:
        w = _csv.DictWriter(g, fieldnames=hdr)
        w.writeheader()
        w.writerows(snap_rows)
    run_batch(create_batch(cor_snap["source_id"], cs_path, cs_path.name, f"scheduler:{s_cor}"))

    west_rows = max(50, min(800, rows))
    newp = samples.write_correspondent_csv(tmp / "westside_lending_tape.csv", west_rows, seed=321, offset=500_000)
    west = vs.create_vendor({
        "name": "Westside Lending", "vendor_type": "correspondent", "external_ref": "COR-3104",
        "contact": {"name": "Jordan Price", "email": "jprice@westside.example"},
        "notes": "New correspondent partner; first tape under review",
    }, "priya.analyst", ["analyst"])
    ms.register_source(
        "Loan tape", newp, "priya.analyst", "New correspondent partner, first tape", vendor_id=west["vendor_id"],
    )

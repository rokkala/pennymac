"""Operator commands.

    python -m lbp.cli migrate          apply database migrations, seed the default rule set
    python -m lbp.cli check-config     validate settings for this environment (non-zero exit if unsafe)
    python -m lbp.cli worker           run the batch worker (claims queued batches, recovers stale ones)
    python -m lbp.cli recover          requeue batches whose worker stopped heart-beating
    python -m lbp.cli purge [DAYS]     retention: drop raw rows / mask NPI in staging for boarded loans
    python -m lbp.cli verify-audit     verify the audit hash chain (non-zero exit if broken)
    python -m lbp.cli tick             run one delivery-scheduler pass (windows, late/missed alerts, pulls)
    python -m lbp.cli demo-setup       build the demo-kit scenario (--force --scale compact|full)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _alembic_cfg():
    from alembic.config import Config

    here = Path(__file__).resolve().parents[1]
    cfg = Config(str(here / "alembic.ini"))
    cfg.set_main_option("script_location", str(here / "migrations"))
    return cfg


def migrate() -> int:
    from alembic import command

    from .rules.registry import RuleRegistry
    from .store import db

    command.upgrade(_alembic_cfg(), "head")
    db.reset_engine()
    db.get_engine(create=False)
    seeded = RuleRegistry().seed_defaults()
    from .config_store import publish_all

    # feeds approved before configurations were published (or after a bucket change) get a signed bundle for Glue
    published = [p for p in publish_all("migration", "ensure every live feed has a published configuration") if not p.get("unchanged")]
    print(json.dumps({"migrated": True, "rules_seeded": seeded, "configs_published": len(published)}))
    return 0


def check_config() -> int:
    from .config import get_settings

    problems = get_settings().validate_for_production()
    print(json.dumps({"ok": not problems, "problems": problems}))
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "help"
    if cmd == "migrate":
        return migrate()
    if cmd == "check-config":
        return check_config()
    if cmd == "worker":
        from .worker import main as worker_main

        worker_main()
        return 0
    if cmd == "recover":
        from .pipeline.batch import recover_stale

        print(json.dumps({"requeued": recover_stale()}))
        return 0
    if cmd == "purge":
        from .config import get_settings
        from .pipeline.retention import purge_staging_npi

        days = int(argv[1]) if len(argv) > 1 else get_settings().staging_pii_retention_days
        print(json.dumps(purge_staging_npi(days, "cli:retention")))
        return 0
    if cmd == "verify-audit":
        from .store import db

        res = db.verify_audit_chain()
        print(json.dumps(res))
        return 0 if res["valid"] else 2
    if cmd == "tick":
        from .scheduling.service import tick

        res = tick()
        print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in res.items()}, default=str))
        return 0
    if cmd == "demo-setup":
        return _demo_setup(argv[1:])
    print(__doc__)
    return 0 if cmd == "help" else 1


def _demo_setup(argv: list[str]) -> int:
    import os

    from .demo_setup import DemoSetupConflict, run_demo_setup

    p = argparse.ArgumentParser(prog="lbp.cli demo-setup")
    p.add_argument("--scale", choices=["compact", "full"], default="compact")
    p.add_argument("--force", action="store_true")
    p.add_argument("--kit", type=Path, default=None)
    p.add_argument("--data-dir", type=Path, default=None)
    args = p.parse_args(argv)
    if args.data_dir:
        os.environ["LBP_DATA_DIR"] = str(args.data_dir.resolve())
        from . import config
        from .store import db

        config.reset_settings()
        db.reset_engine()
    try:
        result = run_demo_setup(scale=args.scale, force=args.force, kit_dir=args.kit)
    except DemoSetupConflict as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 2
    print(json.dumps({"ok": True, **result.to_dict()}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Command line: `snowcv <command>` or `python -m snowcv <command>`."""

from __future__ import annotations

import argparse
import json
import sys

from snowcv.core.config import load_config
from snowcv.core.layout import Layout
from snowcv.core.licences import UnknownLicenceError, evaluate, parse_licence
from snowcv.core.manifest import Manifest
from snowcv.core.schema import SchemaNotFrozenError, check_frozen, freeze, load_schema


def _open(args) -> tuple:
    cfg = load_config(args.config)
    schema = load_schema()
    check_frozen(schema)
    return cfg, schema


def cmd_init(args) -> int:
    cfg, schema = _open(args)
    Layout(cfg.data_root, schema).ensure()
    with Manifest.open(cfg, schema) as m:
        info = m.info()
    print(f"data root:  {cfg.data_root}")
    print(f"manifest:   {cfg.manifest_path}")
    print(f"schema:     v{info['label_schema_version']} ({info['label_schema_sha256'][:12]})")
    return 0


def cmd_schema_check(args) -> int:
    schema = load_schema()
    try:
        check_frozen(schema)
    except SchemaNotFrozenError as e:
        print(f"NOT FROZEN: {e}", file=sys.stderr)
        return 1
    print(f"OK: label schema v{schema.version} frozen ({schema.sha256[:12]})")
    return 0


def cmd_schema_freeze(args) -> int:
    schema = load_schema()
    path = freeze(schema)
    print(f"froze label schema v{schema.version} ({schema.sha256[:12]}) -> {path}")
    return 0


def cmd_schema_show(args) -> int:
    schema = load_schema()
    print(f"label schema v{schema.version}  ignore_index={schema.ignore_index}")
    for layer in schema.layers.values():
        print(f"\n[{layer.name}] {layer.description}")
        for c in layer.classes:
            print(f"  {c.id:>3}  {c.name:<22} rgb{c.color}")
    print("\n[texture materials]")
    for mat in schema.texture_materials:
        print(f"  {mat.name:<14} -> {mat.snow_class}")
    return 0


def cmd_licence(args) -> int:
    try:
        lic = parse_licence(args.text, args.version)
    except UnknownLicenceError as e:
        print(f"reject: {e}")
        return 1
    cfg = load_config(args.config)
    decision, reason = evaluate(
        lic, allow_share_alike=cfg.licence_policy.allow_share_alike, allow_gfdl=cfg.licence_policy.allow_gfdl
    )
    print(f"{decision.value}: {reason}")
    return 0 if decision.value != "reject" else 1


def cmd_stats(args) -> int:
    cfg, schema = _open(args)
    with Manifest.open(cfg, schema) as m:
        print(json.dumps(m.stats(), indent=2, ensure_ascii=False))
    return 0


def cmd_show(args) -> int:
    cfg, schema = _open(args)
    with Manifest.open(cfg, schema) as m:
        try:
            rec = m.get(args.asset_id)
        except KeyError:
            print(f"no asset {args.asset_id}", file=sys.stderr)
            return 1
        out = {
            "asset": rec.model_dump(mode="json"),
            "parents": m.parents(rec.asset_id),
            "history": [h.__dict__ for h in m.history(rec.asset_id)],
            "attribution": m.attribution(rec.asset_id),
        }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def cmd_check_splits(args) -> int:
    cfg, schema = _open(args)
    with Manifest.open(cfg, schema) as m:
        violations = m.check_split_integrity()
    for v in violations:
        print(v)
    print(f"{len(violations)} violation(s)")
    return 1 if violations else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="snowcv", description="Snow Clearance CV dataset tooling")
    p.add_argument("--config", help="config YAML (default: $SNOWCV_CONFIG or built-in defaults)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the data layout and manifest").set_defaults(func=cmd_init)

    sp = sub.add_parser("schema", help="label schema").add_subparsers(dest="schema_cmd", required=True)
    sp.add_parser("check", help="verify the schema matches its lock").set_defaults(func=cmd_schema_check)
    sp.add_parser("freeze", help="write the lock (requires a version bump on change)").set_defaults(
        func=cmd_schema_freeze
    )
    sp.add_parser("show", help="print classes").set_defaults(func=cmd_schema_show)

    lp = sub.add_parser("licence", help="check a licence string against the admission policy")
    lp.add_argument("text")
    lp.add_argument("--version", help="licence version when given separately (Openverse)")
    lp.set_defaults(func=cmd_licence)

    mp = sub.add_parser("manifest", help="provenance manifest").add_subparsers(dest="manifest_cmd", required=True)
    mp.add_parser("stats", help="counts by origin/source/split/licence").set_defaults(func=cmd_stats)
    show = mp.add_parser("show", help="one asset with parents, history and attribution")
    show.add_argument("asset_id")
    show.set_defaults(func=cmd_show)
    mp.add_parser("check-splits", help="report camera/day/ancestry leakage between splits").set_defaults(
        func=cmd_check_splits
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SchemaNotFrozenError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

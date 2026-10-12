# Snow Clearance CV

Dataset tooling for detecting uncleared snow on parking lots, sidewalks, yards and roofs from client CCTV cameras.

- Plan: [`docs/dataset_code_plan.md`](docs/dataset_code_plan.md)
- Current stage: **Stage 0: Foundations** ([status](docs/stage0/README.md))

## Setup

```bash
pip install -e ".[dev]"
snowcv schema check     # label schema matches its lock
snowcv init             # creates ./data layout + data/manifest.sqlite
pytest
```

Data never goes into git. Set `SNOWCV_DATA_ROOT` (or `--config path.yaml`) to put it elsewhere.

## Layout

```
src/snowcv/core/        M0: config, label schema, licence policy, file layout, manifest
  resources/labels.yaml       frozen label schema (v1.0.0)
  resources/labels.lock.json  schema hash; any edit needs a version bump + `snowcv schema freeze`
config/default.yaml     project config (data root, licence and split policy)
docs/stage0/            Stage 0 checklists: client agreement, legal questions, access requests
tests/
```

## Commands

| Command | What it does |
|---|---|
| `snowcv schema show` | Print surface/snow classes and texture materials |
| `snowcv schema check` / `freeze` | Verify / re-lock the label schema |
| `snowcv licence "CC BY-SA 4.0"` | Run a licence string through the admission policy |
| `snowcv manifest stats` | Counts by origin, source, split, licence |
| `snowcv manifest show <asset_id>` | Record, parents, processing history, attribution chain |
| `snowcv manifest check-splits` | Camera / day / ancestry leakage between train, val, test |

## Using the core from other modules

```python
from snowcv.core import AssetRecord, Layout, Manifest, file_sha256, load_config, load_schema

cfg, schema = load_config("config/default.yaml"), load_schema()
layout = Layout(cfg.data_root, schema)
with Manifest.open(cfg, schema) as m:
    path = layout.raw_harvested("wikimedia", "Snowy_roof.jpg")
    m.add_asset(
        AssetRecord(origin="harvested", source="wikimedia", source_id="File:Snowy_roof.jpg",
                    url="https://commons.wikimedia.org/wiki/File:Snowy_roof.jpg",
                    author="...", licence="CC BY-SA 4.0",
                    path=layout.rel(path), sha256=file_sha256(path)),
        module="M1.harvest_sources",
    )
```

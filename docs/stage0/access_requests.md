# Access requests (Stage 0)

Keep credentials out of git: put them in `.env` (ignored) or a secrets store and record only **who holds them** here.

## 1. SAM 3 weights (M5 prelabel)

| Field | Value |
|---|---|
| What | Segment Anything 3 checkpoints (text-prompted segmentation) |
| Where | Gated model repo on Hugging Face (Meta, `facebook/sam3` at time of writing; check the official SAM 3 GitHub README for the current link) |
| How | Log in to Hugging Face with the team account → open the model page → accept the licence and submit the access form → wait for approval → create a read token |
| Before use | Save a copy of the licence text in `docs/licences/` and confirm it allows commercial use of **outputs used as pre-labels** (add to `legal_questions.md` Q4 if unclear) |
| Fallback while waiting | Grounding DINO + SAM 2 (both Apache-2.0) |
| Requested on | _date_ |
| Granted on | _date_ |
| Token holder | _name_ |

## 2. Mapillary API token (M1 harvest)

| Field | Value |
|---|---|
| What | Mapillary API v4 client token |
| Where | mapillary.com → Dashboard → Developers → register an application |
| Scopes needed | Read only (image search by bbox + capture date, image thumbnails, metadata) |
| Imagery licence | CC BY-SA 4.0, so the manifest stores it as `CC-BY-SA-4.0` with the `share_alike` flag |
| Terms to respect | No attempt to re-identify people or vehicles. Images go through M3 before use (the manifest blocks split assignment until `privacy_status = blurred`) |
| Planned queries | Novosibirsk and similar cities. Nov–Mar for snowy scenes, Jun–Aug for snow-free backgrounds |
| Requested on | _date_ |
| Token holder | _name_ |
| Stored as | env var `MAPILLARY_TOKEN` |

## 3. Other sources (no token needed, check before M1)

- **Openverse API:** anonymous access is rate limited; register an OAuth app for higher limits. Filter `license_type=commercial,modification`; the manifest re-checks every licence anyway.
- **Wikimedia Commons API:** set a descriptive `User-Agent` with contact email (Wikimedia policy).
- **Poly Haven / ambientCG:** CC0; keep the asset page URL as `url` in the manifest.

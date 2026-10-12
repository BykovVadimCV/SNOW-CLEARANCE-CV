# Client agreement checklist (Stage 0)

Four things must be agreed with the client before Stage 1 can start pulling frames:
how we reach the cameras, what we measure, where the alarm threshold sits, and the legal
basis for processing. Each answer below feeds a specific module; the module is noted per section.

Status legend: `[ ]` open · `[~]` discussed, not signed · `[x]` agreed (link the email / minutes)

---

## A. Camera access (M2 client_ingest)

- [ ] Access method per camera: **RTSP stream** / **VMS export** (which VMS, which API version) / **snapshot HTTP API**
- [ ] Network path: public IP, VPN, or an on-site box pushing frames out
- [ ] Credentials: who issues them and how they are handed over (not by email in clear text; never in git)
- [ ] Polling rate allowed: we need **1 frame per 15–30 min** through the winter, plus a burst of snow-free frames now
- [ ] Night / IR mode: which cameras switch to IR, and at what times
- [ ] Notice of camera moves or replacements: the client tells us when a camera is moved or replaced (this invalidates calibration, M4)
- [ ] Site plans with dimensions, if available (they make M4 calibration metric)

Fill one row per camera:

| camera_id | site / address | what it sees (parking, sidewalk, yard, roof) | resolution | IR | access method | contact |
|---|---|---|---|---|---|---|
| cam01 | | | | | | |

`camera_id` must match `[A-Za-z0-9._-]`; it becomes a folder name and the manifest key.

## B. Metric (M4, M9, M14)

Proposal for discussion:

- **Unit:** snow-covered **ground area in m²** and **% of the inspection zone**, per surface class (parking, sidewalk, yard driveway, each roof type). Measured top-down through the camera calibration, so the result does not depend on how far the area is from the camera.
- **Inspection zone:** a polygon drawn per camera in the M4 tool. **Storage zones** are drawn separately and excluded.
- **Occluded ground** (parked cars) is excluded from both the numerator and the denominator, and reported as "% visible".
- [ ] Agreed metric: ______________________

## C. Decision threshold (M9 sampler, M14 evaluation)

- [ ] The flag rule. Examples:
  - coverage above X % of the zone
  - any contiguous snow patch above Y m²
  - piles outside storage zones
- [ ] Time rule: flag only if snow is still present **after the regulatory deadline counted from the end of snowfall**
  - GOST R 50597-2017, tables 8.1–8.4
  - Novosibirsk 12-hour rule
  - the snowfall end time comes later from a weather feed (M15)
- [ ] Roofs: what triggers a flag?
  - accumulation above 30 cm?
  - icicles over pedestrian areas?
  - snow overhanging the edge?
- [ ] Which matters more to the client: **missed snow** (recall) or **false alarms** (precision)? This sets where M14 measures and where M9 oversamples.

## D. What counts as snow (labelling rules, schema v1.0.0)

The label classes are frozen (`snowcv schema show`). Confirm how each one is treated:

| Snow class | Counts towards the flag? | Notes |
|---|---|---|
| fresh | [ ] | Does a thin dusting count, or only above some depth? |
| packed (incl. ruts, trodden paths) | [ ] | |
| slush_ice (slush, glaze, ice crust) | [ ] | Wet asphalt with no slush does **not** count (it is `none`) |
| pile | [ ] | Inside a storage zone it never counts. Windrows along edges: allowed for how many hours? |

- [ ] Snow on parked cars, fences and walls is labelled, but never counted (it sits on `other`).
- [ ] De-icing reagent stains and wet patches: not snow.

## E. Personal data: processing assignment (152-FZ art. 6 p. 3)

Camera frames can show people's faces and car plates. We process them **on the client's instruction**: the client is the operator and we are the processor. The assignment (поручение) should state:

- [ ] Purposes: detecting snow and checking clearance; building training data for that
- [ ] The personal data covered (video frames that may contain images of people and vehicle plates) and the actions on it:
  - collection
  - recording
  - storage
  - **blurring at ingest**
  - use of the blurred frames for model training
  - deletion
- [ ] Our duties:
  - keep the data confidential
  - apply security measures under art. 19
  - notify the client of incidents
  - provide documents on request
  - (the lawyer confirms the full required list for the current wording of art. 6 p. 3)
- [ ] **Originals are never stored.** Faces and plates are blurred before the frame is written (M3). The manifest refuses unblurred client frames.
- [ ] Storage location: servers in the Russian Federation (art. 18 p. 5). List any subprocessors (cloud GPU), with their countries.
- [ ] Retention: how long blurred frames and labels are kept, and deletion at contract end
- [ ] Right to use **blurred** client frames in our training sets after the contract ends: yes or no
- [ ] Signed by: ______  Date: ______

## F. Practicalities

- [ ] Contact for camera outages
- [ ] Who on the client side reviews sample labels (to align on the snow definition early)
- [ ] Pilot plan: operator verdicts are fed back as labels, including a random sample of unflagged frames (Stage 6)

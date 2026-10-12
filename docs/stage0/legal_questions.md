# Open legal questions (Stage 0)

These questions are for the lawyer. For each one: what we do today, and what changes depending on the answer.
The data pipeline already records the information needed to act on any answer: the manifest stores licence, author, URL and full ancestry for every image and texture patch.

## Licences of training data

**Q1. Share-alike scope.**
- **Situation:** Mapillary imagery and many Wikimedia images are CC BY-SA 4.0. We use them in three ways:
  - (a) whole images in the training set
  - (b) cut-out texture patches composited into synthetic images
  - (c) backgrounds for synthetic images
- **Questions:**
  - Does BY-SA attach to the **synthetic images** we produce?
  - Does it attach to the **dataset** as a whole?
  - Does it attach to the **trained model weights**?
  - What must we do to comply (attribution file, licence notice, releasing the derived images under BY-SA)?
- **Today:** BY-SA images are admitted and flagged `share_alike` (config `allow_share_alike: true`). `Manifest.attribution()` lists every BY-SA ancestor of each output.
- **If the answer is restrictive:** set `allow_share_alike: false`, or keep BY-SA images out of the synthetic pipeline only.

**Q2. Attribution form.** CC BY requires credit. Is a dataset-level attribution file shipped with the dataset (author, title/URL, licence, "modified") enough for:
- texture patches cut from photos and blended into thousands of synthetic images?
- the trained model, if it is delivered to the client?

**Q3. Public-domain marks on Wikimedia.** Commons uses many `PD-*` templates (PD-old, PD-self, PD-USGov ...). Which of them are safe to treat as public domain for commercial use in Russia? Today only plain "Public domain" / PDM / CC0 are accepted.

## Models used as tools

**Q4. Models trained on non-commercial data, used only for pre-labels.**
- **Situation:** OneFormer / Mask2Former checkpoints were trained on datasets with non-commercial terms (e.g. ADE20K, Cityscapes). We would use them **offline to draft masks** that humans then correct (M5). The models are never shipped.
- **Question:** Is that permitted? Do the corrected labels inherit any restriction?
- **The same question applies to:**
  - SAM 3 under its own licence
  - any model whose weights licence differs from its code licence

**Q5. Depth Anything V2.** Only the Small checkpoint is Apache-2.0; the larger ones are non-commercial. We use only Small (M4). Please confirm no further obligation.

**Q6. AGPL.** We avoid Ultralytics YOLO (AGPL-3.0) for face and plate detection (M3). Please confirm that is necessary for a hosted service, and name what we should check in other detector licences.

## Personal data (152-FZ)

**Q7. Processing assignment.** Please give the required contents of the processing assignment (art. 6 p. 3, current wording), and check the draft list in `client_agreement.md` section E.

**Q8. Status of blurred frames.**
- **Situation:** faces and plates are blurred at ingest; originals are never stored.
- **Questions:**
  - Are the blurred frames still personal data?
  - Can we keep them, and use them for training, after the client contract ends?
  - Is camera footage used only for snow detection (no identification) outside the scope of biometric personal data (art. 11)?

**Q9. Localisation and cross-border transfer.**
- If we train on GPU servers outside Russia using only **blurred** frames:
  - is that a cross-border transfer (art. 12)?
  - does it need notification to Roskomnadzor?
- What does art. 18 p. 5 require for the initial collection and storage?

**Q10. Own capture campaign (Stage 4).** We plan to photograph car parks and sidewalks before and after clearing, with blurring at capture. What notices or permissions do we need on private property (courtyards, client sites)?

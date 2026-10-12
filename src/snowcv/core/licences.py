"""Licence parsing and the admission policy for third-party images.

Rule (plan M1): keep only licences that allow commercial use AND modification.
That drops every NC and every ND variant. Share-alike (BY-SA, incl. all
Mapillary imagery) is admitted but flagged until the lawyer answers the
share-alike scope question (docs/stage0/legal_questions.md, Q1).

Internal licence codes (not from third parties):
  CLIENT-DPA  client camera frames, processed under the client's
              data-processing assignment (152-FZ art. 6 p. 3)
  OWN         our own captures
  DERIVED     generated from other assets; the effective terms are the union
              of the ancestors' terms (see Manifest.attribution)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class UnknownLicenceError(ValueError):
    pass


class Decision(str, Enum):
    ALLOW = "allow"
    FLAG = "flag"  # admitted, but carries an open legal question
    REJECT = "reject"


@dataclass(frozen=True)
class Licence:
    code: str  # canonical, e.g. "CC-BY-SA-4.0", "CC0-1.0", "PDM"
    commercial: bool
    derivatives: bool
    share_alike: bool
    attribution: bool
    internal: bool = False

    @property
    def flag(self) -> str | None:
        if self.share_alike:
            return "share_alike"
        return None


CLIENT_DPA = Licence("CLIENT-DPA", commercial=True, derivatives=True, share_alike=False, attribution=False, internal=True)
OWN = Licence("OWN", commercial=True, derivatives=True, share_alike=False, attribution=False, internal=True)
DERIVED = Licence("DERIVED", commercial=True, derivatives=True, share_alike=False, attribution=False, internal=True)
INTERNAL = {lic.code: lic for lic in (CLIENT_DPA, OWN, DERIVED)}

_CC_VERSIONS = {"1.0", "2.0", "2.1", "2.5", "3.0", "4.0"}
_CC_ELEMENTS = {"by", "sa", "nc", "nd"}
_FILLER = {"cc", "international", "unported", "generic", "license", "licence", "deed", "legalcode"}


def _normalise(text: str) -> str:
    t = text.strip().lower()
    t = re.sub(r"https?://creativecommons\.org/(licenses|publicdomain)/", "cc-", t)
    t = t.replace("creative commons", "cc")
    for long, short in (
        ("attribution", "by"),
        ("share-alike", "sa"),
        ("sharealike", "sa"),
        ("non-commercial", "nc"),
        ("noncommercial", "nc"),
        ("no-derivatives", "nd"),
        ("noderivatives", "nd"),
        ("noderivs", "nd"),
        ("no derivatives", "nd"),
    ):
        t = t.replace(long, short)
    t = re.sub(r"[\s_/,()]+", "-", t)
    return re.sub(r"-+", "-", t).strip("-")


def parse_licence(text: str, version: str | None = None) -> Licence:
    """Parse free-form licence strings from Openverse, Wikimedia, Mapillary etc.

    ``version`` is for APIs that return it separately (Openverse: license="by-sa",
    license_version="4.0").
    """
    if not text or not text.strip():
        raise UnknownLicenceError("empty licence")
    if text.strip().upper() in INTERNAL:
        return INTERNAL[text.strip().upper()]

    t = _normalise(text)
    tokens = [tok for tok in t.split("-") if tok]
    joined = "-".join(tokens)

    found_versions = re.findall(r"\d\.\d", joined)
    ver = version.strip() if version else (found_versions[0] if found_versions else None)

    if joined.startswith(("cc0", "cc-zero", "zero")) or "cc0" in tokens or joined.startswith("cc-cc0"):
        return Licence("CC0-1.0", True, True, False, False)
    if joined in {"pdm", "pd", "public-domain", "publicdomain", "cc-mark", "cc-pdm", "pd-mark"} or joined.startswith(
        ("public-domain", "pdm-", "cc-mark")
    ):
        return Licence("PDM", True, True, False, False)
    if joined.startswith("gfdl") or "gfdl" in tokens:
        return Licence("GFDL", commercial=True, derivatives=True, share_alike=True, attribution=True)

    elems = [tok for tok in tokens if tok not in _FILLER and not re.fullmatch(r"\d\.\d|\d", tok)]
    # Ported licences ("CC BY-SA 3.0 DE") carry a jurisdiction code after the version.
    ports = [tok for tok in elems if len(tok) == 2 and tok.isalpha() and tok not in _CC_ELEMENTS]
    elems = [tok for tok in elems if tok not in ports]
    if elems and elems[0] == "by" and set(elems) <= _CC_ELEMENTS and len(ports) <= 1:
        nc, nd, sa = "nc" in elems, "nd" in elems, "sa" in elems
        if nd and sa:
            raise UnknownLicenceError(f"invalid CC combination in {text!r}")
        if ver is not None and ver not in _CC_VERSIONS:
            raise UnknownLicenceError(f"unknown CC version {ver!r} in {text!r}")
        code = "CC-" + "-".join(["BY"] + [e.upper() for e in ("nc", "nd", "sa") if e in elems])
        if ver:
            code += f"-{ver}"
        if ports:
            code += f"-{ports[0].upper()}"
        return Licence(code, commercial=not nc, derivatives=not nd, share_alike=sa, attribution=True)

    raise UnknownLicenceError(f"unrecognised licence {text!r}")


def evaluate(lic: Licence, *, allow_share_alike: bool = True, allow_gfdl: bool = False) -> tuple[Decision, str]:
    """Admission decision for a third-party licence, with a human-readable reason."""
    if lic.internal:
        return Decision.ALLOW, "internal licence"
    if not lic.commercial:
        return Decision.REJECT, f"{lic.code}: non-commercial"
    if not lic.derivatives:
        return Decision.REJECT, f"{lic.code}: no derivatives"
    if lic.code == "GFDL" and not allow_gfdl:
        return Decision.REJECT, "GFDL: impractical for images (full licence text must travel); pick a CC dual licence"
    if lic.share_alike:
        if not allow_share_alike:
            return Decision.REJECT, f"{lic.code}: share-alike disabled by policy"
        return Decision.FLAG, f"{lic.code}: share-alike, scope pending legal review"
    return Decision.ALLOW, f"{lic.code}: commercial use and modification allowed"

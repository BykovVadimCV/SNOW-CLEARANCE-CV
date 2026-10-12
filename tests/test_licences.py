import pytest

from snowcv.core.licences import Decision, UnknownLicenceError, evaluate, parse_licence


@pytest.mark.parametrize(
    "text, version, code, decision",
    [
        ("CC0", None, "CC0-1.0", Decision.ALLOW),
        ("cc0", "1.0", "CC0-1.0", Decision.ALLOW),
        ("https://creativecommons.org/publicdomain/zero/1.0/", None, "CC0-1.0", Decision.ALLOW),
        ("pdm", None, "PDM", Decision.ALLOW),
        ("Public domain", None, "PDM", Decision.ALLOW),
        ("CC BY 4.0", None, "CC-BY-4.0", Decision.ALLOW),
        ("by", "2.0", "CC-BY-2.0", Decision.ALLOW),
        ("Creative Commons Attribution-ShareAlike 4.0 International", None, "CC-BY-SA-4.0", Decision.FLAG),
        ("by-sa", "4.0", "CC-BY-SA-4.0", Decision.FLAG),
        ("CC BY-SA 3.0 DE", None, "CC-BY-SA-3.0-DE", Decision.FLAG),
        ("CC BY-ND 4.0", None, "CC-BY-ND-4.0", Decision.REJECT),
        ("by-nc-sa", "2.0", "CC-BY-NC-SA-2.0", Decision.REJECT),
        ("CC BY-NC-ND 4.0", None, "CC-BY-NC-ND-4.0", Decision.REJECT),
        ("https://creativecommons.org/licenses/by-nc/4.0/", None, "CC-BY-NC-4.0", Decision.REJECT),
        ("GFDL", None, "GFDL", Decision.REJECT),
    ],
)
def test_parse_and_policy(text, version, code, decision):
    lic = parse_licence(text, version)
    assert lic.code == code
    assert evaluate(lic)[0] is decision


@pytest.mark.parametrize("text", ["", "All rights reserved", "Copyrighted free use", "by-nd-sa", "CC BY 9.9"])
def test_unknown_rejected(text):
    with pytest.raises(UnknownLicenceError):
        parse_licence(text)


def test_share_alike_switch():
    lic = parse_licence("CC BY-SA 4.0")
    assert evaluate(lic, allow_share_alike=False)[0] is Decision.REJECT
    assert lic.flag == "share_alike"


def test_internal_codes():
    for code in ("CLIENT-DPA", "OWN", "DERIVED"):
        lic = parse_licence(code)
        assert lic.internal and evaluate(lic)[0] is Decision.ALLOW

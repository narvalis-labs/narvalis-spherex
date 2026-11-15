"""Name-resolution fallback (no network: SIMBAD and HTTP are mocked)."""
import pytest

import epochlab.references as refs

# Hand-written XML in the Sesame -oxp layout, for parser testing only (values are placeholders).
XML = """<?xml version="1.0"?><Sesame><Target option="SNV"><name>TestStar</name>
<Resolver name="S=Simbad (via url):    1"><oname>TestStar</oname>
<jradeg>10.5</jradeg><jdedeg>-20.25</jdedeg>
<pmRA>123.4</pmRA><pmDE>-56.7</pmDE><plx><v>89.1</v><e>0.1</e></plx><Vel><v>-12.3</v></Vel>
</Resolver></Target></Sesame>"""


def test_parse_sesame():
    r = refs.parse_sesame_xml(XML, "TestStar")
    assert (r.ra_deg, r.dec_deg, r.pmra_masyr, r.pmdec_masyr, r.parallax_mas, r.rv_kms) == (10.5, -20.25, 123.4, -56.7, 89.1, -12.3)
    assert r.epoch_jyear == 2000.0 and r.source.startswith("Sesame/")


def test_parse_sesame_not_found():
    with pytest.raises(LookupError):
        refs.parse_sesame_xml("<Sesame><Target><Resolver name='S'><INFO>nothing</INFO></Resolver></Target></Sesame>", "x")


def test_fallback_when_simbad_tap_fails(monkeypatch):
    def boom(name):
        raise RuntimeError("Unable to access the capabilities endpoint: 404 Not Found")
    monkeypatch.setattr(refs, "resolve_simbad", boom)
    monkeypatch.setattr(refs, "resolve_sesame", lambda n: refs.parse_sesame_xml(XML, n))
    ref, log = refs.resolve_name("TestStar")
    assert ref.ra_deg == 10.5 and "resolve_simbad failed" in log[0]


def test_all_resolvers_fail(monkeypatch):
    monkeypatch.setattr(refs, "resolve_simbad", lambda n: (_ for _ in ()).throw(RuntimeError("a")))
    monkeypatch.setattr(refs, "resolve_sesame", lambda n: (_ for _ in ()).throw(RuntimeError("b")))
    with pytest.raises(LookupError, match="could not resolve"):
        refs.resolve_name("x")


# Nested layout (pm inside <pm>, as Sesame returns it for SIMBAD answers); values are placeholders.
XML_NESTED = """<?xml version="1.0"?><Sesame><Target option="SNV"><name>T2</name>
<Resolver name="S=Simbad (via url):    1"><oname>T2</oname><jradeg>331.2</jradeg><jdedeg>-56.8</jdedeg>
<pm><v>4700</v><e>1</e><pmRA>3900.5</pmRA><epmRA>1</epmRA><pmDE>-2500.25</pmDE><epmDE>1</epmDE></pm>
<plx><v>270.1</v><e>0.5</e></plx></Resolver></Target></Sesame>"""


def test_parse_sesame_nested_pm():
    r = refs.parse_sesame_xml(XML_NESTED, "T2")
    assert (r.pmra_masyr, r.pmdec_masyr, r.parallax_mas, r.pm_known) == (3900.5, -2500.25, 270.1, True)


def test_missing_pm_is_flagged_not_zeroed_silently():
    xml = XML_NESTED.replace("<pm><v>4700</v><e>1</e><pmRA>3900.5</pmRA><epmRA>1</epmRA><pmDE>-2500.25</pmDE><epmDE>1</epmDE></pm>", "")
    r = refs.parse_sesame_xml(xml, "T2")
    assert r.pm_known is False
    ref, note = refs.match_gaia(r)
    assert ref is None and "no proper motion" in note

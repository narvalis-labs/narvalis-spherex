"""Catalogue references: SIMBAD name resolution and Gaia DR3 astrometry, plus static control stars."""
from __future__ import annotations

import numpy as np

from .astrometry import AstrometricReference, predict_position

GAIA_TAP = "https://gea.esac.esa.int/tap-server/tap"
GAIA_COLS = ("source_id, ra, dec, pmra, pmdec, pmra_error, pmdec_error, parallax, "
             "radial_velocity, phot_g_mean_mag, ref_epoch")


def _col(row, *names):
    for n in names:
        for cand in (n, n.upper(), n.lower()):
            try:
                v = row[cand]
            except (KeyError, IndexError, ValueError):
                continue
            if np.ma.is_masked(v):
                return None
            try:
                v = float(v)
            except (TypeError, ValueError):
                return v
            return v if np.isfinite(v) else None
    return None


def resolve_simbad(name: str) -> AstrometricReference:
    """SIMBAD position (ICRS, epoch J2000) and proper motion/parallax/RV for `name`."""
    from astroquery.simbad import Simbad

    s = Simbad()
    for fields in (("pmra", "pmdec", "plx_value", "rvz_radvel"), ("pmra", "pmdec", "plx", "rv_value")):
        try:
            s.add_votable_fields(*fields)
            break
        except Exception:  # noqa: BLE001
            s = Simbad()
    t = s.query_object(name)
    if t is None or len(t) == 0:
        raise LookupError(f"SIMBAD could not resolve '{name}'")
    r = t[0]
    ra, dec = _col(r, "ra"), _col(r, "dec")
    if ra is None or dec is None or isinstance(ra, str):
        from astropy.coordinates import SkyCoord
        import astropy.units as u
        c = SkyCoord(str(_col(r, "RA")), str(_col(r, "DEC")), unit=(u.hourangle, u.deg))
        ra, dec = c.ra.deg, c.dec.deg
    pmra, pmdec = _col(r, "pmra", "PMRA"), _col(r, "pmdec", "PMDEC")
    known = isinstance(pmra, float) and isinstance(pmdec, float)
    return AstrometricReference(
        ra_deg=float(ra), dec_deg=float(dec), epoch_jyear=2000.0,
        pmra_masyr=pmra if known else 0.0, pmdec_masyr=pmdec if known else 0.0, pm_known=known,
        parallax_mas=_col(r, "plx_value", "PLX_VALUE", "plx"), rv_kms=_col(r, "rvz_radvel", "RV_VALUE"),
        source=f"SIMBAD {_col(r, 'main_id', 'MAIN_ID') or name}",
    )


SESAME_URLS = (
    "https://cds.unistra.fr/cgi-bin/nph-sesame/-oxp/SNV?{q}",
    "https://vizier.cfa.harvard.edu/viz-bin/nph-sesame/-oxp/SNV?{q}",
)


def parse_sesame_xml(xml_text: str, name: str) -> AstrometricReference:
    """Parse a CDS Sesame -oxp XML answer. Positions are ICRS at epoch J2000 (Sesame convention);
    pmRA is mu_alpha* in mas/yr. Raises LookupError if no resolver returned a position."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml_text)
    for res in root.iter("Resolver"):
        ra, dec = res.findtext("jradeg"), res.findtext("jdedeg")
        if not ra or not dec:
            continue
        def num(tag):
            # Sesame nests some values (e.g. <pm><pmRA>..</pmRA></pm>, <plx><v>..</v></plx>): search descendants
            el = res.find(f".//{tag}")
            if el is None:
                return None
            txt = el.findtext("v") if el.find("v") is not None else el.text
            try:
                return float(txt)
            except (TypeError, ValueError):
                return None
        pmra, pmdec = num("pmRA"), num("pmDE")
        known = pmra is not None and pmdec is not None
        return AstrometricReference(
            ra_deg=float(ra), dec_deg=float(dec), epoch_jyear=2000.0,
            pmra_masyr=pmra if known else 0.0, pmdec_masyr=pmdec if known else 0.0, pm_known=known,
            parallax_mas=num("plx"), rv_kms=num("Vel"),
            source=f"Sesame/{res.get('name', '?').strip()} {res.findtext('oname') or name}",
        )
    raise LookupError(f"Sesame returned no position for '{name}'")


def resolve_sesame(name: str, timeout: float = 30.0) -> AstrometricReference:
    import httpx
    from urllib.parse import quote
    errs = []
    for url in SESAME_URLS:
        try:
            r = httpx.get(url.format(q=quote(name)), timeout=timeout, follow_redirects=True)
            r.raise_for_status()
            return parse_sesame_xml(r.text, name)
        except Exception as exc:  # noqa: BLE001
            errs.append(f"{url.split('/')[2]}: {type(exc).__name__}: {exc}")
    raise LookupError("; ".join(errs))


def resolve_name(name: str) -> tuple[AstrometricReference, list[str]]:
    """SIMBAD (astroquery/TAP) first, then CDS Sesame and its CfA mirror. Returns (ref, log)."""
    log = []
    for fname in ("resolve_simbad", "resolve_sesame"):
        try:
            ref = globals()[fname](name)
            return ref, log
        except Exception as exc:  # noqa: BLE001
            msg = " ".join(str(exc).split())[:300]
            log.append(f"{fname} failed: {type(exc).__name__}: {msg}")
    raise LookupError(f"could not resolve '{name}'. " + " | ".join(log))


GAIA_MIRRORS = (
    # (label, TAP url, table, ADQL column list). GAVO's dr3lite is a column subset of gaiadr3.gaia_source with
    # identical values; ref_epoch is constant 2016.0 in DR3, so it is supplied as a literal.
    ("ESA Gaia archive", GAIA_TAP, "gaiadr3.gaia_source", GAIA_COLS),
    ("GAVO Heidelberg mirror", "https://dc.zah.uni-heidelberg.de/tap", "gaia.dr3lite",
     "source_id, ra, dec, pmra, pmdec, pmra_error, pmdec_error, parallax, radial_velocity, phot_g_mean_mag, "
     "2016.0 AS ref_epoch"),
)
GAIA_FIELDS = ("source_id", "ra", "dec", "pmra", "pmdec", "pmra_error", "pmdec_error", "parallax",
               "radial_velocity", "phot_g_mean_mag", "ref_epoch")
GAIA_TIMEOUT_S = 25.0


def _gaia_cache_path(ra: float, dec: float, radius_arcsec: float, top: int):
    import hashlib
    from .config import settings
    key = hashlib.sha256(f"{ra:.8f},{dec:.8f},{radius_arcsec / 3600.0:.8f},{top}".encode()).hexdigest()[:24]
    return settings.data_dir / "cache" / "gaia" / f"{key}.json"


def _rows_to_table(rows: list[dict]):
    from astropy.table import MaskedColumn, Table
    t = Table()
    for f in GAIA_FIELDS:
        vals = [r.get(f) for r in rows]
        mask = [v is None for v in vals]
        fill = 0 if f == "source_id" else np.nan
        data = np.array([fill if v is None else v for v in vals], dtype=np.int64 if f == "source_id" else float)
        t[f] = MaskedColumn(data, mask=mask)
    return t


def _table_to_rows(tab) -> list[dict]:
    out = []
    for r in tab:
        d = {}
        for f in GAIA_FIELDS:
            v = r[f] if f in r.colnames else None
            if v is None or np.ma.is_masked(v):
                d[f] = None
            elif f == "source_id":
                d[f] = int(v)
            else:
                v = float(v)
                d[f] = v if np.isfinite(v) else None
        out.append(d)
    return out


def _tap_sync(url: str, query: str):
    """Synchronous TAP query with a hard timeout (pyvo's run_sync has none and would wait for minutes)."""
    import io
    import httpx
    from astropy.io.votable import parse_single_table
    r = httpx.post(url.rstrip("/") + "/sync", timeout=GAIA_TIMEOUT_S, follow_redirects=True,
                   data={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "votable", "QUERY": query})
    r.raise_for_status()
    return parse_single_table(io.BytesIO(r.content)).to_table()


def gaia_cone(ra: float, dec: float, radius_arcsec: float, top: int = 200):
    """Gaia DR3 cone search. Order: local cache, ESA archive, GAVO mirror (same DR3 values).

    Every successful answer is cached on disk, so a reanalysis is reproducible even when the archives are down.
    Returns (table, description of the query and the service that answered).
    """
    import json
    cpath = _gaia_cache_path(ra, dec, radius_arcsec, top)
    where = (f"1=CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra:.8f}, {dec:.8f}, {radius_arcsec / 3600.0:.8f}))"
             f" ORDER BY phot_g_mean_mag")
    if cpath.exists():
        c = json.loads(cpath.read_text(encoding="utf-8"))
        return _rows_to_table(c["rows"]), f"{c['query']} [cached answer from {c['service']}]"
    errors = []
    for label, url, table, cols in GAIA_MIRRORS:
        q = f"SELECT TOP {top} {cols} FROM {table} WHERE {where}"
        try:
            tab = _tap_sync(url, q)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{label}: {type(exc).__name__}: {str(exc)[:160]}")
            continue
        rows = _table_to_rows(tab)
        try:
            cpath.parent.mkdir(parents=True, exist_ok=True)
            cpath.write_text(json.dumps({"service": label, "query": q, "rows": rows}), encoding="utf-8")
        except OSError:
            pass
        return _rows_to_table(rows), f"{q} [{label}]"
    raise ConnectionError("Gaia DR3 unavailable from every mirror: " + " | ".join(errors))


def _from_gaia_row(r) -> AstrometricReference:
    return AstrometricReference(
        ra_deg=float(r["ra"]), dec_deg=float(r["dec"]), epoch_jyear=float(r["ref_epoch"]),
        pmra_masyr=float(r["pmra"]), pmdec_masyr=float(r["pmdec"]),
        pmra_err=_col(r, "pmra_error"), pmdec_err=_col(r, "pmdec_error"),
        parallax_mas=_col(r, "parallax"), rv_kms=_col(r, "radial_velocity"),
        source=f"Gaia DR3 {int(r['source_id'])}",
    )


def match_gaia(seed: AstrometricReference, radius_arcsec: float = 3.0) -> tuple[AstrometricReference | None, str]:
    """Find the Gaia DR3 counterpart of a SIMBAD seed by propagating it to Gaia's epoch (2016.0)."""
    from astropy.time import Time
    mjd2016 = Time(2016.0, format="jyear", scale="tcb").utc.mjd
    if not seed.pm_known:
        return None, "resolver gave no proper motion, so the position cannot be propagated to Gaia's epoch"
    ra16, dec16 = predict_position(seed, mjd2016, include_parallax=False)
    rows, q = [], ""
    for rad in (radius_arcsec, 10.0):
        tab, q = gaia_cone(ra16, dec16, rad, top=20)
        rows = [r for r in tab if not np.ma.is_masked(r["pmra"])]
        if rad > radius_arcsec:  # wider search: only accept a source whose proper motion agrees
            tol = lambda r: max(50.0, 0.1 * np.hypot(seed.pmra_masyr, seed.pmdec_masyr))
            rows = [r for r in rows if np.hypot(float(r["pmra"]) - seed.pmra_masyr, float(r["pmdec"]) - seed.pmdec_masyr) < tol(r)]
        if rows:
            radius_arcsec = rad
            break
    if not rows:
        return None, f"no Gaia DR3 source with matching proper motion within 10\" (query: {q})"
    # Prefer the source whose proper motion agrees with SIMBAD, then the closest.
    def score(r):
        dpm = np.hypot(float(r["pmra"]) - seed.pmra_masyr, float(r["pmdec"]) - seed.pmdec_masyr)
        dpos = np.hypot((float(r["ra"]) - ra16) * np.cos(np.radians(dec16)), float(r["dec"]) - dec16) * 3600
        return dpm / 50.0 + dpos
    best = min(rows, key=score)
    return _from_gaia_row(best), f"matched within {radius_arcsec}\" of SIMBAD position propagated to 2016.0"


def static_controls(ra: float, dec: float, radius_arcsec: float, exclude_within_arcsec: float = 20.0,
                    max_pm: float = 5.0, gmag_range=(9.0, 15.0), n: int = 3) -> list[AstrometricReference]:
    """Bright, essentially static Gaia stars near the target, used as false-positive controls."""
    tab, _ = gaia_cone(ra, dec, radius_arcsec, top=500)
    out = []
    for r in tab:
        if np.ma.is_masked(r["pmra"]) or np.ma.is_masked(r["phot_g_mean_mag"]):
            continue
        g = float(r["phot_g_mean_mag"])
        if not (gmag_range[0] <= g <= gmag_range[1]):
            continue
        if np.hypot(float(r["pmra"]), float(r["pmdec"])) > max_pm:
            continue
        sep = np.hypot((float(r["ra"]) - ra) * np.cos(np.radians(dec)), float(r["dec"]) - dec) * 3600
        if sep < exclude_within_arcsec:
            continue
        out.append(_from_gaia_row(r))
        if len(out) >= n:
            break
    return out

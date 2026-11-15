"""IRSA SPHEREx archive access: SIA2 discovery, cutout download, on-disk cache and provenance.

Nothing here fabricates data: if the archive cannot be reached, an exception propagates and the
job is marked failed with the exact error.
"""
from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from pathlib import Path

import httpx
import numpy as np

from .config import Settings


@dataclass
class Observation:
    obs_id: str
    collection: str
    access_url: str
    t_min_mjd: float | None
    t_max_mjd: float | None
    em_min_m: float | None
    em_max_m: float | None
    bandpass: str | None
    subtype: str | None
    s_region: str | None

    @property
    def t_mid_mjd(self) -> float | None:
        if self.t_min_mjd is None or self.t_max_mjd is None:
            return self.t_min_mjd
        return 0.5 * (self.t_min_mjd + self.t_max_mjd)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["t_mid_mjd"] = self.t_mid_mjd
        return d


def _val(row, *names):
    for n in names:
        try:
            v = row[n]
        except (KeyError, IndexError, ValueError):
            continue
        if v is None or (hasattr(v, "mask") and bool(np.ma.getmaskarray(v).all())):
            continue
        if isinstance(v, bytes):
            v = v.decode()
        try:
            if isinstance(v, (np.floating, float)) and not np.isfinite(v):
                continue
        except TypeError:
            pass
        return v.item() if hasattr(v, "item") else v
    return None


_TRANSIENT = ("500", "502", "503", "504", "Proxy Error", "timed out", "Timeout", "Connection", "RemoteDisconnected",
              "Error reading from remote server")


def _is_transient(exc: Exception) -> bool:
    """Server-side or network hiccups worth retrying (IRSA returns intermittent 502 'Proxy Error' under load)."""
    txt = f"{type(exc).__name__}: {exc}"
    return any(t in txt for t in _TRANSIENT)


def _retry(fn, what: str, log: list[str] | None = None, attempts: int = 4, base_delay_s: float = 2.0):
    """Call fn(); on a transient error retry after 2, 4, 8 s. Non-transient errors are raised at once.
    Every retry is logged so the dossier/status shows what happened."""
    for k in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if k == attempts - 1 or not _is_transient(exc):
                raise
            delay = base_delay_s * 2 ** k
            if log is not None:
                log.append(f"{what}: transient error ({type(exc).__name__}: {str(exc)[:120]}), retry {k + 1}/{attempts - 1} in {delay:.0f} s")
            time.sleep(delay)


# SPHEREx per-epoch image collections seen at IRSA (Nov 2026); used only when live discovery fails
KNOWN_COLLECTIONS = ("spherex_dr1", "spherex_qr3")


def discover_collections() -> list[str]:
    """SPHEREx collections IRSA advertises right now (excluding all-sky cubes, which are not per-epoch)."""
    from astroquery.ipac.irsa import Irsa
    t = Irsa.list_collections(filter="spherex")
    names = [str(n) for n in t["collection"]]
    return [n for n in names if "cube" not in n.lower()]


def _sia_rows(svc, ra, dec, collection):
    kw = {"pos": (ra, dec, 1.0 / 3600.0), "maxrec": 20000}
    if collection:
        kw["collection"] = collection
    return svc.search(**kw).to_table()


def _rows_to_obs(tab, coll_label, only_spherex=False) -> list[Observation]:
    out = []
    for row in tab:
        url = _val(row, "access_url")
        if not url:
            continue
        coll = str(_val(row, "obs_collection") or coll_label or "")
        if only_spherex and "spherex" not in coll.lower():
            continue
        fmt = str(_val(row, "access_format") or "")
        if fmt and "fits" not in fmt.lower():
            continue
        dtype = str(_val(row, "dataproduct_type") or "image").lower()
        if dtype not in ("image", ""):
            continue
        out.append(Observation(
            obs_id=str(_val(row, "obs_id", "obs_publisher_did") or url.rsplit("/", 1)[-1]),
            collection=coll,
            access_url=str(url),
            t_min_mjd=_f(_val(row, "t_min")),
            t_max_mjd=_f(_val(row, "t_max")),
            em_min_m=_f(_val(row, "em_min")),
            em_max_m=_f(_val(row, "em_max")),
            bandpass=_s(_val(row, "energy_bandpassname")),
            subtype=_s(_val(row, "dataproduct_subtype")),
            s_region=_s(_val(row, "s_region")),
        ))
    return out


def query_observations(ra: float, dec: float, settings: Settings, collections: tuple[str, ...] | None = None,
                       log: list[str] | None = None) -> list[Observation]:
    """All SPHEREx spectral images whose footprint contains (ra, dec).

    Order: configured collections -> (if none returned anything, or 'auto') collections discovered from
    IRSA -> unrestricted SIA2 search filtered to obs_collection containing 'spherex'. Every attempt is logged.
    """
    import pyvo

    log = log if log is not None else []
    # IRSA's SIA URL is itself the SIA2 query endpoint, so pyvo's /capabilities lookup is skipped
    # (check_baseurl=False). That lookup is an extra round-trip that IRSA often answers with 502 'Proxy Error'
    # while the query endpoint keeps working. The searches below are retried on transient errors.
    svc = pyvo.dal.SIA2Service(settings.irsa_sia_url, check_baseurl=False)
    wanted = [c for c in (collections or settings.collections) if c.lower() != "auto"]
    out: list[Observation] = []

    def try_colls(colls, why):
        got = []
        for c in colls:
            try:
                o = _rows_to_obs(_retry(lambda: _sia_rows(svc, ra, dec, c), f"SIA2 '{c}'", log), c)
                log.append(f"SIA2 collection '{c}' ({why}): {len(o)} images")
                got += o
            except Exception as exc:  # noqa: BLE001
                log.append(f"SIA2 collection '{c}' ({why}) failed: {type(exc).__name__}: {exc}")
        return got

    out = try_colls(wanted, "configured")
    if not out:
        try:
            found = _retry(discover_collections, "collection discovery", log)
            log.append(f"IRSA advertises SPHEREx collections: {found}")
            out = try_colls([c for c in found if c not in wanted], "discovered")
        except Exception as exc:  # noqa: BLE001
            log.append(f"collection discovery failed: {type(exc).__name__}: {exc}")
            # discovery runs on IRSA's TAP service, which can be down while SIA still answers: try the known names
            out = try_colls([c for c in KNOWN_COLLECTIONS if c not in wanted], "known names, discovery unavailable")
    if not out:
        try:
            out = _rows_to_obs(_retry(lambda: _sia_rows(svc, ra, dec, None), "SIA2 unrestricted", log), None, only_spherex=True)
            log.append(f"SIA2 unrestricted search filtered to SPHEREx: {len(out)} images")
        except Exception as exc:  # noqa: BLE001
            log.append(f"SIA2 unrestricted search failed: {type(exc).__name__}: {exc}")

    # De-duplicate identical files that may appear in several collections (keep first = priority order)
    seen, uniq = set(), []
    for o in out:
        key = o.access_url.split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        uniq.append(o)
    uniq.sort(key=lambda o: (o.t_mid_mjd is None, o.t_mid_mjd or 0))
    return uniq


def _f(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _s(v):
    return None if v is None else str(v)


def select_spread(obs: list[Observation], n: int) -> list[Observation]:
    """Pick at most n observations spread evenly in time (deterministic)."""
    if len(obs) <= n:
        return list(obs)
    idx = np.unique(np.round(np.linspace(0, len(obs) - 1, n)).astype(int))
    return [obs[i] for i in idx]


@dataclass
class Download:
    url: str
    path: str
    sha256: str
    bytes: int
    cached: bool
    fetched_utc: str
    http_status: int | None

    def to_dict(self) -> dict:
        return asdict(self)


def cutout_url(obs: Observation, ra: float, dec: float, size_arcsec: float, settings: Settings) -> str:
    q = settings.cutout_query.format(ra=f"{ra:.7f}", dec=f"{dec:.7f}", size=f"{size_arcsec / 3600.0:.6f}")
    return obs.access_url + q if q else obs.access_url


def fetch(url: str, settings: Settings) -> Download:
    cache = settings.data_dir / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(url.encode()).hexdigest()[:32]
    path = cache / f"{key}.fits"
    meta = cache / f"{key}.json"
    if path.exists() and meta.exists():
        m = json.loads(meta.read_text(encoding="utf-8"))
        return Download(**{**m, "cached": True})
    last_exc = None
    for attempt in range(4):
        try:
            with httpx.Client(timeout=settings.http_timeout_s, follow_redirects=True) as cl:
                r = cl.get(url)
            r.raise_for_status()
            body = r.content
            if not body.startswith(b"SIMPLE"):
                raise ValueError(f"response is not FITS (first bytes: {body[:40]!r})")
            tmp = path.with_suffix(".part")
            tmp.write_bytes(body)
            tmp.replace(path)
            d = Download(url=url, path=str(path), sha256=hashlib.sha256(body).hexdigest(), bytes=len(body),
                         cached=False, fetched_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                         http_status=r.status_code)
            meta.write_text(json.dumps(d.to_dict()))
            return d
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(2.0 * 2 ** attempt)   # 2, 4, 8, 16 s: IRSA cutouts occasionally time out under load
    raise RuntimeError(f"download failed after 4 attempts: {url}: {type(last_exc).__name__}: {last_exc}")


def fetch_many(urls: list[str], settings: Settings) -> list[Download | Exception]:
    def one(u):
        try:
            return fetch(u, settings)
        except Exception as exc:  # noqa: BLE001
            return exc
    with ThreadPoolExecutor(max_workers=settings.max_parallel_downloads) as ex:
        return list(ex.map(one, urls))

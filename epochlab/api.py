"""HTTP API + static web UI.

GET  /api/health
POST /api/jobs                     body: AnalysisRequest fields -> {job_id}
GET  /api/jobs                     list of finished/running jobs
GET  /api/jobs/{id}/status.json    {state, progress, message}
GET  /api/jobs/{id}/dossier.json   full reproducible dossier
GET  /api/jobs/{id}/frames/{file}  display PNGs
GET  /api/jobs/{id}/bundle.zip     dossier + PNGs + list of archive URLs (FITS are re-downloadable)

Paths mirror the on-disk layout so a static export (GitHub Pages) serves the same URLs.
"""
from __future__ import annotations

import io
import json
import os
import re
import threading
import time
import traceback
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .config import settings
from .pipeline import AnalysisRequest, analyze

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
JOB_RE = re.compile(r"^[a-f0-9]{12}$")
_pool = ThreadPoolExecutor(max_workers=2)
_lock = threading.Lock()

app = FastAPI(title="Narvalis — SPHEREx time-domain verifier", version=__version__)


class JobIn(BaseModel):
    target_name: str | None = Field(None, max_length=80)
    ra_deg: float | None = Field(None, ge=0, lt=360)
    dec_deg: float | None = Field(None, ge=-90, le=90)
    ref_pmra: float | None = None
    ref_pmdec: float | None = None
    ref_parallax: float | None = None
    ref_epoch: float | None = None
    use_gaia: bool = True
    n_controls: int = Field(2, ge=0, le=5)
    cutout_size_arcsec: float | None = Field(None, ge=60, le=600)
    max_frames: int | None = Field(None, ge=3, le=300)


def _jobs_dir() -> Path:
    p = settings.data_dir / "jobs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _status_path(job_id: str) -> Path:
    return _jobs_dir() / job_id / "status.json"


def _write_status(job_id: str, **kw):
    p = _status_path(job_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        cur.update(kw, updated_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(cur))
        tmp.replace(p)


def _run(job_id: str, req: AnalysisRequest):
    try:
        analyze(req, settings, job_id=job_id,
                progress=lambda f, m: _write_status(job_id, state="running", progress=round(f, 3), message=m))
        _write_status(job_id, state="done", progress=1.0, message="Done")
    except Exception as exc:  # noqa: BLE001
        _write_status(job_id, state="failed", message=f"{type(exc).__name__}: {exc}",
                      traceback=traceback.format_exc()[-4000:])


def mark_interrupted_jobs() -> int:
    """Jobs run in this process's threads; after a restart, any job still 'queued'/'running' can never finish.
    Mark them failed so the UI does not wait on them forever."""
    n = 0
    for st in _jobs_dir().glob("*/status.json"):
        try:
            cur = json.loads(st.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if cur.get("state") in ("queued", "running"):
            _write_status(st.parent.name, state="failed", message="Interrupted: the server was restarted. Run the analysis again (downloads are cached).")
            n += 1
    return n


@app.on_event("startup")
def _on_startup():
    mark_interrupted_jobs()


def _check(job_id: str) -> Path:
    if not JOB_RE.match(job_id):
        raise HTTPException(400, "bad job id")
    p = _jobs_dir() / job_id
    if not p.exists():
        raise HTTPException(404, "job not found")
    return p


# ---------------------------------------------------------------- sky tiles proxy
# The browser may not reach CDS directly (ad-blockers, DNS filters, firewalls). The server already has
# outbound access for IRSA, so it relays the HiPS tiles of a small allow-list of surveys and caches them.
HIPS_BASE = "https://alasky.cds.unistra.fr"
# CDS publishes the same HiPS on several servers; if one refuses (404/403/5xx) or is unreachable, the next is tried.
HIPS_MIRRORS = {
    # official mirrors listed by the CDS MocServer (hips_service_url_*); NASA/IRSA first — it is the archive this
    # tool already depends on, and it kept answering in Nov 2026 while alasky showed "page unavailable"
    "2MASS/Color": ["https://irsa.ipac.caltech.edu/data/hips/CDS/2MASS/Color",
                    "https://alasky.cds.unistra.fr/2MASS/Color", "https://alaskybis.cds.unistra.fr/2MASS/Color"],
    "DSS/DSSColor": ["https://irsa.ipac.caltech.edu/data/hips/CDS/DSS2/color", "https://skies.esac.esa.int/DSSColor",
                     "https://alasky.cds.unistra.fr/DSS/DSSColor", "https://alaskybis.cds.unistra.fr/DSS/DSSColor"],
}
HIPS_ALLOWED = set(HIPS_MIRRORS)
_hips_good: dict[str, str] = {}   # survey -> mirror that last answered


def _hips_fetch(name: str, path: str):
    """Fetch one HiPS file from the first mirror that answers 200. Returns (body, None) or (None, (status, detail))."""
    import httpx
    bases = HIPS_MIRRORS[name]
    if name in _hips_good:
        bases = [_hips_good[name]] + [b for b in bases if b != _hips_good[name]]
    tried = []
    for base in bases:
        host = base.split("/")[2]
        try:
            r = httpx.get(f"{base}/{path}", timeout=20, follow_redirects=True, headers=UA)
        except Exception as exc:  # noqa: BLE001
            tried.append(f"{host}: unreachable ({type(exc).__name__})")
            continue
        if r.status_code == 200:
            _hips_good[name] = base
            return r.content, None
        tried.append(f"{host}: HTTP {r.status_code}")
        if r.status_code == 404 and path != "properties":
            break   # a missing tile is normal (outside the survey); the survey itself is fine
    statuses = [t for t in tried if "HTTP" in t]
    code = 404 if statuses and all("HTTP 404" in t for t in statuses) and len(statuses) == len(tried) else 502
    return None, (code, "CDS answered " + "; ".join(tried))
HIPS_PATH = re.compile(r"^(properties|Allsky\.(jpg|png)|Norder\d{1,2}/Dir\d{1,6}/Npix\d{1,10}\.(jpg|png))$")


@app.get("/api/sky/{group}/{survey}/{path:path}")
def sky_tile(group: str, survey: str, path: str):
    name = f"{group}/{survey}"
    if name not in HIPS_ALLOWED or not HIPS_PATH.match(path):
        raise HTTPException(404)
    cache = settings.data_dir / "hipscache" / group / survey / path
    if not cache.exists():
        body, err = _hips_fetch(name, path)
        if err:
            raise HTTPException(err[0], err[1])
        if path == "properties":
            # drop mirror URLs so the viewer keeps fetching tiles through this relay
            body = b"\n".join(l for l in body.splitlines() if not l.strip().startswith(b"hips_service_url")) + b"\n"
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(cache.suffix + ".part")
        tmp.write_bytes(body)
        tmp.replace(cache)
    media = "text/plain" if path == "properties" else ("image/png" if path.endswith(".png") else "image/jpeg")
    return FileResponse(cache, media_type=media, headers={"Cache-Control": "public, max-age=604800"})


UA = {"User-Agent": f"EpochLab/{__version__} (NASA Space Apps 2026 student project)"}


# ---------------------------------------------------------------- live service status
# The header shows whether the archives are reachable *right now* from this server, not merely whether the server is up.
# One tiny request per service, cached for 60 s; the browser asks every few minutes or when the user clicks the chip.
_status_cache: dict = {"t": 0.0, "data": None}
_status_lock = threading.Lock()


def _probe(url: str) -> dict:
    import httpx
    t0 = time.time()
    try:
        r = httpx.get(url, timeout=12, follow_redirects=True, headers=UA)
        ms = round((time.time() - t0) * 1000)
        state = "online" if r.status_code == 200 else ("degraded" if r.status_code >= 500 else "error")
        return {"state": state, "http": r.status_code, "ms": ms}
    except Exception as exc:  # noqa: BLE001
        return {"state": "offline", "http": None, "ms": round((time.time() - t0) * 1000),
                "detail": f"{type(exc).__name__}: {str(exc)[:160]}"}


@app.get("/api/status")
def service_status(refresh: bool = False):
    with _status_lock:
        if not refresh and _status_cache["data"] and time.time() - _status_cache["t"] < 60:
            return _status_cache["data"]
        targets = {
            # the same SIA2 query endpoint the pipeline uses, asked for at most one row
            "irsa": f"{settings.irsa_sia_url}?POS=CIRCLE+269.45+4.69+0.0003&MAXREC=1",
        }
        with ThreadPoolExecutor(max_workers=2) as ex:
            irsa = ex.submit(_probe, targets["irsa"])
            cds = ex.submit(lambda: [(_probe(f"{b}/properties"), b.split("/")[2]) for b in HIPS_MIRRORS["2MASS/Color"]])
            res = {"irsa": irsa.result()}
            mirrors = cds.result()
            ok = [m for m in mirrors if m[0]["state"] == "online"]
            best = ok[0] if ok else mirrors[0]
            res["cds"] = {**best[0], "host": best[1], "mirrors": {h: (p["http"] or p["state"]) for p, h in mirrors}}
        data = {**res, "checked_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        _status_cache.update(t=time.time(), data=data)
        return data


# ---------------------------------------------------------------- connection test (every external service used)
# One small real request per service, made FROM THIS SERVER (that is where the pipeline runs), in parallel.
_conn_cache: dict = {"t": 0.0, "data": None}


def _latest_frame_url() -> str | None:
    """URL of one SPHEREx file already used by a finished real analysis (to test the download path itself)."""
    try:
        for d in sorted(_jobs_dir().iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            f = d / "dossier.json"
            if not f.exists():
                continue
            dz = json.loads(f.read_text(encoding="utf-8"))
            if not str(dz.get("data_kind", "")).startswith("REAL"):
                continue
            for fr in dz.get("frames", []):
                u = (fr.get("download") or {}).get("url")
                if u and u.startswith("http"):
                    return u
    except Exception:  # noqa: BLE001
        pass
    return None


def _probe_full(url: str, head: bool = False) -> dict:
    import httpx
    t0 = time.time()
    try:
        with httpx.Client(timeout=15, follow_redirects=True, headers=UA) as c:
            if head:
                r = c.head(url)
                if r.status_code in (405, 501):
                    with c.stream("GET", url) as rs:
                        r = rs
            else:
                r = c.get(url)
        ms = round((time.time() - t0) * 1000)
        code = r.status_code
        state = ("online" if ms < 4000 else "slow") if code < 400 else ("server_error" if code >= 500 else "error")
        return {"state": state, "http": code, "ms": ms}
    except Exception as exc:  # noqa: BLE001
        return {"state": "unreachable", "http": None, "ms": round((time.time() - t0) * 1000),
                "detail": f"{type(exc).__name__}: {' '.join(str(exc).split())[:160]}"}


@app.get("/api/connections")
def connections(refresh: bool = False):
    if not refresh and _conn_cache["data"] and time.time() - _conn_cache["t"] < 30:
        return _conn_cache["data"]
    from urllib.parse import quote
    sia = settings.irsa_sia_url
    tap = sia.rsplit("/", 1)[0] + "/TAP/sync"
    services = [
        ("irsa_sia", "IRSA image search", "Finds every SPHEREx exposure that covers the target",
         f"{sia}?POS=CIRCLE+269.45+4.69+0.0003&MAXREC=1", False),
        ("irsa_tap", "IRSA collection list", "Lists the SPHEREx data releases (DR1, QR…)",
         f"{tap}?REQUEST=doQuery&LANG=ADQL&FORMAT=csv&QUERY=" + quote("SELECT TOP 1 table_name FROM TAP_SCHEMA.tables"), False),
        ("irsa_files", "IRSA image download", "Delivers the SPHEREx cutouts themselves", _latest_frame_url(), True),
        ("gaia", "ESA Gaia DR3", "Reference positions and proper motions",
         "https://gea.esac.esa.int/tap-server/tap/sync?REQUEST=doQuery&LANG=ADQL&FORMAT=csv&QUERY="
         + quote("SELECT TOP 1 source_id FROM gaiadr3.gaia_source"), False),
        ("sesame", "CDS Sesame", "Turns a star name into coordinates",
         "https://cds.unistra.fr/cgi-bin/nph-sesame/-oxp/SNV?" + quote("Barnard's Star"), False),
        ("simbad", "CDS SIMBAD", "Star names and catalogue data",
         "https://simbad.cds.unistra.fr/simbad/sim-tap/sync?REQUEST=doQuery&LANG=ADQL&FORMAT=csv&QUERY="
         + quote("SELECT TOP 1 main_id FROM basic"), False),
        ("sky", "Sky context images (2MASS)", "Background map only, not used in the analysis",
         HIPS_MIRRORS["2MASS/Color"][0] + "/properties", False),
    ]
    out = []
    with ThreadPoolExecutor(max_workers=len(services)) as ex:
        futs = {k: ex.submit(_probe_full, url, head) for k, _, _, url, head in services if url}
        for k, name, role, url, _ in services:
            host = url.split("/")[2] if url else None
            res = futs[k].result() if k in futs else {"state": "untested", "http": None, "ms": None,
                                                        "detail": "no finished real analysis yet to take a file from"}
            out.append({"id": k, "name": name, "role": role, "host": host, **res})
    data = {"services": out, "checked_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    _conn_cache.update(t=time.time(), data=data)
    return data


# ---------------------------------------------------------------- real-data self-test (local machine only)
# Runs scripts/selftest_real.py --run in a child process so it can be started from a browser on the same machine.
# Refused for any client that is not this computer (the app may later sit behind a public reverse proxy).
_selftest: dict = {"proc": None, "started": None}
SELFTEST_LOG = Path(__file__).resolve().parent.parent / "validation" / "selftest.log"


def _from_public_internet(request: Request) -> bool:
    """True when a reverse proxy in front of us (e.g. the NanoPi nginx) reports a public client address.
    Behind a proxy the direct peer is always a private address, so the peer alone cannot be trusted: the last
    X-Forwarded-For entry is the one written by the nearest proxy (earlier entries can be forged by the client)."""
    import ipaddress
    xff = (getattr(request, "headers", None) or {}).get("x-forwarded-for", "")
    if not xff.strip():
        return False
    last = xff.split(",")[-1].strip()
    try:
        ip = ipaddress.ip_address(last)
    except ValueError:
        return True  # unparseable: treat as untrusted
    return not (ip.is_loopback or ip.is_private or _trusted(ip))


def _trusted(ip) -> bool:
    """Extra networks allowed to delete analyses, e.g. the team's home public IP when using the domain.
    EPOCHLAB_TRUSTED_NETS="203.0.113.7/32,2001:db8::/48" (empty by default)."""
    import ipaddress
    import os
    for net in filter(None, (x.strip() for x in os.environ.get("EPOCHLAB_TRUSTED_NETS", "").split(","))):
        try:
            if ip in ipaddress.ip_network(net, strict=False):
                return True
        except ValueError:
            continue
    return False


def _local_or_private(request: Request):
    """This computer or a device on the same private network (home Wi-Fi). Used for reversible actions only."""
    import ipaddress
    if _from_public_internet(request):
        raise HTTPException(403, "this action is only allowed from the computer running Narvalis or a device on its local network")
    host = request.client.host if request.client else ""
    if host in ("localhost", "testclient"):
        return
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_loopback or ip.is_private or _trusted(ip):
            return
    except ValueError:
        pass
    raise HTTPException(403, "this action is only allowed from the computer running Narvalis or a device on its local network")


def _local_only(request: Request):
    if _from_public_internet(request):
        raise HTTPException(403, "this action is only allowed on the computer running the Narvalis server")
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(403, "this action is only allowed on the computer running the Narvalis server")


@app.post("/api/selftest")
def selftest_start(request: Request, mode: str = "run"):
    import subprocess
    import sys
    _local_only(request)
    p = _selftest["proc"]
    if p is not None and p.poll() is None:
        raise HTTPException(409, "self-test already running")
    SELFTEST_LOG.parent.mkdir(exist_ok=True)
    log = open(SELFTEST_LOG, "w", encoding="utf-8")
    script = Path(__file__).resolve().parent.parent / "scripts" / "selftest_real.py"
    env = {**__import__("os").environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    if mode not in ("run", "injection"):
        raise HTTPException(400, "mode must be 'run' or 'injection'")
    _selftest.update(proc=subprocess.Popen([sys.executable, str(script), f"--{mode}"], stdout=log, stderr=subprocess.STDOUT,
                                           cwd=str(script.parent.parent), env=env),
                     started=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    return {"started_utc": _selftest["started"], "log": str(SELFTEST_LOG)}


@app.get("/api/selftest")
def selftest_status(request: Request, tail: int = 40):
    _local_only(request)
    p = _selftest["proc"]
    state = "never started" if p is None else ("running" if p.poll() is None else f"finished (exit {p.returncode})")
    lines = SELFTEST_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, min(tail, 400)):] if SELFTEST_LOG.exists() else []
    return {"state": state, "started_utc": _selftest["started"], "log_tail": lines}


@app.get("/api/health")
def health():
    return {"ok": True, "version": __version__, "collections": list(settings.collections), "mode": "live"}


def _sha(x: str) -> str:
    import hashlib
    return hashlib.sha256(x.encode()).hexdigest()


@app.post("/api/jobs")
def create_job(body: JobIn):
    if not body.target_name and (body.ra_deg is None or body.dec_deg is None):
        raise HTTPException(422, "provide target_name or ra_deg + dec_deg")
    import secrets
    job_id = uuid.uuid4().hex[:12]
    req = AnalysisRequest(**body.model_dump())
    # The browser that started an analysis gets a secret token: with it, that visitor (and only that visitor) can
    # remove the analysis again from a public server. Only its hash is stored.
    token = secrets.token_urlsafe(18)
    _write_status(job_id, state="queued", progress=0.0, message="Queued", request=body.model_dump(),
                  owner_sha256=_sha(token))
    _pool.submit(_run, job_id, req)
    return {"job_id": job_id, "owner_token": token}


def _may_remove(request: Request, st: dict) -> None:
    """Who may move an analysis to / from the trash: this computer or its local network (anything), anyone for a
    FAILED analysis (it holds no result), and the visitor who started it (owner token)."""
    try:
        _local_or_private(request)
        return
    except HTTPException:
        pass
    if st.get("state") == "failed":
        return
    tok = request.headers.get("x-narvalis-owner", "")
    if tok and st.get("owner_sha256") and _sha(tok) == st["owner_sha256"]:
        return
    raise HTTPException(403, "only analyses that failed or that you started from this browser can be removed here; "
                             "everything else only from the computer running Narvalis")


@app.get("/api/jobs")
def list_jobs():
    out = []
    for d in sorted(_jobs_dir().iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        s = d / "status.json"
        if s.exists():
            st = json.loads(s.read_text(encoding="utf-8"))
            out.append({"job_id": d.name, "state": st.get("state"), "request": st.get("request"),
                        "updated_utc": st.get("updated_utc")})
    return {"jobs": out[:100]}


def _trash_dir() -> Path:
    p = settings.data_dir / "trash"
    p.mkdir(parents=True, exist_ok=True)
    return p


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str, request: Request):
    """Move one analysis to the trash (it can be restored). Only from the machine running the server, never while
    it is running. Downloaded SPHEREx files in the shared cache are not touched."""
    p = _check(job_id)
    st = {}
    try:
        st = json.loads((p / "status.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    _may_remove(request, st)
    if st.get("state") in ("queued", "running"):
        raise HTTPException(409, "this analysis is still running")
    import shutil
    if p.resolve().parent != _jobs_dir().resolve():
        raise HTTPException(400, "bad job path")
    dest = _trash_dir() / job_id
    if dest.exists():
        shutil.rmtree(dest)
    shutil.move(str(p), str(dest))
    (dest / ".deleted_utc").write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    return {"deleted": job_id, "restorable": True}


@app.get("/api/trash")
def list_trash():
    out = []
    for d in sorted(_trash_dir().iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        s = d / "status.json"
        if JOB_RE.match(d.name) and s.exists():
            st = json.loads(s.read_text(encoding="utf-8"))
            when = (d / ".deleted_utc").read_text().strip() if (d / ".deleted_utc").exists() else None
            out.append({"job_id": d.name, "state": st.get("state"), "request": st.get("request"), "deleted_utc": when})
    return {"jobs": out[:100]}


@app.post("/api/trash/{job_id}/restore")
def restore_job(job_id: str, request: Request):
    if not JOB_RE.match(job_id):
        raise HTTPException(400, "bad job id")
    src = _trash_dir() / job_id
    if not src.exists():
        raise HTTPException(404, "not in the trash")
    try:
        st = json.loads((src / "status.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        st = {}
    _may_remove(request, st)
    dest = _jobs_dir() / job_id
    if dest.exists():
        raise HTTPException(409, "an analysis with this id already exists")
    import shutil
    shutil.move(str(src), str(dest))
    (dest / ".deleted_utc").unlink(missing_ok=True)
    os.utime(dest)   # back to the top of the list
    return {"restored": job_id}


@app.get("/api/jobs/{job_id}/status.json")
def job_status(job_id: str):
    p = _check(job_id) / "status.json"
    if not p.exists():
        raise HTTPException(404)
    return JSONResponse(json.loads(p.read_text(encoding="utf-8")))


@app.get("/api/jobs/{job_id}/dossier.json")
def job_dossier(job_id: str):
    p = _check(job_id) / "dossier.json"
    if not p.exists():
        raise HTTPException(404, "dossier not ready")
    return FileResponse(p, media_type="application/json")


@app.get("/api/jobs/{job_id}/frames/{name}")
def job_frame(job_id: str, name: str):
    if not re.match(r"^\d{3}(_diff)?\.png$", name):
        raise HTTPException(400)
    p = _check(job_id) / "frames" / name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/jobs/{job_id}/bundle.zip")
def job_bundle(job_id: str):
    jd = _check(job_id)
    dp = jd / "dossier.json"
    if not dp.exists():
        raise HTTPException(404)
    d = json.loads(dp.read_text(encoding="utf-8"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(dp, "dossier.json")
        for png in (jd / "frames").glob("*.png"):
            z.write(png, f"frames/{png.name}")
        urls = [f"{f['download']['sha256']}  {f['download']['url']}" for f in d["frames"] if "download" in f]
        z.writestr("SHA256SUMS_archive_urls.txt", "\n".join(urls) + "\n")
        z.writestr("REPRODUCE.md", REPRODUCE_MD.format(job=job_id))
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="narvalis_{job_id}.zip"'})


REPRODUCE_MD = """# Reproducing Narvalis job {job}

1. `git clone` the Narvalis repository (Python package `epochlab`) and `pip install -r requirements.txt`.
2. Place `dossier.json` anywhere and run:
   `python -m epochlab.cli reproduce dossier.json`
3. The command re-downloads exactly the archive files listed in `SHA256SUMS_archive_urls.txt`,
   checks their SHA-256, re-runs every measurement with the recorded settings and reports any difference.

Every number in the dossier is produced by code in the repository; nothing is entered by hand.
"""

if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

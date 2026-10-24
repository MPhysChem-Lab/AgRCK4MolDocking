"""Module B - client for the NVIDIA-hosted DiffDock NIM.

Contract checked on 2026-10-21 against build.nvidia.com/mit/diffdock (v2.3):
POST JSON {protein, ligand, ligand_file_type, num_poses, time_divisions, steps,
save_trajectory}; Bearer auth. Response: ligand_positions (SDF strings) and
position_confidence (floats), list-of-lists when several ligands are sent.
One ligand per request here, so results can be cached and resumed per ligand.

Every raw response is stored under the cache dir keyed by the SHA-256 of the
request payload; a repeated request is served from disk.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import requests

RETRY_STATUS = {408, 429, 500, 502, 503, 504}


class DiffDockError(RuntimeError):
    pass


@dataclass
class DockResult:
    poses: list[str]            # SDF blocks, in the order returned by DiffDock
    confidences: list[float]    # DiffDock confidence (NOT affinity), same order
    cache_file: str
    from_cache: bool
    request_hash: str


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def parse_response(raw: dict) -> tuple[list[str], list[float]]:
    """Extract poses/confidences for a single-ligand request.

    Accepts the flat form and the batch (list-of-lists) form with one entry.
    """
    status = raw.get("status")
    if isinstance(status, list):
        status = status[0] if status else None
    if status is not None and str(status).lower() != "success":
        raise DiffDockError(f"DiffDock reported status={status!r}: {raw.get('details', '')}")
    poses = raw.get("ligand_positions")
    conf = raw.get("position_confidence")
    if poses is None or conf is None:
        raise DiffDockError(f"Unexpected response keys: {sorted(raw)}")
    if poses and isinstance(poses[0], list):
        poses, conf = poses[0], conf[0]
    if len(poses) != len(conf):
        raise DiffDockError(f"{len(poses)} poses but {len(conf)} confidences")
    return list(poses), [float(c) if c is not None else float("nan") for c in conf]


class DiffDockClient:
    def __init__(self, api_key: str | None, cfg: dict, cache_dir: str | Path, session: requests.Session | None = None):
        self.api_key = api_key
        self.cfg = cfg
        self.url = cfg["url"]
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.http = session or requests.Session()

    def build_payload(self, protein_pdb: str, ligand_sdf: str, num_poses: int) -> dict:
        return {
            "protein": protein_pdb,
            "ligand": ligand_sdf,
            "ligand_file_type": "sdf",
            "num_poses": int(num_poses),
            "time_divisions": int(self.cfg.get("time_divisions", 20)),
            "steps": int(self.cfg.get("steps", 18)),
            "save_trajectory": False,
        }

    def dock(self, protein_pdb: str, ligand_sdf: str, num_poses: int) -> DockResult:
        payload = self.build_payload(protein_pdb, ligand_sdf, num_poses)
        key = payload_hash(payload)
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            raw = json.loads(cache_file.read_text())
            poses, conf = parse_response(raw)
            return DockResult(poses, conf, str(cache_file), True, key)
        if not self.api_key:
            raise DiffDockError("NVIDIA_API_KEY not set (copy .env.example to .env) and no cached response.")
        raw = self._post(payload)
        poses, conf = parse_response(raw)   # validate before caching
        tmp = cache_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(raw))
        tmp.replace(cache_file)
        return DockResult(poses, conf, str(cache_file), False, key)

    # ------------------------------------------------------------------ http
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
                "Accept": "application/json"}

    def _post(self, payload: dict) -> dict:
        retries = int(self.cfg.get("max_retries", 3))
        backoff = float(self.cfg.get("backoff_s", 5))
        timeout = float(self.cfg.get("timeout_s", 300))
        last = ""
        for attempt in range(retries + 1):
            try:
                r = self.http.post(self.url, headers=self._headers(), json=payload, timeout=timeout)
            except (requests.ConnectionError, requests.Timeout) as e:
                last = f"{type(e).__name__}: {e}"
            else:
                if r.status_code == 200:
                    return r.json()
                if r.status_code == 202:
                    return self._poll(r)
                if r.status_code in (401, 403):
                    raise DiffDockError(f"HTTP {r.status_code}: authentication rejected - check NVIDIA_API_KEY.")
                if r.status_code not in RETRY_STATUS:
                    raise DiffDockError(f"HTTP {r.status_code}: {r.text[:1000]}")
                last = f"HTTP {r.status_code}: {r.text[:300]}"
                ra = r.headers.get("Retry-After")
                if ra and ra.isdigit():
                    time.sleep(min(float(ra), 120))
                    continue
            if attempt < retries:
                time.sleep(backoff * 2 ** attempt)
        raise DiffDockError(f"DiffDock request failed after {retries + 1} attempts: {last}")

    def _poll(self, first: requests.Response) -> dict:
        """NVCF-style async: 202 + NVCF-REQID header, poll the status URL until 200."""
        req_id = first.headers.get("NVCF-REQID")
        if not req_id:
            raise DiffDockError("HTTP 202 without NVCF-REQID header; cannot poll.")
        url = self.cfg.get("poll_url", "https://health.api.nvidia.com/v1/status/{req_id}").format(req_id=req_id)
        deadline = time.monotonic() + float(self.cfg.get("max_wait_s", 900))
        interval = float(self.cfg.get("poll_interval_s", 5))
        while time.monotonic() < deadline:
            time.sleep(interval)
            r = self.http.get(url, headers=self._headers(), timeout=float(self.cfg.get("timeout_s", 300)))
            if r.status_code == 200:
                return r.json()
            if r.status_code != 202:
                raise DiffDockError(f"Polling {req_id}: HTTP {r.status_code}: {r.text[:500]}")
        raise DiffDockError(f"Polling {req_id}: no result within max_wait_s")

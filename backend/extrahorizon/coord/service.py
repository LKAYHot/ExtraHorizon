"""The analysis pipeline: read → verify → compare → cross-check → report (+ live re-check).

Raw layers are cached in memory (``EH_COORD_CACHE_TTL_S``) and on disk. If the county's
services cannot be reached, the last copy on disk is used and the report says when it was
read — it never pretends to be live.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import shapely
from shapely.geometry import mapping

from .arcgis import ArcGISClient, DataClient, FixtureClient, SourceError
from .catalog import BOUNDARY, BY_KEY, CONFLICTS, PUBLISHER, REGION, SOURCES, Source
from .crosscheck import county_pairs, cross_check
from .model import Project, canonical_agency, clean, epoch_ms_to_date, from_row
from .overlap import LocalProjection, Params, find_overlaps
from .report import all_findings, excluded_totals, fact_sheet, highlights, plan_pairs, summarize
from .verify import EXCLUDE_REASONS, SourceAudit, check_geometry, county_region, dataset_checks, record_verdict

log = logging.getLogger("extrahorizon.coord")
Progress = Callable[[dict[str, Any]], None]
CONFLICT_FIELDS = "OBJECTID,FACTYPE1,AGCYNAME1,CONFLTID1,FACTYPE2,AGCYNAME2,CONFLTID2,STARTDATE,ENDDATE,MODIDATE"
MAX_FINDINGS = 300  # listed in the panel: the strongest findings …
PER_PAIR_FINDINGS = 25  # … plus the best of every pair of plans and every highlighted one
RETRY_FAILED_S = 60.0  # a read with a failed layer is tried again after this long


@dataclass
class RawLayer:
    key: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    geoms: dict[int, dict[str, Any]] = field(default_factory=dict)
    item: dict[str, Any] = field(default_factory=dict)
    layer: dict[str, Any] = field(default_factory=dict)
    reported: int = 0
    fetched_at: str = ""
    error: str | None = None
    from_disk: bool = False

    def dump(self) -> dict[str, Any]:
        return {"key": self.key, "rows": self.rows, "geoms": {str(k): v for k, v in self.geoms.items()},
                "item": self.item, "layer": self.layer, "reported": self.reported, "fetched_at": self.fetched_at}

    @classmethod
    def load(cls, d: dict[str, Any]) -> RawLayer:
        return cls(d["key"], d["rows"], {int(k): v for k, v in d["geoms"].items()}, d["item"], d["layer"],
                   d["reported"], d["fetched_at"], None, True)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class CoordService:
    def __init__(self, settings: Any, client: DataClient | None = None) -> None:
        self.s = settings
        offline_dir = getattr(settings, "coord_offline_dir", None)
        self.client: DataClient = client or (FixtureClient(Path(offline_dir)) if offline_dir
                                             else ArcGISClient(settings.coord_http_timeout_s))
        self.cache_dir = Path(settings.cache_dir) / "coord"
        self._raw: dict[str, RawLayer] = {}
        self._loaded_at: dt.datetime | None = None
        self._degraded = False  # the last read had a failed layer
        self._lock = asyncio.Lock()

    @property
    def offline(self) -> bool:
        return bool(getattr(self.client, "offline", False))

    def today(self) -> dt.date:
        """The analysis date: today — or, offline, the date the fixtures were written for."""
        return getattr(self.client, "as_of", None) or dt.date.today()

    def params(self, given: dict[str, Any] | None = None) -> Params:
        """The analysis parameters: a session's own values over the server's defaults, as of today."""
        g = {k: v for k, v in (given or {}).items() if v is not None}
        return Params(distance_m=g.get("distance_m", self.s.coord_distance_m),
                      window_days=g.get("window_days", self.s.coord_window_days),
                      area_m=max(1.0, float(g.get("area_m", self.s.coord_area_m))), today=self.today())

    def status(self) -> dict[str, Any]:
        return {"enabled": True, "offline": self.offline, "sources": len(SOURCES),
                "loaded_at": self._loaded_at.isoformat() if self._loaded_at else None}

    async def aclose(self) -> None:
        await self.client.aclose()

    # ------------------------------------------------------------------ reading
    async def _read(self, src: Source, today: dt.date, progress: Progress) -> RawLayer:
        progress({"step": "fetch", "source": src.key, "title": src.title, "state": "start"})
        conflicts = src.key == CONFLICTS.key
        boundary = src.key == BOUNDARY.key
        try:
            item, layer, reported = await asyncio.gather(self.client.item_info(src), self.client.layer_info(src),
                                                         self.client.count(src))
            geoms: dict[int, dict[str, Any]] = {}
            if boundary:
                geom = await self.client.boundary(src)
                rows = [{"OBJECTID": 1}] if geom else []
                geoms = {1: geom} if geom else {}
            else:
                rows = await (self.client.attributes(src, CONFLICT_FIELDS) if conflicts else self.client.attributes(src))
            if not conflicts and not boundary:
                cand = []
                for r in rows:
                    if r.get("OBJECTID") is None:
                        continue
                    reason, _ = record_verdict(r, today, epoch_ms_to_date(r.get("STARTDATE")),
                                               epoch_ms_to_date(r.get("ENDDATE")), epoch_ms_to_date(r.get("UPDATDATE")))
                    if reason is None:
                        cand.append(int(r["OBJECTID"]))
                geoms = await self.client.geometries(src, cand) if cand else {}
            raw = RawLayer(src.key, rows, geoms, item, layer, reported, _now().isoformat())
            if not self.offline:
                self._save(raw)
            progress({"step": "fetch", "source": src.key, "title": src.title, "state": "done", "records": len(rows)})
            return raw
        except SourceError as e:
            cached = self._load(src.key)
            if cached is not None:
                cached.error = f"live read failed ({e.message}); using the copy read at {cached.fetched_at[:16]} UTC"
                progress({"step": "fetch", "source": src.key, "title": src.title, "state": "cached",
                          "records": len(cached.rows), "message": e.message})
                return cached
            progress({"step": "fetch", "source": src.key, "title": src.title, "state": "error", "message": e.message})
            return RawLayer(src.key, error=e.message, fetched_at=_now().isoformat())

    def _save(self, raw: RawLayer) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_dir / f"{raw.key}.json.tmp"
            tmp.write_text(json.dumps(raw.dump()), encoding="utf-8")
            tmp.replace(self.cache_dir / f"{raw.key}.json")
        except OSError as e:
            log.warning("coord cache write failed for %s: %s", raw.key, e)

    def _load(self, key: str) -> RawLayer | None:
        p = self.cache_dir / f"{key}.json"
        try:
            return RawLayer.load(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else None
        except (OSError, ValueError, KeyError):
            return None

    async def _ensure(self, today: dt.date, progress: Progress, refresh: bool) -> None:
        async with self._lock:
            # a read where some layer failed is retried after a minute, not kept for the whole TTL
            ttl = min(RETRY_FAILED_S, self.s.coord_cache_ttl_s) if self._degraded else self.s.coord_cache_ttl_s
            fresh = self._loaded_at is not None and (_now() - self._loaded_at).total_seconds() < ttl
            if fresh and not refresh:
                progress({"step": "fetch", "state": "cached", "loaded_at": self._loaded_at.isoformat()})
                return
            sem = asyncio.Semaphore(4)

            async def one(src: Source) -> RawLayer:
                async with sem:
                    return await self._read(src, today, progress)

            layers = await asyncio.gather(*(one(src) for src in (*SOURCES, CONFLICTS, BOUNDARY)))
            self._raw = {r.key: r for r in layers}
            self._loaded_at = _now()
            self._degraded = any(r.error for r in layers)

    # ------------------------------------------------------------------ analysis
    async def analyze(self, params: Params | None = None, progress: Progress | None = None,
                      refresh: bool = False) -> dict[str, Any]:
        params = params or self.params()
        emit = progress or (lambda _m: None)
        await self._ensure(params.today, emit, refresh)
        raw = self._raw  # this read (a later refresh swaps in a new dict)
        read = [raw[s.key] for s in SOURCES if s.key in raw]
        if not any(r.rows for r in read) and any(r.error for r in read):
            first = next(r.error for r in read if r.error)
            raise SourceError("all", f"none of the county's layers could be read ({first})")
        loop = asyncio.get_running_loop()

        def emit_from_thread(m: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(emit, m)

        # the CPU part (up to seconds with wide rules) runs off the event loop: every session's voice and
        # camera keep flowing meanwhile
        report = await asyncio.to_thread(self._compute, raw, params, emit_from_thread)
        emit({"step": "done", "state": "done", "report_id": report["id"]})
        return report

    def _compute(self, raw: dict[str, RawLayer], params: Params, emit: Progress) -> dict[str, Any]:
        emit({"step": "verify", "state": "start"})
        bound = raw.get(BOUNDARY.key)
        region = county_region(bound.geoms.get(1) if bound and bound.geoms else None)
        audits, projects, geoms, verified, excluded = self._verify(params.today, raw, region)
        emit({"step": "verify", "state": "done", "projects": len(projects)})
        emit({"step": "compare", "state": "start"})
        findings = find_overlaps(projects, geoms, params)
        emit({"step": "compare", "state": "done", "findings": len(findings)})
        conflicts = raw.get(CONFLICTS.key) or RawLayer(CONFLICTS.key, error="not read")
        pairs = county_pairs(conflicts.rows)
        xc = cross_check(findings, pairs, verified, excluded, CONFLICTS.url)
        emit({"step": "crosscheck", "state": "done", "county_pairs": len(pairs)})
        report = self._assemble(params, audits, projects, geoms, findings, xc, conflicts)
        report["region"]["check"] = "the county's boundary" if region is not None else "a bounding box"
        report["boundary_source"] = self._source_info(BOUNDARY, bound, params.today, static=True)
        if region is None:
            note = "the county's boundary could not be read; 'inside the county' was checked against a bounding box"
            report["stale_note"] = "; ".join(x for x in (report["stale_note"], note) if x)
        return report

    def _source_info(self, src: Source, raw: RawLayer | None, today: dt.date, static: bool = False) -> dict[str, Any]:
        raw = raw or RawLayer(src.key, error="not read")
        edit = (raw.layer.get("editingInfo") or {}).get("lastEditDate")
        return {"key": src.key, "title": src.title, "url": src.url, "item_url": src.item_url, "error": raw.error,
                "last_edit": epoch_ms_to_date(edit).isoformat() if edit else None,
                "checks": [c.public() for c in dataset_checks(src, raw.item, raw.layer, raw.reported, len(raw.rows),
                                                              today, self.offline, static=static)] if raw.rows else []}

    def _verify(self, today: dt.date, raw: dict[str, RawLayer] | None = None, region: Any | None = None):
        audits: list[SourceAudit] = []
        projects: list[Project] = []
        geoms: list[Any] = []
        verified: set[tuple[str, str]] = set()
        excluded: dict[tuple[str, str], str] = {}
        layers = self._raw if raw is None else raw
        for src in SOURCES:
            raw = layers.get(src.key)
            audit = SourceAudit(src.key, src.title, src.kind, src.url, src.item_url, src.utility)
            audits.append(audit)
            if raw is None:
                audit.error = "not read"
                continue
            audit.error = raw.error
            audit.fetched_at = raw.fetched_at
            if raw.error and not raw.rows:
                continue
            audit.reported, audit.received = raw.reported, len(raw.rows)
            audit.checks = dataset_checks(src, raw.item, raw.layer, raw.reported, len(raw.rows), today, self.offline)
            edit = (raw.layer.get("editingInfo") or {}).get("lastEditDate")
            audit.last_edit = epoch_ms_to_date(edit).isoformat() if edit else None
            groups: dict[tuple[str, str], list[tuple[Project, Any]]] = {}
            for row in raw.rows:
                if row.get("OBJECTID") is None:
                    audit.exclude("missing_id")
                    continue
                p = from_row(src.key, row, src.project_url(str(row.get("PROJECTID") or "").strip()))
                if canonical_agency(row.get("AGCYNAME") or "")[1]:
                    audit.note("agency_alias")
                    p.notes.append("agency_alias")
                reason, notes = record_verdict(row, today, p.start, p.end, p.updated)
                for n in notes:
                    audit.note(n)
                    p.notes.append(n)
                if reason:
                    audit.exclude(reason)
                    excluded.setdefault((src.key, p.project_id), EXCLUDE_REASONS[reason])
                    continue
                audit.candidates += 1
                g, greason, gnotes = check_geometry(raw.geoms.get(p.object_id), region)
                for n in gnotes:
                    audit.note(n)
                    p.notes.append(n)
                if greason:
                    audit.exclude(greason)
                    excluded.setdefault((src.key, p.project_id), EXCLUDE_REASONS[greason])
                    continue
                groups.setdefault((p.agency, p.project_id), []).append((p, g))
            for (_agency, pid), items in groups.items():
                p0, g0 = items[0]
                if len(items) > 1:
                    g0 = shapely.union_all([g for _p, g in items])
                    p0.parts = len(items)
                    p0.start = min(p.start for p, _g in items if p.start)
                    p0.end = max(p.end for p, _g in items if p.end)
                    audit.note("parts_merged")
                    p0.notes.append("parts_merged")
                projects.append(p0)
                geoms.append(g0)
                verified.add((src.key, pid))
            audit.verified = len(groups)
        for k in verified:
            excluded.pop(k, None)
        # a stable order (layer, plan, project ID) — not the order or object IDs the service happens to return —
        # so the same data always gives the same finding IDs
        rank = {s.key: i for i, s in enumerate(SOURCES)}
        order = sorted(range(len(projects)), key=lambda i: (rank[projects[i].source], projects[i].plan,
                                                            projects[i].project_id))
        return audits, [projects[i] for i in order], [geoms[i] for i in order], verified, excluded

    def _assemble(self, params: Params, audits: list[SourceAudit], projects: list[Project], geoms: list[Any],
                  findings: list, xc: dict[str, Any], conflicts: RawLayer) -> dict[str, Any]:
        proj = LocalProjection(params.lat0, params.lon0)
        features = []
        for p, g in zip(projects, geoms):
            simple = proj.inverse(proj.forward(g).simplify(3.0, preserve_topology=True))
            simple = shapely.set_precision(simple, 1e-6)
            features.append({"type": "Feature", "id": p.uid, "geometry": mapping(simple),
                             "properties": {"uid": p.uid, "plan": p.plan_short, "kind": p.kind}})
        plans: dict[str, dict[str, Any]] = {}
        for p in projects:
            e = plans.setdefault(p.plan, {"key": p.plan, "label": p.plan_short, "agency": p.agency,
                                          "facility": p.facility, "kind": p.kind,
                                          "utility": BY_KEY[p.source].utility, "count": 0})
            e["count"] += 1
        pub_audits = [a.public() for a in audits]
        # listed: the strongest findings, the best of every pair of plans (so no pair is empty in the panel)
        # and every highlighted one (so everything in her fact sheet can be shown)
        hl = highlights(findings)
        listed = {f.id for f in findings[:MAX_FINDINGS]} | set(hl)
        per_pair: dict[tuple[str, str], int] = {}
        for f in findings:
            key = (min(f.a.plan_short, f.b.plan_short), max(f.a.plan_short, f.b.plan_short))
            if per_pair.get(key, 0) < PER_PAIR_FINDINGS:
                per_pair[key] = per_pair.get(key, 0) + 1
                listed.add(f.id)
        pub = [f.public() for f in findings]
        excluded = excluded_totals(pub_audits)
        received = sum(a.received for a in audits)
        passed = received - sum(e["count"] for e in excluded)  # every record is excluded once or kept
        stale = [a for a in audits if a.error and a.received]
        now_local = dt.datetime.now().astimezone()
        offset = now_local.utcoffset() or dt.timedelta(0)
        sign = "+" if offset >= dt.timedelta(0) else "−"
        hours, rem = divmod(abs(int(offset.total_seconds())), 3600)
        conf_layer = conflicts.layer or {}
        conf_edit = (conf_layer.get("editingInfo") or {}).get("lastEditDate")
        return {
            "id": uuid.uuid4().hex[:12],
            "generated_at": _now().isoformat(),
            "generated_at_local": now_local.strftime("%Y-%m-%d %H:%M") + f" (UTC{sign}{hours:02d}:{rem // 60:02d})",
            "offline": self.offline,
            "stale_note": ("; ".join(f"{a.key}: {a.error}" for a in stale) or None),
            "region": {"name": REGION["name"], "center": REGION["center"], "bbox": REGION["bbox"]},
            "publisher": PUBLISHER,
            "params": params.public(),
            "sources": pub_audits,
            "conflicts_source": {"key": CONFLICTS.key, "title": CONFLICTS.title, "url": CONFLICTS.url,
                                 "item_url": CONFLICTS.item_url, "reported": conflicts.reported,
                                 "received": len(conflicts.rows), "error": conflicts.error,
                                 "last_edit": epoch_ms_to_date(conf_edit).isoformat() if conf_edit else None,
                                 "checks": [c.public() for c in dataset_checks(
                                     CONFLICTS, conflicts.item, conflicts.layer, conflicts.reported,
                                     len(conflicts.rows), params.today, self.offline)] if conflicts.rows else []},
            "plans": sorted(plans.values(), key=lambda e: (-e["count"], e["label"])),
            "summary": {
                "records_reported": sum(a.reported for a in audits),
                "records_received": received,
                "records_excluded": received - passed,
                "records_passed": passed,
                "records_merged": passed - len(projects),  # extra parts of a project published in several records
                "projects_verified": len(projects),
                "excluded": excluded,
                "findings": len(findings),
                "by_category": summarize(findings),
                "plans": len(plans),
            },
            "crosscheck": xc,
            "pairs": plan_pairs(findings),
            "highlights": hl,
            "findings_total": len(findings),
            "findings": [x for x in pub if x["id"] in listed],
            # every finding, for her tools and the fact sheet (server side only — see public_report)
            "_all_findings": pub,
            "projects_index": [p.public() for p in projects],
            "projects_geojson": {"type": "FeatureCollection", "features": features},
        }

    # ------------------------------------------------------------------ live re-check
    async def recheck(self, report: dict[str, Any], finding_id: str) -> dict[str, Any]:
        """Read both projects of a finding again from the county's service right now and compare."""
        f = next((x for x in all_findings(report) if x["id"] == finding_id), None)
        if f is None:
            raise KeyError(finding_id)
        index = {p["uid"]: p for p in report["projects_index"]}
        out: dict[str, Any] = {"finding": finding_id, "checked_at": _now().isoformat(), "records": []}
        live_geoms = []
        ok = True
        today = self.today()
        bound = self._raw.get(BOUNDARY.key)
        region = county_region(bound.geoms.get(1) if bound and bound.geoms else None)
        for uid in (f["a"], f["b"]):
            p = index[uid]
            src = BY_KEY[p["source"]]
            try:
                feats = await self.client.project_records(src, p["project_id"])
            except SourceError as e:
                out["records"].append({"uid": uid, "found": False, "error": e.message})
                ok = False
                continue
            # the same project of the same agency (the county republishes layers: object IDs change)
            feats = [x for x in feats if canonical_agency((x.get("properties") or {}).get("AGCYNAME") or "")[0]
                     == p["agency"]]
            if not feats:
                out["records"].append({"uid": uid, "found": False, "error": "record no longer published"})
                ok = False
                continue
            # verify the live record(s) again exactly like the analysis did, then merge the parts
            kept, reasons = [], []
            for x in feats:
                props = x.get("properties") or {}
                start, end = epoch_ms_to_date(props.get("STARTDATE")), epoch_ms_to_date(props.get("ENDDATE"))
                reason, _ = record_verdict(props, today, start, end, epoch_ms_to_date(props.get("UPDATDATE")))
                g = None
                if reason is None:
                    g, reason, _ = check_geometry(x.get("geometry"), region)
                if reason:
                    reasons.append(reason)
                else:
                    kept.append((props, start, end, g))
            first = feats[0].get("properties") or {}
            if not kept:
                why = EXCLUDE_REASONS.get(reasons[0], reasons[0])
                out["records"].append({"uid": uid, "found": True, "changed": [f"no longer passes the checks: {why}"],
                                       "live": {"project_id": p["project_id"], "status": clean(first.get("GENPRJSTAT"))},
                                       "record_url": p["record_url"]})
                ok = False
                continue
            live = {
                "project_id": p["project_id"],
                "status": clean(kept[0][0].get("GENPRJSTAT")),
                "start": min(k[1] for k in kept).isoformat(),
                "end": max(k[2] for k in kept).isoformat(),
                "parts": len(kept),
            }
            changed = [k for k in ("status", "start", "end") if live[k] != p[k]]
            ok = ok and not changed
            out["records"].append({"uid": uid, "found": True, "changed": changed, "live": live,
                                   "record_url": p["record_url"]})
            live_geoms.append(shapely.union_all([k[3] for k in kept]))
        if len(live_geoms) == 2:
            params = report["params"]
            proj = LocalProjection(REGION["center"][0], REGION["center"][1])
            d = float(proj.forward(live_geoms[0]).distance(proj.forward(live_geoms[1])))
            out["distance_m_live"] = round(d, 1)
            same = abs(d - f["distance_m"]) <= max(1.0, 0.01 * f["distance_m"])
            out["distance_matches"] = same
            ok = ok and same and d <= max(params["distance_m"], params["area_m"])
        out["ok"] = ok
        return out


def fact_sheet_for(report: dict[str, Any] | None) -> str | None:
    return fact_sheet(report) if report else None


def public_report(report: dict[str, Any] | None) -> dict[str, Any] | None:
    """The report as the browser gets it: without the server-side keys (``_all_findings``)."""
    if report is None:
        return None
    return {k: v for k, v in report.items() if not k.startswith("_")}

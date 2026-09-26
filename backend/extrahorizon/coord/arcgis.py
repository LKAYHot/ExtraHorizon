"""Reading the county's ArcGIS feature services (read-only public REST API, HTTPS).

Two steps per layer keep the transfer small: the attributes of *all* records (to verify and
count what is excluded and why), then the geometries of the candidate records only. The
number of records received is checked against the count the service reports.

``FixtureClient`` serves the same interface from local GeoJSON files — used by the tests and
the offline e2e run; its report is labelled as test data everywhere.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Protocol

import httpx
from shapely import unary_union
from shapely.geometry import mapping, shape

from .catalog import OUT_FIELDS, Source, sql_str

ITEM_URL = "https://www.arcgis.com/sharing/rest/content/items/{}"


class SourceError(Exception):
    def __init__(self, key: str, message: str) -> None:
        super().__init__(f"{key}: {message}")
        self.key = key
        self.message = message


class DataClient(Protocol):
    offline: bool

    async def layer_info(self, src: Source) -> dict[str, Any]: ...
    async def item_info(self, src: Source) -> dict[str, Any]: ...
    async def count(self, src: Source) -> int: ...
    async def attributes(self, src: Source, out_fields: str = OUT_FIELDS) -> list[dict[str, Any]]: ...
    async def geometries(self, src: Source, object_ids: list[int]) -> dict[int, dict[str, Any]]: ...
    async def project_records(self, src: Source, project_id: str) -> list[dict[str, Any]]: ...
    async def boundary(self, src: Source) -> dict[str, Any] | None: ...
    async def aclose(self) -> None: ...


def _one_geometry(features: list[dict[str, Any]]) -> dict[str, Any] | None:
    geoms = [f["geometry"] for f in features if f.get("geometry")]
    if len(geoms) <= 1:
        return geoms[0] if geoms else None
    return mapping(unary_union([shape(g) for g in geoms]))


class ArcGISClient:
    offline = False

    def __init__(self, timeout_s: float = 30.0, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout_s, follow_redirects=False,
                                                   headers={"User-Agent": "ExtraHorizon-coordination/0.3"})

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _json(self, src: Source, url: str, params: dict[str, Any], post: bool = False) -> dict[str, Any]:
        params = {**params, "f": params.get("f", "json")}
        try:
            r = await (self._client.post(url, data=params) if post else self._client.get(url, params=params))
        except httpx.HTTPError as e:
            raise SourceError(src.key, f"not reachable ({type(e).__name__})") from e
        if r.status_code != 200:
            raise SourceError(src.key, f"HTTP {r.status_code}")
        try:
            data = r.json()
        except ValueError as e:
            raise SourceError(src.key, "the answer is not JSON") from e
        if isinstance(data, dict) and "error" in data:
            err = data["error"] or {}
            raise SourceError(src.key, f"service error {err.get('code')}: {err.get('message')}")
        return data

    async def layer_info(self, src: Source) -> dict[str, Any]:
        return await self._json(src, src.url, {})

    async def item_info(self, src: Source) -> dict[str, Any]:
        return await self._json(src, ITEM_URL.format(src.item_id), {})

    async def count(self, src: Source) -> int:
        d = await self._json(src, f"{src.url}/query", {"where": "1=1", "returnCountOnly": "true"})
        return int(d.get("count", 0))

    async def attributes(self, src: Source, out_fields: str = OUT_FIELDS) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page = 1000
        while True:
            d = await self._json(src, f"{src.url}/query", {
                "where": "1=1", "outFields": out_fields, "returnGeometry": "false",
                "orderByFields": "OBJECTID", "resultOffset": len(rows), "resultRecordCount": page})
            feats = d.get("features", [])
            rows += [f.get("attributes", {}) for f in feats]
            if not feats or (not d.get("exceededTransferLimit") and len(feats) < page):
                return rows
            if len(rows) > 200_000:
                raise SourceError(src.key, "unexpectedly large layer")

    async def geometries(self, src: Source, object_ids: list[int]) -> dict[int, dict[str, Any]]:
        out: dict[int, dict[str, Any]] = {}
        for i in range(0, len(object_ids), 100):
            chunk = object_ids[i:i + 100]
            d = await self._json(src, f"{src.url}/query", {
                "objectIds": ",".join(str(o) for o in chunk), "outFields": "OBJECTID", "returnGeometry": "true",
                "outSR": "4326", "geometryPrecision": "6", "f": "geojson"}, post=True)
            for f in d.get("features", []):
                oid = (f.get("properties") or {}).get("OBJECTID", f.get("id"))
                if oid is not None and f.get("geometry"):
                    out[int(oid)] = f["geometry"]
        return out

    async def boundary(self, src: Source) -> dict[str, Any] | None:
        """The county's boundary polygon in WGS84, generalized to ≈30 m (enough to tell the county from the Keys)."""
        d = await self._json(src, f"{src.url}/query", {
            "where": "1=1", "outFields": "OBJECTID", "returnGeometry": "true", "outSR": "4326",
            "geometryPrecision": "5", "maxAllowableOffset": "0.0003", "f": "geojson"})
        return _one_geometry(d.get("features", []))

    async def project_records(self, src: Source, project_id: str) -> list[dict[str, Any]]:
        """Every record (part) of one project, as GeoJSON features — by project ID, which survives the
        county republishing a layer (object IDs do not)."""
        d = await self._json(src, f"{src.url}/query", {
            "where": f"PROJECTID={sql_str(project_id)}", "outFields": OUT_FIELDS, "returnGeometry": "true",
            "outSR": "4326", "geometryPrecision": "6", "f": "geojson"})
        return list(d.get("features", []))


class FixtureClient:
    """The same interface over local files: ``<key>.geojson`` (+ optional ``_meta.json``, whose
    ``"_as_of"`` date is the "today" the fixtures were written for)."""

    offline = True

    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        meta = self.folder / "_meta.json"
        self.meta = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
        self.as_of = dt.date.fromisoformat(self.meta["_as_of"]) if "_as_of" in self.meta else None

    async def aclose(self) -> None:
        return None

    def _features(self, src: Source) -> list[dict[str, Any]]:
        p = self.folder / f"{src.key}.geojson"
        if not p.exists():
            return []
        return json.loads(p.read_text(encoding="utf-8")).get("features", [])

    async def layer_info(self, src: Source) -> dict[str, Any]:
        info = {"name": src.key, "fields": [{"name": n} for n in (
            "OBJECTID", "PRJNAME", "PROJECTID", "PRJSCOPE", "AGCYNAME", "FACTYPE", "AGYPRJSTAT", "GENPRJSTAT",
            "STARTDATE", "ENDDATE", "GENCONTEMAIL", "GENCONTNUM", "UPDATDATE", "FACTYPE1", "AGCYNAME1",
            "CONFLTID1", "FACTYPE2", "AGCYNAME2", "CONFLTID2")]}
        info.update(self.meta.get(src.key, {}).get("layer", {}))
        return info

    async def item_info(self, src: Source) -> dict[str, Any]:
        base = {"title": src.title, "owner": "fixture", "access": "public", "modified": None}
        base.update(self.meta.get(src.key, {}).get("item", {}))
        return base

    async def count(self, src: Source) -> int:
        return len(self._features(src))

    async def attributes(self, src: Source, out_fields: str = OUT_FIELDS) -> list[dict[str, Any]]:
        return [dict(f.get("properties") or {}) for f in self._features(src)]

    async def geometries(self, src: Source, object_ids: list[int]) -> dict[int, dict[str, Any]]:
        want = set(object_ids)
        return {int(f["properties"]["OBJECTID"]): f["geometry"] for f in self._features(src)
                if f.get("geometry") and int(f["properties"]["OBJECTID"]) in want}

    async def boundary(self, src: Source) -> dict[str, Any] | None:
        return _one_geometry(self._features(src))

    async def project_records(self, src: Source, project_id: str) -> list[dict[str, Any]]:
        return [f for f in self._features(src)
                if str(f["properties"].get("PROJECTID") or "").strip() == str(project_id).strip()]

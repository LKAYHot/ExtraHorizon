"""Open-data sources for the utility-coordination analysis.

Miami-Dade County publishes its right-of-way coordination data (the county's "iMDC Utility
Coordination" system) as public ArcGIS feature services under the county's publishing account
``MDPublisher`` (organization ``8Pc9XBTAsYuxx9Ny``, hosted by Esri). Every layer has the same
schema — project name, project ID, scope, agency, facility type, agency and general status,
STARTDATE / ENDDATE, an agency contact and a footprint — one layer per kind of work (water,
sewer, stormwater, roadway, …). The county also publishes the pairs of projects its own
system found to conflict ("Potential Collaboration Project"), which the analysis uses as an
independent cross-check.

Verified live on 2026-09-26: the layers below exist and answer; Gas, Power, Cable, Bridge,
Transit and Moratorium are published but currently empty (0 records) — the report says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

MDC_SERVICES = "https://services.arcgis.com/8Pc9XBTAsYuxx9Ny/arcgis/rest/services"
PUBLISHER = "Miami-Dade County (ArcGIS account MDPublisher)"
PUBLISHER_OWNER = "MDPublisher"
HUB = "https://gis-mdc.opendata.arcgis.com"


@dataclass(frozen=True)
class Source:
    key: str  # the county's layer name, also used in the county's conflict list (FACTYPE1/2)
    title: str
    kind: str  # water | sewer | reclaimed | stormwater | paving | roadway | canal | … (utility or right-of-way work)
    service: str
    item_id: str
    utility: bool  # a utility network (water, sewer, power, gas, telecom, stormwater) vs. other right-of-way work
    layer: int = 0

    @property
    def url(self) -> str:
        return f"{MDC_SERVICES}/{self.service}/FeatureServer/{self.layer}"

    @property
    def item_url(self) -> str:
        return f"https://www.arcgis.com/home/item.html?id={self.item_id}"

    def project_url(self, project_id: str) -> str:
        """A human-readable page of a project's record(s), served by the county's own service. By project ID:
        the county republishes its layers (object IDs change), project IDs stay."""
        return query_page(self.url, f"PROJECTID={sql_str(project_id)}")


def sql_str(value: str) -> str:
    """A string literal for an ArcGIS `where` clause."""
    return "'" + str(value).replace("'", "''") + "'"


def query_page(layer_url: str, where: str) -> str:
    return f"{layer_url}/query?where={quote(where, safe='')}&outFields=*&f=html"


SOURCES: tuple[Source, ...] = (
    Source("UtilCoordWater", "Utility Coordination - Water Projects", "water", "UtilCoordWater_gdb",
           "9e9f0d9f314c4b6fb5ccd8372a9ae89d", True),
    Source("UtilCoordSewer", "Utility Coordination - Sewer Projects", "sewer", "UtilCoordSewer_gdb",
           "adb5057f6a634139ba0a4acd3673e649", True),
    Source("UtilCoordReclaimed", "Utility Coordination - Reclaimed Projects", "reclaimed", "UtilCoordReclaimed_gdb",
           "84d711eeecb544fa8071b991f9b528dc", True),
    Source("UtilCoordStormwater", "Utility Coordination - Stormwater Projects", "stormwater", "UtilCoordStormwater_gdb",
           "5221c90dc912446cbf4c3395112b6107", True),
    Source("UtilCoordPower", "Utility Coordination - Power Projects", "power", "UtilCoordPower_gdb",
           "99c416cd7f9c43929ae34c4dd22afbb1", True),
    Source("UtilCoordGas", "Utility Coordination - Gas Projects", "gas", "UtilCoordGas_gdb",
           "f3ffc1ff40fc4845ac1606c2c58929da", True),
    Source("UtilCoordCable", "Utility Coordination - Cable Projects", "cable", "UtilCoordCable_gdb",
           "5b623caa70d04af782904e9af8a2a3bf", True),
    Source("UtilCoordRoadway", "Utility Coordination - Roadway Projects", "roadway", "UtilCoordRoadway_gdb",
           "d543e47f73ef474dbb0942c831f92acb", False),
    Source("UtilCoordPaving", "Utility Coordination - Paving Projects", "paving", "UtilCoordPaving_gdb",
           "d5ff967dad974716ad3a0792d468dde9", False),
    Source("UtilCoordBridge", "Utility Coordination - Bridge Projects", "bridge", "UtilCoordBridge_gdb",
           "f9d151db696d461594286c91b06c7804", False),
    Source("UtilCoordTransit", "Utility Coordination - Transit Projects", "transit", "UtilCoordTransit_gdb",
           "2bc605d954d747eb96ccc67bb151da40", False),
    Source("UtilCoordCanal", "Utility Coordination - Canal Projects", "canal", "UtilCoordCanal_gdb",
           "24fb6126bcfc47d795a4b7e26836f50e", False),
    Source("UtilCoordMiscellaneous", "Utility Coordination - Miscellaneous Projects", "misc", "UtilCoordMiscellaneous_gdb",
           "934ba4ba485444a0a045b7094fc56198", False),
    Source("UtilCoordMoratorium", "Utility Coordination - Moratorium Projects", "moratorium", "UtilCoordMoratorium_gdb",
           "7e25ee21358d4678880bb1297965ed97", False),
)

# the county's own list of project pairs that conflict (independent cross-check)
CONFLICTS = Source("PotentialConflictProject", "Potential Collaboration Project", "conflicts",
                   "PotentialConflictProject_gdb", "7b7a298329c74ac5b2e15fd490c90d20", False)

# the county's own boundary polygon (same publisher): "inside Miami-Dade County" is checked against it
BOUNDARY = Source("MiamiDadeBoundary", "Miami-Dade Boundary", "boundary", "MiamiDadeBoundary_gdb",
                  "cec575982ea64ef7a11e587e532c6b6a", False)

BY_KEY = {s.key: s for s in SOURCES}

REGION = {
    "name": "Miami-Dade County, Florida",
    # generous bounding box of the county (lon/lat) — only if the county's boundary layer cannot be read
    "bbox": (-80.95, 25.10, -80.05, 26.00),
    "center": (25.76, -80.30),  # lat, lon
}

# the same department appears under two spellings in the data
AGENCY_ALIASES = {
    "City of Miami - RPW": "City of Miami - Resilience and Public Works",
    "City of Miami - Real Estate and Asset Manageme": "City of Miami - Real Estate and Asset Management",
}
AGENCY_SHORT = {
    "Miami-Dade Water and Sewer Department": "WASD",
    "Miami-Dade County Department of Transportation and Public Works": "DTPW",
    "FDOT": "FDOT",
    "City of Miami - Resilience and Public Works": "Miami RPW",
    "City of Miami - Office of Capital Improvements": "Miami OCI",
    "City of Miami - Parks and Recreation": "Miami Parks",
    "City of Coral Gables": "Coral Gables",
}

REQUIRED_FIELDS = ("OBJECTID", "PRJNAME", "PROJECTID", "AGCYNAME", "FACTYPE", "GENPRJSTAT", "AGYPRJSTAT",
                   "STARTDATE", "ENDDATE")
OUT_FIELDS = ("OBJECTID,PRJNAME,PROJECTID,PRJSCOPE,AGCYNAME,FACTYPE,AGYPRJSTAT,GENPRJSTAT,STARTDATE,ENDDATE,"
              "GENCONTEMAIL,GENCONTNUM,UPDATDATE")

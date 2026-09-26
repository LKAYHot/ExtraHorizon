"""The analysis report (for the UI), the fact sheet (for the tutor) and the grounding check.

The tutor never sees raw data: only this fact sheet — every number, date, project and
source it may mention, with finding IDs (F1, F2, …) to cite. After she answers, every number
and date in her text is checked against the fact sheet; anything else is reported to the UI.
"""

from __future__ import annotations

import re
from typing import Any

from .overlap import CATEGORY_LABEL, Finding
from .verify import EXCLUDE_REASONS

TOP_FACTS = 12


def fmt_project(p: dict[str, Any]) -> str:
    return (f'{p["plan_short"]} "{p["name"]}" (project {p["project_id"]}, {p["status"] or "status n/a"}, '
            f'{p["start"]} → {p["end"]})')


_fmt_project = fmt_project


def finding_line(f: dict[str, Any], projects: dict[str, dict[str, Any]]) -> str:
    """One finding as the fact sheet (and her tools) state it."""
    a, b = projects[f["a"]], projects[f["b"]]
    county = "yes" if f["county"].get("listed") else "no"
    return (f"{f['id']} — {f['category_label']} — {fmt_project(a)} ↔ {fmt_project(b)}: "
            + "; ".join(f["reasons"]) + f"; in the county's conflict list: {county}.")


def all_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Every finding of the analysis (the panel lists only the strongest ones)."""
    return report.get("_all_findings") or report["findings"]


def fact_sheet(report: dict[str, Any], top: int = TOP_FACTS, mention: str = "") -> str:
    """Plain text with every fact the tutor may use about the analysis. Findings the learner
    asks about (by ID such as F57, or by a project ID) are added to the highlighted ones."""
    if report.get("error"):
        return ("[Utility-coordination analysis — FAILED] The analysis could not be completed: "
                f"{report['error']}. Say so plainly; do not guess any results.")
    s = report["summary"]
    p = report["params"]
    projects = {x["uid"]: x for x in report["projects_index"]}
    lines = [
        "[Verified utility-coordination analysis — the ONLY facts you may state about it; cite findings by their IDs]",
        f"Data: {report['region']['name']} — the county's public Utility Coordination layers "
        f"({report['publisher']}), read {report['generated_at_local']}"
        + (" — OFFLINE TEST FIXTURE, not real county data." if report.get("offline") else ".")
        + (f" Note: {report['stale_note']}" if report.get("stale_note") else ""),
        f"Records received: {s['records_received']:,} of {s['records_reported']:,} reported by the services. "
        f"Records excluded: {s['records_excluded']:,}"
        + (" — " + ", ".join(f"{e['label']} {e['count']:,}" for e in s["excluded"]) if s["excluded"] else "") + ". "
        f"Records that passed every check: {s['records_passed']:,}, forming {s['projects_verified']:,} future or "
        f"ongoing planned projects"
        + _merged(s["records_merged"]) + ".",
    ]
    short = lambda x: x["title"].replace("Utility Coordination - ", "")  # noqa: E731
    lost = [x for x in report["sources"] if x.get("error") and not x["received"]]
    if lost:
        lines.append("Could not be read now, so left out of this analysis: "
                     + ", ".join(f"{short(x)} ({x['error']})" for x in lost) + ".")
    empty = [short(x) for x in report["sources"] if x["reported"] == 0 and not x.get("error")]
    if empty:
        lines.append("Published but empty right now (0 records): " + ", ".join(empty) + ".")
    lines.append("Plans compared (agency · facility: verified projects): "
                 + "; ".join(f"{x['label']} {x['count']:,}" for x in report["plans"]) + ".")
    lines.append(f"Rules: close = footprints within {p['distance_m']:,.0f} m (0 m = they intersect); same time = "
                 f"schedules overlap or are at most {p['window_days']} days apart; 'same time' alone is flagged only "
                 f"within {p['area_m']:,.0f} m. Today = {p['today']}.")
    c = s["by_category"]
    lines.append(f"Findings: {s['findings']:,} in total — close and at the same time: {c.get('both', 0):,}; "
                 f"close only: {c.get('near', 0):,}; same time nearby: {c.get('same_time', 0):,}.")
    x = report["crosscheck"]
    lines.append(f"County cross-check (the county's own conflict list, {x['county_pairs']:,} pairs): of our "
                 f"{x['our_intersecting']:,} pairs with intersecting footprints, {x['our_intersecting_confirmed']:,} "
                 f"are also in the county's list and {x['our_intersecting_not_listed']:,} are not (a coordinator should "
                 f"check those); of the county pairs between projects we verified, we flag "
                 f"{x['county_pairs_we_also_flag']:,} of {x['county_pairs_between_verified_projects']:,}"
                 + _not_flagged(x) + ".")
    by_reason = x.get("county_pairs_with_excluded_project") or {}
    if by_reason:
        total = x.get("county_pairs_with_excluded_project_total", sum(by_reason.values()))
        lines.append(f"County pairs involving a project we excluded: {total:,} — by reason: " + ", ".join(
            f"{k} {v:,}" for k, v in by_reason.items())
            + (" (a pair with two excluded projects counts under both reasons)" if sum(by_reason.values()) > total
               else "") + ".")
    if report.get("pairs"):
        lines.append("Which plans overlap (findings per pair of plans): " + "; ".join(
            f"{e['plans'][0]} ↔ {e['plans'][1]}: {e['total']:,} (close and same time {e['both']:,})"
            for e in report["pairs"][:10]) + ".")
    by_id = {f["id"]: f for f in all_findings(report)}
    total = report.get("findings_total", s["findings"])
    if len(report["findings"]) < total:
        lines.append(f"Listed in the panel: the {len(report['findings']):,} strongest of the {total:,} findings, "
                     f"including the best of every pair of plans; the others are not listed.")
    chosen = [by_id[i] for i in report.get("highlights", []) if i in by_id][:top] or report["findings"][:top]
    lines.append(f"Highlighted findings (the best of each pair of plans, then the next best; {len(chosen)} of "
                 f"{s['findings']:,}):")
    # what the question points at — typed or spoken ("F сто сорок шесть" = F146), any finding of the analysis
    from .refs import finding_ids, project_refs

    asked_ids = finding_ids(mention or "")
    for fid in [i for i in asked_ids if i not in by_id]:
        lines.append(f"Asked about {fid}: there is no {fid} in this analysis (F1–F{total}).")
    asked_pids = set(project_refs(mention or "", report))
    extra = [by_id[i] for i in asked_ids if i in by_id and by_id[i] not in chosen]
    extra += [f for f in all_findings(report) if f not in chosen and f not in extra and (
        projects[f["a"]]["project_id"] in asked_pids or projects[f["b"]]["project_id"] in asked_pids)]
    extra = extra[:10]
    for f in chosen:
        lines.append(finding_line(f, projects))
    if extra:
        lines.append("Asked about in this question:")
        lines += [finding_line(f, projects) + " Suggested: " + " ".join(f["actions"]) for f in extra]
    return "\n".join(lines)


# numbers may run into a unit ("90m", "2,426m²", "3km"); not inside a word ("F26", "R26")
_NUM = re.compile(r"(?<![\w.,])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)")
_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")  # also inside 2026-11-04T00:00
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_MDY = re.compile(rf"\b{_MON}\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)
_DMY = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MON},?\s+(\d{{4}})\b", re.I)
_MY = re.compile(rf"\b{_MON},?\s+(\d{{4}})\b", re.I)
_PCT = re.compile(r"(?<![\w.,])(\d+(?:\.\d+)?)\s*(?:%|percent\b|per cent\b)", re.I)
_FID = re.compile(r"\b[Ff]\d{1,6}\b")
_QUOTED = re.compile(r'"([^"]{3,})"')
_PID = re.compile(r"\(project ([^,()]+),")
_TOKEN = re.compile(r"[A-Za-z]+|\d[\d,]*(?:\.\d+)?")
_UNITS = {"m", "km", "ft", "feet", "foot", "mi", "mile", "miles", "meter", "meters", "metre", "metres", "day", "days",
          "week", "weeks", "month", "months", "year", "years", "hour", "hours"}
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                         "nov", "dec"), 1)}


def _norm(n: str) -> str:
    n = n.replace(",", "")
    if "." in n:
        n = n.rstrip("0").rstrip(".")
    return str(int(n)) if n.isdigit() else n


def _month(name: str) -> int:
    return _MONTHS[name.lower()[:3]]


def _dates(text: str) -> tuple[list[tuple[str, str]], str]:
    """Every date in the text as (as written, ISO 'YYYY-MM-DD' or 'YYYY-MM'), and the text without them."""
    found: list[tuple[str, str]] = []

    def take(m: re.Match[str], iso: str) -> str:
        found.append((m.group(0), iso))
        return " "

    text = _ISO.sub(lambda m: take(m, f"{m.group(1)}-{m.group(2)}-{m.group(3)}"), text)
    text = _MDY.sub(lambda m: take(m, f"{m.group(3)}-{_month(m.group(1)):02d}-{int(m.group(2)):02d}"), text)
    text = _DMY.sub(lambda m: take(m, f"{m.group(3)}-{_month(m.group(2)):02d}-{int(m.group(1)):02d}"), text)
    text = _MY.sub(lambda m: take(m, f"{m.group(2)}-{_month(m.group(1)):02d}"), text)
    return found, text


def _name_keys(names: list[str]) -> set[tuple[str, str, str]]:
    """Numbers inside project names and IDs with the word before / after them ("SR 826", "48-inch"):
    a name's number is grounded only in its own context, never as a figure on its own."""
    keys: set[tuple[str, str, str]] = set()
    for name in names:
        toks = _TOKEN.findall(name)
        for i, t in enumerate(toks):
            if not t[0].isdigit():
                continue
            n = _norm(t)
            if i > 0 and toks[i - 1][0].isalpha():
                keys.add(("<", toks[i - 1].lower(), n))
            if i + 1 < len(toks) and toks[i + 1][0].isalpha():
                keys.add((">", n, toks[i + 1].lower()))
    return keys


def _mask(text: str, strings: list[str]) -> str:
    for x in sorted(strings, key=len, reverse=True):
        if len(x) >= 4:
            text = re.sub(rf"(?<![\w.-]){re.escape(x)}(?![\w-])", " ", text, flags=re.I)
    return text


def grounding_check(answer: str, sheet: str) -> dict[str, Any]:
    """Figures in the answer that the fact sheet does not contain: numbers ≥ 10 (also with units), dates in any
    common form, percentages (the sheet has none — she must not compute them) and finding IDs. Numbers that are
    part of a project's name or ID count only in that context ("SR 826", "48-inch", "project 20018")."""
    names = _QUOTED.findall(sheet)
    pids = [p.strip() for p in _PID.findall(sheet)]
    sheet_dates, sheet_rest = _dates(sheet)
    allowed_dates = {iso for _w, iso in sheet_dates}
    allowed_months = {iso[:7] for iso in allowed_dates}
    allowed_years = {iso[:4] for iso in allowed_dates}
    facts = {_norm(m.group(1)) for m in _NUM.finditer(_mask(sheet_rest, names + pids))}
    keys = _name_keys(names + [f"project {p}" for p in pids])
    allowed_ids = {f.upper() for f in _FID.findall(sheet)}
    unknown: list[str] = []
    checked = 0
    found, rest = _dates(answer)
    for written, iso in found:
        checked += 1
        if not (iso in allowed_dates if len(iso) == 10 else iso in allowed_months):
            unknown.append(written.strip())
    for fid in _FID.findall(rest):
        checked += 1
        if fid.upper() not in allowed_ids:
            unknown.append(fid.upper())
    rest = _FID.sub(" ", rest)
    for m in _PCT.finditer(rest):
        checked += 1
        unknown.append(m.group(0).strip())
    rest = _PCT.sub(" ", _mask(rest, names + pids))
    toks = _TOKEN.findall(rest)
    for i, t in enumerate(toks):
        if not t[0].isdigit():
            continue
        n = _norm(t)
        prev = toks[i - 1].lower() if i > 0 and toks[i - 1][0].isalpha() else ""
        nxt = toks[i + 1].lower() if i + 1 < len(toks) and toks[i + 1][0].isalpha() else ""
        if n.isdigit() and int(n) < 10 and nxt not in _UNITS:
            continue  # "two findings", list numbers — but "3 km" or "5 days" is a figure
        checked += 1
        if n in facts or ("<", prev, n) in keys or (">", n, nxt) in keys or (len(n) == 4 and n in allowed_years):
            continue
        unknown.append(t)
    return {"ok": not unknown, "checked": checked, "unknown": sorted(set(unknown))[:20]}


def _not_flagged(x: dict[str, Any]) -> str:
    """Why the county's pairs between verified projects that we do not flag are not flagged."""
    same = x.get("county_pairs_same_project", 0)
    other = x.get("county_pairs_we_do_not_flag_count", len(x.get("county_pairs_we_do_not_flag") or []))
    if not same and not other:
        return ""
    if not other:
        return f" (the other {same:,} pair one project with itself across two layers)"
    verb = "is" if other == 1 else "are"
    if not same:
        return f" (the other {other:,} {verb} not flagged under these rules)"
    return (f" (of the others, {same:,} pair one project with itself across two layers and {other:,} {verb} not "
            f"flagged under these rules)")


def plan_pairs(findings: list[Finding]) -> list[dict[str, Any]]:
    """Findings per pair of plans (which utilities overlap with which), largest first."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for f in findings:
        a, b = sorted((f.a.plan_short, f.b.plan_short))
        e = out.setdefault((a, b), {"plans": [a, b], "total": 0, "both": 0, "near": 0, "same_time": 0,
                                    "best": f.id})
        e["total"] += 1
        e[f.category] += 1
    return sorted(out.values(), key=lambda e: (-e["both"], -e["total"], e["plans"]))


def highlights(findings: list[Finding], k: int = TOP_FACTS) -> list[str]:
    """IDs of the top findings to discuss: the best of every pair of plans first, then the next
    best — at most two findings per project, so one long corridor does not fill the list."""
    chosen: list[str] = []
    uses: dict[str, int] = {}

    def take(f: Finding) -> None:
        chosen.append(f.id)
        for uid in (f.a.uid, f.b.uid):
            uses[uid] = uses.get(uid, 0) + 1

    seen_pairs: set[tuple[str, str]] = set()
    for f in findings:  # already best first
        pair = tuple(sorted((f.a.plan_short, f.b.plan_short)))
        if pair not in seen_pairs and len(chosen) < k:
            seen_pairs.add(pair)
            take(f)
    for f in findings:
        if len(chosen) >= k:
            break
        if f.id in chosen or uses.get(f.a.uid, 0) >= 2 or uses.get(f.b.uid, 0) >= 2:
            continue
        take(f)
    order = {f.id: n for n, f in enumerate(findings)}
    return sorted(chosen, key=lambda i: order[i])


def _merged(n: int) -> str:
    if not n:
        return ""
    if n == 1:
        return " (1 of those records is a further part of a project published in several records and counts once)"
    return f" ({n:,} of those records are further parts of projects published in several records and count once)"


def summarize(findings: list[Finding]) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in findings:
        out[f.category] = out.get(f.category, 0) + 1
    return out


def excluded_totals(audits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tot: dict[str, int] = {}
    for a in audits:
        for e in a["excluded"]:
            tot[e["code"]] = tot.get(e["code"], 0) + e["count"]
    return [{"code": k, "count": v, "label": EXCLUDE_REASONS.get(k, k)} for k, v in sorted(tot.items(), key=lambda kv: -kv[1])]


__all__ = ["CATEGORY_LABEL", "excluded_totals", "fact_sheet", "grounding_check", "summarize"]

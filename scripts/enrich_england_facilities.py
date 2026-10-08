#!/usr/bin/env python3
"""
RestStop UK — England facility enrichment from OpenStreetMap / Overpass.

Goals:
- Enrich England stops with high-confidence facility positives.
- Preserve unknown vs explicit no: unprocessed England facility flags are reset
  to null, positives are set true, and direct explicit no tags can set false.
- Avoid treating absence in OSM as proof that a facility does not exist.
- Use conservative radii by stop type for nearby POIs.

The script is intentionally deterministic and idempotent.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA_MIN = ROOT / "data/frontend/reststops-uk.min.json"
DATA_PRETTY = ROOT / "data/frontend/reststops-uk.json"
REPORT = ROOT / "data/frontend/england-facilities-report.json"

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
USER_AGENT = "RestStopUK-facility-enrichment/1.0 (+https://reststopuk.co.uk/)"
TIMEOUT = 120
BATCH_SIZE = 30
REQUEST_PAUSE = 0.45
MAX_RETRIES = 5

FIELDS = [
    "toilets", "fuel", "food", "ev", "showers", "hgv",
    "motorhome", "overnight", "shop", "drinking_water",
]

YES = {"yes", "true", "1", "designated", "customers", "permissive", "paid"}
NO = {"no", "false", "0"}

def norm(v: Any) -> str:
    return str(v).strip().lower() if v is not None else ""

def truth(v: Any) -> bool | None:
    if v is True or v == 1:
        return True
    if v is False or v == 0:
        return False
    s = norm(v)
    if s in YES:
        return True
    if s in NO:
        return False
    return None

def miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.7613
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))

def radius_m(stop: dict[str, Any]) -> int:
    t = (stop.get("location_type") or stop.get("type") or "").lower()
    # Conservative: avoid attributing town-centre POIs to lay-bys/rest areas.
    if "service" in t:
        return 350
    if "truck" in t or "hgv" in t:
        return 250
    return 100

def osm_kind_id(stop: dict[str, Any]) -> tuple[str, int] | None:
    raw = stop.get("osm_id") or stop.get("id")
    if not raw:
        return None
    m = re.match(r"^(node|way|relation):(\d+)$", str(raw))
    if not m:
        return None
    return m.group(1), int(m.group(2))

def element_point(el: dict[str, Any]) -> tuple[float, float] | None:
    if "lat" in el and "lon" in el:
        return float(el["lat"]), float(el["lon"])
    c = el.get("center")
    if c and "lat" in c and "lon" in c:
        return float(c["lat"]), float(c["lon"])
    return None

def post_overpass(query: str) -> dict[str, Any]:
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        endpoint = ENDPOINTS[attempt % len(ENDPOINTS)]
        try:
            res = requests.post(
                endpoint,
                data={"data": query},
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT,
            )
            if res.status_code == 200:
                return res.json()
            if res.status_code in (429, 502, 503, 504):
                raise RuntimeError(f"{endpoint} returned {res.status_code}")
            res.raise_for_status()
        except Exception as exc:
            last_err = exc
            wait = min(30, 2 ** attempt)
            print(f"[overpass] attempt {attempt+1}/{MAX_RETRIES} failed: {exc}; sleeping {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"Overpass failed after retries: {last_err}")

def set_from_direct_tags(stop: dict[str, Any], tags: dict[str, Any], source_counts: Counter) -> None:
    # Explicit direct tags are highest confidence.
    direct = {
        "toilets": ["toilets"],
        "fuel": ["fuel"],
        "food": ["food", "restaurant", "fast_food", "cafe"],
        "ev": ["charging_station", "ev_charging"],
        "showers": ["shower", "showers"],
        "hgv": ["hgv", "hgv_parking"],
        "motorhome": ["motorhome", "motorhome_parking", "caravan"],
        "overnight": ["overnight", "overnight_parking", "motorhome:overnight"],
        "shop": ["shop"],
        "drinking_water": ["drinking_water", "water_point"],
    }
    amenity = norm(tags.get("amenity"))
    shop = norm(tags.get("shop"))
    if amenity == "toilets":
        stop["toilets"] = True; source_counts["direct:toilets"] += 1
    if amenity == "fuel":
        stop["fuel"] = True; source_counts["direct:fuel"] += 1
    if amenity in {"restaurant", "cafe", "fast_food", "food_court"}:
        stop["food"] = True; source_counts["direct:food"] += 1
        if amenity == "cafe":
            stop["coffee"] = True
    if amenity == "charging_station":
        stop["ev"] = True; source_counts["direct:ev"] += 1
    if amenity == "shower":
        stop["showers"] = True; source_counts["direct:showers"] += 1
    if amenity == "drinking_water":
        stop["drinking_water"] = True; source_counts["direct:drinking_water"] += 1
    if shop in {"convenience", "kiosk", "supermarket"}:
        stop["shop"] = True; source_counts["direct:shop"] += 1

    for field, keys in direct.items():
        for key in keys:
            if key not in tags:
                continue
            tv = truth(tags.get(key))
            if tv is not None:
                stop[field] = tv
                source_counts[f"direct:{field}"] += 1
                break

def poi_facilities(tags: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    amenity = norm(tags.get("amenity"))
    shop = norm(tags.get("shop"))
    tourism = norm(tags.get("tourism"))

    if amenity == "toilets":
        out.add("toilets")
    if amenity == "fuel":
        out.add("fuel")
    if amenity in {"restaurant", "cafe", "fast_food", "food_court"}:
        out.add("food")
    if amenity == "charging_station":
        out.add("ev")
    if amenity == "shower":
        out.add("showers")
    if amenity == "drinking_water":
        out.add("drinking_water")
    if shop in {"convenience", "kiosk", "supermarket"}:
        out.add("shop")
    if tourism in {"hotel", "motel"}:
        # Kept in tags/report, not a Must-have field in dataset.
        pass

    if truth(tags.get("toilets")) is True:
        out.add("toilets")
    if truth(tags.get("fuel")) is True:
        out.add("fuel")
    if any(truth(tags.get(k)) is True for k in ("restaurant", "fast_food", "cafe", "food")):
        out.add("food")
    if any(truth(tags.get(k)) is True for k in ("charging_station", "ev_charging")):
        out.add("ev")
    if any(truth(tags.get(k)) is True for k in ("shower", "showers")):
        out.add("showers")
    if truth(tags.get("hgv")) is True or truth(tags.get("hgv_parking")) is True:
        out.add("hgv")
    if any(truth(tags.get(k)) is True for k in ("motorhome", "motorhome_parking", "caravan")):
        out.add("motorhome")
    if any(truth(tags.get(k)) is True for k in ("overnight", "overnight_parking", "motorhome:overnight")):
        out.add("overnight")
    if truth(tags.get("drinking_water")) is True or truth(tags.get("water_point")) is True:
        out.add("drinking_water")
    return out

def direct_element_enrichment(stops: list[dict[str, Any]], source_counts: Counter) -> None:
    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for s in stops:
        kid = osm_kind_id(s)
        if kid:
            grouped[kid[0]].append((kid[1], s))

    by_key = {(kind, oid): s for kind, items in grouped.items() for oid, s in items}

    for kind, items in grouped.items():
        ids = [oid for oid, _ in items]
        for pos in range(0, len(ids), 350):
            chunk = ids[pos:pos+350]
            selector = f"{kind}(id:{','.join(map(str, chunk))});"
            q = f"[out:json][timeout:120];({selector});out tags center;"
            data = post_overpass(q)
            for el in data.get("elements", []):
                s = by_key.get((el.get("type"), int(el.get("id"))))
                if s:
                    set_from_direct_tags(s, el.get("tags", {}), source_counts)
            time.sleep(REQUEST_PAUSE)

def nearby_enrichment(stops: list[dict[str, Any]], source_counts: Counter) -> None:
    for start in range(0, len(stops), BATCH_SIZE):
        batch = stops[start:start+BATCH_SIZE]
        clauses = []
        for s in batch:
            lat, lon = float(s["lat"]), float(s["lng"])
            r = radius_m(s)
            clauses.extend([
                f'nwr(around:{r},{lat},{lon})["amenity"~"^(toilets|fuel|charging_station|restaurant|cafe|fast_food|food_court|shower|drinking_water)$"];',
                f'nwr(around:{r},{lat},{lon})["shop"~"^(convenience|kiosk|supermarket)$"];',
                f'nwr(around:{r},{lat},{lon})["hgv"];',
                f'nwr(around:{r},{lat},{lon})["motorhome"];',
                f'nwr(around:{r},{lat},{lon})["overnight"];',
            ])
        q = "[out:json][timeout:120];(" + "".join(clauses) + ");out center tags;"
        data = post_overpass(q)

        # Deduplicate objects returned by overlapping around() clauses.
        seen = set()
        elements = []
        for el in data.get("elements", []):
            key = (el.get("type"), el.get("id"))
            if key in seen:
                continue
            seen.add(key)
            elements.append(el)

        for el in elements:
            p = element_point(el)
            if not p:
                continue
            facs = poi_facilities(el.get("tags", {}))
            if not facs:
                continue
            plat, plon = p
            for s in batch:
                r = radius_m(s)
                d_miles = miles(float(s["lat"]), float(s["lng"]), plat, plon)
                if d_miles * 1609.344 <= r:
                    for field in facs:
                        if s.get(field) is not True:
                            s[field] = True
                            source_counts[f"nearby:{field}"] += 1

        done = min(start+BATCH_SIZE, len(stops))
        print(f"[nearby] {done}/{len(stops)} England stops processed")
        time.sleep(REQUEST_PAUSE)

def enrich(data: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    england = [s for s in data if s.get("country") == "England"]
    source_counts: Counter = Counter()

    # Legacy England rows used false as a placeholder for "not processed".
    # Convert those fields to unknown before adding verified positives.
    for s in england:
        for field in FIELDS:
            s[field] = None
        # Optional UI aliases.
        s["coffee"] = None
        s["facilities_status"] = "osm_enrichment_v1_pending"

    direct_element_enrichment(england, source_counts)
    nearby_enrichment(england, source_counts)

    for s in england:
        s["facilities_status"] = "osm_enriched_v1"

    confirmed = {field: sum(1 for s in england if s.get(field) is True) for field in FIELDS}
    explicit_no = {field: sum(1 for s in england if s.get(field) is False) for field in FIELDS}
    unknown = {field: sum(1 for s in england if s.get(field) is None) for field in FIELDS}

    report = {
        "schema": 1,
        "country": "England",
        "stops_processed": len(england),
        "method": "OpenStreetMap direct tags + conservative nearby POI matching via Overpass",
        "radii_metres": {"services": 350, "truck_hgv": 250, "layby_rest_area": 100},
        "confirmed_true": confirmed,
        "explicit_false": explicit_no,
        "unknown": unknown,
        "evidence_counts": dict(sorted(source_counts.items())),
        "notes": [
            "Absence of an OSM facility is kept as unknown, not converted to false.",
            "Nearby POIs are matched conservatively by stop type.",
            "Overnight parking is only set from explicit OSM overnight tags.",
        ],
    }
    return data, report

def main() -> None:
    data = json.loads(DATA_MIN.read_text(encoding="utf-8"))
    data, report = enrich(data)

    # Keep compact production data and readable source dataset in sync.
    DATA_MIN.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    DATA_PRETTY.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()

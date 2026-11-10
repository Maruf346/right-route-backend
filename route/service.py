from rest_framework.exceptions import ValidationError
import math
import re
import requests
from django.conf import settings
from core.models import AIExtractResponse


def _normalize_road_token(text: str) -> str:
    """Normalize a road or highway reference for comparison/matching."""
    s = (text or "").lower().strip()
    s = re.sub(r"\b(north|south|east|west|nb|sb|eb|wb|exit\s*\d+[a-z]?)\b", " ", s)
    s = re.sub(r"[-_/]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _split_intersection_parts(address: str):
    """Split 'RoadA and RoadB, City, State' into (road_a, road_b, tail)."""
    head, _, tail = (address or "").partition(",")
    parts = re.split(r"\s+(?:and|&)\s+", head.strip(), maxsplit=1, flags=re.IGNORECASE)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip(), tail.strip()
    return head.strip(), "", tail.strip()


def clean_intersection_list(raw_intersections: list) -> list:
    """Remove self-intersections (e.g. 'I-94 and I-94') and duplicate road pairs."""
    cleaned = []
    seen_pairs = set()
    for item in raw_intersections or []:
        if not item or not str(item).strip():
            continue
        addr = str(item).strip()
        r1, r2, _ = _split_intersection_parts(addr)
        n1, n2 = _normalize_road_token(r1), _normalize_road_token(r2)
        if n1 and n2 and n1 == n2:
            continue
        pair_key = tuple(sorted((n1, n2))) if (n1 and n2) else (n1,)
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)
        cleaned.append(addr)
    return cleaned


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    )
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _valid_coord(coord) -> bool:
    if not coord or len(coord) != 2:
        return False
    lat, lng = coord
    return lat is not None and lng is not None and (abs(lat) > 0.001 or abs(lng) > 0.001)


def _is_within_corridor(lat: float, lng: float, start_coords, end_coords, margin_deg: float = 2.5) -> bool:
    if not (_valid_coord(start_coords) and _valid_coord(end_coords)):
        return True
    min_lat = min(start_coords[0], end_coords[0]) - margin_deg
    max_lat = max(start_coords[0], end_coords[0]) + margin_deg
    min_lng = min(start_coords[1], end_coords[1]) - margin_deg
    max_lng = max(start_coords[1], end_coords[1]) + margin_deg
    return min_lat <= lat <= max_lat and min_lng <= lng <= max_lng


def _build_query_candidates(address: str) -> list:
    """Build normalized Google Geocoding query candidates preserving specificity."""
    r1, r2, tail = _split_intersection_parts(address)
    candidates = []
    if r1 and r2:
        clean_r1 = re.sub(r"\b(north|south|east|west|nb|sb|eb|wb)\b", "", r1, flags=re.IGNORECASE).strip()
        clean_r2 = re.sub(r"\b(north|south|east|west|nb|sb|eb|wb)\b", "", r2, flags=re.IGNORECASE).strip()
        base_amp = f"{clean_r1 or r1} & {clean_r2 or r2}"
        if tail:
            candidates.append(f"{base_amp}, {tail}")
            tail_parts = [p.strip() for p in tail.split(",") if p.strip()]
            if len(tail_parts) > 1:
                candidates.append(f"{base_amp}, {tail_parts[-1]}")
        else:
            candidates.append(base_amp)
    candidates.append(address)
    # Deduplicate preserving order
    seen = set()
    unique = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def _geocode_single_intersection(address: str, bounds_str: str | None, start_coords, end_coords):
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    best_fallback = None
    for query in _build_query_candidates(address):
        params = {"address": query, "key": settings.GOOGLE_MAP_API_KEY}
        if bounds_str:
            params["bounds"] = bounds_str
        try:
            response = requests.get(url, params=params, timeout=10)
            AIExtractResponse.objects.create(response_json=str(response))
            data = response.json()
            AIExtractResponse.objects.create(response_json=str(data))
        except Exception as e:
            print(f"Geocode error for '{query}': {e}")
            continue

        if data.get("status") != "OK":
            continue

        for result in data.get("results", []):
            loc = (result.get("geometry") or {}).get("location") or {}
            lat, lng = loc.get("lat"), loc.get("lng")
            if lat is None or lng is None:
                continue
            if not _is_within_corridor(lat, lng, start_coords, end_coords):
                continue
            types = result.get("types") or []
            loc_type = (result.get("geometry") or {}).get("location_type", "")
            is_exact = "intersection" in types
            if is_exact:
                return {"name": address, "lat": lat, "lng": lng, "_exact": True}
            if best_fallback is None and loc_type != "APPROXIMATE":
                best_fallback = {"name": address, "lat": lat, "lng": lng, "_exact": False}
    return best_fallback


def _refine_via_osrm_steps(resolved: list, start_coords, end_coords):
    """Refine imprecise 'route'-level highway junctions using OSRM step maneuvers."""
    for idx, item in enumerate(resolved):
        if not item or item.get("_exact"):
            continue
        prev_pt = start_coords
        for j in range(idx - 1, -1, -1):
            if resolved[j] and _valid_coord((resolved[j]["lat"], resolved[j]["lng"])):
                prev_pt = (resolved[j]["lat"], resolved[j]["lng"])
                break
        next_pt = end_coords
        for j in range(idx + 1, len(resolved)):
            if resolved[j] and resolved[j].get("_exact") and _valid_coord((resolved[j]["lat"], resolved[j]["lng"])):
                next_pt = (resolved[j]["lat"], resolved[j]["lng"])
                break
        if not (_valid_coord(prev_pt) and _valid_coord(next_pt)):
            continue

        r1, r2, tail = _split_intersection_parts(item["name"])
        target_b = _normalize_road_token(r2 or r1)
        exit_match = re.search(r"\bexit\s*(\d+[a-z]?)\b", item["name"], re.IGNORECASE)
        target_exit = exit_match.group(1).lower() if exit_match else None

        try:
            url = (
                f"https://router.project-osrm.org/route/v1/driving/"
                f"{prev_pt[1]},{prev_pt[0]};{next_pt[1]},{next_pt[0]}?steps=true"
            )
            resp = requests.get(url, timeout=8)
            if resp.status_code != 200:
                continue
            steps = resp.json().get("routes", [{}])[0].get("legs", [{}])[0].get("steps", [])
            matched_loc = None
            for step in steps:
                exits = [x.strip().lower() for x in str(step.get("exits") or "").split(";") if x.strip()]
                step_refs = [_normalize_road_token(x) for x in str(step.get("ref") or "").split(";") if x.strip()]
                step_name = _normalize_road_token(step.get("name") or "")
                loc = (step.get("maneuver") or {}).get("location")
                if not loc or len(loc) != 2:
                    continue
                if target_exit and target_exit in exits:
                    matched_loc = (loc[1], loc[0])
                    break
                if target_b and (
                    target_b in step_refs
                    or (len(target_b) >= 4 and target_b in step_name)
                ):
                    matched_loc = (loc[1], loc[0])
                    break
            if matched_loc:
                item["lat"], item["lng"] = matched_loc[0], matched_loc[1]
                item["_exact"] = True
        except Exception as e:
            print(f"OSRM step refinement skipped for '{item['name']}': {e}")

def extract_route_data(permit_file=None, permit_text=None):
        file_extract_url = "http://54.236.158.228:8001/api/ocr/extract"
        text_extract_url = "http://54.236.158.228:8001/api/ocr/extract-text"

        if permit_file:
            permit_file.seek(0)
            payload = {
                "file": (
                    permit_file.name,
                    permit_file.read(),
                    permit_file.content_type
                )
            }
        elif permit_text:
            payload = {
                "text": permit_text
            }
        else:
            raise ValidationError(
                "Permit file or Permit text must be need."
            )
        
        try:
            if permit_file:
                response = requests.post(
                    file_extract_url,
                    files=payload,
                    timeout=30
                )
            elif permit_text:
                response = requests.post(
                    text_extract_url,
                    data=payload,
                    timeout=30
                )
            print("response: ", response)
            if response.status_code != 200:
                raise ValidationError(
                    "Documents Extract Failed!"
                )
            response_data = response.json()
        
            if not response_data.get('success') and not response_data.get('route_information'):
                raise ValidationError(
                    "Documents Extract Failed!"
                )
            return response_data.get('route_information')
        except requests.exceptions.Timeout:
            raise ValidationError(
                "OCR server timeout."
            )
        except requests.exceptions.ConnectionError:
            raise ValidationError(
                "Cannot connect to OCR server."
            )
        except Exception as e:
            raise ValidationError(str(e))



def get_intersection_lat_lng(address_list: list, start_coords=None, end_coords=None):
    """Resolve intersection names to accurate coordinates biased to the route corridor."""
    cleaned_addresses = clean_intersection_list(address_list)
    if not cleaned_addresses:
        return []

    bounds_str = None
    if _valid_coord(start_coords) and _valid_coord(end_coords):
        min_lat = min(start_coords[0], end_coords[0]) - 1.5
        max_lat = max(start_coords[0], end_coords[0]) + 1.5
        min_lng = min(start_coords[1], end_coords[1]) - 1.5
        max_lng = max(start_coords[1], end_coords[1]) + 1.5
        bounds_str = f"{min_lat},{min_lng}|{max_lat},{max_lng}"

    resolved = [
        _geocode_single_intersection(addr, bounds_str, start_coords, end_coords)
        for addr in cleaned_addresses
    ]
    _refine_via_osrm_steps(resolved, start_coords, end_coords)

    waypoints = []
    for item in resolved:
        if not item:
            continue
        lat, lng = item["lat"], item["lng"]
        if _valid_coord(start_coords) and _haversine_km(lat, lng, start_coords[0], start_coords[1]) < 0.15:
            continue
        if _valid_coord(end_coords) and _haversine_km(lat, lng, end_coords[0], end_coords[1]) < 0.15:
            continue
        waypoints.append({"name": item["name"], "lat": lat, "lng": lng})
    return waypoints


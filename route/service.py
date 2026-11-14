from rest_framework.exceptions import ValidationError
import math
import re
import json
import requests
from django.conf import settings
from core.models import AIExtractResponse


US_STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}


def normalize_state_code(value):
    """Normalize a US state abbreviation/name to its two-letter code."""
    raw = str(value or "").strip()
    if not raw:
        return None
    upper = raw.upper().replace(".", "")
    if upper in US_STATE_NAMES:
        return upper
    for code, name in US_STATE_NAMES.items():
        if upper == name.upper():
            return code
    match = re.search(r"\b([A-Z]{2})\s*(?:DOT|DEPARTMENT OF TRANSPORTATION)\b", upper)
    return match.group(1) if match and match.group(1) in US_STATE_NAMES else None


def detect_issuing_state(route_data=None, permit_text=None, state_hint=None):
    """Determine permit jurisdiction, preferring the explicit client hint."""
    hinted = normalize_state_code(state_hint)
    if hinted:
        return hinted

    route_data = route_data if isinstance(route_data, dict) else {}
    for key in ("issuing_state", "state", "state_code", "permit_state", "jurisdiction"):
        detected = normalize_state_code(route_data.get(key))
        if detected:
            return detected

    searchable = f"{permit_text or ''} {json.dumps(route_data, default=str)}"
    # Permit headers are authoritative. Prefer "Nebraska DOT", "State of
    # Nebraska", etc. over route text that may legitimately mention the next
    # state at a border crossing.
    for code, name in US_STATE_NAMES.items():
        header_pattern = (
            rf"(?:\bstate\s+of\s+{re.escape(name)}\b|"
            rf"\b{re.escape(name)}\s+(?:DOT|department\s+of\s+transportation)\b)"
        )
        if re.search(header_pattern, searchable, re.IGNORECASE):
            return code
    dot_match = re.search(r"\b([A-Z]{2})\s*DOT\b", searchable, re.IGNORECASE)
    if dot_match and dot_match.group(1).upper() in US_STATE_NAMES:
        return dot_match.group(1).upper()
    mentioned = [
        code for code, name in US_STATE_NAMES.items()
        if re.search(rf"\b{re.escape(name)}\b", searchable, re.IGNORECASE)
    ]
    if len(mentioned) == 1:
        return mentioned[0]
    return None


def _explicit_state_in_address(address):
    text = str(address or "").strip()
    for code, name in US_STATE_NAMES.items():
        if re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE):
            return code
    # State highway notation, e.g. ND-200, IA 92, or NE-2.
    route_prefix = re.match(r"^([A-Z]{2})(?:-|\s+)\d+\b", text.upper())
    if route_prefix and route_prefix.group(1) in US_STATE_NAMES:
        return route_prefix.group(1)
    match = re.search(r"(?:,\s*|\s)([A-Z]{2})(?:\s+\d{5}(?:-\d{4})?)?\s*$", text)
    if match and match.group(1) in US_STATE_NAMES:
        return match.group(1)
    return None


def _result_state_code(result):
    for component in result.get("address_components", []):
        if "administrative_area_level_1" in component.get("types", []):
            return normalize_state_code(component.get("short_name") or component.get("long_name"))
    return None


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
    return _coerce_coordinate_pair(coord[0], coord[1]) is not None


def _coerce_coordinate_pair(lat, lng):
    """Return finite numeric coordinates within geographic bounds, or None."""
    if isinstance(lat, bool) or isinstance(lng, bool):
        return None
    try:
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lng)):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    if abs(lat) <= 0.001 and abs(lng) <= 0.001:
        return None
    return lat, lng


def _is_within_corridor(lat: float, lng: float, start_coords, end_coords, margin_deg: float = 2.5) -> bool:
    if not (_valid_coord(start_coords) and _valid_coord(end_coords)):
        return True
    min_lat = min(start_coords[0], end_coords[0]) - margin_deg
    max_lat = max(start_coords[0], end_coords[0]) + margin_deg
    min_lng = min(start_coords[1], end_coords[1]) - margin_deg
    max_lng = max(start_coords[1], end_coords[1]) + margin_deg
    return min_lat <= lat <= max_lat and min_lng <= lng <= max_lng


def _build_query_candidates(address: str, state_code=None) -> list:
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
    if state_code:
        state_name = US_STATE_NAMES[state_code]
        candidates = [
            candidate
            if re.search(rf"\b(?:{state_code}|{re.escape(state_name)})\b", candidate, re.IGNORECASE)
            else f"{candidate}, {state_name}, USA"
            for candidate in candidates
        ]
    # Deduplicate preserving order
    seen = set()
    unique = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def _geocode_single_intersection(address: str, bounds_str: str | None, start_coords, end_coords, state_code=None):
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    best_fallback = None
    explicit_state = _explicit_state_in_address(address)
    if state_code and explicit_state and explicit_state != state_code:
        return None

    for query in _build_query_candidates(address, state_code=state_code):
        params = {"address": query, "key": settings.GOOGLE_MAP_API_KEY}
        if bounds_str:
            params["bounds"] = bounds_str
        if state_code:
            params["components"] = f"country:US|administrative_area:{state_code}"
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
            if state_code and _result_state_code(result) != state_code:
                continue
            loc = (result.get("geometry") or {}).get("location") or {}
            coordinates = _coerce_coordinate_pair(loc.get("lat"), loc.get("lng"))
            if coordinates is None:
                continue
            lat, lng = coordinates
            if not _is_within_corridor(lat, lng, start_coords, end_coords):
                continue
            types = result.get("types") or []
            loc_type = (result.get("geometry") or {}).get("location_type", "")
            is_exact = "intersection" in types
            if is_exact:
                return {"name": address, "lat": lat, "lng": lng, "_exact": True}
            if best_fallback is None and loc_type != "APPROXIMATE":
                best_fallback = {"name": address, "lat": lat, "lng": lng, "_exact": False}
    # For parsed permits, do not place a point elsewhere in the state merely
    # because the road name exists there. It must also fit the start/end route
    # corridor; otherwise report it as unresolved for manual correction.
    if state_code and _valid_coord(start_coords) and _valid_coord(end_coords):
        return None
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

def extract_route_data(permit_file=None, permit_text=None, state_hint=None):
    file_extract_url = "http://54.236.158.228:8001/api/ocr/extract"
    text_extract_url = "http://54.236.158.228:8001/api/ocr/extract-text"

    if permit_file:
        permit_file.seek(0)
        payload = {
            "file": (
                permit_file.name,
                permit_file.read(),
                getattr(permit_file, "content_type", "application/octet-stream"),
            )
        }
    elif permit_text:
        payload = {"text": permit_text}
    else:
        raise ValidationError("A permit file or permit_text is required.")

    try:
        if permit_file:
            response = requests.post(
                file_extract_url,
                files=payload,
                data={"state_hint": state_hint} if state_hint else None,
                timeout=30,
            )
        else:
            if state_hint:
                payload["state_hint"] = state_hint
            response = requests.post(text_extract_url, data=payload, timeout=30)
        if response.status_code != 200:
            raise ValidationError("Permit OCR extraction failed.")
        response_data = response.json()
        route_information = response_data.get("route_information")
        if not response_data.get("success") and not route_information:
            raise ValidationError("Permit OCR extraction failed.")
        if not isinstance(route_information, dict):
            raise ValidationError("OCR service returned an invalid route structure.")
        return route_information
    except requests.exceptions.Timeout:
        raise ValidationError("OCR server timeout.")
    except requests.exceptions.ConnectionError:
        raise ValidationError("Cannot connect to OCR server.")
    except ValidationError:
        raise
    except (ValueError, requests.exceptions.RequestException) as exc:
        raise ValidationError(f"OCR request failed: {exc}")



def get_intersection_lat_lng(address_list: list, start_coords=None, end_coords=None, state_hint=None):
    """Resolve intersections inside the issuing state and optional route corridor."""
    state_code = normalize_state_code(state_hint)
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
        _geocode_single_intersection(
            addr,
            bounds_str,
            start_coords,
            end_coords,
            state_code=state_code,
        )
        for addr in cleaned_addresses
    ]
    # OSRM is useful for unbounded legacy requests, but its public route service
    # does not provide a state-boundary guarantee. Keep state-restricted results
    # exactly as Google validated them.
    if not state_code:
        _refine_via_osrm_steps(resolved, start_coords, end_coords)

    waypoints = []
    for item in resolved:
        if not item:
            continue
        coordinates = _coerce_coordinate_pair(item.get("lat"), item.get("lng"))
        if coordinates is None:
            continue
        lat, lng = coordinates
        if _valid_coord(start_coords) and _haversine_km(lat, lng, start_coords[0], start_coords[1]) < 0.15:
            continue
        if _valid_coord(end_coords) and _haversine_km(lat, lng, end_coords[0], end_coords[1]) < 0.15:
            continue
        waypoints.append({"name": item["name"], "lat": lat, "lng": lng})
    return waypoints


def _value_name(value):
    if isinstance(value, dict):
        return value.get("name") or value.get("location") or value.get("address")
    return value if isinstance(value, str) else None


def _first_value(data, keys):
    for key in keys:
        value = _value_name(data.get(key))
        if value and value.strip():
            return value.strip()
    return None


def _extract_origin_destination(route_data, permit_text):
    origin = _first_value(route_data, ("origin", "start", "start_location", "from"))
    destination = _first_value(route_data, ("destination", "end", "end_location", "to"))
    text = str(permit_text or "")
    if not origin:
        match = re.search(r"\bfrom\s+(.+?)(?=\s+(?:via|to)\s+)", text, re.IGNORECASE)
        origin = match.group(1).strip(" ,.;") if match else None
    if not destination:
        matches = list(re.finditer(r"\bto\s+([^,.;\n]+)", text, re.IGNORECASE))
        destination = matches[-1].group(1).strip(" ,.;") if matches else None
    return origin, destination


def _extract_waypoint_names(route_data):
    raw = (
        route_data.get("intersection")
        or route_data.get("intersections")
        or route_data.get("waypoints")
        or route_data.get("route_instructions")
        or []
    )
    if isinstance(raw, str):
        raw = [part.strip() for part in re.split(r"[\n;]+", raw) if part.strip()]
    names = []
    for item in raw if isinstance(raw, list) else []:
        name = _value_name(item)
        if name:
            names.append(name.strip())
    return names


def _geocode_named_location(name, state_code):
    if not name:
        return None
    result = _geocode_single_intersection(
        name,
        bounds_str=None,
        start_coords=None,
        end_coords=None,
        state_code=state_code,
    )
    if not result:
        return None
    coordinates = _coerce_coordinate_pair(result.get("lat"), result.get("lng"))
    if coordinates is None:
        return None
    return {
        "name": name,
        "latitude": coordinates[0],
        "longitude": coordinates[1],
    }


def parse_permit_route(permit_file=None, permit_text=None, state_hint=None):
    """Extract, validate, and state-restrict a permit into frontend route data."""
    route_data = extract_route_data(
        permit_file=permit_file,
        permit_text=permit_text,
        state_hint=state_hint,
    ) or {}
    if not isinstance(route_data, dict):
        raise ValidationError("OCR service returned an invalid route structure.")

    issuing_state = detect_issuing_state(route_data, permit_text, state_hint)
    if not issuing_state:
        raise ValidationError(
            "Unable to determine the issuing state. Submit state_hint (for example, 'NE')."
        )

    origin_name, destination_name = _extract_origin_destination(route_data, permit_text)
    origin = _geocode_named_location(origin_name, issuing_state)
    destination = _geocode_named_location(destination_name, issuing_state)
    start_coords = (
        (origin["latitude"], origin["longitude"])
        if origin else None
    )
    end_coords = (
        (destination["latitude"], destination["longitude"])
        if destination else None
    )

    waypoint_names = _extract_waypoint_names(route_data)
    resolved = get_intersection_lat_lng(
        waypoint_names,
        start_coords=start_coords,
        end_coords=end_coords,
        state_hint=issuing_state,
    )
    waypoints = []
    for item in resolved:
        coordinates = _coerce_coordinate_pair(item.get("lat"), item.get("lng"))
        if coordinates is None:
            continue
        waypoints.append({
            "index": len(waypoints) + 1,
            "name": item["name"],
            "waypoint_type": "CHECKPOINT",
            "latitude": coordinates[0],
            "longitude": coordinates[1],
        })

    permit_number = _first_value(
        route_data,
        ("permit_number", "permit_no", "permit_id", "number"),
    )
    resolved_names = {item["name"] for item in waypoints}
    unresolved = [name for name in waypoint_names if name not in resolved_names]
    return {
        "status": "success",
        "permit_number": permit_number,
        "issuing_state": issuing_state,
        "origin": origin,
        "destination": destination,
        "waypoints": waypoints,
        "unresolved_waypoints": unresolved,
    }

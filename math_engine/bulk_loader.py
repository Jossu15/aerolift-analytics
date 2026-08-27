"""
math_engine.bulk_loader
-----------------------
Bulk data ingestion and validation for gas-well datasets.

Supports JSON, CSV, and Excel (.xlsx) files.  Parses flexible column
names (aliases), fills sensible defaults, runs liquid-loading analysis
on every well, and returns structured results comparing predicted vs.
observed status.

Field units throughout (see CONTEXT.md).
"""
import csv
import io
import json
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from math_engine.liquid_loading import (
    turner_critical_velocity,
    coleman_critical_velocity,
    actual_gas_velocity,
    minimum_flow_rate,
)
from math_engine.gas_properties import get_gas_properties

# ======================================================================
# Column alias mapping — accepts many common header variants
# ======================================================================
_COLUMN_ALIASES: Dict[str, Tuple[str, ...]] = {
    "tag":            ("tag", "well_id", "well", "name", "pozo", "id",
                       "well_name", "wellid"),
    "p_wh":           ("p_wh", "pwh", "whp", "whp_psia", "p_wh_psia",
                       "presion_superficie", "wellhead_pressure",
                       "surface_pressure", "whp_mpa"),
    "t_wh_f":         ("t_wh_f", "twh", "twh_f", "t_surface_f",
                       "surface_temp", "temperatura_superficie",
                       "temperature_surface", "wht_c", "wht_f"),
    "gamma_g":        ("gamma_g", "gas_gravity", "sg_gas", "gg",
                       "gravedad_gas", "gas_sg"),
    "tubing_id_in":   ("tubing_id_in", "tubing_id", "tid", "d_tubing",
                       "tubing_diameter", "id_tubing", "tubing"),
    "q_gas_mscfd":    ("q_gas_mscfd", "q_gas", "qgas", "gas_rate",
                       "tasa_gas", "test_rate_mscfd", "test_rate",
                       "rate_mscfd", "qg", "gas_rate_m3d"),
    "q_water_bpd":    ("q_water_bpd", "q_water", "water_rate", "agua",
                       "water_bpd", "qw", "liquid_rate_m3d"),
    "depth_ft":       ("depth_ft", "depth", "tvd", "tvd_ft", "profundidad",
                       "well_depth", "true_vertical_depth", "depth_m"),
    "status":         ("status", "estado", "loading_status", "observed",
                       "actual_status", "field_status", "actual"),
    "p_res":          ("p_res", "pres", "reservoir_pressure", "p_reservoir",
                       "pi", "initial_pressure", "bhp_mpa"),
    "t_res_f":        ("t_res_f", "tres", "reservoir_temp", "t_reservoir",
                       "bottomhole_temp", "bht_c"),
    "liquid_sg":      ("liquid_sg", "sg_liquid", "liquid_gravity"),
    "cond_yield":     ("cond_yield", "condensate_yield", "condensate"),
    "water_yield":    ("water_yield", "water_cut"),
    "vsg_ms":         ("vsg_ms", "vsg", "current_velocity"),
    "inclination_deg": ("inclination_deg", "inclination", "angle_deg"),
}

# Columns that need unit conversion from metric to field units
_UNIT_CONVERSIONS = {
    # (column, from_unit, to_unit, factor_or_func)
    "whp_mpa":  ("p_wh", lambda v: v * 145.038),       # MPa -> psia
    "wht_c":    ("t_wh_f", lambda v: v * 9.0/5.0 + 32), # °C -> °F
    "bhp_mpa":  ("p_res", lambda v: v * 145.038),       # MPa -> psia
    "bht_c":    ("t_res_f", lambda v: v * 9.0/5.0 + 32),# °C -> °F
    "gas_rate_m3d": ("q_gas_mscfd", lambda v: v * 0.0353147),  # m³/d -> Mscf/D
    "liquid_rate_m3d": ("q_water_bpd", lambda v: v * 6.28981), # m³/d -> bbl/D
    "depth_m":  ("depth_ft", lambda v: v * 3.28084),     # m -> ft
}

# Default values when columns are missing
_DEFAULTS = {
    "tag": None,       # Will be auto-generated if missing
    "p_wh": None,      # Required — no default
    "t_wh_f": 80.0,    # Typical surface temperature
    "gamma_g": 0.6,    # Typical gas gravity
    "tubing_id_in": 1.995,  # Standard tubing
    "q_gas_mscfd": None,    # Required — no default
    "q_water_bpd": 0.0,
    "depth_ft": None,
    "status": None,
    "p_res": None,
    "t_res_f": None,
    "liquid_sg": 1.0,
    "cond_yield": 0.0,
    "water_yield": 0.0,
}

# Reverse alias map: for each canonical name, build set of all aliases
# so JSON dicts with non-canonical keys can be resolved.
_REVERSE_ALIASES: Dict[str, set] = {}
for _canon, _aliases in _COLUMN_ALIASES.items():
    _REVERSE_ALIASES[_canon] = set(_aliases) | {_canon}


# ======================================================================
# File parsers
# ======================================================================

def _normalize_header(raw_header: str) -> str:
    """Lowercase, strip, remove non-alphanumeric (keep _), collapse underscores."""
    s = raw_header.strip().lower()
    s = s.replace(" ", "_").replace("-", "_")      # spaces/hyphens -> _
    s = s.replace("³", "3")                        # superscript 3 -> 3
    s = re.sub(r"[^a-z0-9_]+", "", s)              # strip parens, /, °, etc.
    s = re.sub(r"_+", "_", s).strip("_")            # collapse multiple _
    return s


def _map_columns(headers: List[str]) -> Dict[str, int]:
    """Map canonical field names to column indices.  Returns dict."""
    mapping = {}
    for idx, raw in enumerate(headers):
        norm = _normalize_header(raw)
        for canonical, aliases in _COLUMN_ALIASES.items():
            if norm in aliases:
                mapping[canonical] = idx
                break
    return mapping


def _safe_float(val: Any, default: float = 0.0) -> Optional[float]:
    """Try to convert to float; return default on failure."""
    if val is None:
        return default
    try:
        s = str(val).strip().replace(",", "")
        if not s:
            return default
        return float(s)
    except (ValueError, TypeError):
        return default


def _raw_get(raw: Dict[str, Any], canonical: str) -> Any:
    """Look up a value from a raw dict trying all known aliases."""
    # Try canonical name directly first
    val = raw.get(canonical)
    if val is not None:
        return val
    # Then try all aliases for this canonical name
    for alias in _REVERSE_ALIASES.get(canonical, set()):
        val = raw.get(alias)
        if val is not None:
            return val
    return None


def _parse_json(file_content: str) -> List[Dict[str, Any]]:
    """Parse JSON file content into list of well dicts."""
    data = json.loads(file_content)
    if isinstance(data, dict):
        # Could be {"wells": [...]} or single well
        if "wells" in data:
            data = data["wells"]
        else:
            data = [data]
    if not isinstance(data, list):
        raise ValueError("JSON must be a list of wells or {'wells': [...]}")
    return data


def _parse_csv(file_content: str) -> List[Dict[str, Any]]:
    """Parse CSV file content into list of well dicts."""
    reader = csv.reader(io.StringIO(file_content))
    rows = [r for r in reader if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise ValueError("CSV needs a header row plus at least one data row")

    col_map = _map_columns(rows[0])
    if "p_wh" not in col_map and "q_gas_mscfd" not in col_map:
        raise ValueError(
            "CSV must have at least 'p_wh' (or alias) and "
            "'q_gas_mscfd' (or alias) columns")

    wells = []
    for line_no, row in enumerate(rows[1:], start=2):
        well = {}
        for canonical, idx in col_map.items():
            if idx < len(row):
                well[canonical] = row[idx].strip()
        wells.append(well)
    return wells


def _parse_excel(file_content: bytes) -> List[Dict[str, Any]]:
    """Parse Excel (.xlsx) file — reads ALL sheets and combines results.

    Auto-detects header row by finding the first row where at least 2
    columns match known aliases (handles title rows, merged cells, etc.).
    """
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(file_content), read_only=True,
                                data_only=True)

    all_wells = []
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        if len(rows) < 2:
            continue

        # Find the header row: first row with >= 2 recognized columns
        header_idx = None
        for ri, row in enumerate(rows):
            headers = [str(h).strip() if h else "" for h in row]
            col_map = _map_columns(headers)
            if len(col_map) >= 2:
                header_idx = ri
                break

        if header_idx is None:
            continue  # No usable header found in this sheet

        headers = [str(h).strip() if h else "" for h in rows[header_idx]]
        col_map = _map_columns(headers)

        for row in rows[header_idx + 1:]:
            if all(v is None for v in row):
                continue
            well = {}
            for canonical, idx in col_map.items():
                if idx < len(row):
                    well[canonical] = row[idx]
            if any(v is not None for v in well.values()):
                all_wells.append(well)

    wb.close()

    if not all_wells:
        raise ValueError(
            "No well data found in any sheet — check column headers "
            "match recognized aliases (p_wh, q_gas, etc.)")
    return all_wells


def parse_file(filename: str, content: bytes) -> List[Dict[str, Any]]:
    """
    Detect format by extension and parse into list of well dicts.

    :param filename: Original filename (used for extension detection).
    :param content: Raw file bytes.
    :return: List of well dicts with raw (string) values.
    """
    lower = filename.lower()
    text = content.decode("utf-8-sig", errors="replace")

    if lower.endswith(".json"):
        return _parse_json(text)
    elif lower.endswith(".csv"):
        return _parse_csv(text)
    elif lower.endswith(".xlsx"):
        return _parse_excel(content)
    elif lower.endswith(".xls"):
        raise ValueError(
            "Legacy .xls format not supported — please save as .xlsx or .csv")
    else:
        # Try JSON first, then CSV
        try:
            return _parse_json(text)
        except (json.JSONDecodeError, ValueError):
            return _parse_csv(text)


# ======================================================================
# Well normalization
# ======================================================================

def _normalize_well(raw: Dict[str, Any], index: int) -> Dict[str, Any]:
    """Convert raw parsed dict to normalized well dict with proper types.

    Auto-detects metric units (MPa, °C, m³/d, m) via known column names
    and converts to field units (psia, °F, Mscf/D, ft).
    """
    # --- Unit conversion pass: detect metric columns and convert ---
    converted = dict(raw)
    for metric_col, (target_col, conv_fn) in _UNIT_CONVERSIONS.items():
        val = _raw_get(converted, metric_col)
        if val is not None:
            try:
                fval = float(str(val).strip().replace(",", ""))
                converted[target_col] = conv_fn(fval)
            except (ValueError, TypeError):
                pass

    tag = (converted.get("tag") or converted.get("name")
           or converted.get("well") or converted.get("well_id") or None)
    if tag is None:
        tag = "BULK-{:04d}".format(index + 1)

    # Determine liquid type from yields if available
    cond = _safe_float(_raw_get(converted, "cond_yield"), 0.0)
    water = _safe_float(_raw_get(converted, "water_yield"), 0.0)
    liquid_type = "condensate" if cond > water else "water"

    return {
        "tag": str(tag).strip(),
        "p_wh": _safe_float(_raw_get(converted, "p_wh")),
        "t_wh_f": _safe_float(_raw_get(converted, "t_wh_f"),
                              _DEFAULTS["t_wh_f"]),
        "gamma_g": _safe_float(_raw_get(converted, "gamma_g"),
                               _DEFAULTS["gamma_g"]),
        "tubing_id_in": _safe_float(_raw_get(converted, "tubing_id_in"),
                                    _DEFAULTS["tubing_id_in"]),
        "q_gas_mscfd": _safe_float(_raw_get(converted, "q_gas_mscfd")),
        "q_water_bpd": _safe_float(_raw_get(converted, "q_water_bpd"), 0.0),
        "depth_ft": _safe_float(_raw_get(converted, "depth_ft")),
        "p_res": _safe_float(_raw_get(converted, "p_res")),
        "t_res_f": _safe_float(_raw_get(converted, "t_res_f")),
        "liquid_sg": _safe_float(_raw_get(converted, "liquid_sg"), 1.0),
        "status": (str(_raw_get(converted, "status") or "").strip() or None),
        "liquid_type": liquid_type,
        "cond_yield": cond,
        "water_yield": water,
        "vsg_ms": _safe_float(_raw_get(converted, "vsg_ms")),
        "inclination_deg": _safe_float(_raw_get(converted, "inclination_deg")),
    }


def _validate_well(w: Dict[str, Any]) -> List[str]:
    """Return list of error strings for a well (empty = ok).

    Accepts:
      - (p_wh + q_gas) for pressure+rate mode
      - p_wh alone (critical rate computed, loading status unknown)
      - (vsg_ms + tubing_id) for direct velocity mode
    """
    errors = []
    has_p = w.get("p_wh") is not None and w["p_wh"] > 0
    has_q = w.get("q_gas_mscfd") is not None and w["q_gas_mscfd"] > 0
    has_vsg = w.get("vsg_ms") is not None and w["vsg_ms"] > 0
    has_tubing = w.get("tubing_id_in") is not None and w["tubing_id_in"] > 0

    if not (has_p or (has_vsg and has_tubing)):
        errors.append(
            "need either p_wh (for critical rate) or (vsg_ms + tubing_id)")
    if not has_tubing and not has_p:
        errors.append("tubing_id_in must be > 0")
    if w.get("gamma_g") is None or w["gamma_g"] <= 0:
        errors.append("gamma_g must be > 0")
    return errors


# ======================================================================
# Bulk analysis
# ======================================================================

def analyze_well(well: Dict[str, Any],
                 method: str = "turner") -> Dict[str, Any]:
    """
    Run liquid-loading analysis on a single normalized well.

    Supports two modes:
    - Pressure+rate mode: computes v_actual from P, T, q, d
    - Direct velocity mode: uses vsg_ms when available (e.g. Gao dataset)

    Returns dict with original well data + prediction fields.
    """
    p = well["p_wh"]
    t_r = (well["t_wh_f"] + 459.67) if well["t_wh_f"] else 540.0
    gg = well["gamma_g"]
    tid = well["tubing_id_in"]
    q = well["q_gas_mscfd"]
    liq_type = well["liquid_type"]
    vsg_direct = well.get("vsg_ms")  # Direct velocity in m/s (Gao etc.)

    method_fn = (turner_critical_velocity if method.lower() == "turner"
                 else coleman_critical_velocity)

    try:
        # Compute critical velocity (needs P, T, gamma_g)
        if p and p > 0:
            v_crit = method_fn(p, t_r, gg, liquid_type=liq_type)
        else:
            # No pressure data — use a placeholder for comparison
            v_crit = method_fn(1000, 540.0, gg, liquid_type=liq_type)

        # Compute actual velocity
        if vsg_direct and vsg_direct > 0:
            # Direct velocity provided (m/s -> ft/s: 1 m/s = 3.28084 ft/s)
            v_act = vsg_direct * 3.28084
        elif p and p > 0 and q and q > 0:
            v_act = actual_gas_velocity(q, p, t_r, gg, tid)
        else:
            v_act = None

        # Compute critical flow rate
        if p and p > 0:
            q_crit = minimum_flow_rate(p, t_r, gg, tid,
                                       liquid_type=liq_type, method=method)
        else:
            q_crit = None

        # Determine loading status
        if v_act is not None and v_crit:
            is_loading = v_act < v_crit
        elif q is not None and q_crit is not None:
            is_loading = q < q_crit
        else:
            is_loading = None

        margin = None
        if q is not None and q_crit is not None and q_crit > 0:
            margin = (q - q_crit) / q_crit
        elif v_act is not None and v_crit and v_crit > 0:
            margin = (v_act - v_crit) / v_crit
    except Exception as exc:
        v_crit = v_act = q_crit = None
        is_loading = None
        margin = None

    # Determine actual status classification
    actual_raw = well.get("status")
    if actual_raw:
        s = actual_raw.lower()
        if "unloaded" in s:
            actual_loaded = False
        elif "load" in s or "lu" in s:
            actual_loaded = True
        else:
            actual_loaded = None  # questionable / unknown
    else:
        actual_loaded = None

    # Compare prediction with observation
    if is_loading is not None and actual_loaded is not None:
        correct = is_loading == actual_loaded
    else:
        correct = None

    return {
        "tag": well["tag"],
        "p_wh": p,
        "t_wh_f": well["t_wh_f"],
        "gamma_g": gg,
        "tubing_id_in": tid,
        "q_gas_mscfd": q,
        "q_water_bpd": well["q_water_bpd"],
        "depth_ft": well["depth_ft"],
        "status_raw": actual_raw,
        "status_actual": ("loaded" if actual_loaded is True
                          else "unloaded" if actual_loaded is False
                          else "unknown"),
        "liquid_type": liq_type,
        "v_crit_ft_s": round(v_crit, 3) if v_crit else None,
        "v_actual_ft_s": round(v_act, 3) if v_act else None,
        "q_crit_mscfd": round(q_crit, 2) if q_crit else None,
        "is_loading": is_loading,
        "margin_pct": round(margin * 100, 1) if margin is not None else None,
        "correct": correct,
        "method": method,
    }


def bulk_analyze(raw_wells: List[Dict[str, Any]],
                 method: str = "turner") -> Dict[str, Any]:
    """
    Parse, normalize, and analyze a batch of wells.

    :param raw_wells: List of raw well dicts (from parse_file).
    :param method: 'turner' or 'coleman'.
    :return: Dict with wells (list of analysis results) + summary stats.
    """
    normalized = []
    parse_errors = []

    for i, raw in enumerate(raw_wells):
        well = _normalize_well(raw, i)
        errs = _validate_well(well)
        if errs:
            parse_errors.append({"tag": well["tag"], "errors": errs})
        else:
            normalized.append(well)

    results = []
    for well in normalized:
        result = analyze_well(well, method=method)
        results.append(result)

    # Summary statistics
    total = len(results)
    with_actual = [r for r in results if r["status_actual"] != "unknown"]
    with_prediction = [r for r in results if r["is_loading"] is not None]

    correct_predictions = [r for r in with_actual if r["correct"] is True]
    total_actual = len(with_actual)
    accuracy = (len(correct_predictions) / total_actual * 100
                if total_actual else None)

    # Breakdown by actual status
    loaded_wells = [r for r in with_actual if r["status_actual"] == "loaded"]
    unloaded_wells = [r for r in with_actual
                      if r["status_actual"] == "unloaded"]
    flagged_loaded = [r for r in loaded_wells if r["is_loading"] is True]
    flagged_unloaded = [r for r in unloaded_wells if r["is_loading"] is True]

    recall = (len(flagged_loaded) / len(loaded_wells) * 100
              if loaded_wells else None)
    false_positive = (len(flagged_unloaded) / len(unloaded_wells) * 100
                      if unloaded_wells else None)

    return {
        "wells": results,
        "summary": {
            "total_parsed": total,
            "parse_errors": len(parse_errors),
            "errors": parse_errors,
            "evaluable": total_actual,
            "accuracy_pct": round(accuracy, 1) if accuracy else None,
            "recall_pct": round(recall, 1) if recall else None,
            "false_positive_pct": (round(false_positive, 1)
                                  if false_positive is not None else None),
            "loaded_count": len(loaded_wells),
            "unloaded_count": len(unloaded_wells),
            "flagged_as_loading": len(with_prediction),
            "method": method,
        },
    }


# ======================================================================
# Export helpers
# ======================================================================

def results_to_csv(analysis: Dict[str, Any]) -> str:
    """Convert bulk analysis results to CSV string."""
    if not analysis["wells"]:
        return ""
    fields = ["tag", "p_wh", "t_wh_f", "gamma_g", "tubing_id_in",
              "q_gas_mscfd", "q_water_bpd", "depth_ft", "status_raw",
              "status_actual", "liquid_type", "v_crit_ft_s",
              "v_actual_ft_s", "q_crit_mscfd", "is_loading",
              "margin_pct", "correct", "method"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for w in analysis["wells"]:
        writer.writerow(w)
    return buf.getvalue()


def results_to_json(analysis: Dict[str, Any]) -> str:
    """Convert bulk analysis results to JSON string."""
    return json.dumps(analysis, indent=2, default=str)

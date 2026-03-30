from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import JSONResponse
import tempfile
import os
import base64
from typing import Optional, Dict, Any, List

# ✅ import your processor file
from step_processor import STEPProcessor

# OCCT props (volume) for per-solid volume
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop_VolumeProperties
from OCC.Extend.TopologyUtils import TopologyExplorer

app = FastAPI(title="STEP Geometry API (pythonocc)", version="1.0")

processor = STEPProcessor()


def _normalize_density_to_kg_per_mm3(d: Optional[float]) -> Optional[float]:
    """
    Accept density in:
      - kg/mm3  (steel: 7.85e-6, aluminum: 2.70e-6)
      - OR g/mm3 (common user input: aluminum 0.00270, steel 0.00785)
    Rule: if d > 1e-4 assume g/mm3 -> convert to kg/mm3 by /1000
    """
    if d is None:
        return None
    d = float(d)
    if d > 1e-4:
        return d / 1000.0
    return d


def _solid_volume_mm3(solid) -> float:
    props = GProp_GProps()
    brepgprop_VolumeProperties(solid, props)
    return float(props.Mass())


def _assign_outer_core_rubber(per_solid: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Deterministic 3-part assignment:
      1) outer_sleeve: candidate with (>=2 radii) and max OD
      2) core: remaining with smallest OD among those with OD
      3) rubber: remaining with max volume
    """
    # sleeve candidates: >=2 cylinder radii and OD available
    sleeve_candidates = [s for s in per_solid if s.get("OD_mm") is not None and len(s.get("cylinder_radii_mm", [])) >= 2]
    outer = max(sleeve_candidates, key=lambda x: x["OD_mm"]) if sleeve_candidates else None

    remaining = [s for s in per_solid if s is not outer]

    # core candidates: OD available
    core_candidates = [s for s in remaining if s.get("OD_mm") is not None]
    core = min(core_candidates, key=lambda x: x["OD_mm"]) if core_candidates else None

    remaining2 = [s for s in remaining if s is not core]

    # rubber: max volume among remaining
    rubber = max(remaining2, key=lambda x: x.get("volume_mm3", -1)) if remaining2 else None

    extras = [s for s in per_solid if s not in (outer, core, rubber)]

    return {"outer_sleeve": outer, "core": core, "rubber": rubber, "extra_solids": extras}


def _analyze_shape_with_components(shape, d_outer, d_core, d_rubber) -> Dict[str, Any]:

    topo = TopologyExplorer(shape)
    solids = list(topo.solids())

    per_solid: List[Dict[str, Any]] = []

    for idx, solid in enumerate(solids, start=1):

        try:
            # ---- CYLINDER DETECTION ----
            radii = processor.extract_cylinder_radii(solid, round_to=6)
        except Exception:
            radii = []

        # ---- DIMENSIONS ----
        try:
            if radii:
                dims = processor.extract_od_id_thickness(radii)
                length = processor.extract_cylinder_length(solid)
            else:
                # 🔥 FALLBACK (VERY IMPORTANT)
                bbox = processor._extract_geometric_properties(solid).get("bounding_box")

                if bbox:
                    dx = bbox["dimensions"]["length_x"]
                    dy = bbox["dimensions"]["length_y"]
                    dz = bbox["dimensions"]["length_z"]

                    dims_sorted = sorted([dx, dy, dz])

                    length = dims_sorted[2]
                    dims = {
                        "OD": dims_sorted[1],
                        "ID": None,
                        "thickness": None
                    }
                else:
                    length = None
                    dims = {"OD": None, "ID": None, "thickness": None}

        except Exception:
            length = None
            dims = {"OD": None, "ID": None, "thickness": None}

        # ---- VOLUME ----
        try:
            vol_mm3 = _solid_volume_mm3(solid)
        except Exception:
            vol_mm3 = None

        per_solid.append({
            "index": idx,
            "cylinder_radii_mm": radii,
            "OD_mm": float(dims["OD"]) if dims.get("OD") else None,
            "ID_mm": float(dims["ID"]) if dims.get("ID") else None,
            "thickness_mm": float(dims["thickness"]) if dims.get("thickness") else None,
            "length_mm": round(length, 3) if length else None,
            "volume_mm3": vol_mm3
        })

    # ---- COMPONENT ASSIGNMENT ----
    comp = _assign_outer_core_rubber(per_solid)

    # ---- WEIGHT ----
    def attach_weight(part: Optional[Dict[str, Any]], dens: Optional[float]):

        if part is None:
            return None

        if dens is None or part.get("volume_mm3") is None:
            part["weight_kg"] = None
            part["weight_requires_density"] = True
            return part

        try:
            part["weight_kg"] = float(part["volume_mm3"]) * dens
            part["weight_requires_density"] = False
        except Exception:
            part["weight_kg"] = None
            part["weight_requires_density"] = True

        return part

    comp["outer_sleeve"] = attach_weight(comp["outer_sleeve"], d_outer)
    comp["core"] = attach_weight(comp["core"], d_core)
    comp["rubber"] = attach_weight(comp["rubber"], d_rubber)

    return {
        "topology": {
            "solids": len(solids),
            "faces": topo.number_of_faces(),
            "edges": topo.number_of_edges(),
            "vertices": topo.number_of_vertices()
        },
        "per_solid": per_solid,
        "components": comp
    }


@app.post("/analyze_base64")
def analyze_base64(
    payload: dict,
    density_outer: float | None = Query(default=None, description="Outer sleeve density (kg/mm3 or g/mm3)."),
    density_core: float | None = Query(default=None, description="Core density (kg/mm3 or g/mm3)."),
    density_rubber: float | None = Query(default=None, description="Rubber density (kg/mm3 or g/mm3)."),
):
    if not processor.is_available():
        raise HTTPException(status_code=500, detail="pythonocc-core not installed / OCCT not available")

    tmp_path = None
    try:
        filename = payload.get("filename", "upload.step")
        content_b64 = payload.get("content_b64")
        if not content_b64:
            raise ValueError("content_b64 missing")

        data = base64.b64decode(content_b64)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".step") as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        shape, metadata = processor._read_step_file(tmp_path)
        geometry = processor._extract_geometric_properties(shape)

        d_outer = _normalize_density_to_kg_per_mm3(density_outer)
        d_core = _normalize_density_to_kg_per_mm3(density_core)
        d_rubber = _normalize_density_to_kg_per_mm3(density_rubber)

        components = _analyze_shape_with_components(shape, d_outer, d_core, d_rubber)

        return {
            "file": filename,
            "metadata": metadata,
            "geometry": geometry,
            **components,
            "units": {
                "length": "mm",
                "area": "square_units (depends on STEP units)",
                "volume": "mm3 (if STEP in mm)",
                "density_input": "kg/mm3 or g/mm3 (auto-normalized)",
                "weight": "kg"
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

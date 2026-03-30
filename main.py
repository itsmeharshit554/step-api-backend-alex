"""
STEP File Analysis API
FastAPI backend for processing STEP files and extracting geometric and topology data
"""

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import tempfile
import os
from typing import Dict, Any
import logging

from .step_processor import STEPProcessor

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="STEP File Analysis API",
    description="API for analyzing STEP files and extracting geometric, topology, and metadata",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize STEP processor
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
    """
    Builds per-solid + components mapping with length & weight.
    """
    topo = TopologyExplorer(shape)
    solids = list(topo.solids())

    per_solid: List[Dict[str, Any]] = []

    for idx, solid in enumerate(solids, start=1):
        radii = processor.extract_cylinder_radii(solid, round_to=6)
        dims = processor.extract_od_id_thickness(radii)  # returns OD, ID, thickness (in same units as STEP)
        length = processor.extract_cylinder_length(solid)  # ✅ you added this
        vol_mm3 = _solid_volume_mm3(solid)

        per_solid.append({
            "index": idx,
            "cylinder_radii_mm": radii,
            "OD_mm": float(dims["OD"]) if dims.get("OD") is not None else None,
            "ID_mm": float(dims["ID"]) if dims.get("ID") is not None else None,
            "thickness_mm": float(dims["thickness"]) if dims.get("thickness") is not None else None,
            "length_mm": length,
            "volume_mm3": vol_mm3
        })

    # Assign 3 components
    comp = _assign_outer_core_rubber(per_solid)

    # Attach weight using per-component density (kg/mm3)
    def attach_weight(part: Optional[Dict[str, Any]], dens: Optional[float]) -> Optional[Dict[str, Any]]:
        if part is None:
            return None
        if dens is None:
            part["weight_kg"] = None
            part["weight_requires_density"] = True
            return part
        part["weight_kg"] = float(part["volume_mm3"]) * dens
        part["weight_requires_density"] = False
        return part

    comp["outer_sleeve"] = attach_weight(comp["outer_sleeve"], d_outer)
    comp["core"] = attach_weight(comp["core"], d_core)
    comp["rubber"] = attach_weight(comp["rubber"], d_rubber)

    return {
        "status": "healthy",
        "service": "STEP File Analysis API",
        "version": "1.0.0"
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/analyze")
async def analyze(
    file: UploadFile = File(...),
    density_outer: float | None = Query(default=None, description="Outer sleeve density (kg/mm3 or g/mm3). Aluminum: 2.70e-6 kg/mm3 or 0.00270 g/mm3"),
    density_core: float | None = Query(default=None, description="Core density (kg/mm3 or g/mm3). Aluminum: 2.70e-6 kg/mm3 or 0.00270 g/mm3"),
    density_rubber: float | None = Query(default=None, description="Rubber density (kg/mm3 or g/mm3). Example: 1.20e-6 kg/mm3 or 0.00120 g/mm3"),
):
    if not processor.is_available():
        raise HTTPException(status_code=500, detail="pythonocc-core not installed / OCCT not available")

    name = (file.filename or "").lower()
    if not (name.endswith(".stp") or name.endswith(".step")):
        raise HTTPException(status_code=400, detail="Only .stp/.step files are supported.")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".step") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        shape, metadata = processor._read_step_file(tmp_path)

        # overall metrics (your existing processor method)
        geometry = processor._extract_geometric_properties(shape)

        d_outer = _normalize_density_to_kg_per_mm3(density_outer)
        d_core = _normalize_density_to_kg_per_mm3(density_core)
        d_rubber = _normalize_density_to_kg_per_mm3(density_rubber)

        components = _analyze_shape_with_components(shape, d_outer, d_core, d_rubber)

        return JSONResponse({
            "file": file.filename,
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
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass


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
        logger.error(f"Error validating file: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        if temp_file and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

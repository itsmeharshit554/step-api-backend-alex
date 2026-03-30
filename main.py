from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import JSONResponse
import tempfile
import os
import base64
from typing import List, Dict, Any, Tuple, Optional, Set

# ---- OpenCascade via OCP (cadquery-ocp) ----
from OCP.STEPControl import STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone

from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib            # static methods have _s suffix in OCP
from OCP.BRepGProp import BRepGProp              # static methods have _s suffix in OCP
from OCP.GProp import GProp_GProps

from OCP.TopExp import TopExp_Explorer
# ✅ CHANGED: add COMPSOLID + SHELL
from OCP.TopAbs import TopAbs_SOLID, TopAbs_COMPSOLID, TopAbs_SHELL, TopAbs_FACE

from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Cylinder

app = FastAPI(title="STEP Geometry API", version="2.1")

processor = STEPProcessor()


def compute_bbox(shape) -> Dict[str, float]:
    """Compute axis-aligned bounding box in mm using OCCT."""
    bbox = Bnd_Box()
    bbox.SetGap(0.0)  # avoid tolerance enlargement
    BRepBndLib.Add_s(shape, bbox, True)  # useTriangulation=True
    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    return {
        "xmin": float(xmin), "ymin": float(ymin), "zmin": float(zmin),
        "xmax": float(xmax), "ymax": float(ymax), "zmax": float(zmax),
        "length_mm": float(xmax - xmin),
        "width_mm":  float(ymax - ymin),
        "height_mm": float(zmax - zmin)
    }


def compute_geom(shape) -> Tuple[float, float]:
    """Compute volume (mm3) and area (mm2) via BRepGProp."""
    vol_props = GProp_GProps()
    area_props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, vol_props)     # props.Mass() = volume
    BRepGProp.SurfaceProperties_s(shape, area_props)   # props.Mass() = area
    return float(vol_props.Mass()), float(area_props.Mass())


# --------------------------
# Topology iteration helpers
# --------------------------
def iter_faces(shape):
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        yield exp.Current()
        exp.Next()


# ✅ ADDED: robust body iterator (SOLID -> COMPSOLID -> SHELL -> fallback to shape)
def iter_bodies(shape):
    """
    Robust body iterator:
    - SOLID first
    - then COMPSOLID
    - then SHELL
    - else whole shape
    """
    solids: List[Any] = []
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    while exp.More():
        solids.append(exp.Current())
        exp.Next()
    if solids:
        for s in solids:
            yield ("solid", s)
        return

    comps: List[Any] = []
    exp = TopExp_Explorer(shape, TopAbs_COMPSOLID)
    while exp.More():
        comps.append(exp.Current())
        exp.Next()
    if comps:
        for c in comps:
            yield ("compsolid", c)
        return

    shells: List[Any] = []
    exp = TopExp_Explorer(shape, TopAbs_SHELL)
    while exp.More():
        shells.append(exp.Current())
        exp.Next()
    if shells:
        for sh in shells:
            yield ("shell", sh)
        return

    yield ("shape", shape)


# ✅ ADDED: debug topology counts (so you see why core/sleeve were null)
def count_topology(shape) -> Dict[str, int]:
    counts = {"solids": 0, "compsolids": 0, "shells": 0, "faces": 0}

    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    while exp.More():
        counts["solids"] += 1
        exp.Next()

    exp = TopExp_Explorer(shape, TopAbs_COMPSOLID)
    while exp.More():
        counts["compsolids"] += 1
        exp.Next()

    exp = TopExp_Explorer(shape, TopAbs_SHELL)
    while exp.More():
        counts["shells"] += 1
        exp.Next()

    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        counts["faces"] += 1
        exp.Next()

    return counts


# --------------------------
# Core/Sleeve feature extraction
# --------------------------
def extract_cylinder_radii(shape, round_to: int = 6) -> List[float]:
    """Return sorted unique radii from cylindrical faces."""
    radii: Set[float] = set()
    for face in iter_faces(shape):
        adaptor = BRepAdaptor_Surface(face)
        if adaptor.GetType() == GeomAbs_Cylinder:
            r = float(adaptor.Cylinder().Radius())
            radii.add(round(r, round_to))
    return sorted(radii)


def classify_solid(solid) -> str:
    """
    Sleeve typically has 2 cylinder radii (ID+OD),
    Core typically has 1 radius (solid rod) or sometimes 2 if hollow.
    Rule: >=2 radii => sleeve else core.
    """
    radii = extract_cylinder_radii(solid, round_to=6)
    return "sleeve" if len(radii) >= 2 else "core"


def od_id_thickness_from_radii(radii: List[float]) -> Dict[str, Optional[float]]:
    if not radii:
        return {"OD_mm": None, "ID_mm": None, "thickness_mm": None}
    if len(radii) >= 2:
        r_in = min(radii)
        r_out = max(radii)
        return {
            "OD_mm": float(2.0 * r_out),
            "ID_mm": float(2.0 * r_in),
            "thickness_mm": float(r_out - r_in)
        }
    r = radii[0]
    return {"OD_mm": float(2.0 * r), "ID_mm": None, "thickness_mm": None}


def solid_length_mm(solid) -> float:
    """Use bbox max dimension as length estimate (works well for bush parts)."""
    bb = compute_bbox(solid)
    return float(max(bb["length_mm"], bb["width_mm"], bb["height_mm"]))


def solid_volume_mm3(solid) -> float:
    props = GProp_GProps()
    brepgprop_VolumeProperties(solid, props)
    return float(props.Mass())


# ✅ CHANGED: uses iter_bodies() + handles shell/shape (volume may be unavailable)
def compute_core_sleeve(shape,
                        density_core_kg_per_mm3: Optional[float] = None,
                        density_sleeve_kg_per_mm3: Optional[float] = None) -> Dict[str, Any]:
    """
    Returns:
      { "core": {...}, "sleeve": {...}, "extra_solids": [...] }
    Works even when STEP has no TopAbs_SOLID (e.g. only shells/compounds).
    """
    topo = TopologyExplorer(shape)
    solids = list(topo.solids())

    per_solid: List[Dict[str, Any]] = []

    for body_type, body in iter_bodies(shape):
        role = classify_solid(body)
        radii = extract_cylinder_radii(body, round_to=6)
        dims = od_id_thickness_from_radii(radii)
        length = solid_length_mm(body)

        # volume is reliable for solid/compsolid; shell/shape may be open => skip volume
        vol: Optional[float] = None
        if body_type in ("solid", "compsolid"):
            vol = solid_volume_mm3(body)

        density = density_core_kg_per_mm3 if role == "core" else density_sleeve_kg_per_mm3
        weight_kg = (vol * density) if (vol is not None and density is not None) else None

        payload = {
            "role": role,
            "body_type": body_type,          # "solid" | "compsolid" | "shell" | "shape"
            "length_mm": length,
            **dims,
            "cylinder_radii_mm": radii,      # debug/trace
            "volume": ({"mm3": vol, "m3": vol * 1e-9} if vol is not None else None),
            "weight_kg": weight_kg,
            "weight_requires_density": density is None,
            "volume_available": vol is not None
        }

        if role not in per_role:
            per_role[role] = payload
        else:
            # keep the one with larger volume if volume is available; else keep first
            existing_vol = per_role[role]["volume"]["mm3"] if per_role[role]["volume"] else -1
            this_vol = vol if vol is not None else -1

            if this_vol > existing_vol:
                extra_solids.append(per_role[role])
                per_role[role] = payload
            else:
                extra_solids.append(payload)

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

        shape = read_step_shape(tmp_path)
        bbox = compute_bbox(shape)
        vol_mm3, area_mm2 = compute_geom(shape)

        # ✅ ADDED: diagnostics
        topo_counts = count_topology(shape)

        core_sleeve = compute_core_sleeve(
            shape,
            density_core_kg_per_mm3=density_core_kg_per_mm3,
            density_sleeve_kg_per_mm3=density_sleeve_kg_per_mm3
        )

        return JSONResponse({
            "file": file.filename,
            "topology_counts": topo_counts,  # ✅ ADDED
            "bounding_box_mm": bbox,
            "solid_volume": {"mm3": vol_mm3, "m3": vol_mm3 * 1e-9},
            "surface_area": {"mm2": area_mm2, "m2": area_mm2 * 1e-6},
            "core": core_sleeve["core"],
            "sleeve": core_sleeve["sleeve"],
            "extra_solids": core_sleeve["extra_solids"],
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

        shape = read_step_shape(tmp_path)
        bbox = compute_bbox(shape)
        vol_mm3, area_mm2 = compute_geom(shape)

        # ✅ ADDED: diagnostics
        topo_counts = count_topology(shape)

        core_sleeve = compute_core_sleeve(
            shape,
            density_core_kg_per_mm3=density_core_kg_per_mm3,
            density_sleeve_kg_per_mm3=density_sleeve_kg_per_mm3
        )

        return {
            "file": filename,
            "topology_counts": topo_counts,  # ✅ ADDED
            "bounding_box_mm": bbox,
            "solid_volume": {"mm3": vol_mm3, "m3": vol_mm3 * 1e-9},
            "surface_area": {"mm2": area_mm2, "m2": area_mm2 * 1e-6},
            "core": core_sleeve["core"],
            "sleeve": core_sleeve["sleeve"],
            "extra_solids": core_sleeve["extra_solids"],
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

# main.py
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import tempfile
import os

# ---- OpenCascade via OCP (cadquery-ocp) ----
from OCP.STEPControl import STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib            # static methods have _s suffix in OCP
from OCP.BRepGProp import BRepGProp              # static methods have _s suffix in OCP
from OCP.GProp import GProp_GProps


app = FastAPI(title="STEP Geometry API", version="1.0")


def read_step_shape(path: str):
    """Read a STEP file and return a TopoDS_Shape."""
    reader = STEPControl_Reader()
    status = reader.ReadFile(path)
    if status != IFSelect_RetDone:
        raise ValueError("Failed to read STEP file (IFSelect_RetDone not returned).")
    if not reader.TransferRoots():
        raise ValueError("STEP transfer failed.")
    # OneShape() returns the unified shape of all transferred roots
    return reader.OneShape()


def compute_bbox(shape):
    """Compute axis-aligned bounding box in mm using OCCT."""
    bbox = Bnd_Box()
    bbox.SetGap(0.0)  # avoid tolerance enlargement
    # In OCP, static OCCT methods are exposed with the `_s` suffix.
    BRepBndLib.Add_s(shape, bbox, True)  # useTriangulation=True
    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    return {
        "xmin": xmin, "ymin": ymin, "zmin": zmin,
        "xmax": xmax, "ymax": ymax, "zmax": zmax,
        "length_mm": xmax - xmin,
        "width_mm":  ymax - ymin,
        "height_mm": zmax - zmin
    }


def compute_geom(shape):
    """Compute volume (mm3) and area (mm2) via BRepGProp."""
    vol_props = GProp_GProps()
    area_props = GProp_GProps()

    # Static methods in OCP use `_s` suffix
    BRepGProp.VolumeProperties_s(shape, vol_props)     # returns mm^3 in props.Mass()
    BRepGProp.SurfaceProperties_s(shape, area_props)   # returns mm^2 in props.Mass()

    vol_mm3 = vol_props.Mass()
    area_mm2 = area_props.Mass()
    return vol_mm3, area_mm2


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    # Basic validation
    name = (file.filename or "").lower()
    if not (name.endswith(".stp") or name.endswith(".step")):
        raise HTTPException(status_code=400, detail="Only .stp/.step files are supported.")

    # Persist to a temp file so OCCT can read it from disk
    with tempfile.NamedTemporaryFile(delete=False, suffix=".step") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        shape = read_step_shape(tmp_path)
        bbox = compute_bbox(shape)
        vol_mm3, area_mm2 = compute_geom(shape)

        # Also return SI units for convenience
        result = {
            "file": file.filename,
            "bounding_box_mm": bbox,
            "solid_volume": {"mm3": vol_mm3, "m3": vol_mm3 * 1e-9},
            "surface_area": {"mm2": area_mm2, "m2": area_mm2 * 1e-6},
            "units": {"length": "mm", "area": "mm2/m2", "volume": "mm3/m3"}
        }
        return JSONResponse(result)

    except Exception as e:
        # Bubble up as 500
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Best-effort cleanup
        try:
            os.remove(tmp_path)
        except Exception:
            pass

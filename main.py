from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import tempfile, os

# ---- OpenCascade via OCP (cadquery-ocp) ----
from OCP.STEPControl import STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib               # <- class with static methods
from OCP.BRepGProp import BRepGProp                 # <- static VolumeProperties/SurfaceProperties
from OCP.GProp import GProp_GProps

app = FastAPI(title="STEP Geometry API", version="1.0")

def read_step_shape(path: str):
    reader = STEPControl_Reader()
    status = reader.ReadFile(path)
    if status != IFSelect_RetDone:
        raise ValueError("Failed to read STEP file.")
    if not reader.TransferRoots():
        raise ValueError("STEP transfer failed.")
    return reader.OneShape()

def compute_bbox(shape):
    bbox = Bnd_Box()
    bbox.SetGap(0.0)
    # In OCP use the static method 'Add', not 'brepbndlib_Add'
    BRepBndLib.Add(shape, bbox, True)   # useTriangulation=True
    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    return {
        "xmin": xmin, "ymin": ymin, "zmin": zmin,
        "xmax": xmax, "ymax": ymax, "zmax": zmax,
        "length_mm": xmax - xmin,
        "width_mm":  ymax - ymin,
        "height_mm": zmax - zmin
    }

def compute_geom(shape):
    vol_props = GProp_GProps()
    area_props = GProp_GProps()
    # Static calls per OCCT/OCP API
    BRepGProp.VolumeProperties(shape, vol_props)      # mm^3
    BRepGProp.SurfaceProperties(shape, area_props)    # mm^2
    vol_mm3 = vol_props.Mass()
    area_mm2 = area_props.Mass()
    return vol_mm3, area_mm2

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    name = (file.filename or "").lower()
    if not (name.endswith(".stp") or name.endswith(".step")):
        raise HTTPException(status_code=400, detail="Only .stp/.step files are supported.")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".step") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        shape = read_step_shape(tmp_path)
        bbox = compute_bbox(shape)
        vol_mm3, area_mm2 = compute_geom(shape)
        return JSONResponse({
            "file": file.filename,
            "bounding_box_mm": bbox,
            "solid_volume": {"mm3": vol_mm3, "m3": vol_mm3 * 1e-9},
            "surface_area": {"mm2": area_mm2, "m2": area_mm2 * 1e-6},
            "units": {"length": "mm", "area": "mm2/m2", "volume": "mm3/m3"}
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try: os.remove(tmp_path)
        except: pass

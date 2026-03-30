# main.py
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import tempfile
import os
import base64
import binascii

# ---- OpenCascade via OCP (cadquery-ocp) ----
from OCP.STEPControl import STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps

app = FastAPI(title="STEP Geometry API", version="1.2")


# --------------------------
# Core OCCT helper routines
# --------------------------

from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Cylinder

def extract_cylinder_radii(shape):
    radii = set()

    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        face = exp.Current()
        exp.Next()

        adaptor = BRepAdaptor_Surface(face)
        if adaptor.GetType() == GeomAbs_Cylinder:
            r = adaptor.Cylinder().Radius()
            radii.add(round(float(r), 5))

    return sorted(list(radii))

def extract_od_id_thickness(radii):
    if not radii:
        return {"OD": None, "ID": None, "thickness": None}

    if len(radii) >= 2:
        r_in = min(radii)
        r_out = max(radii)
        return {
            "OD": 2 * r_out,
            "ID": 2 * r_in,
            "thickness": r_out - r_in
        }

    r = radii[0]
    return {"OD": 2 * r, "ID": None, "thickness": None}


from OCP.TopAbs import TopAbs_SOLID

def extract_parts(shape):
    parts = []

    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    idx = 1

    while exp.More():
        solid = exp.Current()
        exp.Next()

        # Bounding box → length
        bbox = Bnd_Box()
        bbox.SetGap(0.0)
        BRepBndLib.Add_s(solid, bbox, True)
        xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()

        dx = xmax - xmin
        dy = ymax - ymin
        dz = zmax - zmin
        length = round(max(dx, dy, dz), 3)

        # Volume
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(solid, props)
        volume = props.Mass()

        # Radii + dims
        radii = extract_cylinder_radii(solid)
        dims = extract_od_id_thickness(radii)

        parts.append({
            "part_index": idx,
            "OD_mm": dims["OD"],
            "ID_mm": dims["ID"],
            "thickness_mm": dims["thickness"],
            "length_mm": length,
            "volume_mm3": volume,
            "radii": radii
        })

        idx += 1

    return parts

def read_step_shape(path: str):
    """Read a STEP file and return a TopoDS_Shape."""
    reader = STEPControl_Reader()
    status = reader.ReadFile(path)  # must return IFSelect_RetDone for success [1](https://www.desmos.com/api/geometry)
    if status != IFSelect_RetDone:
        raise ValueError("Failed to read STEP file (IFSelect_RetDone not returned).")
    if not reader.TransferRoots():
        raise ValueError("STEP transfer failed.")
    return reader.OneShape()


def compute_bbox(shape):
    bbox = Bnd_Box()
    bbox.SetGap(0.0)
    BRepBndLib.Add_s(shape, bbox, True)
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
    BRepGProp.VolumeProperties_s(shape, vol_props)
    BRepGProp.SurfaceProperties_s(shape, area_props)
    return vol_props.Mass(), area_props.Mass()


# --------------------------
# Request model (Swagger will show correct fields)
# --------------------------
class AnalyzeBase64Request(BaseModel):
    filename: str
    content_b64: str


# --------------------------
# Base64 utilities (handles PA + Swagger)
# --------------------------
def normalize_b64(b64: str) -> str:
    s = b64.strip()

    # If someone sends data URI, strip prefix:
    # data:application/octet-stream;base64,AAA...
    if s.lower().startswith("data:") and "," in s:
        s = s.split(",", 1)[1]

    # remove whitespace/newlines
    s = "".join(s.split())

    # fix padding
    pad = len(s) % 4
    if pad != 0:
        s += "=" * (4 - pad)

    return s


def decode_b64(b64: str) -> bytes:
    s = normalize_b64(b64)
    try:
        return base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError) as e:
        raise HTTPException(
            status_code=400,
            detail=f"content_b64 is not valid base64: {str(e)}"
        )


def assert_step_signature(data: bytes):
    head = data.lstrip()[:200]
    if b"ISO-10303-21" not in head:
        raise HTTPException(
            status_code=400,
            detail="Decoded bytes do not look like a STEP Part 21 file "
                   "(missing 'ISO-10303-21' near start). "
                   "Most common causes: placeholder text, Power Automate expressions sent to Swagger, "
                   "or base64 truncated."
        )


@app.get("/health")
def health():
    return {"status": "ok"}


# --------------------------
# Multipart endpoint (for Postman/clients)
# --------------------------
@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    name = (file.filename or "").lower()
    if not (name.endswith(".stp") or name.endswith(".step")):
        raise HTTPException(status_code=400, detail="Only .stp/.step files supported.")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".step") as tmp:
            tmp_path = tmp.name
            # stream to disk
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                tmp.write(chunk)

        shape = read_step_shape(tmp_path)
        bbox = compute_bbox(shape)
        vol_mm3, area_mm2 = compute_geom(shape)
        parts = extract_parts(shape)

        return JSONResponse({
            "file": file.filename,
            "bounding_box_mm": bbox,
            "solid_volume": {"mm3": vol_mm3, "m3": vol_mm3 * 1e-9},
            "surface_area": {"mm2": area_mm2, "m2": area_mm2 * 1e-6},
            "parts": parts,
            "units": {"length": "mm", "area": "mm2/m2", "volume": "mm3/m3"}
        })

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass


# --------------------------
# JSON base64 endpoint (Power Automate)
# --------------------------
@app.post("/analyze_base64")
def analyze_base64(req: AnalyzeBase64Request):
    tmp_path = None
    try:
        if not req.filename.lower().endswith((".stp", ".step")):
            raise HTTPException(status_code=400, detail="filename must end with .stp or .step")

        data = decode_b64(req.content_b64)
        assert_step_signature(data)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".step") as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        shape = read_step_shape(tmp_path)  # IFSelect_RetDone must be returned for success [1](https://www.desmos.com/api/geometry)
        bbox = compute_bbox(shape)
        vol_mm3, area_mm2 = compute_geom(shape)
        parts = extract_parts(shape)
        return {
            "parts": parts,
            "file": req.filename,
            "bounding_box_mm": bbox,
            "solid_volume": {"mm3": vol_mm3, "m3": vol_mm3 * 1e-9},
            "surface_area": {"mm2": area_mm2, "m2": area_mm2 * 1e-6},
            "units": {"length": "mm", "area": "mm2/m2", "volume": "mm3/m3"}
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

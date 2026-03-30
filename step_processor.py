import logging
from typing import Dict, Any, List, Tuple, Set
import os
import math

from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_FACE
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop_VolumeProperties
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib_Add
from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
from OCC.Core.GeomAbs import GeomAbs_Cylinder
from OCC.Extend.TopologyUtils import TopologyExplorer

logger = logging.getLogger(__name__)


class STEPProcessor:

    def _read_step_file(self, file_path: str):
        reader = STEPControl_Reader()
        status = reader.ReadFile(file_path)

        if status != IFSelect_RetDone:
            raise ValueError("STEP file read failed")

        reader.TransferRoots()
        shape = reader.OneShape()

        return shape

    # -----------------------------
    # CYLINDER RADII
    # -----------------------------
    def extract_cylinder_radii(self, shape, round_to=6) -> List[float]:
        radii = set()

        exp = TopExp_Explorer(shape, TopAbs_FACE)

        while exp.More():
            face = exp.Current()
            exp.Next()

            adaptor = BRepAdaptor_Surface(face)

            try:
                if adaptor.GetType() == GeomAbs_Cylinder:
                    r = float(adaptor.Cylinder().Radius())
                    radii.add(round(r, round_to))
            except:
                continue

        return sorted(radii)

    # -----------------------------
    # CYLINDER DETAILS
    # -----------------------------
    def extract_cylinders(self, shape, round_to=6):
        cylinders = []

        exp = TopExp_Explorer(shape, TopAbs_FACE)

        while exp.More():
            face = exp.Current()
            exp.Next()

            adaptor = BRepAdaptor_Surface(face)

            try:
                if adaptor.GetType() == GeomAbs_Cylinder:
                    cyl = adaptor.Cylinder()
                    ax = cyl.Axis()

                    loc = ax.Location()
                    direc = ax.Direction()

                    cylinders.append({
                        "radius": round(float(cyl.Radius()), round_to),
                        "axis_dir": (direc.X(), direc.Y(), direc.Z()),
                        "axis_loc": (loc.X(), loc.Y(), loc.Z())
                    })
            except:
                continue

        return cylinders

    # -----------------------------
    # OD / ID / THICKNESS
    # -----------------------------
    def extract_od_id_thickness(self, radii):
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

    # -----------------------------
    # FALLBACK (BOUNDING BOX)
    # -----------------------------
    def fallback_dimensions(self, shape):
        bbox = Bnd_Box()
        brepbndlib_Add(shape, bbox)

        xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()

        dx = xmax - xmin
        dy = ymax - ymin
        dz = zmax - zmin

        dims = sorted([dx, dy, dz])

        return {
            "length": dims[2],
            "OD": dims[1]
        }

    # -----------------------------
    # LENGTH
    # -----------------------------
    def extract_length(self, shape):

        cylinders = self.extract_cylinders(shape)

        if not cylinders:
            return self.fallback_dimensions(shape)["length"]

        cyl = max(cylinders, key=lambda c: c["radius"])

        dx, dy, dz = cyl["axis_dir"]
        mag = math.sqrt(dx*dx + dy*dy + dz*dz)

        ux, uy, uz = dx/mag, dy/mag, dz/mag

        bbox = Bnd_Box()
        brepbndlib_Add(shape, bbox)

        xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()

        corners = [
            (xmin, ymin, zmin), (xmin, ymin, zmax),
            (xmin, ymax, zmin), (xmin, ymax, zmax),
            (xmax, ymin, zmin), (xmax, ymin, zmax),
            (xmax, ymax, zmin), (xmax, ymax, zmax),
        ]

        proj = [x*ux + y*uy + z*uz for x, y, z in corners]

        return max(proj) - min(proj)

    # -----------------------------
    # WEIGHT
    # -----------------------------
    def extract_weight(self, shape, density):

        props = GProp_GProps()
        brepgprop_VolumeProperties(shape, props)

        volume = props.Mass()
        return volume * density

    # -----------------------------
    # CLASSIFY CORE / SLEEVE
    # -----------------------------
    def classify(self, radii):

        if len(radii) >= 2:
            return "sleeve"
        return "core"

    # -----------------------------
    # MAIN FUNCTION
    # -----------------------------
    def extract_all_parameters(self, file_path: str, density: float):

        shape = self._read_step_file(file_path)
        explorer = TopologyExplorer(shape)

        results = []

        for solid in explorer.solids():

            radii = self.extract_cylinder_radii(solid)

            # ---- DIMENSIONS ----
            if radii:
                dims = self.extract_od_id_thickness(radii)
                length = self.extract_length(solid)
            else:
                fallback = self.fallback_dimensions(solid)

                dims = {
                    "OD": fallback["OD"],
                    "ID": None,
                    "thickness": None
                }
                length = fallback["length"]

            # ---- WEIGHT ----
            try:
                weight = self.extract_weight(solid, density)
            except:
                weight = None

            results.append({
                "role": self.classify(radii),
                "length": round(length, 3) if length else None,
                "OD": round(dims["OD"], 3) if dims["OD"] else None,
                "ID": round(dims["ID"], 3) if dims["ID"] else None,
                "thickness": round(dims["thickness"], 3) if dims["thickness"] else None,
                "weight": round(weight, 6) if weight else None,
                "radii_detected": radii
            })

        return {
            "total_parts": len(results),
            "parts": results
        }
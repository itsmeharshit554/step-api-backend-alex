import logging
from typing import Dict, Any, List, Tuple, Set
import os

<<<<<<< HEAD
try:
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.IFSelect import IFSelect_RetDone
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import (
        TopAbs_SOLID, TopAbs_SHELL, TopAbs_FACE, 
        TopAbs_EDGE, TopAbs_VERTEX, TopAbs_COMPOUND
    )
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.BRepGProp import (
        brepgprop_VolumeProperties,
        brepgprop_SurfaceProperties,
        brepgprop_LinearProperties
    )
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepBndLib import brepbndlib_Add
    from OCC.Core.BRepCheck import BRepCheck_Analyzer
    from OCC.Core.TopoDS import TopoDS_Shape, TopoDS_Compound
    from OCC.Core.TopTools import TopTools_IndexedMapOfShape
    from OCC.Core.TopExp import topexp
    from OCC.Extend.TopologyUtils import TopologyExplorer
    from OCC.Core.STEPCAFControl import STEPCAFControl_Reader
    from OCC.Core.TDocStd import TDocStd_Document
    from OCC.Core.XCAFDoc import (
        XCAFDoc_DocumentTool_ShapeTool,
        XCAFDoc_DocumentTool_ColorTool,
        XCAFDoc_DocumentTool_LayerTool,
        XCAFDoc_DocumentTool_MaterialTool
    )
    from OCC.Core.TCollection import TCollection_ExtendedString
    from OCC.Core.TDF import TDF_LabelSequence
    
    OCCT_AVAILABLE = True
except ImportError:
    OCCT_AVAILABLE = False
=======
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
>>>>>>> parent of 2ae2505 (Changes to main and stp_processor)

logger = logging.getLogger(__name__)


class STEPProcessor:

    def _read_step_file(self, file_path: str):
        reader = STEPControl_Reader()
        status = reader.ReadFile(file_path)

        if status != IFSelect_RetDone:
<<<<<<< HEAD
            raise ValueError(f"Failed to read STEP file: {file_path}")
        
        # Transfer roots
        step_reader.PrintCheckLoad(False, IFSelect_RetDone)
        nb_roots = step_reader.NbRootsForTransfer()
        step_reader.PrintCheckTransfer(False, IFSelect_RetDone)
        
        logger.info(f"Found {nb_roots} roots in STEP file")
        
        # Transfer all roots
        step_reader.TransferRoots()
        shape = step_reader.OneShape()
        
        # Extract basic metadata
        metadata = {
            "nb_roots": nb_roots,
            "transfer_status": "success"
        }
        
        return shape, metadata
    
    def _extract_geometric_properties(self, shape: TopoDS_Shape) -> Dict[str, Any]:
        """
        Extract geometric properties (volume, surface area, bounding box)
        
        Args:
            shape: TopoDS_Shape to analyze
            
        Returns:
            Dictionary with geometric properties
        """
        properties = {}
        
        # Volume calculation
        try:
            props = GProp_GProps()
            brepgprop_VolumeProperties(shape, props)
            volume = props.Mass()
            center_of_mass = props.CentreOfMass()
            
            properties["volume"] = {
                "value": volume,
                "unit": "cubic_units"
            }
            properties["center_of_mass"] = {
                "x": center_of_mass.X(),
                "y": center_of_mass.Y(),
                "z": center_of_mass.Z()
            }
        except Exception as e:
            logger.warning(f"Could not calculate volume: {e}")
            properties["volume"] = None
        
        # Surface area calculation
        try:
            props = GProp_GProps()
            brepgprop_SurfaceProperties(shape, props)
            surface_area = props.Mass()
            
            properties["surface_area"] = {
                "value": surface_area,
                "unit": "square_units"
            }
        except Exception as e:
            logger.warning(f"Could not calculate surface area: {e}")
            properties["surface_area"] = None
        
        # Bounding box
        try:
            bbox = Bnd_Box()
            brepbndlib_Add(shape, bbox)
            
            xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
            
            properties["bounding_box"] = {
                "min": {"x": xmin, "y": ymin, "z": zmin},
                "max": {"x": xmax, "y": ymax, "z": zmax},
                "dimensions": {
                    "length_x": xmax - xmin,
                    "length_y": ymax - ymin,
                    "length_z": zmax - zmin
                }
            }
        except Exception as e:
            logger.warning(f"Could not calculate bounding box: {e}")
            properties["bounding_box"] = None
        
        return properties
    
    def _extract_topology_info(self, shape: TopoDS_Shape) -> Dict[str, Any]:
        """
        Extract topology information (counts of solids, faces, edges, vertices)
        
        Args:
            shape: TopoDS_Shape to analyze
            
        Returns:
            Dictionary with topology counts
        """
        topology = {
            "solids": 0,
            "compounds": 0,
            "shells": 0,
            "faces": 0,
            "edges": 0,
            "vertices": 0
        }
        
        # Count topology elements
        explorer = TopologyExplorer(shape)
        
        topology["solids"] = explorer.number_of_solids()
        topology["compounds"] = explorer.number_of_compounds()
        topology["shells"] = explorer.number_of_shells()
        topology["faces"] = explorer.number_of_faces()
        topology["edges"] = explorer.number_of_edges()
        topology["vertices"] = explorer.number_of_vertices()
        
        # Additional details
        topology["details"] = {
            "has_free_edges": len(list(explorer.edges())) != topology["edges"],
            "shape_type": shape.ShapeType()
        }
        
        return topology
    
    def _validate_shape(self, shape: TopoDS_Shape) -> Dict[str, Any]:
        """
        Validate shape quality and check for issues
        
        Args:
            shape: TopoDS_Shape to validate
            
        Returns:
            Dictionary with validation results
        """
        validation = {
            "is_valid": False,
            "is_done": False,
            "issues": []
        }
        
        try:
            analyzer = BRepCheck_Analyzer(shape)
            validation["is_valid"] = analyzer.IsValid()
            
            if not validation["is_valid"]:
                # The shape has issues
                validation["issues"].append("Shape contains geometric or topological errors")
            
            validation["is_done"] = True
            
        except Exception as e:
            logger.error(f"Validation error: {e}")
            validation["issues"].append(f"Validation failed: {str(e)}")
        
        # Additional quality checks
        try:
            explorer = TopologyExplorer(shape)
            
            # Check for degenerate edges
            degenerate_count = 0
            for edge in explorer.edges():
                if edge.Degenerated():
                    degenerate_count += 1
            
            if degenerate_count > 0:
                validation["issues"].append(f"Found {degenerate_count} degenerate edges")
            
            validation["quality_metrics"] = {
                "degenerate_edges": degenerate_count,
                "total_edges": explorer.number_of_edges()
            }
            
        except Exception as e:
            logger.warning(f"Quality check error: {e}")
        
        return validation
    
    def _extract_assembly_structure(self, file_path: str) -> Dict[str, Any]:
        """
        Extract assembly structure and metadata using XCAF
        
        Args:
            file_path: Path to STEP file
            
        Returns:
            Dictionary with assembly information
        """
        assembly_info = {
            "is_assembly": False,
            "parts": [],
            "layers": [],
            "colors": []
        }
        
        try:
            # Create XCAF document
            doc = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
            
            # Read STEP file with XCAF
            reader = STEPCAFControl_Reader()
            reader.SetColorMode(True)
            reader.SetLayerMode(True)
            reader.SetNameMode(True)
            
            status = reader.ReadFile(file_path)
            
            if status == IFSelect_RetDone:
                reader.Transfer(doc)
                
                # Get shape tool
                shape_tool = XCAFDoc_DocumentTool_ShapeTool(doc.Main())
                
                # Get free shapes (top-level components)
                labels = TDF_LabelSequence()
                shape_tool.GetFreeShapes(labels)
                
                assembly_info["is_assembly"] = labels.Length() > 1
                assembly_info["part_count"] = labels.Length()
                
                # Extract part names if available
                parts = []
                for i in range(1, labels.Length() + 1):
                    label = labels.Value(i)
                    name = label.EntryDumpToString()
                    
                    # Try to get actual name
                    # Note: Name extraction can be complex, this is simplified
                    parts.append({
                        "label": name,
                        "index": i
                    })
                
                assembly_info["parts"] = parts
                
        except Exception as e:
            logger.warning(f"Could not extract assembly structure: {e}")
            assembly_info["error"] = str(e)
        
        return assembly_info
=======
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
>>>>>>> parent of 2ae2505 (Changes to main and stp_processor)

"""
STEP File Processor using Open CASCADE Technology (OCCT)
Handles reading, analysis, and extraction of data from STEP files
"""

import logging
from typing import Dict, Any, List, Tuple
import os
import math

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
    
    from typing import Dict, Any, List, Tuple, Set

    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.GeomAbs import GeomAbs_Cylinder
    from OCC.Core.BRepBndLib import brepbndlib_Add
    from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
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

logger = logging.getLogger(__name__)


class STEPProcessor:
    """Process STEP files and extract various data points"""
    
    def __init__(self):
        """Initialize the STEP processor"""
        if not OCCT_AVAILABLE:
            logger.warning("pythonocc-core not available. Install it for STEP processing.")
        self.occt_available = OCCT_AVAILABLE
    
    def is_available(self) -> bool:
        """Check if OCCT is available"""
        return self.occt_available
    
    def analyze_file(self, file_path: str) -> Dict[str, Any]:
        """
        Comprehensive analysis of STEP file
        
        Args:
            file_path: Path to STEP file
            
        Returns:
            Dictionary with all analysis results
        """
        if not self.occt_available:
            raise RuntimeError("pythonocc-core not installed")
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Read the STEP file
        shape, metadata = self._read_step_file(file_path)
        
        # Gather all data
        result = {
            "file_info": {
                "file_size_bytes": os.path.getsize(file_path),
                "file_path": os.path.basename(file_path)
            },
            "metadata": metadata,
            "geometry": self._extract_geometric_properties(shape),
            "topology": self._extract_topology_info(shape),
            "validation": self._validate_shape(shape),
            "assembly": self._extract_assembly_structure(file_path)
        }
        
        return result
    
    def get_geometric_properties(self, file_path: str) -> Dict[str, Any]:
        """Extract only geometric properties"""
        shape, _ = self._read_step_file(file_path)
        return self._extract_geometric_properties(shape)
    
    def get_topology_info(self, file_path: str) -> Dict[str, Any]:
        """Extract only topology information"""
        shape, _ = self._read_step_file(file_path)
        return self._extract_topology_info(shape)
    
    def validate_file(self, file_path: str) -> Dict[str, Any]:
        """Validate STEP file"""
        shape, _ = self._read_step_file(file_path)
        return self._validate_shape(shape)
    
    def _read_step_file(self, file_path: str) -> Tuple[TopoDS_Shape, Dict[str, Any]]:
        """
        Read STEP file and return shape and metadata
        
        Args:
            file_path: Path to STEP file
            
        Returns:
            Tuple of (shape, metadata)
        """
        step_reader = STEPControl_Reader()
        status = step_reader.ReadFile(file_path)
        
        if status != IFSelect_RetDone:
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
    
    
    def extract_cylinder_radii(self, shape: TopoDS_Shape, round_to: int = 6) -> List[float]:
        
        """
        Return unique cylinder radii found on cylindrical faces of the given shape/solid.
        Radii are returned sorted ascending.
        """
        radii: Set[float] = set()

        exp = TopExp_Explorer(shape, TopAbs_FACE)
        while exp.More():
            face = exp.Current()
            exp.Next()

            adaptor = BRepAdaptor_Surface(face)
            if adaptor.GetType() == GeomAbs_Cylinder:
                r = float(adaptor.Cylinder().Radius())
                radii.add(round(r, round_to))

        return sorted(radii)


    # -----------------------------
    # 2) Extract cylinders (richer output: radius + axis)
    # -----------------------------
    def extract_cylinders(self, shape: TopoDS_Shape, round_to: int = 6) -> List[Dict[str, Any]]:
        """
        Returns cylinder features: radius + axis direction + axis location.
        Useful if you later want coaxial grouping.
        """
        out: List[Dict[str, Any]] = []

        exp = TopExp_Explorer(shape, TopAbs_FACE)
        while exp.More():
            face = exp.Current()
            exp.Next()

            adaptor = BRepAdaptor_Surface(face)
            if adaptor.GetType() == GeomAbs_Cylinder: 
                cyl = adaptor.Cylinder()
                ax = cyl.Axis()
                loc = ax.Location()
                direc = ax.Direction()

                out.append({
                    "radius": round(float(cyl.Radius()), round_to),
                    "axis_dir": (
                        round(float(direc.X()), round_to),
                        round(float(direc.Y()), round_to),
                        round(float(direc.Z()), round_to),
                    ),
                    "axis_loc": (
                        round(float(loc.X()), round_to),
                        round(float(loc.Y()), round_to),
                        round(float(loc.Z()), round_to),
                    ),
                })

        return out



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
            bbox.SetGap(0.0)
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
    
    
    def _classify_solid(self, solid: TopoDS_Shape) -> str:
        
        """
        Classify solid as 'core' or 'sleeve' based on number of unique cylinder radii.

        Rule (for bush-like parts):
          - sleeve (hollow) typically has 2 radii (ID + OD)
          - core (solid rod) typically has 1 radius
        """
        radii = self.extract_cylinder_radii(solid, round_to=6)
        return "sleeve" if len(radii) >= 2 else "core"

    
    
    def extract_od_id_thickness(self, radii: List[float]) -> Dict[str, Any]:
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


    
    def extract_cylinder_length(self, shape: TopoDS_Shape, round_to: int = 3) -> float:
        """
        Estimate cylinder length by projecting bounding box along cylinder axis.
        Works for bush / rod type parts.
        """

        cylinders = self.extract_cylinders(shape, round_to=6)
        if not cylinders:
            return None

        # Take dominant cylinder (largest radius)
        cyl = max(cylinders, key=lambda c: c["radius"])

        # Axis direction
        dx, dy, dz = cyl["axis_dir"]
        axis_len = math.sqrt(dx*dx + dy*dy + dz*dz)
        ux, uy, uz = dx/axis_len, dy/axis_len, dz/axis_len

        # Bounding box
        bbox = Bnd_Box()
        brepbndlib_Add(shape, bbox)
        xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()

        corners = [
            (xmin, ymin, zmin), (xmin, ymin, zmax),
            (xmin, ymax, zmin), (xmin, ymax, zmax),
            (xmax, ymin, zmin), (xmax, ymin, zmax),
            (xmax, ymax, zmin), (xmax, ymax, zmax),
        ]

        projections = [
            x*ux + y*uy + z*uz for x, y, z in corners
        ]

        length = max(projections) - min(projections)
        return round(length, round_to)

    
    def extract_weight(self, shape: TopoDS_Shape, density: float, round_to: int = 3) -> float:
        """
        Compute weight from STEP volume and provided density.

        density:
            kg/mm3  → if STEP is in mm
            kg/m3   → if STEP is in meters
        """

        props = GProp_GProps()
        brepgprop_VolumeProperties(shape, props)
        volume = props.Mass()

        weight = volume * density
        return round(weight, round_to)

    
    def extract_length_and_weight(
        self,
        file_path: str,
        density: float
    ) -> Dict[str, Any]:

        shape, _ = self._read_step_file(file_path)

        return {
            "length": self.extract_cylinder_length(shape),
            "weight": self.extract_weight(shape, density),
        }

    
    


    
    def _validate_shape(self, shape: TopoDS_Shape) -> Dict[str, Any]:
        validation = {
            "is_valid": False,
            "is_done": False,
            "issues": []
        }

        try:
            analyzer = BRepCheck_Analyzer(shape)
            validation["is_valid"] = analyzer.IsValid()

            if not validation["is_valid"]:
                validation["issues"].append("Shape contains geometric or topological errors")

            validation["is_done"] = True

        except Exception as e:
            logger.error(f"Validation error: {e}")
            validation["issues"].append(f"Validation failed: {str(e)}")

        # ---- Per-solid validation ----
        validation["per_solid"] = []
        try:
            explorer = TopologyExplorer(shape)
            for solid in explorer.solids():
                role = self._classify_solid(solid)
                solid_analyzer = BRepCheck_Analyzer(solid)

                validation["per_solid"].append({
                    "role": role,
                    "is_valid": solid_analyzer.IsValid()
                })
        except Exception as e:
            logger.warning(f"Per-solid validation error: {e}")

        # ---- Degenerate edges ----
        try:
            explorer = TopologyExplorer(shape)
            degenerate_count = sum(1 for e in explorer.edges() if e.Degenerated())

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
            "part_count": 0,
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

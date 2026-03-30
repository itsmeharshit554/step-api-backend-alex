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


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "STEP File Analysis API",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """Detailed health check"""
    return {
        "status": "healthy",
        "occt_available": processor.is_available(),
        "supported_formats": ["STEP", "STP"]
    }


@app.post("/analyze")
async def analyze_step_file(file: UploadFile = File(...)) -> Dict[str, Any]:
    """
    Analyze a STEP file and return comprehensive data
    
    Args:
        file: Uploaded STEP file (.step or .stp)
    
    Returns:
        JSON with geometric properties, topology, metadata, and validation results
    """
    # Validate file extension
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in ['.step', '.stp']:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Expected .step or .stp, got {file_ext}"
        )
    
    # Create temporary file to save upload
    temp_file = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_file_path = temp_file.name
        
        logger.info(f"Processing file: {file.filename} ({len(content)} bytes)")
        
        # Process the STEP file
        result = processor.analyze_file(temp_file_path)
        
        # Add original filename to result
        result["file_info"]["original_filename"] = file.filename
        
        return result
        
    except Exception as e:
        logger.error(f"Error processing file: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error processing STEP file: {str(e)}"
        )
    
    finally:
        # Clean up temporary file
        if temp_file and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except Exception as e:
                logger.warning(f"Failed to delete temp file: {e}")


@app.post("/analyze/geometry")
async def analyze_geometry_only(file: UploadFile = File(...)) -> Dict[str, Any]:
    """
    Extract only geometric properties from STEP file
    
    Args:
        file: Uploaded STEP file
    
    Returns:
        Geometric properties (volume, surface area, bounding box)
    """
    # Validate file
    if not file.filename or not file.filename.lower().endswith(('.step', '.stp')):
        raise HTTPException(status_code=400, detail="Invalid STEP file")
    
    temp_file = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.step') as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_file_path = temp_file.name
        
        result = processor.get_geometric_properties(temp_file_path)
        return result
        
    except Exception as e:
        logger.error(f"Error processing geometry: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        if temp_file and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)


@app.post("/analyze/topology")
async def analyze_topology_only(file: UploadFile = File(...)) -> Dict[str, Any]:
    """
    Extract only topology information from STEP file
    
    Args:
        file: Uploaded STEP file
    
    Returns:
        Topology counts (solids, shells, faces, edges, vertices)
    """
    if not file.filename or not file.filename.lower().endswith(('.step', '.stp')):
        raise HTTPException(status_code=400, detail="Invalid STEP file")
    
    temp_file = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.step') as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_file_path = temp_file.name
        
        result = processor.get_topology_info(temp_file_path)
        return result
        
    except Exception as e:
        logger.error(f"Error processing topology: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        if temp_file and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)


@app.post("/validate")
async def validate_step_file(file: UploadFile = File(...)) -> Dict[str, Any]:
    """
    Validate STEP file quality and structure
    
    Args:
        file: Uploaded STEP file
    
    Returns:
        Validation results and quality metrics
    """
    if not file.filename or not file.filename.lower().endswith(('.step', '.stp')):
        raise HTTPException(status_code=400, detail="Invalid STEP file")
    
    temp_file = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.step') as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_file_path = temp_file.name
        
        result = processor.validate_file(temp_file_path)
        return result
        
    except Exception as e:
        logger.error(f"Error validating file: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        if temp_file and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

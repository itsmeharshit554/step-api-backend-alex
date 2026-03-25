FROM python:3.10-slim

# Minimal runtime libs for OCP (OpenCascade) + headless FastAPI
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglu1-mesa \
    libxrender1 \
    libsm6 \
    libxext6 \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps (multipart is needed for file upload)
RUN pip install --no-cache-dir fastapi uvicorn[standard] pydantic==1.10.13 numpy python-multipart
# OpenCascade Python bindings (prebuilt wheel; no compiling OCCT)
RUN pip install --no-cache-dir OCP==7.7.0

# Copy code
COPY . /app

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host","0.0.0.0","--port","8000"]

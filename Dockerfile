FROM python:3.10-slim

# Minimal runtime libs for OpenCascade (OCP) + headless FastAPI
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
# OpenCascade Python bindings (CadQuery/OCP wheel; imports as `from OCP import ...`)
RUN pip install --no-cache-dir cadquery-ocp==7.9.3.1

# Copy your app
COPY . /app

# Render expects a web service to listen on 0.0.0.0:$PORT (default 10000)
# Use the shell-form CMD so $PORT expands at runtime.
EXPOSE 10000
CMD ["sh","-c","uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}"]

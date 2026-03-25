FROM python:3.11

# Install system dependencies required by OpenCascade (OCP) + CadQuery
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglu1-mesa \
    libfreetype6 \
    libxext6 \
    libxrender1 \
    libfontconfig1 \
    liboce-foundation-dev \
    liboce-modeling-dev \
    liboce-ocaf-dev \
    liboce-visualization-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]

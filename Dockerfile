FROM mambaorg/micromamba:1.5.8

USER root

# Set working directory
WORKDIR /app

# Copy environment file
COPY environment.yml .

# Create environment using micromamba (faster and more reliable)
RUN micromamba create -f environment.yml && \
    micromamba clean --all --yes

# Copy application code
COPY ./app /app/app

# Expose port
EXPOSE 8000

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV MAMBA_DOCKERFILE_ACTIVATE=1

# Activate environment and run
CMD ["/usr/local/bin/_dockerfile_shell.sh", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

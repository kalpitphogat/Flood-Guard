# FloodGuard India — one image, one port.
#
#   docker build --build-arg GIT_COMMIT=$(git rev-parse --short HEAD) -t floodguard .
#   docker run -p 8000:8000 -v "$PWD/data:/app/data" floodguard
#   -> dashboard and API both at http://localhost:8000
#
# Stage 1 builds the React dashboard; stage 2 is the Python API, which also
# serves the built dashboard (see backend/app/main.py), so nothing else has to
# be started at a venue.

# ---------------------------------------------------------------- dashboard
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- API + solvers
FROM python:3.12-slim
ARG GIT_COMMIT=unknown
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FLOODGUARD_DATA_DIR=/app/data \
    FLOODGUARD_GIT_COMMIT=${GIT_COMMIT} \
    NUMBA_CACHE_DIR=/tmp/numba

WORKDIR /app
# rasterio, pyogrio and netCDF4 ship manylinux wheels with GDAL/HDF5 bundled,
# so no system GDAL is needed.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/ ./backend/
RUN pip install -e ./backend
COPY data/catalog/ ./data/catalog/
COPY data/scenarios/ ./data/scenarios/
COPY docs/ ./docs/
COPY --from=web /web/dist ./frontend/dist

# Compile the numba kernels at build time, so the first request of a live demo
# does not pay the JIT cost.
RUN cd backend && python -c "from floodguard.validation.run import run_validation; run_validation('/tmp/v', quick=True)" > /dev/null

WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# FloodGuard India — SIH PS 26161
# Works with GNU make. On Windows use Git Bash or WSL.

PYTHON      ?= python
PIP         ?= $(PYTHON) -m pip
SCENARIO    ?= tehri_bhagirathi
BACKEND_DIR := backend
FRONTEND_DIR:= frontend

.DEFAULT_GOAL := help

.PHONY: help setup setup-pip setup-conda data preprocess validate simulate simulate-both demo test test-backend test-frontend build serve profile-sph lint clean audit

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

setup: setup-pip  ## Install everything (pip path; use setup-conda if you have conda)

setup-pip:  ## Install Python deps via pip + frontend deps via npm
	$(PIP) install -r requirements.txt
	$(PIP) install -e $(BACKEND_DIR)
	cd $(FRONTEND_DIR) && npm install

setup-conda:  ## Create the conda env (gets ANUGA + GDAL cleanly)
	conda env create -f environment.yml || conda env update -f environment.yml
	@echo "Now: conda activate floodguard && make setup-pip"

data:  ## Fetch + cache all input layers for SCENARIO (default: tehri_bhagirathi)
	$(PYTHON) -m floodguard.cli data --scenario data/scenarios/$(SCENARIO).yaml

preprocess:  ## Condition DEM, build grid, reservoir curve, cross-sections
	$(PYTHON) -m floodguard.cli preprocess --scenario data/scenarios/$(SCENARIO).yaml

validate:  ## Run Ritter/Stoker/lake-at-rest/mass-balance -> docs/validation/
	$(PYTHON) -m floodguard.cli validate --out docs/validation

simulate:  ## Headless end-to-end run for SCENARIO
	$(PYTHON) -m floodguard.cli simulate --scenario data/scenarios/$(SCENARIO).yaml

demo:  ## Start backend + frontend on the precomputed demo bundle
	$(PYTHON) -m floodguard.cli demo

serve-backend:  ## Run the API only
	cd $(BACKEND_DIR) && $(PYTHON) -m uvicorn app.main:app --reload --port 8000

serve-frontend:  ## Run the Vite dev server only
	cd $(FRONTEND_DIR) && npm run dev

test: test-backend test-frontend  ## Run every test suite (backend + frontend)

test-backend:  ## Backend tests (pytest)
	$(PYTHON) -m pytest $(BACKEND_DIR)/tests -q

test-frontend:  ## Frontend tests (Vitest + Testing Library)
	cd $(FRONTEND_DIR) && npm test

simulate-both:  ## Run SCENARIO with both engines (FloodGuard-SWE + FloodGuard-SPH) at 90 m
	$(PYTHON) -m floodguard.cli simulate --scenario data/scenarios/$(SCENARIO).yaml --resolution 90 --engines swe_fv,sph_swe

build:  ## Build the dashboard; the API then serves it itself
	cd $(FRONTEND_DIR) && npm run build

serve: build  ## ONE process on :8000 — API + built dashboard (the venue setup)
	cd $(BACKEND_DIR) && $(PYTHON) -m uvicorn app.main:app --host 0.0.0.0 --port 8000

profile-sph:  ## Short SPH-only run with particle diagnostics (SECONDS=400)
	$(PYTHON) scripts/profile_sph.py --scenario $(SCENARIO) --seconds $(or $(SECONDS),400)

lint:  ## Ruff + tsc
	$(PYTHON) -m ruff check $(BACKEND_DIR)
	cd $(FRONTEND_DIR) && npm run typecheck

audit:  ## Clone reference repos and regenerate the audit scaffold
	$(PYTHON) scripts/clone_references.py

clean:  ## Remove derived artefacts (never touches data/raw)
	rm -rf data/processed/* outputs/* runs/* .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

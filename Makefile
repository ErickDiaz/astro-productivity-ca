.PHONY: help install env shell extract transform all test lint format clean clean-cache notebooks

PYTHON := poetry run

help:
	@echo "astroca - bibliometria de astronomia en Centroamerica y el Caribe"
	@echo ""
	@echo "  make install      Instala dependencias con poetry"
	@echo "  make env          Crea .env a partir de .env.example"
	@echo "  make shell        Abre una shell con el entorno activo"
	@echo ""
	@echo "  make extract      Fase 1: descarga publicaciones de NASA ADS -> data/raw"
	@echo "  make transform    Fase 2: resuelve afiliacion -> pais     -> data/processed"
	@echo "  make all          extract + transform"
	@echo ""
	@echo "  make notebooks    Levanta JupyterLab"
	@echo "  make test         Corre los tests"
	@echo "  make lint         Revisa estilo con ruff"
	@echo "  make format       Autoformatea con ruff"
	@echo "  make clean-cache  Borra la cache de respuestas de ADS"
	@echo "  make clean        Borra datos generados y cache"

install:
	poetry install

env:
	@if [ -f .env ]; then \
	    echo "✓ .env ya existe, no lo sobreescribo"; \
	else \
	    cp .env.example .env && \
	    echo "✓ .env creado — agrega tu ADS_DEV_KEY"; \
	    echo "  Token: https://ui.adsabs.harvard.edu/user/settings/token"; \
	fi

shell:
	poetry shell

# ── Pipeline ────────────────────────────────────────────────────────────────
# extract escribe data/raw/publications_<fecha>.parquet (inmutable, fechado).
# transform lee el raw mas reciente y escribe data/processed/.
# Los notebooks solo leen data/processed: nunca llaman a la API.

extract:
	$(PYTHON) astroca extract publications

transform:
	$(PYTHON) astroca transform affiliations

all: extract transform

notebooks:
	$(PYTHON) jupyter lab

# ── Calidad ─────────────────────────────────────────────────────────────────
test:
	$(PYTHON) pytest -v

lint:
	$(PYTHON) ruff check src tests

format:
	$(PYTHON) ruff format src tests
	$(PYTHON) ruff check --fix src tests

clean-cache:
	rm -rf .cache/ads
	@echo "✓ cache de ADS borrada"

clean: clean-cache
	rm -rf data/raw data/interim data/processed outputs
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "✓ datos generados borrados"

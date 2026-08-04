.PHONY: install dev test coverage lint format clean build release

install:
	pip install -e .

dev:
	pip install -r requirements-dev.txt
	pip install -e .

test:
	pytest

coverage:
	pytest --cov=netinfo --cov-report=term-missing --cov-report=html

lint:
	python -m flake8 netinfo.py tests/ || true

format:
	python -m black netinfo.py tests/ || true

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache/ .coverage htmlcov/ __pycache__ tests/__pycache__

build: clean
	python -m build

release-test: build
	python -m twine upload --repository testpypi dist/*

release: build
	python -m twine upload dist/*

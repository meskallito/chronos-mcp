.PHONY: help install dev-install format lint test test-unit test-integration coverage clean build publish

help:
	@echo "Available commands:"
	@echo "  make install         Install package"
	@echo "  make dev-install     Install package with dev dependencies"
	@echo "  make format          Format code with black and isort"
	@echo "  make lint            Run all linters"
	@echo "  make test            Run all tests"
	@echo "  make test-unit       Run unit tests only"
	@echo "  make test-integration Run integration tests only"
	@echo "  make coverage        Run tests with coverage report"
	@echo "  make clean           Clean build artifacts"
	@echo "  make build           Build distribution packages"
	@echo "  make publish         Publish to PyPI (requires credentials)"

install:
	pip install -e .

dev-install:
	pip install -e ".[dev]"
	pre-commit install

format:
	isort chronos_mcp tests
	black --target-version py311 chronos_mcp tests

lint:
	isort --check-only chronos_mcp tests
	black --target-version py311 --check chronos_mcp tests
	flake8 chronos_mcp tests --max-line-length=100
	mypy chronos_mcp

test:
	pytest tests/ -v

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

coverage:
	pytest tests/ --cov=chronos_mcp --cov-report=term-missing --cov-report=html --cov-report=xml
	@echo "Coverage report generated in htmlcov/index.html"

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	rm -rf .coverage
	rm -rf htmlcov/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete

build: clean
	python -m build

publish: build
	twine check dist/*
	twine upload dist/*

# Development helpers
server:
	python -m chronos_mcp

radicale:
	python -m radicale --config tests/fixtures/radicale.conf

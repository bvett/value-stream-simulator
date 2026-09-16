# Repository Guidelines

## Project Structure & Module Organization
Core package code lives in `src/value_stream/`. Simulation behavior is centered around modules such as `simulation.py`, `model.py`, and the workflow/resource packages under `src/value_stream/resources/` and `src/value_stream/utils/`. Tests live in `tests/` and generally mirror the package surface with files like `test_simulation.py` and `test_model_factory.py`. Example entry points are in `src/examples/`, and exploratory notebooks live in `src/examples/tutorial.ipynb` and `experiments.ipynb`.

## Build, Test, and Development Commands
Create an environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

Run the test suite with coverage:

```bash
pytest --cov=src --cov-report=xml tests -s
```

Run a focused test file during development:

```bash
pytest tests/test_simulation.py -s
```

Try the sample simulation with:

```bash
python src/examples/demo.py
```

## Coding Style & Naming Conventions
Target Python 3.11+ as declared in `pyproject.toml`. Use 4-space indentation, snake_case for modules, functions, and variables, and PascalCase for classes. Keep imports and package references compatible with the `src/` layout. The workspace is configured for the Black formatter (`ms-python.black-formatter`), standard type checking, and relative import formatting; preserve those conventions when editing.

## Testing Guidelines
Tests are written with `unittest` and executed via `pytest`. Name files `test_*.py` and group related assertions in `Test...` classes. Add or update tests whenever simulation rules, factory behavior, or resource workflows change. Coverage output is expected in `coverage.xml`; keep new code covered at the same level as adjacent modules.

## Commit & Pull Request Guidelines
Recent commits use short, imperative subjects such as `move TaskGenerator to own module` and `correcting error in tutorial`. Keep commit messages focused on one change and describe the behavioral impact plainly. Pull requests should include a concise summary, note any affected simulation assumptions, link related issues when present, and attach screenshots or plots if example output or notebook visuals changed.

# ExecPlans

When writing complex features or significant refactors, use an ExecPlan (as described in .agent/PLANS.md) from design to implementation.

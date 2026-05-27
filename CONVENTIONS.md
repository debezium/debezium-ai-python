# Python Coding Conventions for Debezium

This document outlines the coding standards, style guidelines, tooling configurations, and Git workflow conventions for Python projects within the Debezium organization.

---

## 1. Code Style and Formatting

We use [Ruff](https://astral.sh/ruff) for all linting and code formatting. Ruff replaces traditional Python quality tools like Black, Flake8, isort, and pyupgrade with a single, highly performant linter.

### Guidelines
* **Line Length**: Limit all lines to a maximum of **120 characters** (configured via `line-length = 120` in `pyproject.toml`).
* **Indentation**: Use **4 spaces** for indentation of all Python code blocks (compliant with PEP 8).
* **Quotes**: Prefer double quotes (`"`) for strings unless single quotes (`'`) are necessary to avoid escaping nested quotes.
* **Imports**: Group imports by standard library, third-party libraries, and first-party local packages, separated by blank lines and sorted alphabetically. Ruff does this automatically with the `I` (isort) rule group.
* **Formatting Command**: Format the entire project using Ruff:
  ```bash
  ruff format .
  ```
* **Linting Command**: Check for style violations and fix them automatically where possible:
  ```bash
  ruff check --fix .
  ```

---

## 2. Type Annotations and Static Analysis

All Python source code must use strict type annotations to ensure code safety, self-documentation, and robustness.

### Guidelines
* **Type Checker**: We use [MyPy](https://mypy-lang.org) in strict mode to validate type annotations.
* **Strict Type Safety**: All function signatures (including return types) and class attributes must have explicit type annotations.
* **Avoid `Any`**: Minimize the use of `Any`. Use generic types (`typing.TypeVar`, `typing.Generic`) or protocols (`typing.Protocol`) to type dynamic behaviors.
* **Run Type Check**: Run MyPy locally before committing:
  ```bash
  mypy .
  ```

---

## 3. Documentation and Comments

Clear documentation is key for open-source maintenance and user onboarding.

### Guidelines
* **Docstring Style**: All public modules, classes, methods, and functions must contain docstrings following the **Google Python Style Guide** format.
* **Docstring Structure**:
  ```python
  def process_event(event_data: dict[str, Any], schema: Schema) -> Document:
      """Processes a Debezium change event payload into a LangChain Document.

      Args:
          event_data: The raw event payload containing database record fields.
          schema: The Debezium schema associated with the event.

      Returns:
          A LangChain Document ready to be upserted into a vector store.

      Raises:
          ValueError: If the event payload is invalid or malformed.
      """
  ```
* **Inline Comments**: Write inline comments sparingly, focusing on *why* a complex algorithm or workaround was implemented, rather than *what* the code does.

---

## 4. Testing

A comprehensive test suite is required to prevent regressions, particularly when mapping databases to dynamic vector stores.

### Guidelines
* **Framework**: We use **pytest** as the test runner.
* **Structure**: Tests are split into:
  - `tests/unit/`: Quick unit tests testing individual components in isolation without external dependencies.
  - `tests/integration/`: Integration tests requiring real databases or vector stores (typically using containers via Podman/Docker, and Testcontainers).
* **Asynchronous Tests**: We use `pytest-asyncio` to test asynchronous code. Mark async tests using `pytest.mark.asyncio` or rely on `asyncio_mode = "auto"` in `pyproject.toml`.
* **Run Tests**:
  ```bash
  pytest
  ```

---

## 5. Git and Contribution Workflow

To maintain a clean history and ensure legal compliance, we follow a strict Git workflow.

### Commit Guidelines
* **DCO Sign-off (Mandatory)**: All commits must include a `Signed-off-by` trailer confirming agreement with the Developer Certificate of Origin (DCO). Always commit using the `-s` flag:
  ```bash
  git commit -s -m "feat: my commit message"
  ```
* **Commit Message Format**: Every commit message must begin with the issue key/number of the GitHub issue it addresses (using the unified Debezium issue tracker at https://github.com/debezium/dbz/issues), followed by a colon and a descriptive message.
  - **GitHub Issue Format**: `debezium/dbz#<issue_number> <message>`
  - **Examples**:
    * `debezium/dbz#12: Initial CI configuration`
* **Exceptions**:
  - Trivial documentation commits can be prefixed with `[docs]` (e.g., `[docs]: Fix typo in README`).
  - CI infrastructure commits can be prefixed with `[ci]` (e.g., `[ci]: Adjust workflow runner versions`).
  - Internal automated/release commits can use `[release]`, `[jenkins-jobs]`, or `[maven-release-plugin]`.

### Branching & PRs
* **Feature Branches**: Work on dedicated feature branches named after the issue (e.g., `dbz-1234` or `gsoc-week-1`).
* **PR Reviews**: Open a Pull Request from your branch, link it to the corresponding GitHub issue, and await review from at least one maintainer. Direct pushes to `main` are disabled.

---

## 6. AI Usage Policy

Contributions must adhere to the Debezium [AI Usage Policy](https://github.com/debezium/debezium/blob/main/AI_USAGE_POLICY.md). Any code generated or assisted by AI must be carefully reviewed, tested, and verified for compliance with code quality guidelines and licensing requirements.

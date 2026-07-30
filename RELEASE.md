# PyDebeziumAI Release Guide

This document outlines the standard release checklist, versioning policies, and build validation steps required to package and publish `pydebeziumai` to PyPI.

---

## 1. Versioning Policy

We strictly adhere to **Semantic Versioning (SemVer)** (`MAJOR.MINOR.PATCH`):
* **PATCH**: Bug fixes, documentation updates, dependency bumps, or internal stability enhancements that do not alter the public API.
* **MINOR**: New features, adapters, or capabilities introduced in a backwards-compatible manner (e.g., adding a new vector store adapter).
* **MAJOR**: Breaking changes that alter public interfaces, remove existing configuration options, or raise system requirements.

---

## 2. Pre-Release Verification

Before tagging a release, verify that the following local checks pass:

1. **Test Suite**: Run the complete unit and integration test suite:
   ```bash
   pytest
   ```
2. **Quality Controls**: Run code formatting and type safety validations:
   ```bash
   ruff format --check .
   ruff check .
   mypy .
   ```
3. **Documentation**: Build the Sphinx HTML documentation locally and ensure there are 0 warnings:
   ```bash
   cd docs
   make html
   cd ..
   ```

---

## 3. Build & Package Verification

We use `build` and `twine` to compile and validate the distribution packages locally.

1. **Install Build Requirements**:
   ```bash
   pip install --upgrade build twine
   ```
2. **Clean Previous Builds**:
   ```bash
   rm -rf dist/ build/ *.egg-info
   ```
3. **Build Packages**:
   Build the source distribution (`sdist`) and the binary wheel distribution (`wheel`):
   ```bash
   python -m build
   ```
4. **Validate Package Layout**:
   * Verify that the generated wheel contains **only** the `pydebeziumai` source code package (no tests, docs, or examples).
   * Verify that the source distribution (`sdist`) contains the complete test suite, documentation sources, and licensing files.
5. **Twine Metadata Check**:
   Validate that the package description matches PyPI requirements and has valid metadata syntax:
   ```bash
   twine check dist/*
   ```

---

## 4. Release Checklist

Once all pre-release checks pass:

1. **Update Version**: Bump the package version string in `pydebeziumai/__init__.py`.
2. **Document Changelog**: Update `docs/changelog.rst` with the release notes and date.
3. **Commit & Tag**: Commit the version bump and tag the commit (replace `0.1.0` with the target version):
   ```bash
   git add pydebeziumai/__init__.py docs/changelog.rst
   git commit -m "release: bump version to v0.1.0"
   git tag -a v0.1.0 -m "Release version 0.1.0"
   ```
4. **Push Tags**: Push the release branch and tags to GitHub:
   ```bash
   git push origin main --tags
   ```

*Note: Pushing a version tag (`v*`) automatically triggers the publishing workflow to compile and upload the packages securely to PyPI using OpenID Connect (OIDC) trusted publishing.*

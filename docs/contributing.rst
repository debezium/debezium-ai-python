Contributing Guide
==================

We welcome contributions to ``pydebeziumai``! Below are guidelines to help you set up your local development environment, run formatting/linting tools, build documentation, and execute the test suite.

Please ensure that your contributions follow the general `Debezium Contributing Guide <https://github.com/debezium/debezium/blob/main/CONTRIBUTING.md>`_ (which covers how to structure pull requests, write commit messages, and sign off your commits) as well as the Debezium `AI Usage Policy <https://github.com/debezium/debezium/blob/main/AI_USAGE_POLICY.md>`_.

Development Environment Setup
-----------------------------

1. Clone the repository and navigate to the project directory:

   .. code-block:: bash

      git clone https://github.com/debezium/debezium-ai-python.git
      cd debezium-ai-python

2. Create and activate a virtual environment:

   .. code-block:: bash

      python3 -m venv .venv
      source .venv/bin/activate

3. Install the package in editable mode along with development and documentation dependencies:

   .. code-block:: bash

      pip install -e ".[dev]"

Code Formatting & Linting
-------------------------

We use Ruff for code formatting and linting, and MyPy for typechecking. Before submitting a pull request, run the following checks:

* **Code Formatting**:

  .. code-block:: bash

     ruff format .

* **Lint Checks**:

  .. code-block:: bash

     ruff check --fix .

* **Type Verification**:

  .. code-block:: bash

     mypy --python-version 3.10 .

Running Tests
-------------

The test suite contains both unit and integration tests.

.. note::
   Running integration tests requires a Java 17+ runtime and local Debezium JAR files. Ensure ``JAVA_HOME`` is configured and the database connector JARs are downloaded before running the tests:

   .. code-block:: bash

      export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
      python3 tools/setup_jars.py
      pytest

Building Documentation
----------------------

To build the HTML documentation locally:

1. Ensure the documentation requirements are installed (included in the ``[dev]`` extra).
2. Navigate to the ``docs/`` directory and build the HTML output:

   .. code-block:: bash

      cd docs
      make html

3. The generated HTML pages will be available under ``docs/_build/html/index.html``.

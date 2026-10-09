"""Operational scripts for the UK Geothermal Well Atlas backend.

Run from the repository root with the backend on the path::

    python -m scripts.cli check
    python -m scripts.cli seed-user --email you@example.com --password ...
    python -m scripts.cli bootstrap

The package is deliberately at the repository root rather than inside
``backend/app`` so the operational surface is visible to anyone auditing what
can be done to a database, without reading the application code.
"""
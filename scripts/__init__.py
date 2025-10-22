"""Helper utilities exposed for test imports.

This package marker allows the ``scripts`` directory to be imported in unit
tests.  The directory primarily houses command-line utilities, so keeping the
file intentionally lightweight avoids altering runtime behaviour while enabling
`pytest` to import helpers as regular modules when needed.
"""

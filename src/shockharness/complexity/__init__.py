"""Complexity metrics, call graph, coupling and hotspot inputs (Milestone E).

Every metric here is advisory: it is reported under ``metrics.complexity`` and
``metrics.graph``, it can raise ``CPLX001``-``CPLX005`` warnings, and it never
fails a plain ``check``. Each counting convention is versioned; the version
string travels with every number so a reader can tell which convention
produced it. See ``docs/complexity.md``.
"""

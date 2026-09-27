"""Static checks for the defect classes the OpenGLContext stack's reviews find.

Each rule has a stable code, ``OGC`` and three digits, and looks at a module's
syntax tree and the comments beside it. ``oglc-check`` runs them from the
command line, and ``-p openglcontext_checks.pytest_plugin`` runs them as part
of a project's test suite.
"""

__version__ = '0.1.0a2'

"""Pytest bootstrap for the Dia de los Muertos Photo Booth test suite.

This lightweight conftest lives at the project root so that running ``pytest``
from ``desafio5/`` puts this directory on ``sys.path``. That makes the domain
modules (``validation``, ``adornments``, ``detection``, ``composition``) and the
Flask ``app`` importable from the test modules under ``tests/`` without any
packaging step.

We deliberately keep this file dependency-free: it only adjusts ``sys.path``,
mirroring the minimal bootstrap approach used by ``desafio4/backend/conftest.py``
(design: proportionate scope).
"""

from __future__ import annotations

import os
import sys

# Put the project root (this directory) on sys.path so ``import validation``,
# ``import app`` and friends resolve when pytest is invoked from ``desafio5/``.
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

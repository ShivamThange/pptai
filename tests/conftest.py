"""Explicit fake deployment capacity for inherited gateway regression fixtures.

Production has no numeric capacity default. F07 resolution tests pass explicit
environment maps and independently exercise missing/invalid configuration.
"""
import pytest


@pytest.fixture(autouse=True)
def fixture_context_capacity(monkeypatch):
    monkeypatch.setenv('LLM_UNKNOWN_CONTEXT_POLICY', 'configured')
    monkeypatch.setenv('LLM_UNKNOWN_CONTEXT_TOKENS', '262144')
    monkeypatch.setenv('LLM_CONTEXT_COUNT_MODE', 'estimate')
    monkeypatch.setenv('STRICT_SECTION_COVERAGE', 'true')
    import sys
    monkeypatch.setenv('PPTAI_PYTHON', sys.executable)
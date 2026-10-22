"""Tests run in mock mode against a throwaway data folder."""

import os
import tempfile

os.environ["SUPPORT_AGENT_MOCK"] = "1"
os.environ["SUPPORT_AGENT_DATA"] = tempfile.mkdtemp(prefix="golden-ci-test-")

import pytest  # noqa: E402

from golden_ci.services import a2a_services  # noqa: E402


@pytest.fixture(scope="session")
def ports():
    with a2a_services() as p:
        yield p

import os
import sys # Added for sys.stderr.fileno()
from pathlib import Path

import pytest
from dotenv import load_dotenv


@pytest.fixture(scope="session", autouse=True)
def load_env_vars_from_dotenv():
    """
    Load environment variables from .env file for the test session.
    This ensures that variables like ANTHROPIC_API_KEY, USE_ANTHROPIC_IN_TEST,
    and TEST_INTEGRATION_VERBOSE are available to the pytest process and
    can be correctly propagated or used.
    """
    # Assuming conftest.py is in the tests/ directory,
    # project_root will be the parent directory of tests/
    project_root = Path(__file__).resolve().parent.parent
    dotenv_path = project_root / ".env"

    # Use os.fdopen(sys.stderr.fileno(), 'w', buffering=1) for unbuffered output if needed,
    # or ensure pytest's -s flag is used to see prints.
    # For simplicity, direct print to sys.stderr might be sufficient with -s.
    if dotenv_path.exists():
        print(f"CONFTES_DEBUG: Loading .env file from: {dotenv_path}", file=sys.stderr, flush=True)
        load_dotenv(dotenv_path=dotenv_path, override=True)
    else:
        print(f"CONFTES_DEBUG: .env file not found at: {dotenv_path}", file=sys.stderr, flush=True)

    # For debugging, print the relevant env vars after attempting to load
    # These prints will be visible if pytest is run with the -s option (or --capture=no)
    print(f"CONFTES_DEBUG: ANTHROPIC_API_KEY is set: {'yes' if os.getenv('ANTHROPIC_API_KEY') else 'no'}", file=sys.stderr, flush=True)
    print(f"CONFTES_DEBUG: USE_ANTHROPIC_IN_TEST: {os.getenv('USE_ANTHROPIC_IN_TEST')}", file=sys.stderr, flush=True)
    print(f"CONFTES_DEBUG: TEST_INTEGRATION_VERBOSE: {os.getenv('TEST_INTEGRATION_VERBOSE')}", file=sys.stderr, flush=True)

from pathlib import Path

import pytest
from agent.config import Settings
from agent.fixtures import FixtureStore
from agent.state import State

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="session")
def store() -> FixtureStore:
    return FixtureStore.load(FIXTURES_DIR)


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def consent(store, settings):
    # Imported lazily so this shared conftest only needs modules that already exist at every
    # commit in the history; each commit's tests therefore collect and pass on their own.
    from agent.consent import ConsentGateway

    return ConsentGateway.from_store(store, "default", settings.max_consent_polls)


@pytest.fixture
def consent_timeout(store, settings):
    from agent.consent import ConsentGateway

    return ConsentGateway.from_store(store, "timeout", settings.max_consent_polls)


@pytest.fixture
def make_state():
    def _make(**factors: str) -> State:
        state = State(session_id="test")
        for name, value in factors.items():
            state.set_factor(name, value)
        return state

    return _make

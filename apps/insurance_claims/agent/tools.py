"""Tool gateway: the only way SOP code reaches claim data.

Defense in depth, on top of the controller's own phase checks:
- every call re-checks that the session is verified;
- the party comes from the verified state, never from model output or caller input;
- a case is returned only if it belongs to the verified party. A missing case and someone
  else's case are indistinguishable (both None), so IDs cannot be probed.
"""

from __future__ import annotations

from .fixtures import Case, FixtureStore
from .state import SopViolation, State


class ToolGateway:
    def __init__(self, store: FixtureStore, state: State) -> None:
        self._store = store
        self._state = state

    def _verified_party(self) -> str:
        if not self._state.verified or not self._state.verified_party_id:
            raise SopViolation("claim data requested before identity verification")
        return self._state.verified_party_id

    def list_cases(self) -> list[Case]:
        party_id = self._verified_party()
        cases = self._store.cases_for_party(party_id)
        self._state.record("TOOL_CALL", tool="list_cases", result_count=len(cases))
        return cases

    def get_case(self, case_id: str) -> Case | None:
        party_id = self._verified_party()
        case = self._store.get_case(case_id)
        if case is not None and case.party_id != party_id:
            case = None
        self._state.record("TOOL_CALL", tool="get_case", case_id=case_id, found=case is not None)
        return case

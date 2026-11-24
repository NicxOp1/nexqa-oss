"""Offline fakes for provider tests: an HTTP session, a caller and a scenario spec."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from nexqa.models.rule_models import CompiledSpec, TestScenario

Handler = Union[Any, Callable[[Dict[str, Any]], Any]]


class FakeResponse:
    def __init__(self, body: Any = None, status_code: int = 200) -> None:
        self.status_code = status_code
        self._body = body
        self.content = b"" if body is None else json.dumps(body).encode()
        self.text = self.content.decode()

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> Any:
        return self._body


class FakeSession:
    """Routes (METHOD, url-suffix) to canned bodies and records every request.

    A handler may be a body, a FakeResponse, a callable(request) -> body, or a
    list of those (served in order, the last one repeats).
    """

    def __init__(self, routes: Dict[Tuple[str, str], Handler]) -> None:
        self.routes = dict(routes)
        self.calls: List[Dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        call = {"method": method.upper(), "url": url, **kwargs}
        self.calls.append(call)
        for (m, suffix), handler in self.routes.items():
            if m == call["method"] and url.endswith(suffix):
                if isinstance(handler, list):
                    handler = handler.pop(0) if len(handler) > 1 else handler[0]
                if callable(handler):
                    handler = handler(call)
                return handler if isinstance(handler, FakeResponse) else FakeResponse(handler)
        return FakeResponse({"error": f"no route for {method} {url}"}, 404)

    def sent(self, method: str, suffix: str) -> List[Dict[str, Any]]:
        return [c for c in self.calls if c["method"] == method and c["url"].endswith(suffix)]


class FakeCaller:
    """Says the scripted lines, then hangs up (returns None)."""

    def __init__(self, lines: List[str]) -> None:
        self.lines = list(lines)
        self.seen: List[Any] = []

    def next_line(self, persona: str, turns: List[Any]) -> Optional[str]:
        self.seen.append((persona, list(turns)))
        return self.lines.pop(0) if self.lines else None


def make_spec(n: int = 1) -> CompiledSpec:
    return CompiledSpec(
        scenarios=[
            TestScenario(
                id=f"s{i}",
                name=f"Scenario {i}",
                user_prompt=f"You are caller {i} and want to book a cleaning.",
                expected_outcome="The agent books the appointment.",
                critical_checkpoints=["Confirms the date"],
            )
            for i in range(1, n + 1)
        ]
    )

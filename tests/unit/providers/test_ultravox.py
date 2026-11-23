import asyncio
import json

from nexqa.providers.ultravox import UltravoxProvider, parse_seconds

from ._fakes import FakeCaller, FakeSession, make_spec


class FakeWebSocket:
    """Answers every user_text_message with the next scripted agent turn."""

    def __init__(self, greeting, replies):
        self.inbox = []
        self.sent = []
        self.replies = list(replies)
        self.closed = False
        if greeting:
            self.inbox += [json.dumps({"type": "state", "state": "speaking"}),
                           json.dumps({"type": "transcript", "role": "agent", "medium": "text",
                                       "text": greeting, "final": True, "ordinal": 0})]

    def send(self, data):
        msg = json.loads(data)
        self.sent.append(msg)
        if msg["type"] == "user_text_message" and self.replies:
            first, rest = self.replies.pop(0)
            self.inbox.append(b"\x00\x01")  # stray audio frame, must be ignored
            self.inbox.append(json.dumps({"type": "transcript", "role": "user",
                                          "text": msg["text"], "final": True}))
            self.inbox.append(json.dumps({"type": "transcript", "role": "agent",
                                          "delta": first, "final": False}))
            self.inbox.append(json.dumps({"type": "transcript", "role": "agent",
                                          "delta": rest, "final": True}))

    def recv(self, timeout=None):
        if not self.inbox:
            raise TimeoutError
        return self.inbox.pop(0)

    def close(self):
        self.closed = True


MESSAGES_P1 = {"next": "https://api.ultravox.ai/api/calls/call_1/messages?cursor=2", "results": [
    {"role": "MESSAGE_ROLE_AGENT", "text": "Hello, clinic.", "timespan": {"start": "0.2s", "end": "1.0s"}},
    {"role": "MESSAGE_ROLE_USER", "text": "Book me", "timespan": {"start": "1.5s", "end": "2s"}},
]}
MESSAGES_P2 = {"next": None, "results": [
    {"role": "MESSAGE_ROLE_TOOL_CALL", "toolName": "book", "invocationId": "i1",
     "text": '{"day": "Tue"}'},
    {"role": "MESSAGE_ROLE_TOOL_RESULT", "toolName": "book", "invocationId": "i1", "text": "ok"},
    {"role": "MESSAGE_ROLE_AGENT", "text": "Booked for Tuesday."},
]}


def test_prompt_read_and_partial_patch():
    agent = {"agentId": "ag_1", "callTemplate": {"systemPrompt": "OLD", "voice": "v"}}
    p = UltravoxProvider({}, session=FakeSession({("GET", "/agents/ag_1"): agent,
                                                  ("PATCH", "/agents/ag_1"): {}}),
                         api_key="uv-key")
    assert p.get_prompt("ag_1") == "OLD"
    assert p.session.calls[0]["headers"]["X-API-Key"] == "uv-key"
    p.update_prompt("ag_1", "NEW")
    assert p.session.sent("PATCH", "/agents/ag_1")[0]["json"] == {
        "callTemplate": {"systemPrompt": "NEW"}}


def test_text_call_with_simulated_caller():
    ws = FakeWebSocket("Hello, clinic.", [("Booked ", "for Tuesday.")])
    routes = {
        ("POST", "/agents/ag_1/calls"): {"callId": "call_1", "joinUrl": "wss://join/call_1"},
        ("GET", "/calls/call_1/messages"): MESSAGES_P1,
        ("GET", "/messages?cursor=2"): MESSAGES_P2,
        ("GET", "/calls/call_1"): {"endReason": "hangup", "billedDuration": "90s"},
    }
    p = UltravoxProvider({"reply_timeout_s": 1, "greeting_timeout_s": 1},
                         session=FakeSession(routes), api_key="k")
    joined = []
    p.ws_connect = lambda url: joined.append(url) or ws
    p.caller = FakeCaller(["Book me"])

    suite = p.register_scenarios("ag_1", make_spec(1), {})
    run = asyncio.run(p.wait_for_results(suite, p.start_run(suite), 0, 60))

    call_body = p.session.sent("POST", "/agents/ag_1/calls")[0]["json"]
    assert call_body["mediumRestriction"] == {"allowedMediums": ["MESSAGE_MEDIUM_TEXT"]}
    assert call_body["initialOutputMedium"] == "MESSAGE_MEDIUM_TEXT"
    assert "serverWebSocket" in call_body["medium"]
    assert joined == ["wss://join/call_1"]
    assert ws.sent[0] == {"type": "user_text_message", "text": "Book me"}
    assert ws.sent[-1]["type"] == "hang_up" and ws.closed

    # The caller saw the live reply assembled from deltas.
    assert p.caller.seen[-1][1][-1].text == "Booked for Tuesday."

    conv = run.conversations[0]
    # The final record comes from GET /calls/{id}/messages (both pages).
    assert conv.transcript_text() == (
        "Agent: Hello, clinic.\nUser: Book me\nAgent: Booked for Tuesday.\n")
    assert conv.turns[0].start_s == 0.2 and conv.turns[1].end_s == 2.0
    assert conv.tool_calls[0].arguments == {"day": "Tue"} and conv.tool_calls[0].result == "ok"
    assert conv.end_reason == "hangup" and conv.duration_s == 90.0
    assert run.billed_minutes == 1.5


def test_parse_seconds():
    assert parse_seconds("1.5s") == 1.5
    assert parse_seconds(None) is None
    assert parse_seconds("n/a") is None

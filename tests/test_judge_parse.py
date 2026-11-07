import pytest
from core.judge import parse_verdict, make_judge

BROKEN = '\n\n{"supported": true, "reason": The record shows FedEx and DELIVERED.}'


class FakeGW:
    def __init__(self, texts):
        self.texts, self.calls = list(texts), 0

    def chat(self, role, model, msgs, **kw):
        self.calls += 1
        return {"text": self.texts.pop(0)}


def test_valid_json_still_parsed():
    assert parse_verdict('{"supported": false, "reason": "x"}') is False
    assert parse_verdict('{"supported": "unclear", "reason": "x"}') == "unclear"


def test_malformed_json_with_single_clear_verdict_is_salvaged():
    assert parse_verdict(BROKEN) is True


def test_contradictory_or_missing_verdict_is_not_salvaged():
    with pytest.raises(ValueError):
        parse_verdict('{"supported": true, "reason": oops "supported": false}')
    with pytest.raises(ValueError):
        parse_verdict("no json here")


def test_judge_retries_once_then_fails_closed():
    both = '{"supported": true, "reason": oops "supported": false}'
    gw = FakeGW([both, '{"supported": true, "reason": "ok"}'])
    assert make_judge(gw, "m")("claim", {}) is True and gw.calls == 2
    gw = FakeGW(["garbage", "garbage"])
    with pytest.raises(ValueError):
        make_judge(gw, "m")("claim", {})
    assert gw.calls == 2

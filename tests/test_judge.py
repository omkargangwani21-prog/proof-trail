import pytest
from types import SimpleNamespace as NS
from core.db import connect
from core.gateway import Gateway
from core.judge import make_judge, judge_model_for


class Scripted:
    def __init__(self, text):
        self.text = text
        self.chat = NS(completions=NS(create=self._c))

    def _c(self, **kw):
        self.kw = kw
        return NS(usage=NS(prompt_tokens=10, completion_tokens=10),
                  choices=[NS(message=NS(content=self.text), finish_reason="stop")])


def judge(text):
    f = Scripted(text)
    g = Gateway(connect(":memory:"), client=f, baseline=0.0, trace_dir="/tmp/pt_traces")
    return make_judge(g, "openai/gpt-oss-120b"), f


def test_true_false_unclear():
    assert judge('{"supported": true, "reason": "x"}')[0]("c", {}) is True
    assert judge('{"supported": false, "reason": "x"}')[0]("c", {}) is False
    assert judge('{"supported": "unclear", "reason": "x"}')[0]("c", {}) == "unclear"


def test_garbage_raises_so_verifier_fails_closed():
    with pytest.raises(Exception):
        judge("no idea")[0]("c", {})


def test_temperature_zero_and_no_self_judging():
    j, f = judge('{"supported": true, "reason": "x"}')
    j("claim", {"shp:1": {}})
    assert f.kw["temperature"] == 0.0
    assert judge_model_for("openai/gpt-oss-120b") != "openai/gpt-oss-120b"
    assert judge_model_for("deepseek-ai/DeepSeek-V4-Flash-0731") == "openai/gpt-oss-120b"

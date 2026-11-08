from types import SimpleNamespace as NS
from core.db import connect
from core.gateway import Gateway

M = "deepseek-ai/DeepSeek-V4-Flash-0731"
MSGS = [{"role": "user", "content": "hi"}]


def reply(text, finish):
    return NS(choices=[NS(message=NS(content=text), finish_reason=finish)], model=M,
              usage=NS(prompt_tokens=10, completion_tokens=20, input_tokens=10, output_tokens=20, total_tokens=30))


class FakeClient:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kw):
        self.calls += 1
        return self.replies.pop(0)


def gw(tmp_path, client):
    return Gateway(connect(str(tmp_path / "t.db")), client=client, hard=100, soft=100, baseline=0,
                   trace_dir=str(tmp_path / "tr"))


def test_empty_length_reply_is_not_cached(tmp_path):
    c = FakeClient([reply("", "length"), reply('{"ok": 1}', "stop")])
    g = gw(tmp_path, c)
    assert g.chat("agent", M, MSGS)["text"] == ""
    assert g.chat("agent", M, MSGS)["text"] == '{"ok": 1}'
    assert c.calls == 2


def test_good_reply_is_still_cached(tmp_path):
    c = FakeClient([reply('{"ok": 1}', "stop")])
    g = gw(tmp_path, c)
    g.chat("agent", M, MSGS)
    assert g.chat("agent", M, MSGS)["cached"] is True
    assert c.calls == 1

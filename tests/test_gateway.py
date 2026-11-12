import pytest
from types import SimpleNamespace as NS
from core.db import connect
from core.gateway import Gateway, BudgetExceeded, UnknownModel, PRICES
from core.drafting import MODEL as DEFAULT_DRAFT_MODEL

M = "deepseek-ai/DeepSeek-V4-Flash-0731"


class Fake:
    def __init__(self):
        self.calls = 0
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kw):
        self.calls += 1
        return NS(usage=NS(prompt_tokens=1000, completion_tokens=1000),
                  choices=[NS(message=NS(content="hi"), finish_reason="stop")])


def gw(**kw):
    f = Fake()
    return Gateway(connect(":memory:"), client=f, trace_dir="/tmp/pt_traces", baseline=0.0, **kw), f


MSG = [{"role": "user", "content": "x"}]


def test_live_draft_default_is_in_gateway_price_table():
    assert DEFAULT_DRAFT_MODEL == "deepseek-ai/DeepSeek-V4.1-Flash-1017"
    assert DEFAULT_DRAFT_MODEL in PRICES


def test_cost_is_computed_from_price_table():
    g, _ = gw()
    r = g.chat("agent", M, MSG)
    assert abs(r["cost_usd"] - 0.00042) < 1e-9


def test_cache_hit_costs_nothing_and_skips_call():
    g, f = gw()
    g.chat("agent", M, MSG)
    r = g.chat("agent", M, MSG)
    assert r["cached"] and r["cost_usd"] == 0.0 and f.calls == 1


def test_cache_salt_forces_fresh_call():
    g, f = gw()
    g.chat("agent", M, MSG, cache_salt="r1")
    g.chat("agent", M, MSG, cache_salt="r2")
    assert f.calls == 2


def test_hard_cap_blocks_call():
    g, f = gw(hard=0.0001)
    with pytest.raises(BudgetExceeded):
        g.chat("agent", M, MSG)
    assert f.calls == 0


def test_unknown_model_rejected():
    g, _ = gw()
    with pytest.raises(UnknownModel):
        g.chat("agent", "some/other-model", MSG)

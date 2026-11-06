import os, json, time, hashlib, datetime
from dotenv import load_dotenv

# $ per million tokens (input, output), from the Nebius console list, 2026-11-05
PRICES = {
    "deepseek-ai/DeepSeek-V4-Flash-0731": (0.14, 0.28),
    "openai/gpt-oss-120b": (0.15, 0.60),
    "deepseek-ai/DeepSeek-V4-Pro-0813": (1.32, 3.96),
    "Qwen/Qwen3-30B-A3B-Instruct-2507": (0.10, 0.30),
    "Qwen/Qwen3-235B-A22B-Instruct-2507": (0.20, 0.60),
    "zai-org/GLM-5.3-Flash": (0.15, 0.50),
    "deepseek-ai/DeepSeek-V4.1-Flash": (0.30, 1.20),
    "nvidia/nemotron-3-super-120b-a12b": (0.30, 0.90),
}
MAX_TOKENS = 6000


class BudgetExceeded(Exception):
    pass


class UnknownModel(Exception):
    pass


LLM_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_calls(
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, model TEXT, role TEXT, prompt_hash TEXT,
  in_tokens INTEGER, out_tokens INTEGER, cost_usd REAL, latency_ms INTEGER, cached INTEGER,
  finish_reason TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS llm_cache(key TEXT PRIMARY KEY, response_json TEXT, created_at TEXT);
"""


class Gateway:
    def __init__(self, conn, client=None, hard=None, soft=None, baseline=None, trace_dir="data/traces"):
        load_dotenv()
        self.conn = conn
        conn.executescript(LLM_SCHEMA)
        if client is None:
            from openai import OpenAI
            client = OpenAI(api_key=os.environ["NEBIUS_API_KEY"],
                            base_url=os.environ.get("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1"),
                            timeout=180)
        self.client = client
        self.hard = float(os.environ.get("PT_BUDGET_HARD", 20)) if hard is None else hard
        self.soft = float(os.environ.get("PT_BUDGET_SOFT", 15)) if soft is None else soft
        # spend before the log existed (smoke tests): about $0.08
        self.baseline = float(os.environ.get("PT_BUDGET_BASELINE", 0.08)) if baseline is None else baseline
        self.trace_dir = trace_dir

    def spent(self):
        row = self.conn.execute("SELECT COALESCE(SUM(cost_usd),0) s FROM llm_calls").fetchone()
        return self.baseline + row["s"]

    def _log(self, run_id, model, role, ph, tin, tout, cost, lat, cached, finish):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO llm_calls(run_id,model,role,prompt_hash,in_tokens,out_tokens,cost_usd,latency_ms,cached,"
            "finish_reason,at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, model, role, ph, tin, tout, cost, lat, int(cached), finish, now))
        self.conn.commit()
        os.makedirs(self.trace_dir, exist_ok=True)
        with open(os.path.join(self.trace_dir, now[:10] + ".jsonl"), "a") as f:
            f.write(json.dumps({"at": now, "run_id": run_id, "role": role, "model": model, "prompt_hash": ph,
                                "in": tin, "out": tout, "cost": cost, "latency_ms": lat, "cached": cached,
                                "finish": finish}) + "\n")

    def chat(self, role, model, messages, max_tokens=MAX_TOKENS, temperature=0.3, cache=True,
             cache_salt="", run_id=None):
        if model not in PRICES:
            raise UnknownModel(model)
        pin, pout = PRICES[model]
        key = hashlib.sha256(json.dumps([model, temperature, max_tokens, messages, cache_salt],
                                        sort_keys=True).encode()).hexdigest()
        ph = key[:16]
        if cache:
            row = self.conn.execute("SELECT response_json FROM llm_cache WHERE key=?", (key,)).fetchone()
            if row:
                d = json.loads(row["response_json"])
                self._log(run_id, model, role, ph, d["in_tokens"], d["out_tokens"], 0.0, 0, True, d["finish_reason"])
                return {**d, "cost_usd": 0.0, "cached": True, "soft_warning": self.spent() >= self.soft}
        if self.spent() + max_tokens * pout / 1e6 > self.hard:
            raise BudgetExceeded(f"spent ${self.spent():.4f}; hard cap ${self.hard:.2f}")
        t0 = time.time()
        r = self.client.chat.completions.create(model=model, messages=messages, max_tokens=max_tokens,
                                                temperature=temperature)
        lat = int((time.time() - t0) * 1000)
        tin, tout = r.usage.prompt_tokens, r.usage.completion_tokens
        cost = (tin * pin + tout * pout) / 1e6
        d = {"text": r.choices[0].message.content or "", "in_tokens": tin, "out_tokens": tout,
             "finish_reason": r.choices[0].finish_reason, "model": model, "latency_ms": lat}
        if cache:
            self.conn.execute("INSERT OR REPLACE INTO llm_cache(key,response_json,created_at) VALUES(?,?,?)",
                              (key, json.dumps(d), datetime.datetime.now(datetime.timezone.utc).isoformat()))
        self._log(run_id, model, role, ph, tin, tout, cost, lat, False, d["finish_reason"])
        return {**d, "cost_usd": cost, "cached": False, "soft_warning": self.spent() >= self.soft}

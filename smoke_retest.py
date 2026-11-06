import json, time
from smoke_common import *
for model, pin, pout in [("zai-org/GLM-5.3-Flash", 0.15, 0.50),
                         ("deepseek-ai/DeepSeek-V4.1-Flash", 0.30, 1.20)]:
    ok = 0; cost = 0.0; toks = []; errs = []
    for i in range(5):
        r = client.chat.completions.create(
            model=model, temperature=0.3, max_tokens=6000,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": json.dumps(BUNDLE)}])
        u = r.usage; toks.append(u.completion_tokens)
        cost += (u.prompt_tokens * pin + u.completion_tokens * pout) / 1e6
        try:
            Draft.model_validate_json(extract(r.choices[0].message.content)); ok += 1
        except Exception as e:
            errs.append(r.choices[0].finish_reason)
    print(f"{model:36s} valid {ok}/5  out_tokens {toks}  cost ${cost:.4f}  fails {errs}")

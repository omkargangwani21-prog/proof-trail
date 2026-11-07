import json, time
from smoke_common import *
for model in ["zai-org/GLM-5.3-Flash", "deepseek-ai/DeepSeek-V4.1-Flash", "google/gemma-3-27b-it"]:
    for i in range(3):
        r = client.chat.completions.create(
            model=model, temperature=0.3, max_tokens=2000,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": json.dumps(BUNDLE)}])
        raw = r.choices[0].message.content or ""
        ch = r.choices[0]
        try:
            Draft.model_validate_json(extract(raw)); status = "OK"
        except ValidationError as e:
            status = str([(x["loc"], x["type"]) for x in e.errors()][:3])
        except Exception as e:
            status = type(e).__name__
        print(model, "| finish:", ch.finish_reason, "| out_tokens:", r.usage.completion_tokens, "|", status)
        if status != "OK":
            print("   starts:", repr(raw[:90]))
            print("   ends:  ", repr(raw[-90:]))

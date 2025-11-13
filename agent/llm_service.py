# weatherai/agent/llm_service.py

from pathlib import Path
import os
import torch
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

app = FastAPI(title="WeatherAI LLM Service")

# -------------------------------
# Paths & runtime configuration
# -------------------------------
ADAPTER_PATH = Path("/Users/mitra/vibe_code/weatherai/artifacts/adapter").resolve()

print(f"[llm_service] Using adapter dir: {ADAPTER_PATH}")
if not (ADAPTER_PATH / "adapter_config.json").exists():
    raise FileNotFoundError(f"adapter_config.json not found in {ADAPTER_PATH}")

BASE_MODEL = os.getenv("BASE_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")
TOKENIZER_PATH = os.getenv("TOKENIZER_PATH", BASE_MODEL)
DEVICE_MAP = os.getenv("DEVICE_MAP", "auto")

# Dtype: prefer float16 on GPU, else float32 on CPU
DTYPE = torch.float16 if torch.cuda.is_available() else torch.float32

MAX_NEW_TOKENS = int(os.getenv("MAX_NEW_TOKENS", "256"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.2"))
TOP_P = float(os.getenv("TOP_P", "0.95"))

# -------------------------------
# Sanity checks
# -------------------------------
if not (ADAPTER_PATH / "adapter_config.json").exists():
    raise FileNotFoundError(f"adapter_config.json not found in {ADAPTER_PATH}")

# -------------------------------
# Load base model + LoRA adapter
# -------------------------------
print(f"[LLM] Loading base model: {BASE_MODEL}")
tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_PATH, use_fast=True)

base = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL,
    torch_dtype=DTYPE,
    device_map=DEVICE_MAP,
)

print(f"[LLM] Applying LoRA adapter from {ADAPTER_PATH}")
model = PeftModel.from_pretrained(base, str(ADAPTER_PATH))
model.eval()

# -------------------------------
# Endpoints
# -------------------------------
@app.get("/health")
def health():
    return {
        "ok": True,
        "base_model": BASE_MODEL,
        "adapter": str(ADAPTER_PATH),
        "device": str(next(model.parameters()).device),
        "dtype": str(next(model.parameters()).dtype),
    }

@app.post("/generate")
async def generate(req: Request):
    data = await req.json()
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return JSONResponse(content={"text": ""})

    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

    with torch.no_grad():
        out = model.generate(
            **inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            temperature=TEMPERATURE,
            top_p=TOP_P,
            do_sample=True if TEMPERATURE > 0 else False,
        )

    text = tokenizer.decode(out[0], skip_special_tokens=True)
    return {"text": text.strip()}

# -------------------------------
# __main__ (uvicorn runner)
# -------------------------------
if __name__ == "__main__":
    import uvicorn

    host = os.getenv("LLM_HOST", "127.0.0.1")
    port = int(os.getenv("LLM_PORT", "8899"))
    print(f"[LLM] Starting FastAPI on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, reload=False)
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

# Resolve adapter dir relative to this file, so it works from any CWD
ADAPTER_PATH = Path(__file__).resolve().parents[1] / "artifacts" / "adapter"

print(f"[llm_service] Using adapter dir: {ADAPTER_PATH}")

BASE_MODEL = os.getenv("BASE_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")
TOKENIZER_PATH = os.getenv("TOKENIZER_PATH", BASE_MODEL)

# For portability: always use CPU + float32
DEVICE = "cpu"
DTYPE = torch.float32

MAX_NEW_TOKENS = int(os.getenv("MAX_NEW_TOKENS", "256"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.2"))
TOP_P = float(os.getenv("TOP_P", "0.95"))

# -------------------------------
# Load base model + optional LoRA
# -------------------------------

print(f"[LLM] Loading base model: {BASE_MODEL}")
tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_PATH, use_fast=True)

base_model = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL,
    torch_dtype=DTYPE,
    device_map=None,   # IMPORTANT: no 'auto' -> no meta/offload
)
base_model.to(DEVICE)
base_model.eval()

model = base_model

# Try to apply LoRA if adapter exists; otherwise fall back gracefully
if ADAPTER_PATH.exists() and (ADAPTER_PATH / "adapter_config.json").exists():
    try:
        print(f"[LLM] Applying LoRA adapter from {ADAPTER_PATH}")
        model = PeftModel.from_pretrained(
            base_model,
            str(ADAPTER_PATH),
            torch_dtype=DTYPE,
            device_map=None,   # keep on CPU
        )
        model.to(DEVICE)
        model.eval()
        print("[LLM] LoRA adapter loaded successfully.")
    except Exception as e:
        print(f"[LLM] Failed to load LoRA adapter: {e}")
        print("[LLM] Falling back to base model only.")
        model = base_model
else:
    print("[LLM] No adapter found or incomplete; using base model only.")

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

    inputs = tokenizer(prompt, return_tensors="pt").to(DEVICE)

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
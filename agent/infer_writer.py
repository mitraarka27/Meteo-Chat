# agent/infer_writer.py
import os, json, re
from typing import Dict, Any, Tuple
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel

BASE   = os.getenv("BASE_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")
ADAPT  = os.getenv("LORA_DIR", "artifacts/adapter")
SYSTEM = "You must output only JSON that matches agent/schema/response_schema.json."

# Lazy globals to avoid reload between Streamlit reruns
_tokenizer = None
_model     = None
_device    = None

def _device_dtype() -> Tuple[str, torch.dtype]:
    use_cuda = torch.cuda.is_available()
    use_mps  = getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()
    device   = "cuda" if use_cuda else ("mps" if use_mps else "cpu")
    dtype    = torch.float16 if (use_cuda or use_mps) else torch.float32
    return device, dtype

def _load_once():
    global _tokenizer, _model, _device
    if _model is not None:
        return
    _device, dtype = _device_dtype()
    _tokenizer = AutoTokenizer.from_pretrained(BASE, use_fast=True)
    if _tokenizer.pad_token is None:
        _tokenizer.pad_token = _tokenizer.eos_token
    base = AutoModelForCausalLM.from_pretrained(BASE, torch_dtype=dtype)
    model = PeftModel.from_pretrained(base, ADAPT)
    model.to(_device)
    model.eval()
    model.config.use_cache = True
    _model = model  # set global

def _extract_json(s: str) -> Dict[str, Any]:
    s = s.strip()
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"\{(?:.|\n)*?\}", s)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    # minimal valid schema fallback
    return {"title":"", "answer":"", "key_numbers":[], "figures":[], "method":"", "citations":[], "limitations":[], "suggested_followups":[]}

@torch.inference_mode()
def write_answer(input_obj: Dict[str, Any], max_new_tokens: int = 220) -> Dict[str, Any]:
    _load_once()
    user = json.dumps(input_obj, ensure_ascii=False)
    prompt = f"<s>[SYSTEM]{SYSTEM}\n[USER]{user}\n[ASSISTANT]"
    enc = _tokenizer(prompt, return_tensors="pt").to(_device)
    out = _model.generate(
        **enc,
        do_sample=False,
        max_new_tokens=max_new_tokens,
        eos_token_id=_tokenizer.eos_token_id
    )
    text = _tokenizer.decode(out[0], skip_special_tokens=False)
    tail = text.split("[ASSISTANT]", 1)[-1]
    return _extract_json(tail)
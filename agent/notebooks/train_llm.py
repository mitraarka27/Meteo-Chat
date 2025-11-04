"""
Tiny Writer LLM Fine-tune (LoRA, single-device, no-TRL)

- Robust JSONL load (no pyarrow)
- No TF/Flax/JAX
- Single-device training (CPU/MPS/CUDA) — avoids device_map sharding bugs
- Torch AdamW (no bitsandbytes)
- Uses transformers.Trainer + PEFT LoRA

Run:
  pip install -U torch transformers peft datasets accelerate
  BASE_MODEL='Qwen/Qwen2.5-1.5B-Instruct' python agent/notebooks/train_llm.py
"""

import os, json, random
from typing import Dict, Any, List
os.environ["TRANSFORMERS_NO_TF"] = "1"
os.environ["TRANSFORMERS_NO_FLAX"] = "1"
os.environ["TRANSFORMERS_NO_JAX"] = "1"

import torch
from datasets import Dataset
from transformers import (
    AutoTokenizer, AutoModelForCausalLM, TrainingArguments, Trainer
)
from transformers.data.data_collator import default_data_collator
from peft import LoraConfig, get_peft_model, TaskType

# ---------------- Config ----------------
DATA_PATH   = "data/train_full.nonempty.jsonl"
BASE_MODEL  = os.getenv("BASE_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")  # open, no gate
OUT_DIR     = "artifacts/adapter"
MAX_SEQ_LEN = 1024
LR          = 2e-4
EPOCHS      = 1
BATCH       = 2
GRAD_ACCUM  = 8
SEED        = 42

os.makedirs(OUT_DIR, exist_ok=True)
random.seed(SEED)

# ---------------- Data (robust JSONL) ----------------
def read_jsonl(path: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            s = line.strip()
            if not s:
                continue
            try:
                items.append(json.loads(s))
            except Exception as e:
                print(f"[skip line {ln}] {e}")
    return items

def to_text(ex: Dict[str, Any]) -> str:
    sys = ex["system"]
    usr = json.dumps(ex["input"], ensure_ascii=False)
    ans = json.dumps(ex["output"], ensure_ascii=False)
    return f"<s>[SYSTEM]{sys}\n[USER]{usr}\n[ASSISTANT]{ans}</s>"

raw = read_jsonl(DATA_PATH)
if not raw:
    raise SystemExit(f"Dataset empty: {DATA_PATH}")
texts = [to_text(r) for r in raw]
ds = Dataset.from_dict({"text": texts})
print(f"Loaded {len(ds)} training examples from {DATA_PATH}")

# ---------------- Device & dtype ----------------
use_cuda = torch.cuda.is_available()
use_mps  = getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()
device   = "cuda" if use_cuda else ("mps" if use_mps else "cpu")
dtype    = torch.float16 if (use_cuda or use_mps) else torch.float32

# ---------------- Tokenizer & Model ----------------
tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, use_fast=True)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

model = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL,
    torch_dtype=dtype,          # <- single dtype
)  # no device_map here
model.to(device)               # <- single device
model.config.use_cache = False # <- needed when training/ckpt

# ---------------- LoRA ----------------
peft_cfg = LoraConfig(
    task_type=TaskType.CAUSAL_LM,
    r=16, lora_alpha=32, lora_dropout=0.05,
    target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"]
)
model = get_peft_model(model, peft_cfg)
model.train()  # ensure training mode

# ---------------- Tokenization ----------------
def tokenize_fn(batch):
    tok = tokenizer(
        batch["text"],
        truncation=True,
        max_length=MAX_SEQ_LEN,
        padding="longest",   # pad in batch by collator
        return_attention_mask=True
    )
    # causal LM: labels = input_ids
    tok["labels"] = tok["input_ids"].copy()
    return tok

tok_ds = ds.map(tokenize_fn, batched=True, remove_columns=["text"])

# Simple collator that leaves labels intact and pads consistently
collator = default_data_collator

# ---------------- Training ----------------
# Keep it simple & version-safe
args = TrainingArguments(
    output_dir=OUT_DIR,
    num_train_epochs=EPOCHS,
    per_device_train_batch_size=BATCH,
    gradient_accumulation_steps=GRAD_ACCUM,
    learning_rate=LR,
    lr_scheduler_type="cosine",
    warmup_ratio=0.03,
    logging_steps=10,
    save_strategy="epoch",
    optim="adamw_torch",
    fp16=bool(use_cuda),  # fp16 only on CUDA; MPS runs float16 compute via dtype
    bf16=False,
    report_to=[],
    dataloader_pin_memory=False,
    gradient_checkpointing=False,  # avoid MPS/grad issues
)

trainer = Trainer(
    model=model,
    args=args,
    train_dataset=tok_ds,
    data_collator=collator,
)

trainer.train()
trainer.save_model(OUT_DIR)
tokenizer.save_pretrained(os.path.join(OUT_DIR, "..", "tokenizer"))
with open(os.path.join(OUT_DIR, "..", "config.json"), "w") as f:
    json.dump({"base_model": BASE_MODEL, "max_seq_len": MAX_SEQ_LEN}, f, indent=2)

print("✅ LoRA adapter saved to:", OUT_DIR)

# ---------------- Smoke test ----------------
from transformers import pipeline
gen = pipeline(
    "text-generation",
    model=model,
    tokenizer=tokenizer,
    device=0 if device=="cuda" else -1,
    max_new_tokens=200,
    do_sample=False,
    temperature=0.1,
    top_p=0.9
)
probe = texts[0].split("[USER]", 1)[1]
sample = gen(f"[SYSTEM]You must output only JSON.\n[USER]{probe}\n[ASSISTANT]")[0]["generated_text"]
print("\n--- SMOKE TEST (tail) ---")
print(sample[-500:])
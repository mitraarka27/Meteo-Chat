# agent/test/sanity.py
import json, sys
from agent.infer_writer import write_answer

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "data/train_full.nonempty.jsonl"
    ok = bad = 0
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            ex = json.loads(line)
            out = write_answer(ex["input"])
            has_title = bool(out.get("title"))
            has_answer = bool(out.get("answer"))
            cites_ok = isinstance(out.get("citations", []), list)
            if has_title and has_answer and cites_ok:
                ok += 1
            else:
                bad += 1
            if i % 20 == 0:
                print(f"[{i}] ok={ok} bad={bad}")
    print(f"✅ done: ok={ok} bad={bad}")

if __name__ == "__main__":
    main()
"""Test multi-line prompt with claude CLI."""
import subprocess, threading, json, time, sys

text = sys.argv[1] if len(sys.argv) > 1 else "你好\n你知道我是谁吗"
claude = r"C:\Users\34355\AppData\Roaming\npm\claude.cmd"
args = [claude, "-p", text, "--output-format", "stream-json", "--verbose"]
print(f"Text repr: {repr(text)}")

proc = subprocess.Popen(
    args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    creationflags=0x08000000,
)

stderr_lines = []
def drain():
    for line in iter(proc.stderr.readline, b""):
        stderr_lines.append(line)
threading.Thread(target=drain, daemon=True).start()

deadline = time.time() + 25
for line in iter(proc.stdout.readline, b""):
    if time.time() > deadline:
        print("TIMEOUT after 25s")
        break
    s = line.decode("utf-8", errors="replace").strip()
    if not s:
        continue
    try:
        evt = json.loads(s)
        t = evt.get("type", "?")
        if t == "result":
            print(f"RESULT: subtype={evt.get('subtype')} cost=${evt.get('total_cost_usd', '?')}")
            print(f"  reply: {evt.get('result', '')[:200]}")
            break
        elif t == "assistant":
            for c in evt.get("message", {}).get("content", []):
                ct = c.get("type", "?")
                if ct == "text":
                    print(f"TEXT: {c['text'][:200]}")
                elif ct == "thinking":
                    print(f"THINK: {c.get('thinking', '')[:100]}...")
    except json.JSONDecodeError:
        print(f"NON-JSON: {s[:100]}")

print(f"Stderr ({len(stderr_lines)} lines):")
for l in stderr_lines[:5]:
    print(f"  {l.decode('utf-8', errors='replace').strip()[:200]}")

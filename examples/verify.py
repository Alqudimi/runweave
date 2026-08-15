from pathlib import Path

value = Path("build/hello.txt").read_text(encoding="utf-8")
if value != "hello\n":
    raise SystemExit(f"unexpected content: {value!r}")
print("verified build/hello.txt")

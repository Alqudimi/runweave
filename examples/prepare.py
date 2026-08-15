from pathlib import Path

build = Path("build")
build.mkdir(exist_ok=True)
(build / "hello.txt").write_text("hello\n", encoding="utf-8")
print("prepared build/hello.txt")

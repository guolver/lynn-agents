#!/usr/bin/env python3
"""AI-powered CI error fixer. Supports any OpenAI-compatible API (DeepSeek, OpenAI, etc.)"""

import os
import subprocess
import sys
from pathlib import Path

# Try openai package, install if missing
try:
    from openai import OpenAI
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "openai", "-q"])
    from openai import OpenAI


def read_file(path: str) -> str:
    """Read file content."""
    return Path(path).read_text()


def write_file(path: str, content: str) -> None:
    """Write file content."""
    Path(path).write_text(content)


def apply_fix(file_path: str, old_content: str, new_content: str) -> bool:
    """Apply a fix to a file."""
    try:
        current = Path(file_path).read_text()
        if old_content in current:
            updated = current.replace(old_content, new_content, 1)
            Path(file_path).write_text(updated)
            print(f"  ✓ Fixed: {file_path}")
            return True
        else:
            print(f"  ⚠ Content not found in {file_path}")
            return False
    except Exception as e:
        print(f"  ✗ Error fixing {file_path}: {e}")
        return False


def main():
    # Configuration from environment
    api_key = (
        os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
    )
    base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
    model = os.getenv("LLM_MODEL", "deepseek-v4-flash")

    if not api_key:
        print("Error: Set LLM_API_KEY, DEEPSEEK_API_KEY, or OPENAI_API_KEY")
        sys.exit(1)

    # Read error log
    error_log = sys.stdin.read() if not sys.stdin.isatty() else ""
    if not error_log and len(sys.argv) > 1:
        error_log = Path(sys.argv[1]).read_text()

    if not error_log:
        print("Usage: cat errors.log | python ai-fix.py")
        print("   or: python ai-fix.py errors.log")
        sys.exit(1)

    print(f"Using {model} at {base_url}")
    print(f"Error log: {len(error_log)} chars")

    client = OpenAI(api_key=api_key, base_url=base_url)

    # First pass: analyze errors and get fix plan
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": """You are a CI error fixer. Analyze the error log and output fixes in this exact format:

For each fix, output:
---FIX---
FILE: <file_path>
OLD:
```
<exact content to replace>
```
NEW:
```
<new content>
```
---END---

Rules:
- Only fix the specific errors shown
- Use exact content matches (copy from error messages)
- One fix per ---FIX--- block
- If you cannot fix, output ---SKIP--- with explanation""",
            },
            {
                "role": "user",
                "content": f"Fix these CI errors:\n\n{error_log[:15000]}",  # Truncate for token limits
            },
        ],
        temperature=0,
        max_tokens=4000,
    )

    result = response.choices[0].message.content
    print("\n=== AI Response ===")
    print(result[:1000] + "..." if len(result) > 1000 else result)

    # Parse and apply fixes
    fixes_applied = 0
    for block in result.split("---FIX---")[1:]:
        if "---END---" not in block:
            continue
        block = block.split("---END---")[0]

        try:
            # Parse FILE:
            file_line = [line for line in block.split("\n") if line.startswith("FILE:")][0]
            file_path = file_line.replace("FILE:", "").strip()

            # Parse OLD and NEW blocks
            old_match = block.split("OLD:")[1].split("NEW:")[0]
            new_match = block.split("NEW:")[1]

            # Extract content between ``` markers
            def extract_code(text):
                if "```" in text:
                    parts = text.split("```")
                    if len(parts) >= 2:
                        code = parts[1]
                        # Remove language identifier if present
                        if code.startswith(
                            ("python", "typescript", "javascript", "tsx", "ts", "py")
                        ):
                            code = "\n".join(code.split("\n")[1:])
                        return code.strip()
                return text.strip()

            old_content = extract_code(old_match)
            new_content = extract_code(new_match)

            if old_content and file_path:
                if apply_fix(file_path, old_content, new_content):
                    fixes_applied += 1

        except Exception as e:
            print(f"  ⚠ Parse error: {e}")
            continue

    print(f"\n=== Applied {fixes_applied} fixes ===")
    return 0 if fixes_applied > 0 else 1


if __name__ == "__main__":
    sys.exit(main())

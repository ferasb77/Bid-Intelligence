"""
Script: Audit git history for accidentally committed secrets across commits on current branch
"""
import subprocess
import re

PATTERNS = [
    re.compile(r'sk-ant-api03-[A-Za-z0-9_-]{40,}'),
    re.compile(r'eyJhbGciOi[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+'),
    re.compile(r'wrkspc_[A-Za-z0-9_-]{15,}'),
]

IGNORE_SNIPPETS = [
    "paste-your-key-here",
    "your-supabase-service-role-key-here",
    "sk-ant-...",
    "sk-ant-paste",
    "eyJ...",
]

def main():
    res = subprocess.run(["git", "log", "-p", "origin/main..HEAD"], capture_output=True, text=True, errors="ignore")
    lines = res.stdout.splitlines()
    findings = []
    
    for idx, line in enumerate(lines):
        if line.startswith("+") and not line.startswith("+++"):
            content = line[1:].strip()
            for p in PATTERNS:
                m = p.search(content)
                if m:
                    val = m.group(0)
                    if not any(ign in val for ign in IGNORE_SNIPPETS):
                        findings.append(f"Line {idx}: {val[:12]}...")

    print(f"Git History Secrets Scanned: {len(lines)} diff lines inspected.")
    print(f"Secret Findings in Branch History: {len(findings)}")
    if findings:
        for f in findings:
            print("  Warning:", f)
    else:
        print("  VERIFIED: Zero secrets detected in git commit history on this branch.")

if __name__ == "__main__":
    main()

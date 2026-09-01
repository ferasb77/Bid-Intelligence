"""
Secret and Raw File Audit Script
Scans all tracked files for secret patterns and raw binary procurement documents.
"""
import os
import re
import subprocess

tracked_files = subprocess.check_output(['git', 'ls-files']).decode('utf-8').splitlines()

secret_patterns = [
    (re.compile(r'sk-ant-api[0-9a-zA-Z_\-]{20,}'), 'Anthropic API Key'),
    (re.compile(r'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\.[0-9a-zA-Z_\-]{20,}'), 'JWT / Supabase Service Key'),
    (re.compile(r'ghp_[0-9a-zA-Z]{30,}'), 'GitHub Token'),
    (re.compile(r'-----BEGIN (?:RSA |EC )?PRIVATE KEY-----'), 'Private Key'),
    (re.compile(r'SUPABASE_SERVICE_KEY\s*=\s*["\'][a-zA-Z0-9_\-\.]{30,}["\']'), 'Hardcoded Supabase Key'),
    (re.compile(r'ANTHROPIC_API_KEY\s*=\s*["\'][a-zA-Z0-9_\-\.]{30,}["\']'), 'Hardcoded Anthropic Key'),
]

raw_file_extensions = ['.pdf', '.docx', '.xlsx', '.zip', '.doc', '.xls', '.ppt', '.pptx']

secret_violations = []
raw_file_violations = []

for fpath in tracked_files:
    ext = os.path.splitext(fpath)[1].lower()
    if ext in raw_file_extensions:
        raw_file_violations.append((fpath, f'Raw procurement document ({ext})'))

    if not os.path.exists(fpath):
        continue

    try:
        with open(fpath, 'r', encoding='utf-8', errors='ignore') as fp:
            content = fp.read()
            for pat, desc in secret_patterns:
                if pat.search(content):
                    secret_violations.append((fpath, desc))
    except Exception:
        pass

print('============================================================')
print('SECRET AND RAW PROCUREMENT FILE AUDIT')
print('============================================================')
print(f'Total Tracked Files: {len(tracked_files)}')

print('\n1. Secret Pattern Scan:')
if secret_violations:
    print('  [FAIL] Secrets found in tracked files:')
    for f, desc in secret_violations:
        print(f'    - {f}: {desc}')
else:
    print('  [PASS] 0 secrets detected across all tracked files.')

print('\n2. Raw Procurement File Scan:')
if raw_file_violations:
    print('  [FAIL] Raw procurement files found in repository:')
    for f, desc in raw_file_violations:
        print(f'    - {f}: {desc}')
else:
    print('  [PASS] 0 raw procurement files tracked in repository.')

print('============================================================')

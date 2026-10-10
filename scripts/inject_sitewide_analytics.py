#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAG = '<script src="/analytics.js" defer></script>'
SKIP = {
    ROOT / 'index.html',  # homepage already has its own consent-aware GA4 implementation
}
EXCLUDED_DIRS = {'.git', '.github', 'node_modules'}

changed = 0
scanned = 0

for path in ROOT.rglob('*.html'):
    if path in SKIP:
        continue
    if any(part in EXCLUDED_DIRS for part in path.parts):
        continue

    scanned += 1
    text = path.read_text(encoding='utf-8')
    if TAG in text or 'G-QKVW0EETP0' in text:
        continue
    if '</head>' not in text:
        print(f'SKIP no </head>: {path.relative_to(ROOT)}')
        continue

    text = text.replace('</head>', TAG + '\n</head>', 1)
    path.write_text(text, encoding='utf-8')
    changed += 1

print(f'Scanned {scanned} static HTML files; injected analytics into {changed}.')

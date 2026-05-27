#!/usr/bin/env python3
"""
run_explain_series.py

Run explain.py over a small audit case list and serialize the diagnostic
outputs to text files. This is intentionally simple infrastructure: it does
not judge correctness, it just makes the diagnostics reproducible.

Example:
    python run_explain_series.py \
      --audit audit_cases_v2.json \
      --output-dir output_v2_9/liz \
      --explain-script explain_v2_9.py \
      --out diagnostics/explain_v2

Useful subsets:
    python run_explain_series.py --audit audit_cases_v2.json --output-dir output_v2_9/liz \
      --explain-script explain_v2_9.py --out diagnostics/explain_v2 --tag consensus

Dry run only:
    python run_explain_series.py --audit audit_cases_v2.json --output-dir output_v2_9/liz \
      --explain-script explain_v2_9.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def safe_float_token(x: Any) -> str:
    return str(x).replace('.', 'p').replace('-', 'm')


def safe_name(s: str) -> str:
    return re.sub(r'[^A-Za-z0-9_.-]+', '_', s).strip('_')


def iter_points(case: dict[str, Any], include_reference: bool) -> list[dict[str, Any]]:
    points = case.get('diagnostic_points', [])
    if include_reference:
        return points
    return [p for p in points if p.get('part_index') == case.get('part_index')]


def main() -> int:
    parser = argparse.ArgumentParser(description='Serialize explain.py diagnostics for audit cases.')
    parser.add_argument('--audit', required=True, help='audit_cases_v2.json')
    parser.add_argument('--output-dir', required=True, help='sectioning output dir containing result.pkl')
    parser.add_argument('--explain-script', default='explain.py', help='path to explain.py / explain_v2_9.py')
    parser.add_argument('--out', default='diagnostics/explain_batch', help='directory for serialized explain outputs')
    parser.add_argument('--python', default=sys.executable, help='Python executable')
    parser.add_argument('--window', type=float, default=4.0)
    parser.add_argument('--case', action='append', default=[], help='case id to include; may repeat')
    parser.add_argument('--tag', action='append', default=[], help='include cases with this tag; may repeat')
    parser.add_argument('--include-reference', action='store_true', help='also run explain points for reference parts')
    parser.add_argument('--dry-run', action='store_true', help='write command list but do not run commands')
    args = parser.parse_args()

    audit_path = Path(args.audit)
    audit = json.loads(audit_path.read_text())
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    selected = []
    wanted_cases = set(args.case)
    wanted_tags = set(args.tag)
    for case in audit.get('cases', []):
        if wanted_cases and case.get('id') not in wanted_cases:
            continue
        if wanted_tags and not (wanted_tags & set(case.get('tags', []))):
            continue
        selected.append(case)

    commands = []
    manifest = {
        'audit': str(audit_path),
        'output_dir': args.output_dir,
        'explain_script': args.explain_script,
        'window': args.window,
        'dry_run': args.dry_run,
        'outputs': [],
    }

    seen = set()
    for case in selected:
        for p in iter_points(case, include_reference=args.include_reference):
            part_idx = int(p['part_index'])
            measure = int(p['measure'])
            beat = float(p['beat'])
            key = (case['id'], part_idx, measure, round(beat, 6))
            if key in seen:
                continue
            seen.add(key)

            filename = (
                f"{case['id']}__part{part_idx:02d}__m{measure:03d}__b{safe_float_token(beat)}.txt"
            )
            output_path = out_dir / filename
            cmd = [
                args.python,
                args.explain_script,
                args.output_dir,
                str(part_idx),
                str(measure),
                str(beat),
                '--window',
                str(args.window),
            ]
            commands.append(' '.join(cmd) + f" > {output_path}")

            record = {
                'case_id': case['id'],
                'case_summary': case.get('summary'),
                'case_tags': case.get('tags', []),
                'part_index': part_idx,
                'measure': measure,
                'beat': beat,
                'why': p.get('why', ''),
                'output_file': str(output_path),
                'command': cmd,
            }

            if args.dry_run:
                manifest['outputs'].append(record | {'returncode': None})
                continue

            proc = subprocess.run(cmd, text=True, capture_output=True)
            output_path.write_text(proc.stdout)
            if proc.stderr:
                err_path = output_path.with_suffix('.stderr.txt')
                err_path.write_text(proc.stderr)
                record['stderr_file'] = str(err_path)
            record['returncode'] = proc.returncode
            manifest['outputs'].append(record)

    (out_dir / 'commands.sh').write_text('#!/usr/bin/env bash\nset -euo pipefail\n' + '\n'.join(commands) + '\n')
    (out_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2))

    print(f"Selected cases: {len(selected)}")
    print(f"Explain points: {len(manifest['outputs'])}")
    print(f"Wrote: {out_dir / 'commands.sh'}")
    print(f"Wrote: {out_dir / 'manifest.json'}")
    if args.dry_run:
        print('Dry run only; no explain commands executed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

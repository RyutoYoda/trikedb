"""Audit saved answer logs without calling models or changing raw results.

python benchmarks/validate_saved.py bench_out --out audit.json
Raw logs are local research inputs, not bundled with the distribution.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics

import webqsp_bench as wq


def audit(root: Path) -> dict:
    rows = []
    for path in sorted(root.rglob('*.jsonl')):
        if not (path.name.startswith('ans_') or path.name.startswith('agent_')):
            continue
        evaluation = path.parent / 'eval_set.json'
        if path.parent == root:
            evaluation = root / 'hybrid' / 'eval_set.json'
        if not evaluation.exists():
            continue
        entries = json.loads(evaluation.read_text())
        gold = {e['id']: e['answers'] for e in entries}
        if len(gold) != len(entries):
            raise ValueError(f'Duplicate evaluation IDs: {evaluation}')
        records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        wq.validate_records(records, gold)
        n = len(records)
        hits = sum(wq.hits_at_1(r['answer'], gold[r['id']]) for r in records)
        row = dict(file=str(path.relative_to(root)), n=n, eval_n=len(gold),
                   missing=len(gold)-n, hits_at_1=round(100*hits/n, 1),
                   f1=round(100*sum(wq.f1(r['answer'], gold[r['id']]) for r in records)/n, 1))
        if all('prompt_tokens' in r for r in records):
            row['median_prompt_tokens'] = int(statistics.median(r['prompt_tokens'] for r in records))
        if all('total_input_tokens' in r for r in records):
            row['median_total_input_tokens'] = int(statistics.median(r['total_input_tokens'] for r in records))
        rows.append(row)
    if not rows:
        raise ValueError('No matching saved answer logs found')
    return {'metric': 'local substring matching; not official WebQSP', 'files': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.root)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(f"Validated {len(result['files'])} files")

"""Audit probe: read existing evidence; vary one job read in memory; rerun L3.

Does not call VerificationService, write the source database, or access keys.
All new execution artifacts go below this audit directory.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from researchflow.contracts.encoding import hash_payload
from researchflow.verification.context import load_context
from researchflow.verification.l1 import L1Verifier
from researchflow.verification.l2 import L2Verifier
from researchflow.verification.l3 import L3Verifier


def read_only_connection(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def main() -> int:
    started = datetime.now(timezone.utc).isoformat()
    clock = time.perf_counter()
    source = ROOT / 'docs/verification/t0/e2e/run_1'
    runtime = source / 'runtime'
    os.environ['RESEARCHFLOW_DATA_ROOT'] = str(source / 'data')
    summaries = json.loads((source.parent / 'runs_summary.json').read_text(encoding='utf-8'))
    task_id = summaries['runs'][0]['task_id']
    with patch('researchflow.verification.context.connect', read_only_connection):
        context = load_context(runtime / 'researchflow.db', runtime, task_id)
    node_id = 'train_logistic_regression'
    job_path = context.attempt_dir(node_id, context.nodes[node_id].attempt_seq) / 'job.json'
    original_bytes = job_path.read_bytes()
    job = json.loads(original_bytes)
    original_seed = job['parameters']['seed']
    job['parameters']['seed'] = original_seed + 1
    real_read_text = Path.read_text

    def altered_read(path, *args, **kwargs):
        if path.resolve() == job_path.resolve():
            return json.dumps(job)
        return real_read_text(path, *args, **kwargs)

    output = Path(__file__).parent / ('run_' + uuid.uuid4().hex[:8])
    output.mkdir(exist_ok=False)
    with patch.object(Path, 'read_text', altered_read):
        l1 = L1Verifier().run(context)
        l2 = L2Verifier().run(context)
        l3 = L3Verifier(output, python_executable=sys.executable, repo_root=ROOT).run(context)
    original_unchanged = job_path.read_bytes() == original_bytes
    spec = next(item for item in context.graph.nodes if item['node_id'] == node_id)
    e2 = context.latest_payload(node_id, 'E2', 'executor_launch')
    reproduced = (
        original_unchanged
        and hash_payload(job['parameters']) != spec['parameters_hash']
        and l1.status == l2.status == l3.status == 'PASS'
    )
    report = {
        'purpose': 'Negative audit: changed job parameters must not silently pass reproduction verification',
        'command': str(sys.executable) + ' -B reports/t0_review_20261114/l3_parameter_probe.py',
        'cwd': str(ROOT), 'interpreter': sys.executable, 'python_version': sys.version,
        'permission': 'sandbox escalation approved for this scoped probe',
        'started_at': started, 'ended_at': datetime.now(timezone.utc).isoformat(),
        'duration_sec': round(time.perf_counter() - clock, 3),
        'source_task_id': task_id, 'source_job_path': str(job_path),
        'source_job_sha256': hashlib.sha256(original_bytes).hexdigest(),
        'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'original_job_unchanged': original_unchanged,
        'injection': 'Path.read_text only for one job, in parent memory; child reruns are real',
        'original_seed': original_seed, 'injected_seed': job['parameters']['seed'],
        'injected_parameters_hash': hash_payload(job['parameters']),
        'nodespec_parameters_hash': spec['parameters_hash'],
        'e2_parameters_hash': e2['parameters_hash'],
        'l1': l1.status, 'l2': l2.status, 'l3': l3.to_dict(),
        'parameter_integrity_gap_reproduced': reproduced,
        'certificate_issuance_tested': False,
        'exit_code': 0 if reproduced else 1,
    }
    report_path = output / 'probe_report.json'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'report': str(report_path), 'l1': l1.status, 'l2': l2.status,
                      'l3': l3.status, 'gap_reproduced': reproduced,
                      'original_unchanged': original_unchanged}, ensure_ascii=False))
    return report['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())

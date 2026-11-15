"""Inspect publish candidates without printing secret values or reading key files."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent


def git(*args):
    result = subprocess.run(['git', '-c', 'core.quotepath=false', *args], cwd=ROOT,
                            capture_output=True, timeout=120)
    if result.returncode:
        raise RuntimeError('Git failed: ' + ' '.join(args))
    return result.stdout


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'working'
    if mode not in {'working', 'staged'}:
        raise SystemExit('mode must be working or staged')
    offline_paths = '--paths-file' in sys.argv
    if offline_paths:
        if mode != 'working':
            raise SystemExit('paths-file supports working mode only')
        # Direct shell Git export avoids spawning Git from Python in restricted Windows.
        paths = sorted(set((OUT / 'candidate_paths.txt').read_text(encoding='utf-8-sig').splitlines()))
        head = (OUT / 'candidate_head.txt').read_text(encoding='utf-8-sig').strip()
    else:
        args = ['ls-files', '-z', '--cached']
        if mode == 'working':
            args += ['--others', '--exclude-standard']
        paths = sorted(set(x.decode('utf-8') for x in git(*args).split(b'\0') if x))
        head = git('rev-parse', 'HEAD').decode().strip()
    forbidden = re.compile(r'(^|/)(\.env(?:\..*)?|[^/]*credentials[^/]*|id_rsa[^/]*|id_ed25519[^/]*)(/|$)|\.(?:private\.json|pem|key|p12|pfx|db(?:-wal|-shm)?|sqlite(?:3)?(?:-wal|-shm)?)$', re.I)
    patterns = {
        'private-key-block': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----[\r\n]+[A-Za-z0-9+/=]{32,}'),
        'github-token': re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})'),
        'api-key-format': re.compile(rb'\bsk-[A-Za-z0-9_-]{24,}\b'),
        'aws-access-key': re.compile(rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
        'private-key-json': re.compile(rb'"(?:private_key|private_key_b64|private_key_hex|private_bytes)"\s*:\s*"[A-Za-z0-9+/=_-]{40,}"'),
    }
    findings = []
    manifest = []
    for rel in paths:
        if forbidden.search(rel):
            if rel.endswith('.env.example'):
                pass
            else:
                findings.append({'path': rel, 'reason': 'forbidden-file-name-not-read'})
                continue
        path = ROOT / rel
        if mode == 'working':
            if not path.is_file():
                findings.append({'path': rel, 'reason': 'missing-file'})
                continue
            data = path.read_bytes()
        else:
            data = git('show', ':' + rel)
        if len(data) > 50 * 1024 * 1024:
            findings.append({'path': rel, 'reason': 'over-50MiB'})
        # Text only; screenshots are checked by filename/size and source review.
        if b'\0' not in data[:8192]:
            for label, pattern in patterns.items():
                for match in pattern.finditer(data):
                    findings.append({'path': rel, 'reason': label,
                                     'line': data.count(b'\n', 0, match.start()) + 1})
        manifest.append({'path': rel, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    report = {'date': datetime.now().astimezone().isoformat(), 'mode': mode,
              'command': str(sys.executable) + ' -B ' + str(Path(__file__)) + ' ' + mode + (' --paths-file' if offline_paths else ''),
              'python': sys.version, 'cwd': str(ROOT), 'head': head,
              'file_count': len(manifest), 'total_bytes': sum(x['bytes'] for x in manifest),
              'findings': findings,
              'limitation': 'Pattern and path scan plus manual scope review; not proof that no secret can exist.',
              'manifest': manifest}
    report_path = OUT / (mode + '_audit.json')
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if mode == 'working':
        (OUT / 'candidates.nul').write_bytes(b'\0'.join(x.encode('utf-8') for x in paths) + b'\0')
    print(json.dumps({'report': str(report_path), 'file_count': report['file_count'],
                      'total_bytes': report['total_bytes'], 'findings': findings}, ensure_ascii=False))
    return 1 if findings else 0


if __name__ == '__main__':
    raise SystemExit(main())

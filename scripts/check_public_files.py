"""Check Git publication candidates without printing possible secret values."""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    result = subprocess.run(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
        cwd=ROOT, check=True, capture_output=True,
    )
    paths = sorted(set(result.stdout.decode('utf-8').split('\0')) - {''})
    # This is a narrow guard, not a complete secret detector.
    patterns = [
        re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
        re.compile(r'gh[pousr]_[A-Za-z0-9]{30,}'),
        re.compile(r'github_pat_[A-Za-z0-9_]{40,}'),
        re.compile(r'(?im)^BILI_PLATFORM_(?:SID|AUX_SECRET_KEY)\s*=\s*[\w/+\-]{20,}'),
    ]
    problems = []
    for name in paths:
        rel = Path(name)
        if (rel.name in {'state.json', 'secret.key', '.env', 'MIGRATION.md'}
                or rel.suffix.lower() in {'.pem', '.key'}
                or any(part in {'.venv', '.test-deps', '__pycache__', 'data', 'dist'} for part in rel.parts)
                or rel.name.startswith('preview-sample')):
            problems.append(f'{name}: private/runtime file')
            continue
        data = (ROOT / rel).read_bytes()
        if b'\0' in data:
            problems.append(f'{name}: binary file requires manual review')
            continue
        text = data.decode('utf-8')
        if any(pattern.search(text) for pattern in patterns):
            problems.append(f'{name}: possible credential')
    for message in problems:
        print(message)
    print(f'Checked {len(paths)} publication candidates; {len(problems)} issue(s).')
    return bool(problems)


if __name__ == '__main__':
    raise SystemExit(main())

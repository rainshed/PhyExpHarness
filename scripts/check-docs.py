"""Check local Markdown navigation; semantic claims still require implementation review."""
import json
import re
import subprocess
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def prose(source):
    """Preserve line numbers but ignore fenced examples and multiline comments."""
    source = re.sub(r'<!--.*?-->', lambda m: '\n' * m[0].count('\n'), source, flags=re.S)
    lines = []
    fence = None
    for line in source.splitlines():
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            lines.append('')
        else:
            lines.append('' if fence else line)
    return '\n'.join(lines)


def anchors(source):
    clean = prose(source)
    found = set(re.findall(r'<(?:a|h[1-6])\b[^>]*\b(?:id|name)=[\'"]([^\'"]+)[\'"]', clean))
    counts = {}
    for line in clean.splitlines():
        heading = re.match(r'^\s{0,3}#{1,6}\s+(.+?)(?:\s+#+)?$', line)
        if not heading:
            continue
        label = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', heading[1])
        label = re.sub(r'<[^>]+>', '', label).lower()
        slug = ''.join(c for c in label if c in ' _-' or unicodedata.category(c)[0] in 'LNM').replace(' ', '-')
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        found.add(slug + (f'-{count}' if count else ''))
    return found


def links(source):
    clean = prose(source)
    # Inline code can contain sample Markdown that is not navigation.
    clean = re.sub(r'(`+)(.+?)\1', '', clean)
    for number, line in enumerate(clean.splitlines(), 1):
        for match in re.finditer(r'\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+[\'"][^\'"]*[\'"])?\s*\)', line):
            yield number, match[1] or match[2]
        for match in re.finditer(r'^\s{0,3}\[[^\]]+\]:\s*(?:<([^>]+)>|(\S+))', line):
            yield number, match[1] or match[2]


def documentation_files(root):
    # Git also lists new, non-ignored pages so the check works before staging.
    # Fall back for source archives without Git metadata.
    try:
        result = subprocess.run(['git', '-C', str(root), 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                                capture_output=True, check=True)
        paths = {Path(p.decode()) for p in result.stdout.split(b'\0') if p}
    except subprocess.CalledProcessError:
        paths = {Path('README.md'), Path('AGENTS.md')}
        excluded = {'node_modules', '__pycache__', 'lib', 'reference', 'brainstorm'}
        def walk(directory):
            if not directory.is_dir():
                return
            for child in directory.iterdir():
                if child.is_symlink() or child.name in excluded:
                    continue
                if child.is_dir():
                    walk(child)
                elif child.suffix == '.md':
                    paths.add(child.relative_to(root))
        for name in ('docs', 'knowledge', 'packages', 'templates'):
            walk(root / name)
    return sorted(p for p in paths if p.suffix == '.md' and (root / p).is_file()
                  and (p.as_posix() in ('README.md', 'AGENTS.md') or p.parts[0] in ('docs', 'knowledge', 'packages', 'templates'))
                  and not any(x in p.parts for x in ('node_modules', 'lib', 'brainstorm'))
                  and not p.as_posix().startswith('knowledge/plugin-sdk/reference/'))


def check(root, files=None):
    root = Path(root).resolve()
    files = documentation_files(root) if files is None else files
    errors, edges, cache = [], {}, {}
    for relative in files:
        file = root / relative
        edges[relative] = set()
        for line, url in links(file.read_text()):
            parsed = urlsplit(url)
            if parsed.scheme or parsed.netloc:
                continue
            target = (root / unquote(parsed.path).lstrip('/') if parsed.path.startswith('/')
                      else file.parent / unquote(parsed.path)) if parsed.path else file
            target = target.resolve()
            where = f'{relative}:{line}'
            if not target.is_relative_to(root) or not target.exists():
                errors.append(f'{where}: missing or outside repository: {url}')
                continue
            destination = target.relative_to(root)
            edges[relative].add(destination)
            current = relative.parts[0] == 'docs' and 'archive' not in relative.parts
            if current and destination.as_posix().startswith('docs/archive/') and destination != Path('docs/archive/README.md'):
                errors.append(f'{where}: current documentation must link current rules, not an archived page: {url}')
            if parsed.fragment and target.suffix == '.md':
                if destination not in cache:
                    cache[destination] = anchors(target.read_text())
                if unquote(parsed.fragment) not in cache[destination]:
                    errors.append(f'{where}: missing heading: {url}')
    # All current pages must be discoverable without going through historical drafts.
    reached, pending = set(), [Path('docs/README.md')]
    while pending:
        page = pending.pop()
        if page in reached or 'archive' in page.parts:
            continue
        reached.add(page)
        pending.extend(edges.get(page, set()))
    for page in files:
        if page.parts[0] == 'docs' and 'archive' not in page.parts and page not in reached:
            errors.append(f'{page}: unreachable from docs/README.md')
    return errors


if __name__ == '__main__':
    pages = documentation_files(ROOT)
    errors = check(ROOT, pages)
    print(json.dumps({'status': 'failed' if errors else 'passed', 'pages': len(pages), 'errors': errors}, ensure_ascii=False, indent=2))
    raise SystemExit(bool(errors))

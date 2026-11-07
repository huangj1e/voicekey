#!/usr/bin/env python3
"""Add VoiceKey to Omarchy's JSONC menu while preserving comments and symlinks."""
import json
import re
import shutil
import sys
import time
from pathlib import Path

KEY = 'setup.default.dictation.voicekey'
ENTRY = {
    'icon': '', 'label': 'VoiceKey',
    'checked': '[[ "$(omarchy-default-dictation)" == "voicekey" ]]',
    'action': 'omarchy-install-dictation-voicekey',
}

def tokens(text):
    out = []
    i = 0
    while i < len(text):
        if text[i].isspace():
            i += 1
        elif text.startswith('//', i):
            end = text.find('\n', i + 2)
            i = len(text) if end < 0 else end
        elif text.startswith('/*', i):
            end = text.find('*/', i + 2)
            if end < 0:
                raise ValueError('unclosed comment')
            i = end + 2
        elif text[i] == '"':
            _, end = json.JSONDecoder().raw_decode(text, i)
            out.append((text[i:end], i, end))
            i = end
        elif text[i] in '{}[]:,':
            out.append((text[i], i, i + 1))
            i += 1
        else:
            match = re.match(r'[^\s{}\[\]:,]+', text[i:])
            if not match:
                raise ValueError('invalid JSONC')
            end = i + len(match.group())
            out.append((text[i:end], i, end))
            i = end
    return out

def update(text):
    ts = tokens(text)
    clean = ''.join(t[0] for i, t in enumerate(ts)
                    if not (t[0] == ',' and i + 1 < len(ts) and ts[i + 1][0] in '}]'))
    parsed = json.loads(clean)
    if not isinstance(parsed, dict):
        raise ValueError('menu root must be an object')
    items = parsed.get('items')
    wrapped = isinstance(items, dict)
    selected = items if wrapped else parsed
    if KEY in selected:
        return text
    if not ts or ts[0][0] != '{':
        raise ValueError('menu root must be an object')
    stack = []
    pairs = {}
    for i, (token, _, _) in enumerate(ts):
        if token in ('{', '['):
            stack.append(i)
        elif token in ('}', ']'):
            if not stack:
                raise ValueError('unbalanced menu')
            pairs[stack.pop()] = i
    root = 0
    if wrapped:
        depth = 0
        for i, (token, _, _) in enumerate(ts):
            if token in ('{', '['): depth += 1
            elif token in ('}', ']'): depth -= 1
            if depth == 1 and token == '"items"' and i + 2 < len(ts) and ts[i+1][0] == ':' and ts[i+2][0] == '{':
                root = i + 2
                break
        else:
            raise ValueError('cannot find items object')
    end_index = pairs[root]
    close = ts[end_index][1]
    last = ts[end_index - 1]
    comma_at = last[2] if last[0] not in ('{', ',') else None
    line = '\n  ' + json.dumps(KEY, ensure_ascii=False) + ': ' + json.dumps(ENTRY, ensure_ascii=False) + '\n'
    result = text[:close] + line + text[close:]
    if comma_at is not None:
        result = result[:comma_at] + ',' + result[comma_at:]
    # Validate our output before touching the user's file.
    result_tokens = tokens(result)
    json.loads(''.join(t[0] for i, t in enumerate(result_tokens)
                       if not (t[0] == ',' and i + 1 < len(result_tokens) and result_tokens[i+1][0] in '}]')))
    return result

def main(path):
    path = Path(path)
    old = path.read_text() if path.exists() else '{}\n'
    new = update(old)
    if new == old:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + '.voicekey-backup-' + str(time.time_ns())))
    path.write_text(new)

if __name__ == '__main__':
    try:
        main(sys.argv[1])
    except (OSError, ValueError, IndexError) as error:
        sys.exit(f'Cannot update Omarchy menu: {error}')

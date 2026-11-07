#!/usr/bin/env python3
"""Manage VoiceKey in Omarchy's JSONC menu while preserving comments and symlinks."""
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

def remove(text):
    ts = tokens(text)
    clean = ''.join(t[0] for i, t in enumerate(ts)
                    if not (t[0] == ',' and i + 1 < len(ts) and ts[i + 1][0] in '}]'))
    parsed = json.loads(clean)
    if not isinstance(parsed, dict):
        raise ValueError('menu root must be an object')
    selected = parsed.get('items') if isinstance(parsed.get('items'), dict) else parsed
    # A user-edited entry is theirs; never remove it silently.
    if selected.get(KEY) != ENTRY:
        return text
    stack, pairs = [], {}
    for i, (token, _, _) in enumerate(ts):
        if token in ('{', '['): stack.append(i)
        elif token in ('}', ']'): pairs[stack.pop()] = i
    root = 0
    if selected is not parsed:
        depth = 0
        for i, (token, _, _) in enumerate(ts):
            if token in ('{', '['): depth += 1
            elif token in ('}', ']'): depth -= 1
            if depth == 1 and token == '"items"' and ts[i+1][0] == ':' and ts[i+2][0] == '{':
                root = i + 2
                break
        else:
            raise ValueError('cannot find items object')
    i = root + 1
    while i < pairs[root]:
        if ts[i][0] == ',':
            i += 1
            continue
        key = json.loads(ts[i][0])
        value_index = i + 2
        value_end = pairs[value_index] if ts[value_index][0] in ('{', '[') else value_index
        if key == KEY:
            start, end = ts[i][1], ts[value_end][2]
            if value_end + 1 < len(ts) and ts[value_end + 1][0] == ',':
                end = ts[value_end + 1][2]
            elif i > root + 1 and ts[i-1][0] == ',':
                # Remove only the delimiter, keeping any intervening comments.
                before = ts[i-1]
                text = text[:before[1]] + text[before[2]:start] + text[end:]
                break
            text = text[:start] + text[end:]
            break
        i = value_end + 1
    else:
        raise ValueError('cannot find menu entry')
    result_tokens = tokens(text)
    json.loads(''.join(t[0] for j, t in enumerate(result_tokens)
                       if not (t[0] == ',' and j + 1 < len(result_tokens) and result_tokens[j+1][0] in '}]')))
    return text

def main(path, operation="add"):
    path = Path(path)
    if operation == 'remove' and not path.exists():
        return
    old = path.read_text() if path.exists() else '{}\n'
    new = remove(old) if operation == 'remove' else update(old)
    if new == old:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + '.voicekey-backup-' + str(time.time_ns())))
    path.write_text(new)

if __name__ == '__main__':
    try:
        if len(sys.argv) not in (2, 3) or (len(sys.argv) == 3 and sys.argv[2] != '--remove'):
            sys.exit('Usage: configure-menu.py PATH [--remove]')
        main(sys.argv[1], 'remove' if len(sys.argv) == 3 else 'add')
    except (OSError, ValueError, IndexError) as error:
        sys.exit(f'Cannot update Omarchy menu: {error}')

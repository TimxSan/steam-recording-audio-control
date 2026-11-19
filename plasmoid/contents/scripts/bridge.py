
import argparse
import fcntl
import json
from pathlib import Path
import os

from app_icons import category_for_source
from audio_backend import AudioController, Graph

APP = 'steam-audio-control'
CONFIG_FILE = Path.home() / '.config' / APP / 'settings.json'
STATE_DIR = Path.home() / '.local' / 'state' / 'steam-audio-control-native'
STATE_FILE = STATE_DIR / 'session.json'
LOCK_FILE = STATE_DIR / 'bridge.lock'


def load(path, default):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else default.copy()
    except (OSError, ValueError, TypeError):
        return default.copy()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temp, path)


def take_state(controller):
    return {
        'steam_id': controller.steam_id,
        'routing': controller.routing,
        'original': controller.original,
        'muted': sorted(controller.muted),
    }


def restore_state(controller, state):
    controller.steam_id = state.get('steam_id')
    controller.routing = bool(state.get('routing', False))
    controller.original = state.get('original', [])
    controller.muted = set(state.get('muted', []))


def process(action, key):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open('a+b') as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        ctl = AudioController()
        if action == 'restore':
            restore_state(ctl, json.loads(STATE_FILE.read_text(encoding='utf-8')))
            if ctl.routing:
                graph = Graph.read()
                saved_inputs = {tuple(target) for _, target in ctl.original}
                current_inputs = {graph.port_ref(port) for port in graph.ports_for(ctl.steam_id, 'in')}
                if saved_inputs & current_inputs or (not saved_inputs and graph.steam_capture() == ctl.steam_id):
                    ctl.restore(graph)
            if not ctl.error:
                save(STATE_FILE, {})
            return {'error': ctl.error}
        settings = load(CONFIG_FILE, {'hidden': []})
        state = load(STATE_FILE, {})
        restore_state(ctl, state)
        ctl.refresh()
        if action == 'mute' and ctl.is_active and key in ctl.sources:
            ctl.set_muted(key, key not in ctl.muted)
        elif action == 'reset' and ctl.is_active:
            ctl.reset()
        elif action == 'hide' and key:
            hidden = set(settings.get('hidden', []))
            if key in hidden:
                hidden.remove(key)
            else:
                hidden.add(key)
            settings['hidden'] = sorted(hidden)
            save(CONFIG_FILE, settings)
        save(STATE_FILE, take_state(ctl))
        hidden = set(settings.get('hidden', []))
        apps = [
            {
                'key': key,
                'name': source.name,
                'iconCategory': category_for_source(key, source.name, min(source.binaries, default='')),
                'muted': key in ctl.muted,
                'hidden': key in hidden,
            }
            for key, source in sorted(ctl.sources.items(), key=lambda pair: pair[1].name.casefold())
        ]
        return {
            'active': bool(ctl.is_active),
            'apps': apps,
            'hiddenCount': sum(1 for a in apps if a['hidden']),
            'error': ctl.error,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['status', 'mute', 'reset', 'hide', 'restore'])
    parser.add_argument('key', nargs='?', default='')
    parser.add_argument('nonce', nargs='?', default='0')
    args = parser.parse_args()
    key = args.key
    try:
        key = bytes.fromhex(key).decode('utf-16-be')
    except ValueError:
        parser.error('Invalid audio source key')
    try:
        result = process(args.action, key)
    except Exception as exc:
        result = {'active': False, 'apps': [], 'hiddenCount': 0, 'error': str(exc)[:240]}
    if args.action == 'restore' and result['error']:
        parser.exit(1, result['error'] + '\n')
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))


if __name__ == '__main__':
    main()

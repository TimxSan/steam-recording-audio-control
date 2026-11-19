
import argparse
import fcntl
import json
from pathlib import Path
import os

from app_icons import category_for_source
from audio_backend import MICROPHONE_KEY, AudioController, Graph

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


def string_set(value):
    return {entry for entry in value if isinstance(entry, str)} if isinstance(value, list) else set()


def take_state(controller):
    return {
        'steam_id': controller.steam_id,
        'routing': controller.routing,
        'original': controller.original,
        'muted': sorted(controller.muted),
        'microphone_muted': controller.microphone_muted,
        'microphone_mutes': sorted(controller.microphone_mutes),
    }


def restore_state(controller, state):
    controller.steam_id = state.get('steam_id')
    controller.routing = bool(state.get('routing', False))
    controller.original = state.get('original', [])
    controller.muted = set(state.get('muted', []))
    controller.microphone_muted = bool(state.get('microphone_muted', False))
    controller.microphone_mutes = set(state.get('microphone_mutes', []))


def process(action, key):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open('a+b') as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        ctl = AudioController()
        if action == 'restore':
            restore_state(ctl, json.loads(STATE_FILE.read_text(encoding='utf-8')))
            graph = Graph.read() if ctl.routing or ctl.microphone_mutes else None
            if ctl.routing and graph is not None:
                saved_inputs = {tuple(target) for _, target in ctl.original}
                current_inputs = {graph.port_ref(port) for port in graph.ports_for(ctl.steam_id, 'in')}
                if saved_inputs & current_inputs or (not saved_inputs and graph.steam_capture() == ctl.steam_id):
                    ctl.restore(graph)
            if ctl.microphone_mutes and graph is not None:
                ctl.update_microphone(graph, mute=False)
            save(STATE_FILE, take_state(ctl) if ctl.error else {})
            return {'error': ctl.error}
        settings = load(CONFIG_FILE, {})
        remember_mutes = settings.get('remember_mutes') is True

        state = load(STATE_FILE, {})
        restore_state(ctl, state)
        ctl.refresh()
        if remember_mutes:
            saved_mutes = string_set(settings.get('muted'))
            ctl.muted = saved_mutes - {MICROPHONE_KEY}
            ctl.microphone_muted = MICROPHONE_KEY in saved_mutes
        elif ctl.steam_id is None:
            ctl.muted.clear()
            ctl.microphone_muted = False

        save_mutes = False
        if action == 'remember-mutes' and key in ('on', 'off'):
            remember_mutes = key == 'on'
            save_mutes = True
        elif action == 'mute' and (ctl.is_active or remember_mutes) and key in ctl.sources:
            ctl.set_muted(key, not ctl.is_muted(key))
            save_mutes = remember_mutes
        elif action == 'reset':
            ctl.reset()
            save_mutes = remember_mutes

        if save_mutes:
            settings['remember_mutes'] = remember_mutes
            if remember_mutes:
                muted = ctl.muted | ({MICROPHONE_KEY} if ctl.microphone_muted else set())
                settings['muted'] = sorted(muted)
            else:
                settings.pop('muted', None)
                if ctl.steam_id is None:
                    ctl.reset()
            save(CONFIG_FILE, settings)

        ctl.apply_mutes()
        save(STATE_FILE, take_state(ctl))
        apps = [
            {
                'key': key,
                'name': source.name,
                'applicationName': source.application_name,
                'icon': source.icon,
                'pid': min(source.pids, default=0),
                'appId': source.app_id,
                'binary': min(source.binaries, default=''),
                'iconCategory': ('voice' if key == MICROPHONE_KEY else category_for_source(
                    key, source.application_name or source.name, min(source.binaries, default='')
                )),
                'microphone': key == MICROPHONE_KEY,
                'muted': ctl.is_muted(key),
            }
            for key, source in sorted(ctl.sources.items(),
                                      key=lambda pair: ((pair[1].application_name or pair[1].name).casefold(), pair[0]))
        ]
        return {
            'active': bool(ctl.is_active),
            'rememberMutes': remember_mutes,
            'hasMutes': bool(ctl.muted or ctl.microphone_muted
                             or (remember_mutes and string_set(settings.get('muted')))),
            'microphoneActive': ctl.microphone_active,
            'apps': apps,
            'error': ctl.error,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['status', 'mute', 'remember-mutes', 'reset', 'restore'])
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
        result = {'active': False, 'apps': [], 'error': str(exc)[:240]}
    if args.action == 'restore' and result['error']:
        parser.exit(1, result['error'] + '\n')
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))


if __name__ == '__main__':
    main()

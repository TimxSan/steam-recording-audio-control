
import argparse
import fcntl
import json
import os
import signal
from pathlib import Path

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
    except FileNotFoundError:
        return default.copy()
    except ValueError as exc:
        raise ValueError(f'Invalid JSON in {path.name}') from exc
    if not isinstance(value, dict):
        raise ValueError(f'Invalid data in {path.name}')
    return value


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temp, path)


def string_set(value):
    return {entry for entry in value if isinstance(entry, str)} if isinstance(value, list) else set()


def legacy_mutes(state):
    muted = string_set(state.get('muted'))
    if state.get('microphone_muted') is True:
        muted.add(MICROPHONE_KEY)
    return muted


def take_state(controller):
    return {
        'steam_id': controller.steam_id,
        'steam_identity': controller.steam_identity,
        'routing': controller.routing,
        'restoring': controller.restoring,
        'legacy_links': controller.legacy_links,
        'original': [[list(source), list(target)] for source, target in controller.original],
        'microphone_mutes': sorted(controller.microphone_mutes),
    }


def restore_state(controller, state):
    controller.steam_id = state.get('steam_id')
    controller.steam_identity = state.get('steam_identity')
    if (controller.steam_id is not None and type(controller.steam_id) is not int
            or controller.steam_identity is not None and not isinstance(controller.steam_identity, str)):
        raise ValueError('Invalid saved Steam recording identity')
    controller.routing = state.get('routing', False)
    controller.restoring = state.get('restoring', False)
    controller.legacy_links = state.get('legacy_links', controller.routing and controller.steam_identity is None)
    if not all(isinstance(flag, bool) for flag in (controller.routing, controller.restoring, controller.legacy_links)):
        raise ValueError('Invalid saved Steam routing state')
    for source, target in state.get('original', []):
        if not all(isinstance(ref, (list, tuple)) and len(ref) == 2 and all(
            isinstance(part, str) and part for part in ref
        ) for ref in (source, target)):
            raise ValueError('Invalid saved PipeWire port reference')
        controller.original.append((tuple(source), tuple(target)))
    mutes = state.get('microphone_mutes', [])
    if not isinstance(mutes, list) or not all(isinstance(entry, str) for entry in mutes):
        raise ValueError('Invalid saved microphone state')
    controller.microphone_mutes = set(mutes)


def process(action, key, desired=None, details=True, suspend=False, widget=False):
    if widget and not Path(__file__).is_file():
        return {'error': ''}
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open('a+b') as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        if widget and not Path(__file__).is_file():
            return {'error': ''}
        state = load(STATE_FILE, {})
        if action == 'resume':
            if state.pop('suspended', False):
                save(STATE_FILE, state)
            return {'error': ''}

        last_saved = state

        def commit(snapshot):
            nonlocal last_saved
            if snapshot != last_saved:
                save(STATE_FILE, snapshot)
                last_saved = snapshot

        ctl = AudioController(lambda: commit(take_state(ctl)))
        restore_state(ctl, state)
        if action == 'restore':
            if ctl.routing or ctl.microphone_mutes:
                graph = Graph.read()
                if suspend and not CONFIG_FILE.exists() and ctl.matches_capture(graph):
                    muted = legacy_mutes(state)
                    if muted:
                        save(CONFIG_FILE, {'muted': sorted(muted)})
                ctl.restore(graph)
                if ctl.microphone_mutes:
                    ctl.update_microphone(graph, mute=False)
            if ctl.error:
                commit(take_state(ctl))
            else:
                commit({'suspended': True} if suspend or state.get('suspended') else {})
            return {'error': ctl.error}
        if state.get('suspended'):
            return {'active': False, 'microphoneActive': False, 'error': ''}

        settings = load(CONFIG_FILE, {})
        refreshed = ctl.refresh(details)

        muted = string_set(settings.get('muted'))
        if 'muted' not in settings and ctl.is_active and ctl.steam_id == state.get('steam_id'):
            muted = legacy_mutes(state)
        ctl.muted = muted - {MICROPHONE_KEY}
        ctl.microphone_muted = MICROPHONE_KEY in muted

        changed_mutes = action == 'reset' or (action in ('mute', 'set-muted') and key in ctl.sources)
        if changed_mutes:
            if action == 'reset':
                ctl.reset()
            else:
                ctl.set_muted(key, not ctl.is_muted(key) if action == 'mute' else desired)
            muted = ctl.muted | ({MICROPHONE_KEY} if ctl.microphone_muted else set())

        if changed_mutes or (muted and 'muted' not in settings):
            settings.pop('remember_mutes', None)
            settings['muted'] = sorted(muted)
            save(CONFIG_FILE, settings)

        if not refreshed:
            return {'error': ctl.error}
        ctl.apply_mutes()
        commit(take_state(ctl))
        result = {
            'active': ctl.is_active,
            'hasMutes': bool(muted),
            'hasUnlistedMutes': bool(muted.difference(ctl.sources)),
            'microphoneActive': ctl.microphone_active,
            'error': ctl.error,
        }
        if not details:
            return result
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
        result['apps'] = apps
        return result


def terminate(signum, _):
    raise SystemExit(128 + signum)


def main():
    signal.signal(signal.SIGTERM, terminate)
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['status', 'mute', 'set-muted', 'reset', 'restore', 'resume'])
    parser.add_argument('key', nargs='?', default='')
    parser.add_argument('nonce', nargs='?', default='0')
    mute = parser.add_mutually_exclusive_group()
    mute.add_argument('--muted', action='store_true', dest='desired', default=None)
    mute.add_argument('--unmuted', action='store_false', dest='desired')
    parser.add_argument('--routing-only', action='store_true')
    parser.add_argument('--suspend', action='store_true')
    parser.add_argument('--widget', action='store_true')
    args = parser.parse_args()
    if args.action == 'set-muted' and args.desired is None:
        parser.error('Use --muted or --unmuted with set-muted')
    try:
        key = bytes.fromhex(args.key).decode('utf-16-be')
    except ValueError:
        parser.error('Invalid audio source key')
        return
    try:
        result = process(args.action, key, args.desired, not args.routing_only, args.suspend, args.widget)
    except Exception as exc:
        result = {'error': str(exc)[:240]}
    if args.action in ('restore', 'resume') and result['error']:
        parser.exit(1, result['error'] + '\n')
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))


if __name__ == '__main__':
    main()

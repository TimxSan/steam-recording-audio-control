
import json
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field

from app_icons import ApplicationResolver

GENERIC_APPS = {'', 'wine', 'wine64', 'wine64-preloader', 'pipewire', 'alsa', 'pulse audio', 'audio stream'}
MICROPHONE_KEY = 'device:steam-microphone'


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=3, check=False)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or 'Unknown PipeWire error').strip())
    return result.stdout


def number(value):
    try:
        return int(value)
    except (ValueError, TypeError):
        return -1


def props(obj):
    return obj.get('info', {}).get('props', {}) or {}


def channel(port):
    p = props(port)
    ch = str(p.get('audio.channel', '')).upper()
    if ch in ('FL', 'FR', 'MONO'):
        return ch
    name = str(p.get('port.name', '')).upper()
    for ending in ('FL', 'FR', 'MONO'):
        if name.endswith('_' + ending):
            return ending
    return ''


@dataclass
class Source:
    key: str
    name: str
    nodes: set = field(default_factory=set)
    binaries: set = field(default_factory=set)
    icon: str = ''
    application_name: str = ''
    pids: set = field(default_factory=set)
    app_id: str = ''


class Graph:
    def __init__(self, dump):
        self.nodes = {}
        self.clients = {}
        self.ports = {}
        self.links = {}
        self.node_ports = defaultdict(list)
        self.cookie = None
        self.default_source = ''
        for item in dump:
            kind = str(item.get('type', '')).split(':')[-1]
            ident = number(item.get('id'))
            if ident < 0:
                continue
            if kind == 'Node':
                self.nodes[ident] = item
            elif kind == 'Client':
                self.clients[ident] = item
            elif kind == 'Core':
                self.cookie = item.get('info', {}).get('cookie')
            elif kind == 'Metadata' and item.get('props', {}).get('metadata.name') == 'default':
                for setting in item.get('metadata', []):
                    if setting.get('key') == 'default.audio.source' and isinstance(setting.get('value'), dict):
                        self.default_source = setting['value'].get('name', '')
            elif kind == 'Port':
                self.ports[ident] = item
                parent = number(props(item).get('node.id'))
                if parent >= 0:
                    self.node_ports[parent].append(ident)
            elif kind == 'Link':
                info = item.get('info') or {}
                p = props(item)
                output = number(info.get('output-port-id'))
                input_port = number(info.get('input-port-id'))
                if output < 0 or input_port < 0:
                    output = number(p.get('link.output.port'))
                    input_port = number(p.get('link.input.port'))
                if output >= 0 and input_port >= 0:
                    self.links[ident] = (output, input_port)

    @classmethod
    def read(cls):
        return cls(json.loads(run('pw-dump')))

    def port_name(self, ident):
        return str(props(self.ports.get(ident, {})).get('port.name', ''))

    def ports_for(self, node_id, direction=None):
        ids = self.node_ports.get(node_id, [])
        if direction is None:
            return ids
        return [p for p in ids if str(props(self.ports[p]).get('port.direction', '')).lower() == direction
                or (direction == 'out' and self.port_name(p).startswith(('output_', 'monitor_')))
                or (direction == 'in' and self.port_name(p).startswith(('input_', 'playback_')))]

    def is_steam_capture_candidate(self, node_id):
        p = props(self.nodes.get(node_id, {}))
        if p.get('media.class') != 'Stream/Input/Audio':
            return False
        media = str(p.get('media.name', '')).lower()
        if any(label in media for label in ('audio recorder', 'voiceengine', 'microphone')):
            return False
        return any('steam' in str(p.get(key, '')).lower() for key in (
            'node.name', 'media.name', 'application.name',
            'application.process.binary', 'application.id', 'node.description',
        ))

    def steam_capture(self):
        best = None
        best_score = 0
        for node_id, node in self.nodes.items():
            if not self.is_steam_capture_candidate(node_id):
                continue
            p = props(node)
            name = str(p.get('node.name', '')).lower()
            media = str(p.get('media.name', '')).lower()
            score = 10
            if media == 'steam' or name == 'steam' or name.startswith('steam-') and media == 'steam':
                score += 50
            inputs = set(self.ports_for(node_id, 'in'))
            for output, input_port in self.links.values():
                if input_port not in inputs:
                    continue
                upstream_port = self.ports.get(output)
                if not upstream_port:
                    continue
                upstream_node = self.nodes.get(number(props(upstream_port).get('node.id')), {})
                upstream_class = props(upstream_node).get('media.class', '')
                if upstream_class == 'Audio/Sink' or self.port_name(output).startswith('monitor_'):
                    score += 80
                    break
            if score > best_score:
                best = node_id
                best_score = score
        return best if best_score >= 60 else None

    def steam_microphone_inputs(self):
        # Steam Game Recording opens a separate input for the microphone.
        inputs = {}
        for node_id, node in self.nodes.items():
            p = props(node)
            if (p.get('media.class') != 'Stream/Input/Audio'
                    or str(p.get('media.name', '')).casefold() != 'audio recorder'
                    or str(p.get('media.role', '')).casefold() != 'game'):
                continue
            identities = (
                str(p.get('application.name', '')).casefold(),
                str(p.get('application.id', '')).casefold(),
                str(p.get('application.process.binary', '')).rsplit('/', 1)[-1].casefold(),
            )
            serial = p.get('object.serial')
            if serial is not None and {'steam', 'com.valvesoftware.steam'}.intersection(identities):
                inputs[f'{self.cookie}:{serial}'] = node_id
        return inputs

    def input_mute(self, node_id):
        for entry in self.nodes[node_id]['info'].get('params', {}).get('Props', []):
            mute = entry.get('mute')
            if isinstance(mute, bool):
                return mute
        return None

    def microphone(self, capture_nodes):
        devices = {node_id: props(node) for node_id, node in self.nodes.items()
                   if props(node).get('media.class') in ('Audio/Source', 'Audio/Source/Virtual')}
        if not devices and not capture_nodes:
            return None

        by_target = {str(device[key]): device for device in devices.values()
                     for key in ('node.name', 'object.serial') if key in device}
        candidates = [by_target.get(str(props(self.nodes[node_id]).get('target.object')))
                      for node_id in capture_nodes]
        for node_id in capture_nodes:
            candidates.extend(devices.get(number(props(self.ports[output]).get('node.id')))
                              for output, _ in self.input_pairs(node_id).values() if output in self.ports)
        candidates.append(by_target.get(self.default_source))
        if len(devices) == 1:
            candidates.extend(devices.values())
        device = next((candidate for candidate in candidates if candidate is not None), {})
        name = str(device.get('node.description') or device.get('node.nick') or '')
        return Source(MICROPHONE_KEY, name, icon='audio-input-microphone')

    def sources(self):
        found = {}
        applications = ApplicationResolver()
        for node_id, node in self.nodes.items():
            p = props(node)
            if p.get('media.class') != 'Stream/Output/Audio':
                continue
            if str(p.get('node.virtual', '')).lower() in ('true', '1'):
                continue
            if not self.ports_for(node_id, 'out'):
                continue
            app = str(p.get('application.name', '')).strip()
            media = str(p.get('media.name', '')).strip()
            binary = str(p.get('application.process.binary', '')).split('/')[-1].strip()
            app_id = str(p.get('application.id', '')).strip()
            label = app if app.lower() not in GENERIC_APPS else (media or binary or 'Unknown application')
            if label.lower() in GENERIC_APPS:
                label = binary or 'Unknown application'
            if label.lower() == 'steam audio control':
                continue
            preferred_binary = binary if binary.lower() not in GENERIC_APPS else ''
            identity = app_id or (app if app.lower() not in GENERIC_APPS else '') or preferred_binary or media or binary or str(p.get('node.name', ''))
            key = identity.strip().lower()
            if not key:
                key = str(node_id)
            source = found.setdefault(key, Source(key, label))
            source.nodes.add(node_id)
            client = props(self.clients.get(number(p.get('client.id')), {}))
            for metadata in (p, client):
                pid = number(metadata.get('application.process.id'))
                if pid > 0:
                    source.pids.add(pid)
                process = str(metadata.get('application.process.binary') or '').rsplit('/', 1)[-1].strip()
                if process:
                    source.binaries.add(process)
            application = applications.resolve(p, client)
            source.application_name = source.application_name or application.name
            source.app_id = source.app_id or application.app_id or app_id or str(
                p.get('pipewire.access.portal.app_id') or client.get('application.id')
                or client.get('pipewire.access.portal.app_id') or ''
            )
            if not source.icon or application.icon.startswith('/') and not source.icon.startswith('/'):
                source.icon = application.icon
        return found

    def input_pairs(self, steam_id):
        steam_ports = set(self.ports_for(steam_id, 'in'))
        return {link_id: pair for link_id, pair in self.links.items() if pair[1] in steam_ports}

    def port_ref(self, port_id):
        port = self.ports.get(port_id)
        if port is None:
            return None
        node = self.nodes.get(number(props(port).get('node.id')))
        if node is None:
            return None
        return (str(props(node).get('node.name', '')), self.port_name(port_id))

    def resolve_ref(self, ref):
        if not ref:
            return None
        node_name, port_name = ref
        for node_id, node in self.nodes.items():
            if str(props(node).get('node.name', '')) == node_name:
                for port_id in self.node_ports.get(node_id, []):
                    if self.port_name(port_id) == port_name:
                        return port_id
        return None

    def desired_pairs(self, steam_id, sources, muted):
        target_ports = self.ports_for(steam_id, 'in')
        targets = defaultdict(list)
        for target in target_ports:
            targets[channel(self.ports[target])].append(target)
        if not target_ports:
            return set()
        desired = set()
        for key, source in sources.items():
            if key in muted:
                continue
            for node in source.nodes:
                output_ports = sorted(self.ports_for(node, 'out'))
                for index, output in enumerate(output_ports):
                    ch = channel(self.ports[output])
                    dests = targets.get(ch, []) if ch else []
                    if ch == 'MONO':
                        dests = targets.get('MONO', []) or (targets.get('FL', []) + targets.get('FR', []))
                    if not dests and len(output_ports) == 1:
                        dests = target_ports
                    elif not dests and not ch and index < len(target_ports):
                        dests = [sorted(target_ports, key=lambda t: (channel(self.ports[t]) != 'FL', t))[index]]
                    for target in dests:
                        desired.add((output, target))
        return desired


class AudioController:
    def __init__(self):
        self.steam_id = None
        self.muted = set()
        self.microphone_muted = False
        self.microphone_mutes = set()  # Capture streams muted by the widget.
        self.microphone_active = False
        self.sources = {}
        self.is_active = False
        self.routing = False
        self.original = []
        self.error = ''
        self._graph = None

    def refresh(self):
        try:
            graph = Graph.read()
            self._graph = graph
            steam = graph.steam_capture()
            previous_capture = graph.is_steam_capture_candidate(self.steam_id)
            if steam is None and previous_capture:
                steam = self.steam_id
            if steam != self.steam_id:
                if self.routing and previous_capture:
                    self.restore(graph)
                if self.steam_id is not None:
                    self.muted.clear()
                    self.microphone_muted = False
                self.steam_id = steam
                self.routing = False
                self.original = []
                self.error = ''
            self.is_active = steam is not None
            self.sources = graph.sources()
            microphone_inputs = graph.steam_microphone_inputs()
            microphone = graph.microphone(microphone_inputs.values())
            if microphone is not None:
                self.sources[microphone.key] = microphone
            self.microphone_active = self.is_active and any(
                graph.input_mute(node_id) is not None for node_id in microphone_inputs.values()
            )
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            self.error = str(exc)[:180]
            self._graph = None
            self.is_active = False
            self.microphone_active = False
            self.sources = {}

    def is_muted(self, key):
        return self.microphone_muted if key == MICROPHONE_KEY else key in self.muted

    def set_muted(self, key, mute):
        self.error = ''
        if key == MICROPHONE_KEY:
            self.microphone_muted = mute
            return
        if mute:
            self.muted.add(key)
        else:
            self.muted.discard(key)

    def reset(self):
        self.error = ''
        self.muted.clear()
        self.microphone_muted = False

    def apply_mutes(self):
        if self._graph is None:
            return
        if self.is_active and self.muted.intersection(self.sources):
            self.reconcile(self._graph)
        elif self.routing:
            self.restore(self._graph)
        if self.microphone_muted or self.microphone_mutes:
            self.update_microphone(self._graph, self.is_active and self.microphone_muted)

    def update_microphone(self, graph, mute):
        inputs = graph.steam_microphone_inputs()
        self.microphone_mutes.intersection_update(inputs)
        try:
            for capture, node_id in inputs.items():
                current = graph.input_mute(node_id)
                if mute and current is False:
                    run('pw-cli', 'set-param', str(node_id), 'Props', '{ mute: true }')
                    self.microphone_mutes.add(capture)
                elif not mute and capture in self.microphone_mutes:
                    if current is not False:
                        run('pw-cli', 'set-param', str(node_id), 'Props', '{ mute: false }')
                    self.microphone_mutes.remove(capture)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            self.error = self.error or 'Microphone control: ' + str(exc)[:140]

    def reconcile(self, graph):
        if self.steam_id is None:
            return
        try:
            current = graph.input_pairs(self.steam_id)
            if not self.routing:
                self.original = [(graph.port_ref(src), graph.port_ref(dst)) for src, dst in current.values()]
                self.original = [(src, dst) for src, dst in self.original if src and dst]
                self.routing = True
            desired = graph.desired_pairs(self.steam_id, self.sources, self.muted)
            actual = set(current.values())
            for link_id, pair in current.items():
                if pair not in desired:
                    run('pw-link', '-d', str(link_id))
            for source_port, target_port in sorted(desired - actual):
                run('pw-link', str(source_port), str(target_port))
            self.error = ''
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            message = 'Audio routing: ' + str(exc)[:140]
            self.muted.clear()
            self.restore()
            self.error = message

    def restore(self, graph=None):
        if not self.routing:
            return
        try:
            graph = graph or Graph.read()
            if self.steam_id is None or self.steam_id not in graph.nodes:
                self.routing = False
                self.original = []
                return
            old_pairs = set()
            for output_ref, input_ref in self.original:
                output = graph.resolve_ref(output_ref)
                input_port = graph.resolve_ref(input_ref)
                if output is not None and input_port is not None:
                    old_pairs.add((output, input_port))
            current = graph.input_pairs(self.steam_id)
            for source_port, target_port in sorted(old_pairs - set(current.values())):
                run('pw-link', str(source_port), str(target_port))
            for link_id, pair in current.items():
                if pair not in old_pairs:
                    run('pw-link', '-d', str(link_id))
            self.routing = False
            self.original = []
            self.error = ''
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            self.error = 'Restore failed: ' + str(exc)[:140]



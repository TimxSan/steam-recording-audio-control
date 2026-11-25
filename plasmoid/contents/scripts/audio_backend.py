
import json
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field

from app_icons import ApplicationResolver

GENERIC_APPS = {'', 'wine', 'wine64', 'wine64-preloader', 'pipewire', 'alsa', 'pulse audio', 'audio stream'}
MICROPHONE_KEY = 'device:steam-microphone'
STEAM_IDENTITIES = {'steam', 'steam.sh', 'com.valvesoftware.steam'}
MANAGED_LINK = 'steam-audio-control.managed'
PIPEWIRE_ERRORS = (OSError, RuntimeError, ValueError, subprocess.SubprocessError)


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
    return (obj.get('info') or {}).get('props') or {}


def channel(port):
    p = props(port)
    ch = str(p.get('audio.channel') or '').upper()
    if ch and ch not in ('UNK', 'UNKNOWN', 'NA'):
        return ch
    ending = str(p.get('port.name', '')).upper().rsplit('_', 1)[-1]
    return ending if ending in ('FL', 'FR', 'MONO', 'FC', 'LFE', 'RL', 'RR', 'SL', 'SR', 'RC', 'FLC', 'FRC') else ''


def connect_ports(output, target, managed=False):
    args = ('-p', json.dumps({MANAGED_LINK: True})) if managed else ()
    run('pw-link', *args, str(output), str(target))


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
        if not isinstance(dump, list):
            raise ValueError('Invalid PipeWire graph')
        self.nodes = {}
        self.clients = {}
        self.ports = {}
        self.links = {}
        self.managed_links = set()
        self.node_ports = defaultdict(list)
        self.cookie = None
        self.default_sink = ''
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
                self.cookie = (item.get('info') or {}).get('cookie')
            elif kind == 'Metadata' and item.get('props', {}).get('metadata.name') == 'default':
                for setting in item.get('metadata', []):
                    value = setting.get('value')
                    if not isinstance(value, dict):
                        continue
                    if setting.get('key') == 'default.audio.source':
                        self.default_source = value.get('name', '')
                    elif setting.get('key') == 'default.audio.sink':
                        self.default_sink = value.get('name', '')
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
                    if p.get(MANAGED_LINK) in (True, 'true', '1'):
                        self.managed_links.add(ident)

    @classmethod
    def read(cls):
        graph = cls(json.loads(run('pw-dump')))
        if graph.cookie is None:
            raise RuntimeError('Cannot identify the PipeWire server')
        return graph

    def port_name(self, ident):
        return str(props(self.ports.get(ident, {})).get('port.name', ''))

    def port_node(self, ident):
        return number(props(self.ports.get(ident, {})).get('node.id'))

    def ports_for(self, node_id, direction=None):
        ids = self.node_ports.get(node_id, [])
        if direction is None:
            return ids
        prefixes = ('output_', 'monitor_') if direction == 'out' else ('input_', 'playback_')
        result = []
        for port in ids:
            port_direction = str(props(self.ports[port]).get('port.direction') or '').lower()
            if port_direction == direction or not port_direction and self.port_name(port).startswith(prefixes):
                result.append(port)
        return result

    def node_identity(self, node_id):
        serial = props(self.nodes.get(node_id, {})).get('object.serial')
        return f'{self.cookie}:{serial}' if self.cookie is not None and serial is not None else None

    def is_steam_node(self, node):
        client = props(self.clients.get(number(node.get('client.id')), {}))
        for metadata in (node, client):
            for key in ('application.name', 'application.id', 'application.process.binary',
                        'pipewire.access.portal.app_id'):
                identity = str(metadata.get(key) or '').rsplit('/', 1)[-1].strip().casefold()
                if identity in STEAM_IDENTITIES:
                    return True
        return False

    def is_steam_capture_candidate(self, node_id):
        p = props(self.nodes.get(node_id, {}))
        if p.get('media.class') != 'Stream/Input/Audio' or not self.is_steam_node(p):
            return False
        media = str(p.get('media.name', '')).casefold()
        name = str(p.get('node.name', '')).casefold()
        role = str(p.get('media.role', '')).casefold()
        if role in ('communication', 'phone', 'voice') or any(
            label in media for label in ('audio recorder', 'voice', 'microphone')
        ):
            return False
        return (media in ('steam', 'game recording', 'steam game recording', 'steam recording') or name == 'steam'
                or role == 'game' and p.get('stream.capture.sink') in (True, 'true', '1'))

    def is_monitor_output(self, port):
        return (self.port_name(port).startswith('monitor_')
                or props(self.nodes.get(self.port_node(port), {})).get('media.class') == 'Audio/Sink')

    def default_monitor_for(self, target):
        target_channel = channel(self.ports[target])
        if not self.default_sink or not target_channel:
            return None
        matches = [port for node_id, node in self.nodes.items()
                   if props(node).get('media.class') == 'Audio/Sink'
                   and props(node).get('node.name') == self.default_sink
                   for port in self.ports_for(node_id, 'out') if channel(self.ports[port]) == target_channel]
        return matches[0] if len(matches) == 1 else None

    def steam_capture(self):
        monitored_nodes = {self.port_node(target) for source, target in self.links.values()
                           if self.is_monitor_output(source)}
        candidates = [node for node in monitored_nodes if self.is_steam_capture_candidate(node)]
        return candidates[0] if len(candidates) == 1 else None

    def steam_microphone_inputs(self):
        inputs = {}
        for node_id, node in self.nodes.items():
            p = props(node)
            if (p.get('media.class') != 'Stream/Input/Audio'
                    or str(p.get('media.name', '')).casefold() != 'audio recorder'
                    or str(p.get('media.role', '')).casefold() != 'game'):
                continue
            identity = self.node_identity(node_id)
            if identity and self.is_steam_node(p):
                inputs[identity] = node_id
        return inputs

    def input_mute(self, node_id):
        params = (self.nodes[node_id].get('info') or {}).get('params') or {}
        for entry in params.get('Props') or []:
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

    def sources(self, details=True):
        found = {}
        applications = ApplicationResolver() if details else None
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
            if applications is None:
                continue
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
        node_name = props(node).get('node.name')
        port_name = self.port_name(port_id)
        return (str(node_name), port_name) if node_name and port_name else None

    def resolve_ref(self, ref, direction, parent=None):
        node_name, port_name = ref
        nodes = self.nodes if parent is None else (parent,)
        matches = [port for node_id in nodes
                   if str(props(self.nodes.get(node_id, {})).get('node.name', '')) == node_name
                   for port in self.ports_for(node_id, direction) if self.port_name(port) == port_name]
        return matches[0] if len(matches) == 1 else None

    def desired_pairs(self, steam_id, sources, muted):
        target_ports = sorted(self.ports_for(steam_id, 'in'))
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
                channels = [channel(self.ports[port]) for port in output_ports]
                for index, output in enumerate(output_ports):
                    ch = channels[index]
                    dests = targets.get(ch, []) if ch else []
                    if not dests and ch == 'MONO':
                        dests = targets.get('FL', []) + targets.get('FR', [])
                    elif not dests and ch in ('FL', 'FR'):
                        dests = targets.get('MONO', [])
                    if not dests and len(output_ports) == 1 and not ch:
                        dests = targets.get('MONO', []) or targets.get('FL', []) + targets.get('FR', [])
                    if not dests and len(output_ports) == len(target_ports) and (
                        not any(channels) or not any(targets)
                    ):
                        dests = [target_ports[index]]
                    for target in dests:
                        desired.add((output, target))
        return desired


class AudioController:
    def __init__(self, checkpoint=lambda: None):
        self.steam_id = None
        self.steam_identity = None
        self.muted = set()
        self.microphone_muted = False
        self.microphone_mutes = set()
        self.microphone_active = False
        self.sources = {}
        self.is_active = False
        self.routing = False
        self.restoring = False
        self.legacy_links = False
        self.original = []
        self.error = ''
        self._graph = None
        self._checkpoint = checkpoint

    def matches_capture(self, graph):
        if not graph.is_steam_capture_candidate(self.steam_id):
            return False
        if self.steam_identity is not None:
            return graph.node_identity(self.steam_id) == self.steam_identity
        inputs = {graph.port_ref(port) for port in graph.ports_for(self.steam_id, 'in')}
        return any(target in inputs for _, target in self.original) or (
            not self.original and graph.steam_capture() == self.steam_id
        )

    def refresh(self):
        try:
            graph = Graph.read()
            self._graph = graph
            steam = graph.steam_capture()
            if self.routing:
                if self.matches_capture(graph) and steam in (None, self.steam_id):
                    steam = self.steam_id
                    self.steam_identity = graph.node_identity(steam)
                else:
                    self.restore(graph)
            if not self.routing:
                self.steam_id = steam
                self.steam_identity = graph.node_identity(steam)
            self.is_active = steam is not None
            self.microphone_active = self.is_active and any(
                graph.input_mute(node_id) is not None for node_id in graph.steam_microphone_inputs().values()
            )
            return True
        except PIPEWIRE_ERRORS as exc:
            self.error = self.error or str(exc)[:180]
            self._graph = None
            self.is_active = False
            self.microphone_active = False
            self.sources = {}
            return False

    def load_sources(self, details, include_microphone=False):
        graph = self._graph
        self.sources = graph.sources(details)
        if details or include_microphone:
            microphone = graph.microphone(graph.steam_microphone_inputs().values())
            if microphone is not None:
                self.sources[microphone.key] = microphone

    def is_muted(self, key):
        return self.microphone_muted if key == MICROPHONE_KEY else key in self.muted

    def set_muted(self, key, mute):
        if key == MICROPHONE_KEY:
            self.microphone_muted = mute
        elif mute:
            self.muted.add(key)
        else:
            self.muted.discard(key)

    def reset(self):
        self.muted.clear()
        self.microphone_muted = False

    def apply_mutes(self):
        if self._graph is None:
            return
        if self.routing and self.restoring:
            if not self.error:
                self.restore(self._graph)
        elif self.is_active and self.muted.intersection(self.sources):
            self.reconcile(self._graph)
        elif self.routing:
            self.restore(self._graph)
        if self.microphone_muted or self.microphone_mutes:
            self.update_microphone(self._graph, self.is_active and self.microphone_muted)

    def update_microphone(self, graph, mute):
        inputs = graph.steam_microphone_inputs()
        try:
            if graph.cookie is None:
                raise RuntimeError('Cannot identify the PipeWire server')
            present = {graph.node_identity(node_id) for node_id in graph.nodes}
            self.microphone_mutes.intersection_update(present)
            if not self.microphone_mutes.issubset(inputs):
                raise RuntimeError('Cannot verify a microphone stream previously muted by the widget')
            for capture, node_id in inputs.items():
                current = graph.input_mute(node_id)
                if mute and current is False:
                    self.microphone_mutes.add(capture)
                    self._checkpoint()
                    run('pw-cli', 'set-param', str(node_id), 'Props', '{ mute: true }')
                elif not mute and capture in self.microphone_mutes:
                    if current is None:
                        raise RuntimeError('Microphone mute state is unavailable')
                    if current:
                        run('pw-cli', 'set-param', str(node_id), 'Props', '{ mute: false }')
                    self.microphone_mutes.remove(capture)
        except PIPEWIRE_ERRORS as exc:
            self.error = self.error or 'Microphone control: ' + str(exc)[:140]

    def reconcile(self, graph):
        if self.steam_identity is None or not self.matches_capture(graph):
            self.error = 'Cannot verify the Steam recording stream'
            return
        try:
            current = graph.input_pairs(self.steam_id)
            desired = graph.desired_pairs(self.steam_id, self.sources, self.muted)
            audible_nodes = {node for key, source in self.sources.items() if key not in self.muted
                             for node in source.nodes}
            if not audible_nodes.issubset({graph.port_node(source) for source, _ in desired}):
                raise RuntimeError('Some audio sources have no matching Steam recording port')
            if not self.routing:
                inputs = set(graph.ports_for(self.steam_id, 'in'))
                monitored = {target for source, target in current.values() if graph.is_monitor_output(source)}
                original = {(graph.port_ref(source), graph.port_ref(target)) for source, target in current.values()}
                if not inputs or not inputs.issubset(monitored) or any(not src or not dst for src, dst in original):
                    raise RuntimeError('Steam system audio connections are not ready')
                self.original = sorted(original)
                self.routing = True
                self._checkpoint()
            actual = set(current.values())
            for source, target in sorted(desired - actual):
                connect_ports(source, target, managed=True)
            kept = set()
            for link_id in sorted(current, key=lambda ident: (ident in graph.managed_links, ident)):
                pair = current[link_id]
                if pair in desired and pair not in kept:
                    kept.add(pair)
                else:
                    run('pw-link', '-d', str(link_id))
        except PIPEWIRE_ERRORS as exc:
            if self.routing:
                self.restore()
            message = 'Audio routing: ' + str(exc)[:140]
            self.error = message + ('; ' + self.error if self.error else '')

    def restore(self, graph=None):
        if not self.routing:
            return
        try:
            graph = graph or Graph.read()
            if graph.cookie is None:
                raise RuntimeError('Cannot identify the PipeWire server')
            if not self.matches_capture(graph):
                identity = graph.node_identity(self.steam_id)
                if self.steam_id in graph.nodes and (
                    identity == self.steam_identity or identity is None
                    or self.steam_identity is None and graph.is_steam_capture_candidate(self.steam_id)
                ):
                    raise RuntimeError('Cannot verify the original Steam recording stream')
                self.clear_routing()
                return

            self.steam_identity = graph.node_identity(self.steam_id)
            self.restoring = True
            self._checkpoint()
            current = graph.input_pairs(self.steam_id)
            linked = set(current.values())
            original = {(graph.resolve_ref(src, 'out'), graph.resolve_ref(dst, 'in', self.steam_id))
                        for src, dst in self.original}
            monitored = {target for source, target in linked - original if graph.is_monitor_output(source)}
            original_monitored = {target for source, target in original
                                  if source is not None and target is not None and graph.is_monitor_output(source)}
            missing = {target for source, target in original if target is None
                       or source is None and target not in monitored and target not in original_monitored}
            for source, target in original - linked:
                if source is not None and target is not None and (
                    target not in monitored or not graph.is_monitor_output(source)
                ):
                    connect_ports(source, target)

            for target in missing - {None}:
                monitor = graph.default_monitor_for(target)
                if monitor is not None:
                    if (monitor, target) not in linked and (monitor, target) not in original:
                        connect_ports(monitor, target)
                    missing.remove(target)

            if not original:
                missing.update(set(graph.ports_for(self.steam_id, 'in')) - monitored)
                if not monitored:
                    missing.add(None)

            for link_id, (source, target) in current.items():
                if target in missing or (source, target) in original:
                    continue
                source_class = props(graph.nodes.get(graph.port_node(source), {})).get('media.class')
                if link_id in graph.managed_links or self.legacy_links and source_class == 'Stream/Output/Audio':
                    run('pw-link', '-d', str(link_id))

            if missing:
                raise RuntimeError('Some original Steam audio ports are unavailable')
            self.clear_routing()
        except PIPEWIRE_ERRORS as exc:
            self.restoring = True
            self.error = 'Restore failed: ' + str(exc)[:140]

    def clear_routing(self):
        self.routing = False
        self.restoring = False
        self.legacy_links = False
        self.original = []

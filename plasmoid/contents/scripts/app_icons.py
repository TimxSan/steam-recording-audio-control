import configparser
from dataclasses import dataclass
from glob import escape
import os
import re
import shlex
from pathlib import Path


_UNHELPFUL = {'', 'wine', 'wine64', 'wine64preloader', 'python', 'python3',
              'pipewire', 'pulse', 'pulseaudio', 'alsa', 'alsaaudio', 'audiostream',
              'webrtcvoiceengine', 'voiceengine'}
_ICON_EXTENSIONS = ('.svg', '.png', '.xpm')


def normalize(value):
    value = str(value or '').strip().casefold()
    if value.endswith('.desktop'):
        value = value[:-8]
    if value.endswith('.exe'):
        value = value[:-4]
    return re.sub(r'[^a-z0-9]+', '', value)


def xdg_data_dirs():
    home = Path.home()
    data_home = Path(os.environ.get('XDG_DATA_HOME') or home / '.local/share')
    dirs = [data_home]
    dirs += [Path(p) for p in (os.environ.get('XDG_DATA_DIRS') or '/usr/local/share:/usr/share').split(':') if p]
    dirs += [home / '.local/share/flatpak/exports/share', Path('/var/lib/flatpak/exports/share')]
    return list(dict.fromkeys(dirs))


def read_desktop(path):
    config = configparser.ConfigParser(interpolation=None, strict=False)
    config.optionxform = str
    try:
        with path.open('r', encoding='utf-8', errors='replace') as source:
            config.read_file(source)
        if 'Desktop Entry' not in config or config['Desktop Entry'].get('Type') != 'Application':
            return None
        entry = config['Desktop Entry']
        return {
            'icon': entry.get('Icon', '').strip(),
            'id': path.name.removesuffix('.desktop'),
            'name': entry.get('Name', ''),
            'wmclass': entry.get('StartupWMClass', ''),
            'flatpak': entry.get('X-Flatpak', ''),
            'exec': entry.get('Exec', ''),
        }
    except (OSError, ValueError, configparser.Error):
        return None


def exec_binary(command):
    try:
        args = shlex.split(command)
    except ValueError:
        return ''
    if args and args[0] == 'env':
        args.pop(0)
        while args:
            if '=' in args[0] and not args[0].startswith('-'):
                args.pop(0)
            elif args[0] in ('-u', '--unset', '-C', '--chdir') and len(args) > 1:
                del args[:2]
            elif args[0] in ('-i', '--ignore-environment', '-0', '--null'):
                args.pop(0)
            else:
                break
    return Path(args[0]).name if args else ''


@dataclass(frozen=True)
class Application:
    name: str = ''
    icon: str = ''
    app_id: str = ''


class ApplicationResolver:
    def __init__(self):
        self.data_dirs = xdg_data_dirs()
        self.by_id = {}
        self.by_name = {}
        self.by_binary = {}
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        for root in self.data_dirs:
            for path in sorted((root / 'applications').rglob('*.desktop')):
                entry = read_desktop(path)
                if not entry:
                    continue
                application = Application(entry['name'].strip(), entry['icon'], entry['id'])
                for field in ('id', 'flatpak'):
                    key = normalize(entry[field])
                    if key:
                        self.by_id.setdefault(key, application)
                for field in ('name', 'wmclass'):
                    key = normalize(entry[field])
                    if key not in _UNHELPFUL:
                        self.by_name.setdefault(key, application)
                binary = normalize(exec_binary(entry['exec']))
                if binary not in _UNHELPFUL and binary != 'steam':
                    self.by_binary.setdefault(binary, application)

    def resolve(self, node, client):
        self._load()
        metadata = (node, client)
        ids = [p.get(field) for p in metadata for field in ('application.id', 'pipewire.access.portal.app_id')]
        names = [p.get('application.name') for p in metadata]
        binaries = [Path(str(p.get('application.process.binary') or '')).name for p in metadata]
        application = self._match(self.by_id, ids)
        if application is None:
            processes = [binary for binary in binaries if normalize(binary) != 'steam']
            application = (self._match(self.by_binary, processes) or self._match(self.by_id, processes)
                           or self._match(self.by_name, processes))
        if application is None:
            application = self._match(self.by_id, names) or self._match(self.by_name, names)
        if application is None:
            application = self._steam_application(*names)

        hints = [str(p.get(field) or '').strip() for p in metadata
                 for field in ('application.icon-name', 'application.icon_name')]
        icons = [self._installed_icon(icon) for icon in [application.icon, *hints] if icon]
        icon = next((icon for icon in icons if icon.startswith('/')), '')
        if not icon:
            identifiers = [application.app_id, *ids, *binaries]
            for value in dict.fromkeys(str(value or '').removesuffix('.desktop') for value in identifiers):
                if normalize(value) in _UNHELPFUL | {'steam'}:
                    continue
                installed = self._installed_icon(value)
                if installed.startswith('/'):
                    icon = installed
                    break
        if not icon:
            icon = next((icon for icon in icons if icon), '')
        return Application(application.name, icon, application.app_id)

    @staticmethod
    def _match(index, values):
        for value in values:
            key = normalize(value)
            if key not in _UNHELPFUL and key in index:
                return index[key]
        return None

    def _installed_icon(self, icon):
        path = Path(icon)
        if path.is_absolute():
            return icon if path.is_file() else ''
        if path.name != icon:
            return ''
        stem = path.stem if path.suffix in _ICON_EXTENSIONS else icon
        name = escape(stem)
        for root in self.data_dirs:
            theme = root / 'icons/hicolor'
            variants = [
                path for path in theme.glob(f'*/apps/{name}.*')
                if path.suffix in _ICON_EXTENSIONS and path.is_file()
            ]
            if variants:
                return str(min(variants, key=self._icon_size))
            for extension in _ICON_EXTENSIONS:
                path = root / 'pixmaps' / (stem + extension)
                if path.is_file():
                    return str(path)
        return icon

    @staticmethod
    def _icon_size(path):
        size = path.parent.parent.name.split('x')[0]
        return (abs(int(size) - 64) + 1 if size.isdigit() else 0, str(path))

    @staticmethod
    def _steam_application(*names):
        keys = {normalize(name) for name in names} - _UNHELPFUL
        if not keys:
            return Application()
        home = Path.home()
        roots = [home / '.local/share/Steam', home / '.steam/steam', home / '.steam/root']
        roots = [root for root in dict.fromkeys(roots) if root.is_dir()]
        if not roots:
            return Application()
        libraries = []
        for root in roots:
            libraries.append(root / 'steamapps')
            folders = root / 'steamapps/libraryfolders.vdf'
            try:
                data = folders.read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
            for raw in re.findall(r'"path"\s+"([^"]+)"', data):
                libraries.append(Path(raw.replace('\\\\', '/')) / 'steamapps')
        for library in dict.fromkeys(libraries):
            if not library.is_dir():
                continue
            for manifest in library.glob('appmanifest_*.acf'):
                try:
                    data = manifest.read_text(encoding='utf-8', errors='replace')
                except OSError:
                    continue
                match = re.search(r'"name"\s+"([^"]+)"', data, re.IGNORECASE)
                if not match or normalize(match.group(1)) not in keys:
                    continue
                appid = manifest.stem.removeprefix('appmanifest_')
                name = match.group(1)
                for root in roots:
                    for path in (root / f'appcache/librarycache/{appid}_icon.jpg',
                                 root / f'appcache/librarycache/{appid}_icon.png',
                                 root / f'appcache/librarycache/{appid}/icon.jpg',
                                 root / f'steam/games/{appid}_icon.jpg'):
                        if path.is_file():
                            return Application(name, str(path))
                return Application(name, f'steam_icon_{appid}')
        return Application()


CATEGORIES = {
    'voice': r'webrtc|voiceengine|headset|microphone|mic|voice',
    'chat': r'discord|teams|skype|element|signal|telegram',
    'browser': r'zen|firefox|browser|chromium|chrome|brave|vivaldi|opera|librewolf',
    'music': r'spotify|music|vlc|rhythmbox|audacious|tidal',
    'video': r'video|obs|camera|screen|stream|capture',
    'games': r'\.exe|game|proton|wine|lutris',
    'system': r'system|daemon|notification|pipewire|wireplumber',
}


def category_for_source(key, name, binary):
    identity = f'{key} {name} {binary}'.lower()
    for category, pattern in CATEGORIES.items():
        if re.search(pattern, identity):
            return category
    return 'generic'

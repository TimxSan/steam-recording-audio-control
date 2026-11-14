

import configparser
import os
import re
import shlex
from pathlib import Path


_UNHELPFUL = {'', 'wine', 'wine64', 'wine64preloader', 'python', 'python3', 'steam',
              'pipewire', 'pulse', 'pulseaudio', 'alsaaudio', 'audiostream'}


def normalize(value):
    value = str(value or '').strip().casefold()
    if value.endswith('.desktop'):
        value = value[:-8]
    if value.endswith('.exe'):
        value = value[:-4]
    return re.sub(r'[^a-z0-9]+', '', value)


def candidate(value):
    value = str(value or '').strip()
    if not value:
        return ''
    return normalize(value)


def xdg_application_dirs():
    home = Path.home()
    data_home = Path(os.environ.get('XDG_DATA_HOME') or home / '.local/share')
    dirs = [data_home]
    dirs += [Path(p) for p in (os.environ.get('XDG_DATA_DIRS') or '/usr/local/share:/usr/share').split(':') if p]
    dirs += [home / '.local/share/flatpak/exports/share', Path('/var/lib/flatpak/exports/share')]
    seen = set()
    for root in dirs:
        path = root / 'applications'
        if path not in seen and path.is_dir():
            seen.add(path)
            yield path


def read_desktop(path):
    config = configparser.ConfigParser(interpolation=None, strict=False)
    config.optionxform = str
    try:
        with path.open('r', encoding='utf-8', errors='replace') as source:
            config.read_file(source)
        if 'Desktop Entry' not in config or config['Desktop Entry'].get('Type') != 'Application':
            return None
        entry = config['Desktop Entry']
        icon = entry.get('Icon', '').strip()
        if not icon:
            return None
        if icon.startswith('/') and not Path(icon).is_file():
            return None
        return {
            'icon': icon,
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


class IconResolver:
    def __init__(self):
        self.by_id = {}
        self.by_name = {}
        self.by_binary = {}
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        for directory in xdg_application_dirs():
            for path in sorted(directory.rglob('*.desktop')):
                entry = read_desktop(path)
                if not entry:
                    continue
                icon = entry['icon']
                for field in ('id', 'flatpak'):
                    key = candidate(entry[field])
                    if key:
                        self.by_id.setdefault(key, icon)
                for field in ('name', 'wmclass'):
                    key = candidate(entry[field])
                    if key:
                        self.by_name.setdefault(key, icon)
                binary = candidate(exec_binary(entry['exec']))
                if binary and binary not in _UNHELPFUL:
                    self.by_binary.setdefault(binary, icon)

    def resolve(self, props, key='', name=''):
        explicit = str(props.get('application.icon-name') or props.get('application.icon_name') or '').strip()
        if explicit:
            if not explicit.startswith('/') or Path(explicit).is_file():
                return explicit
        self._load()
        app_id = candidate(props.get('application.id'))
        if app_id and app_id in self.by_id:
            return self.by_id[app_id]
        for value in (name, props.get('application.name'), key,
                      props.get('node.name'), props.get('node.description')):
            value = candidate(value)
            if value and value not in _UNHELPFUL and value in self.by_name:
                return self.by_name[value]
        binary = candidate(Path(str(props.get('application.process.binary') or '')).name)
        if binary and binary not in _UNHELPFUL and binary in self.by_binary:
            return self.by_binary[binary]
        if app_id and app_id in self.by_name:
            return self.by_name[app_id]
        return self._steam_icon(name, key, props.get('application.name'))

    @staticmethod
    def _steam_icon(*names):
        keys = {candidate(name) for name in names}
        keys.discard('')
        if not keys:
            return ''
        home = Path.home()
        roots = [home / '.local/share/Steam', home / '.steam/steam', home / '.steam/root']
        roots = [root for root in dict.fromkeys(roots) if root.is_dir()]
        if not roots:
            return ''
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
                if not match or candidate(match.group(1)) not in keys:
                    continue
                appid = manifest.stem.removeprefix('appmanifest_')
                for root in roots:
                    for path in (root / f'appcache/librarycache/{appid}_icon.jpg',
                                 root / f'appcache/librarycache/{appid}_icon.png',
                                 root / f'appcache/librarycache/{appid}/icon.jpg',
                                 root / f'steam/games/{appid}_icon.jpg'):
                        if path.is_file():
                            return str(path)
                for base in (home / '.local/share/icons/hicolor', Path('/usr/share/icons/hicolor')):
                    if base.is_dir():
                        for path in base.glob(f'*/apps/steam_icon_{appid}.*'):
                            if path.is_file():
                                return str(path)
        return ''

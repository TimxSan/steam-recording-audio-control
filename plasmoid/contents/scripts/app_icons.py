import re


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

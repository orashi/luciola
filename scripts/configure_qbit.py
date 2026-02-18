from qbittorrentapi import Client


def load_env(path='.env'):
    env = {}
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            env[k] = v
    return env


env = load_env()
client = Client(
    host=env.get('QBIT_HOST', '127.0.0.1'),
    port=int(env.get('QBIT_PORT', '8080')),
    username=env.get('QBIT_USERNAME', ''),
    password=env.get('QBIT_PASSWORD', ''),
)
client.auth_log_in()

incoming = env.get('INCOMING_ROOT', '/media/incoming')
qsave = env.get('QBIT_SAVE_ROOT', '/downloads')
category = env.get('QBIT_CATEGORY', 'anime')

# Set qB-side default save path (container path)
client.app.set_preferences({'save_path': qsave})

# Ensure category exists with qB-side target path
try:
    client.torrents_create_category(name=category, save_path=qsave)
except Exception:
    client.torrents_edit_category(name=category, save_path=qsave)

prefs = client.app.preferences
print({
    'ok': True,
    'version': client.app.version,
    'save_path': prefs.get('save_path'),
    'category': category,
    'category_path': qsave,
    'host_incoming_root': incoming,
})

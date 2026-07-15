import sys, json, subprocess

d = json.load(sys.stdin)
parts = []

# Current dir (last 2 folders)
cd = d.get('workspace', {}).get('current_dir', '')
if cd:
    normalized = cd.replace('\\', '/')
    parts.append('/'.join(normalized.split('/')[-2:]))

# Git branch
try:
    result = subprocess.run(['git', 'rev-parse', '--git-dir'],
                          capture_output=True, timeout=1)
    if result.returncode == 0:
        branch = subprocess.run(['git', 'branch', '--show-current'],
                               capture_output=True, timeout=1)
        if branch.stdout:
            b = branch.stdout.decode().strip()
            if b:
                parts.append(f'[{b}]')
except:
    pass

# Model name
mn = d.get('model', {}).get('display_name')
if mn:
    parts.append(mn)

# Context usage
u = d.get('context_window', {}).get('used_percentage')
r = d.get('context_window', {}).get('remaining_percentage')
if u and r:
    parts.append(f'Ctx: {u}%/{r}%')
elif u:
    parts.append(f'Ctx: {u}%')

# Session name
sn = d.get('session_name')
if sn:
    parts.append(f'({sn})')

print(' | '.join(parts))

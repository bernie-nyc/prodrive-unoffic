#!/usr/bin/env python3
"""
fix_deps.py — Patch dependency issues in the WebClients build.

WebClients is a monorepo with Proton-internal dependencies and registries that are
inaccessible from CI/build environments. This script performs several fixups:

1. REMOVE PROBLEMATIC DEPS — Strips rowsnColumns, proton-meet, electron, and
   proton-foundation-search from dependency sections in all WebClients package.json
   files. These packages either don't exist on public npm or aren't needed for
   the Drive desktop build.

2. PATCH DRIVE BUILD — Changes appMode from 'sso' to 'standalone' (SSO expects
   Proton's domain; standalone works with any origin like tauri://). Removes any
   --api flag (Tauri IPC handles API calls). Adds --no-sri because WebKitGTK
   rejects script integrity attributes on the tauri:// protocol.

3. PATCH ACCOUNT BUILD — Sets --api=/api so the account app uses relative API
   paths instead of a hardcoded absolute Proton domain.  Without this, SSO-mode
   builds use https://api.proton.me as the base, which omits /api/ from the path
   and bypasses the fetch proxy, causing "cannot fetch server time" at login.
   Also adds --no-sri (same WebKitGTK tauri:// SRI rejection as drive).

4. DISABLE SRI FOR VERIFY — Same WebKitGTK tauri:// SRI rejection; adds
   --no-sri to the verify app's build:web script.

5. CONFIGURE YARN — Removes npmScopes and npmRegistries sections (internal Proton
   registries unreachable from CI), overrides npmRegistryServer to the public
   registry, and disables immutable installs for CI compatibility.

6. PIN THE BUILD TOOLCHAIN — build-webclients.sh empties WebClients/yarn.lock
   before `yarn install`, so every dependency floats to the newest version that
   satisfies its range. For the webpack toolchain that is dangerous: webpack
   5.110 (published after Proton locked 5.109.2) changed how
   `optimization.minimize` is normalised and esbuild-loader then fed esbuild a
   non-boolean `minify`, failing every app build with
   `"minify" must be a boolean`. This step reads the upstream yarn.lock while
   it still exists and pins each dependency of @proton/pack (the package that
   owns the webpack config) to its locked version via the root `resolutions`
   field, so the toolchain stays at the combination Proton actually tested.

Run BEFORE `yarn install` in WebClients. Requires WebClients/ to exist (cloned).
"""
import json
import re
import sys
from pathlib import Path

# Check if WebClients directory exists
webclient_dir = Path('WebClients')
if not webclient_dir.exists():
    print("❌ ERROR: WebClients directory not found!")
    print("   Please clone WebClients first:")
    print("   git clone --depth=1 https://github.com/ProtonMail/WebClients.git WebClients")
    sys.exit(1)

print("Scanning for problematic dependencies...")
count = 0

for pkg in Path('WebClients').rglob('package.json'):
    if 'node_modules' in str(pkg) or '.yarn' in str(pkg):
        continue
    try:
        data = json.loads(pkg.read_text())
        modified = False

        for section in ('dependencies', 'devDependencies', 'peerDependencies', 'optionalDependencies'):
            if section in data:
                for k in list(data[section].keys()):
                    if any(bad in k.lower() for bad in ['rowsncolumns', 'proton-meet', 'electron', 'proton-foundation-search']):
                        print(f"  Removing {k} from {pkg}")
                        del data[section][k]
                        modified = True
                        count += 1

        if modified:
            pkg.write_text(json.dumps(data, indent=2) + '\n')

    except Exception as e:
        print(f"  Warning: Could not process {pkg}: {e}")

print(f"✅ Patched {count} dependencies")

# Patch Proton Drive to use standalone mode for desktop wrapper
# SSO mode expects to run on Proton's domain, standalone mode works with any origin
# No --api flag needed: Tauri IPC intercepts all fetch/XHR calls to Proton domains
print("\nPatching Proton Drive build configuration...")
drive_pkg_path = Path('WebClients/applications/drive/package.json')
if drive_pkg_path.exists():
    drive_data = json.loads(drive_pkg_path.read_text())
    if 'scripts' in drive_data and 'build:web' in drive_data['scripts']:
        old_script = drive_data['scripts']['build:web']
        # Change appMode from sso to standalone for desktop wrapper
        new_script = re.sub(r'--appMode=sso', '--appMode=standalone', old_script)
        # Remove any --api override - Tauri IPC handles API calls via fetch interception
        new_script = re.sub(r'\s*--api=\S+', '', new_script)
        # Disable SRI: WebKitGTK rejects script integrity attributes on tauri:// protocol,
        # causing "Loading chunk X failed" even when the fetch returns HTTP 200.
        if '--no-sri' not in new_script:
            new_script = new_script.rstrip() + ' --no-sri'
        if old_script != new_script:
            drive_data['scripts']['build:web'] = new_script
            drive_pkg_path.write_text(json.dumps(drive_data, indent=4) + '\n')
            print("  Changed appMode to standalone, disabled SRI (WebKitGTK tauri:// incompatibility)")
        else:
            print("  build:web already configured")
    else:
        print("  Warning: Could not find build:web script")
else:
    print("  Warning: Could not find drive package.json")

# Patch account app: force relative API paths and disable SRI.
# Without --api=/api the account app in SSO mode hard-codes an absolute Proton
# API base URL (e.g. https://api.proton.me).  Requests to that domain omit the
# /api/ path prefix, so the fetch proxy's url.includes('/api/') guard misses
# them — they fall through to native WebKit fetch which fails with CORS and
# surfaces as "cannot fetch server time" in the SRP login flow.
# Setting --api=/api forces relative paths that the proxy always catches.
print("\nPatching Proton Account build configuration...")
account_pkg_path = Path('WebClients/applications/account/package.json')
if account_pkg_path.exists():
    account_data = json.loads(account_pkg_path.read_text())
    if 'scripts' in account_data and 'build:web' in account_data['scripts']:
        old_script = account_data['scripts']['build:web']
        new_script = old_script
        # Remove any existing --api flag before we set our own
        new_script = re.sub(r'\s*--api=\S+', '', new_script)
        # Force relative API paths so all calls go through the Tauri IPC proxy
        if '--api=/api' not in new_script:
            new_script = new_script.rstrip() + ' --api=/api'
        if '--no-sri' not in new_script:
            new_script = new_script.rstrip() + ' --no-sri'
        if old_script != new_script:
            account_data['scripts']['build:web'] = new_script
            account_pkg_path.write_text(json.dumps(account_data, indent=4) + '\n')
            print("  Set --api=/api (relative paths) and disabled SRI for account app")
        else:
            print("  account app already configured correctly")
    else:
        print("  Warning: Could not find build:web script in account package.json")
else:
    print("  Warning: Could not find account package.json")

# Disable SRI for verify app (same WebKitGTK tauri:// SRI rejection issue)
for app_name, app_pkg_path in [
    ('verify', Path('WebClients/applications/verify/package.json')),
]:
    if app_pkg_path.exists():
        app_data = json.loads(app_pkg_path.read_text())
        if 'scripts' in app_data and 'build:web' in app_data['scripts']:
            old_script = app_data['scripts']['build:web']
            if '--no-sri' not in old_script:
                new_script = old_script.rstrip() + ' --no-sri'
                app_data['scripts']['build:web'] = new_script
                app_pkg_path.write_text(json.dumps(app_data, indent=4) + '\n')
                print(f"  Disabled SRI for {app_name} app")
            else:
                print(f"  {app_name} SRI already disabled")
    else:
        print(f"  Warning: Could not find {app_name} package.json")

# Configure yarn for better reliability and compatibility
print("\nConfiguring Yarn settings...")
yarnrc_path = Path('WebClients/.yarnrc.yml')
yarnrc_content = yarnrc_path.read_text() if yarnrc_path.exists() else ""

# Parse and rewrite .yarnrc.yml
lines = yarnrc_content.split('\n')
new_lines = []
skip_until_dedent = False
skip_depth = 0

for line in lines:
    stripped = line.lstrip()
    current_indent = len(line) - len(stripped)

    if stripped.startswith('npmScopes:'):
        skip_until_dedent = True
        skip_depth = current_indent
        print("  Removing npmScopes (internal Proton registries)")
        continue

    if stripped.startswith('npmRegistries:'):
        skip_until_dedent = True
        skip_depth = current_indent
        print("  Removing npmRegistries (internal registry auth)")
        continue

    if skip_until_dedent:
        if stripped and current_indent <= skip_depth:
            skip_until_dedent = False
        else:
            continue

    if stripped.startswith('npmRegistryServer:'):
        new_lines.append('npmRegistryServer: "https://registry.npmjs.org"')
        print("  Overriding npmRegistryServer to use public npm registry")
        continue

    new_lines.append(line)

yarnrc_content = '\n'.join(new_lines)

if 'npmRegistryServer' not in yarnrc_content:
    yarnrc_content += '\nnpmRegistryServer: "https://registry.npmjs.org"\n'
    print("  Added official npm registry configuration")

if 'enableImmutableInstalls' not in yarnrc_content:
    yarnrc_content += 'enableImmutableInstalls: false\n'
    print("  Disabled immutable installs mode")

yarnrc_path.write_text(yarnrc_content)
print("✅ Yarn configured with public npm registry")

# Stub removed @proton/components exports.
# DrawerAppButton was removed from @proton/components upstream.
# Rather than patching the barrel (whose path changes across WebClients versions),
# we patch the Drive app's DriveWindow.tsx to define a local no-op stub and
# remove the now-missing import so the webpack build doesn't fail.
print("\nPatching removed @proton/components exports...")
drive_window_path = Path('WebClients/applications/drive/src/app/legacy/components/layout/DriveWindow.tsx')
if drive_window_path.exists():
    content = drive_window_path.read_text()
    if 'DrawerAppButton' in content:
        import re as _re

        # 1. Remove DrawerAppButton from any { ..., DrawerAppButton, ... } import line
        content = _re.sub(r',\s*DrawerAppButton\b', '', content)
        content = _re.sub(r'\bDrawerAppButton\s*,', '', content)
        # Handle the case where it's the only import in the braces
        content = _re.sub(r'\{\s*DrawerAppButton\s*\}', '{}', content)

        # 2. Add a local stub after the last import in the file so any remaining
        #    JSX references compile.  If there are no remaining references the
        #    stub is harmless.
        last_import_match = None
        for m in _re.finditer(r'^import .+$', content, _re.MULTILINE):
            last_import_match = m
        stub_component = (
            "\n// Compatibility stub — DrawerAppButton removed from @proton/components\n"
            "const DrawerAppButton: React.FC<Record<string, unknown>> = () => null;\n"
        )
        if last_import_match and 'const DrawerAppButton' not in content:
            insert_pos = last_import_match.end()
            content = content[:insert_pos] + stub_component + content[insert_pos:]

        drive_window_path.write_text(content)
        print("  Patched DriveWindow.tsx: removed DrawerAppButton import, added no-op stub")
    else:
        print("  DriveWindow.tsx: DrawerAppButton not present (already clean)")
else:
    print("  DriveWindow.tsx not found — skipping DrawerAppButton patch")


# Pin the build toolchain to the versions in the upstream lockfile.
# build-webclients.sh truncates yarn.lock before installing, so without this
# every @proton/pack dependency (webpack, webpack-cli, esbuild-loader, swc,
# terser-webpack-plugin, ...) resolves to whatever npm published most recently.
# Proton only ever tested the combination recorded in their yarn.lock; copy it
# into root `resolutions` so the wiped lockfile cannot drift the toolchain.
def parse_yarn_lock_versions(lock_text):
    """Map package name -> set of locked versions (npm: descriptors only)."""
    versions = {}
    current_names = []
    for line in lock_text.splitlines():
        if not line or line.startswith('#'):
            continue
        if line[0] not in ' \t':
            current_names = []
            header = line.rstrip()
            if not header.endswith(':') or header.startswith('__metadata'):
                continue
            header = header[:-1].strip().strip('"')
            for descriptor in header.split(', '):
                descriptor = descriptor.strip().strip('"')
                at = descriptor.find('@', 1)
                if at == -1:
                    continue
                name, spec = descriptor[:at], descriptor[at + 1:]
                if spec.startswith('npm:'):
                    current_names.append(name)
            continue
        stripped = line.strip()
        if stripped.startswith('version:') and current_names:
            version = stripped[len('version:'):].strip().strip('"')
            for name in current_names:
                versions.setdefault(name, set()).add(version)
            current_names = []
    return versions


print("\nPinning build toolchain to upstream yarn.lock versions...")
lock_path = Path('WebClients/yarn.lock')
pack_pkg_path = Path('WebClients/packages/pack/package.json')
root_pkg_path = Path('WebClients/package.json')
if not lock_path.exists() or lock_path.stat().st_size == 0:
    print("  Warning: WebClients/yarn.lock missing or empty — toolchain not pinned")
elif not pack_pkg_path.exists() or not root_pkg_path.exists():
    print("  Warning: packages/pack/package.json or root package.json missing — toolchain not pinned")
else:
    locked = parse_yarn_lock_versions(lock_path.read_text())
    pack_data = json.loads(pack_pkg_path.read_text())
    root_data = json.loads(root_pkg_path.read_text())
    resolutions = root_data.setdefault('resolutions', {})
    pinned, skipped_multi, skipped_missing = [], [], []
    for name in sorted(pack_data.get('dependencies', {})):
        if name.startswith('@proton/') or name in resolutions:
            continue
        found = locked.get(name)
        if not found:
            skipped_missing.append(name)
        elif len(found) > 1:
            # Several incompatible ranges coexist in the tree; a blanket pin
            # would force them all onto one version. Leave those alone.
            skipped_multi.append(f"{name} ({', '.join(sorted(found))})")
        else:
            version = next(iter(found))
            resolutions[name] = version
            pinned.append(f"{name}@{version}")
    root_pkg_path.write_text(json.dumps(root_data, indent=4) + '\n')
    print(f"  Pinned {len(pinned)} toolchain packages via root resolutions")
    for entry in pinned:
        print(f"    {entry}")
    if skipped_multi:
        print(f"  Left unpinned (multiple locked versions): {', '.join(skipped_multi)}")
    if skipped_missing:
        print(f"  Left unpinned (not in yarn.lock): {', '.join(skipped_missing)}")
    if 'webpack' not in resolutions:
        print("  ERROR: webpack was not pinned; the build toolchain would float")
        sys.exit(1)
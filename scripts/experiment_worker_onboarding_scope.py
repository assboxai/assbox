"""Read the actual guest user-unit derivations from production worker images."""
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys


nix, store, out = map(Path, sys.argv[1:4])
architecture = sys.argv[4] if len(sys.argv) == 5 else 'x86_64-linux'
assert architecture in ('x86_64-linux', 'aarch64-linux')
source = Path.cwd()
git = lambda *args: subprocess.check_output(['git', *args], text=True).strip()
revision = git('rev-parse', 'HEAD')
reference = f'git+file://{source}?rev={revision}'
expression = f'''
let
  source = builtins.getFlake {json.dumps(reference)};
  base = source.nixosConfigurations.{architecture}-uefi-none-headless;
  produce = extra:
    let config = (base.extendModules {{ modules = [ {{
      assbox.worker = {{ enable = true; components = [ "hermes" "hermes-gateway" ]; stateGiB = 8; }};
    }} extra ]; }}).config;
    in config.system.build.assboxWorkerImage.drvPath;
in {{
  offline = produce {{ assbox.worker = {{ egress = "offline"; nameservers = [ ]; }}; }};
  internet = produce {{ assbox.worker = {{ egress = "internet"; nameservers = [ "192.0.2.53" ]; uplinkInterfaces = [ "enp0s5" ]; }}; }};
  guestSudo = produce {{ assbox.worker = {{ egress = "offline"; nameservers = [ ]; allowGuestSudo = true; }}; }};
  timeZone = produce ({{ lib, ... }}: {{
    assbox.worker = {{ egress = "offline"; nameservers = [ ]; }};
    time.timeZone = lib.mkForce "America/Denver";
  }});
}}
'''


def run(*args, timeout=90):
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise SystemExit(result.stderr)
    return result.stdout


images = json.loads(run(nix, 'eval', '--json', '--impure', '--offline', '--no-update-lock-file',
                        '--no-write-lock-file', '--expr', expression, timeout=170))
assert set(images) == {'offline', 'internet', 'guestSudo', 'timeZone'}
observed = {}
for scope, image in images.items():
    paths = run(store, '--query', '--requisites', image).splitlines()
    units = [path for path in paths if re.fullmatch(r'/nix/store/[a-z0-9]{32}-unit-assbox-hermes-gateway\.service\.drv', path)]
    unit, = units
    outputs = run(nix, 'derivation', 'show', unit)
    (out / (scope + '-unit.json')).write_text(outputs)
    payload = json.loads(outputs)
    entries = payload['derivations'] if 'derivations' in payload else payload
    entry, = entries
    assert entry in (unit, Path(unit).name), entry
    node = entries[entry]
    properties = node['env']
    contents = '\n'.join(properties.values())
    marker, = re.findall(r'ConditionPathExists=%h/\.config/assbox/onboarded/(hermes-gateway-[0-9a-f]{20})', contents)
    observed[scope] = {'imageDerivation': image, 'unitDerivation': unit, 'marker': marker,
                       'unitJsonSha256': sha256(outputs.encode()).hexdigest()}

base = observed['offline']['marker']
assert all(observed[mode]['marker'] != base for mode in ('internet', 'guestSudo'))
assert observed['timeZone']['marker'] == base
assert len({item['imageDerivation'] for item in observed.values()}) == 4
report = {'revision': revision, 'tree': git('rev-parse', 'HEAD^{tree}'), 'architecture': architecture, 'workerHostCases': observed,
          'scope': 'Real generated worker image derivations and the embedded Hermes Gateway systemd unit. Changes to host egress or guest sudo rotate the marker. A harmless timezone change preserves it.'}
(out / 'verified.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))

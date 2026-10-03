"""Exercise the Hermes adapter's interpreter selection without building a package."""
import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class HermesPythonTests(unittest.TestCase):
    def evaluate(self, dependencies, expose_interpreter=False):
        library = os.environ['ASSBOX_NIX_LIB']
        expression = '''
        let
          lib = import LIBRARY;
          python = rec {
            outPath = "/declared-python";
            sitePackages = "lib/python3.14/site-packages";
            withPackages = choose:
              assert lib.all (p: p.pythonModule == python) (choose {});
              { outPath = "/declared-python-env"; };
          };
          otherPython = { outPath = "/wrong-python"; };
          raw = {
            dependencies = DEPENDENCIES;
            overridePythonAttrs = adapt: adapt {
              makeWrapperArgs = [ "--run" "/original/bin/python3" ];
            };
          } // INTERPRETER;
          adapted = import ADAPTER {
            inherit lib raw;
            pkgs.python3.withPackages = _: throw "host Python must not be selected";
          };
        in {
          wrappers = adapted.makeWrapperArgs;
          imports = adapted.installCheckPhase;
          retained = adapted.postInstallCheck;
          dependencies = map (p: p.pname) adapted.dependencies;
        }
        '''.replace('LIBRARY', json.dumps(library)).replace(
            'DEPENDENCIES', dependencies).replace('INTERPRETER',
            '{ pythonModule = python; }' if expose_interpreter else '{}').replace(
            'ADAPTER', json.dumps(str(ROOT / 'nix/hermes.nix')))
        return subprocess.run(['nix', 'eval', '--impure', '--json', '--expr', expression],
                              capture_output=True, text=True, timeout=30)

    def test_application_without_python_module_uses_dependency_interpreter(self):
        result = self.evaluate('''[
          { pname = "openai"; pythonModule = python; }
          { pname = "numpy"; pythonModule = python; }
        ]''')
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value['wrappers'], ['--run', '/declared-python-env/bin/python3'])
        self.assertIn('/declared-python-env/bin/python3', value['imports'])
        self.assertIn('lib/python3.14/site-packages', value['retained'])
        self.assertEqual(value['dependencies'], ['openai'])

    def test_mixed_native_extension_interpreters_are_refused(self):
        result = self.evaluate('''[
          { pname = "openai"; pythonModule = python; }
          { pname = "pydantic"; pythonModule = otherPython; }
        ]''', expose_interpreter=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('assertion', result.stderr)

    def test_missing_declared_interpreter_is_refused(self):
        result = self.evaluate('[]')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('do not identify their Python interpreter', result.stderr)


if __name__ == '__main__':
    unittest.main()

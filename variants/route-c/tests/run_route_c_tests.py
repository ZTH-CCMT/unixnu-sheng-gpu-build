#!/usr/bin/env python3
"""Route C: unchanged frozen17 + actual production Engine/Core fast-start tests."""
from pathlib import Path
import argparse,hashlib,json,os,re,subprocess,sys
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
root=a.root.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1';env['TMPDIR']=str(out)
env['UBSAN_OPTIONS']='halt_on_error=1:print_stacktrace=1';env['ASAN_OPTIONS']='halt_on_error=1'
commands=[]
def run(cmd):
 commands.append([str(x) for x in cmd]);r=subprocess.run(cmd,capture_output=True,text=True,env=env)
 if r.returncode or re.search(r'runtime error:|ERROR: (?:AddressSanitizer|LeakSanitizer)|Sanitizer:DEADLYSIGNAL',r.stderr):
  print(r.stdout,end='');print(r.stderr,end='');raise RuntimeError('command/sanitizer failed: '+str(cmd))
 return r
base=run([sys.executable,'-B',str(root/'tests/run_host_tests.py'),'--root',str(root),'--out',str(out/'frozen17')])
flags=['-g','-O1','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-fno-omit-frame-pointer']
driver=root/'device/drivers/ShengNovatekTouch';package=root/'device/package'
objects=[out/'frozen17'/x for x in ('NvtTouchCore.o','NvtProtocol.o','reference-NvtTouchCore.c.o','reference-baseline_adapter.c.o')]
binary=out/'route_c_cases'
run([os.environ.get('CXX','c++'),'-std=c++17',*flags,'-I',str(driver),'-I',str(package),str(root/'tests/route_c_cases.cpp'),*[str(x) for x in objects],'-o',str(binary)])
r=run([str(binary)]);(out/'stdout.txt').write_text(r.stdout);(out/'stderr.txt').write_text(r.stderr)
record={'status':'PASS_HOST_SYNTHETIC_NOT_HARDWARE','route':'C-fast-confirm','original17':json.loads((out/'frozen17/host-test-results.json').read_text()),'route_cases':json.loads(r.stdout.splitlines()[-1]),'commands':commands,'production_hashes':{str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest() for f in (driver/'NvtTouchCore.c',driver/'NvtTouchCore.h',package/'TouchEngine.h')},'fixture_changes':'Original test_timed_touch.cpp and default1000 peak unchanged; new fast-start tests use multi-node shapes.'}
(out/'route-c-results.json').write_text(json.dumps(record,indent=2)+'\n');print(base.stdout,end='');print(r.stdout,end='')
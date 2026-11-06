#!/usr/bin/env python3
"""Route B real-engine synthetic tests; no hardware/network access."""
import argparse,hashlib,json,os,re,shutil,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
r=a.root.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
cc=shutil.which(os.environ.get('CC','cc'));cxx=shutil.which(os.environ.get('CXX','c++'))
if not cc or not cxx:raise SystemExit('Host C/C++ compiler missing')
d=r/'device/drivers/ShengNovatekTouch';pkg=r/'device/package'
flags=['-g','-O1','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-fno-omit-frame-pointer']
commands=[];objects=[]
for name in ('NvtTouchCore','NvtProtocol'):
 obj=out/(name+'.o');cmd=[cc,'-std=c11',*flags,'-I',str(d),'-c',str(d/(name+'.c')),'-o',str(obj)];commands.append(cmd);subprocess.run(cmd,check=True);objects.append(obj)
binary=out/'test_measured_position';cmd=[cxx,'-std=c++17',*flags,'-I',str(d),'-I',str(pkg),str(r/'tests/test_measured_position.cpp'),*[str(x) for x in objects],'-o',str(binary)];commands.append(cmd);subprocess.run(cmd,check=True)
env=os.environ.copy();env['UBSAN_OPTIONS']='halt_on_error=1:print_stacktrace=1';env['ASAN_OPTIONS']='halt_on_error=1'
s=subprocess.run([str(binary)],capture_output=True,text=True,env=env);(out/'stdout.txt').write_text(s.stdout);(out/'stderr.txt').write_text(s.stderr)
sanitizer_failure=bool(re.search(r'runtime error:|ERROR: (?:AddressSanitizer|LeakSanitizer)|UndefinedBehaviorSanitizer|Sanitizer:DEADLYSIGNAL',s.stderr))
code=s.returncode or (2 if sanitizer_failure else 0)
result=dict(status='PASS_HOST_SYNTHETIC_NOT_HARDWARE' if code==0 else 'FAIL',route='B-measured-position',exit_code=code,sanitizer_failure=sanitizer_failure,commands=commands,stdout=s.stdout,stderr=s.stderr,production_hashes={str(f.relative_to(r)):hashlib.sha256(f.read_bytes()).hexdigest() for f in (d/'NvtTouchCore.c',d/'NvtTouchCore.h',d/'NvtProtocol.c',pkg/'TouchEngine.h')})
(out/'route-test-results.json').write_text(json.dumps(result,indent=2)+'\n');print(s.stdout,end='');print(s.stderr,end='');raise SystemExit(code)

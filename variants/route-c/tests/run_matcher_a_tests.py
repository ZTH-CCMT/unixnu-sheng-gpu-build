#!/usr/bin/env python3
"""Route A: exact production Core/Engine vs frozen AG; no hardware/network."""
import argparse,hashlib,json,os,re,shutil,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--out',type=Path,required=True);p.add_argument('--skip-original',action='store_true');a=p.parse_args()
root=a.root.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
tests=root/'tests';driver=root/'device/drivers/ShengNovatekTouch';package=root/'device/package'
os.environ['TMPDIR']=str(out)
commands=[]
def run(cmd,**kw):
 commands.append([str(x) for x in cmd]);options=dict(text=True,capture_output=True);options.update(kw)
 r=subprocess.run([str(x) for x in cmd],check=False,**options)
 if r.returncode:
  failure=dict(status='FAIL_HOST_STAGE_NOT_HARDWARE',exit_code=r.returncode,commands=commands,stdout=r.stdout,stderr=r.stderr)
  (out/'route-test-results.json').write_text(json.dumps(failure,indent=2)+'\n');(out/'stdout.txt').write_text(r.stdout or '');(out/'stderr.txt').write_text(r.stderr or '')
  print(r.stdout or '',end='');print(r.stderr or '',end='',file=sys.stderr);raise SystemExit(r.returncode)
 return r
if not a.skip_original:run([sys.executable,'-B',tests/'run_host_tests.py','--root',root,'--out',out/'original17'])
cc=shutil.which(os.environ.get('CC','cc'));cxx=shutil.which(os.environ.get('CXX','c++'))
if not cc or not cxx:raise SystemExit('Host C/C++ compiler missing')
flags=['-g','-O1','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-fno-omit-frame-pointer'];inc=['-I'+str(driver),'-I'+str(package)]
obj=[]
for source,name,extra in [(tests/'route_a_probe.c','production-route.o',[]),(driver/'NvtProtocol.c','production-protocol.o',[]),(tests/'parent_ag_probe.c','parent-ag.o',['-D'+n+'=ag_'+n for n in ['nvt_touch_reset','nvt_touch_process','nvt_touch_process_timed','nvt_touch_expire','nvt_touch_wait_us','nvt_touch_row_center','nvt_touch_column_center','nvt_touch_map_edge_axis']])]:
 target=out/name;run([cc,'-std=c11',*flags,*inc,*extra,'-c',source,'-o',target]);obj.append(target)
binary=out/'route-a-tests';run([cxx,'-std=c++17',*flags,*inc,tests/'test_route_a.cpp',*obj,'-o',binary])
env=os.environ.copy();env['UBSAN_OPTIONS']='halt_on_error=1:print_stacktrace=1';env['ASAN_OPTIONS']='halt_on_error=1'
r=run([binary],text=True,capture_output=True,env=env);(out/'stdout.txt').write_text(r.stdout);(out/'stderr.txt').write_text(r.stderr)
assert not re.search(r'runtime error:|ERROR: (?:AddressSanitizer|LeakSanitizer)|UndefinedBehaviorSanitizer|Sanitizer:DEADLYSIGNAL',r.stderr),r.stderr
last=json.loads(r.stdout.strip().splitlines()[-1]);last.update(commands=commands,production_core_sha256=hashlib.sha256((driver/'NvtTouchCore.c').read_bytes()).hexdigest(),parent_AG_core_sha256=hashlib.sha256((tests/'reference-aggressive/NvtTouchCore.c').read_bytes()).hexdigest(),original17_run=not a.skip_original,sanitizer_options={'UBSAN_OPTIONS':env['UBSAN_OPTIONS'],'ASAN_OPTIONS':env['ASAN_OPTIONS']},traces=[x for x in r.stdout.splitlines() if x.startswith('TRACE ')])
(out/'route-test-results.json').write_text(json.dumps(last,indent=2)+'\n');print(r.stdout,end='');print(r.stderr,end='')

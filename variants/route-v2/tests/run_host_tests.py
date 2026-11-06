#!/usr/bin/env python3
"""Build real production TouchEngine/Core contract tests. No hardware/network."""
import argparse,hashlib,json,os,re,shutil,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
root=a.root.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
tests=Path(__file__).resolve().parent;driver=root/'device/drivers/ShengNovatekTouch';package=root/'device/package'
cc=shutil.which(os.environ.get('CC','cc'));cxx=shutil.which(os.environ.get('CXX','c++'))
if not cc or not cxx:raise SystemExit('Host C/C++ compiler missing')
flags=['-g','-O1','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-fno-omit-frame-pointer']
commands=[]
def run(cmd):
    commands.append([str(x) for x in cmd]);subprocess.run(cmd,check=True)
objects=[]
for name in ['NvtTouchCore','NvtProtocol']:
    obj=out/(name+'.o');run([cc,'-std=c11',*flags,'-I',str(driver),'-c',str(driver/(name+'.c')),'-o',str(obj)]);objects.append(obj)
renames=['nvt_touch_reset','nvt_touch_process','nvt_touch_row_center','nvt_touch_column_center','nvt_touch_map_edge_axis']
for filename in ['NvtTouchCore.c','baseline_adapter.c']:
    obj=out/('reference-'+filename+'.o');run([cc,'-std=c11',*flags,*['-D'+n+'=baseline_'+n for n in renames],'-I',str(tests/'reference'),'-c',str(tests/'reference'/filename),'-o',str(obj)]);objects.append(obj)
binary=out/'test_timed_touch';run([cxx,'-std=c++17',*flags,'-I',str(driver),'-I',str(package),str(tests/'test_timed_touch.cpp'),*[str(x) for x in objects],'-o',str(binary)])
env=os.environ.copy();env['UBSAN_OPTIONS']='halt_on_error=1:print_stacktrace=1';env['ASAN_OPTIONS']='halt_on_error=1'
r=subprocess.run([str(binary)],text=True,capture_output=True,env=env);(out/'stdout.txt').write_text(r.stdout);(out/'stderr.txt').write_text(r.stderr)
sanitizer_failure=bool(re.search(r'runtime error:|ERROR: (?:AddressSanitizer|LeakSanitizer)|UndefinedBehaviorSanitizer|Sanitizer:DEADLYSIGNAL',r.stderr))
exit_code=r.returncode if r.returncode else 2 if sanitizer_failure else 0
receipt={'status':'PASS_HOST_SYNTHETIC_NOT_HARDWARE' if exit_code==0 else 'FAIL','sanitizer_failure':sanitizer_failure,'sanitizer_options':{'UBSAN_OPTIONS':env['UBSAN_OPTIONS'],'ASAN_OPTIONS':env['ASAN_OPTIONS']},'exit_code':exit_code,'commands':commands,'stdout':r.stdout,'stderr':r.stderr,'production_hashes':{str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest() for f in [driver/'NvtTouchCore.c',driver/'NvtTouchCore.h',package/'TouchEngine.h']}}
(out/'host-test-results.json').write_text(json.dumps(receipt,indent=2)+'\n');print(r.stdout,end='');print(r.stderr,end='')
raise SystemExit(exit_code)

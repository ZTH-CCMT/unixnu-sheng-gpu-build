#!/usr/bin/env python3
"""Compile the actual Astra touch C and C++ modules with host sanitizers."""
from pathlib import Path
import argparse,hashlib,json,os,subprocess,sys
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
r=a.root.resolve();o=a.out.resolve();o.mkdir(parents=True,exist_ok=False)
d=r/'device/drivers/ShengNovatekTouch';pkg=r/'device/package'
flags=['-g','-O1','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-fno-omit-frame-pointer']
env=dict(os.environ,TMPDIR=str(o),TMP=str(o),TEMP=str(o),PYTHONDONTWRITEBYTECODE='1',ASAN_OPTIONS='halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
commands=[];groups=[]
def run(cmd,name):
 commands.append(list(map(str,cmd)));s=subprocess.run(list(map(str,cmd)),text=True,capture_output=True,env=env)
 (o/(name+'.stdout')).write_text(s.stdout);(o/(name+'.stderr')).write_text(s.stderr)
 if s.returncode:
  (o/'failure.json').write_text(json.dumps({'command':list(map(str,cmd)),'returncode':s.returncode,'stdout':s.stdout,'stderr':s.stderr},indent=2))
  print(s.stdout);print(s.stderr,file=sys.stderr);raise SystemExit(s.returncode)
 return s.stdout
objects=[]
extract=r/'tests/extract_astra_probe.py'
if extract.exists():run([sys.executable,'-B',extract,'--root',r,'--out',o],'probe-extraction')
for stem in ['NvtProtocol','NvtTouchCore','NvtPartialObservation','NvtCoverage']:
 obj=o/(stem+'.o');run([os.environ.get('CC','cc'),'-std=c11',*flags,'-Wframe-larger-than=8192','-I',d,'-MMD','-MF',o/(stem+'.d'),'-c',d/(stem+'.c'),'-o',obj],stem);objects.append(obj)
for source in sorted((r/'tests').glob('test_astra_*.cpp')):
 name=source.stem;binary=o/name
 run([os.environ.get('CXX','c++'),'-std=c++17',*flags,'-I',d,'-I',pkg,'-I',o,source,*objects,'-o',binary],name+'-compile')
 stdout=run([binary],name);print(stdout,flush=True);groups.append({'source':source.name,'output':stdout})
assert len(groups)>=4,'Missing Core, PM, timeline or Engine integration suite'
files=sorted((r/'device').rglob('*'))
report={'status':'PASS_ACTUAL_TOUCH_MODULES_HOST_SANITIZERS_NOT_HARDWARE','groups':groups,'commands':commands,'source_sha256':{x.relative_to(r).as_posix():hashlib.sha256(x.read_bytes()).hexdigest() for x in files if x.is_file()},'native_built':False,'hardware_tested':False}
(o/'results.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'status':report['status'],'groups':len(groups)}))

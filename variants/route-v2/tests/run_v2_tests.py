#!/usr/bin/env python3
# Public, synthetic production-Core contracts; no real device traces or identity.
from pathlib import Path
import argparse,hashlib,json,os,re,subprocess,sys
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();root=a.root.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True);tests=Path(__file__).resolve().parent
core=root/'device/drivers/ShengNovatekTouch';pkg=root/'device/package'
wanted={'NvtTouchCore.c':'dfe424e8582d392e46245951f64a7a8e61e55592fbfe181c6f3da24383ff9207','NvtTouchCore.h':'6489771d5ece805a791c067656940fc2e382ec2ea5e6d644abd33b1977964b6f'}
for n,h in wanted.items():assert hashlib.sha256((core/n).read_bytes()).hexdigest()==h,n
subprocess.run([sys.executable,'-B',str(tests/'run_host_tests.py'),'--root',str(root),'--out',str(out/'original17')],check=True)
flags=['-g','-O1','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-fno-omit-frame-pointer'];env=dict(os.environ,TMPDIR=str(out),PYTHONDONTWRITEBYTECODE='1',ASAN_OPTIONS='halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1');objects=[];commands=[];records=[]
for name in ['NvtTouchCore','NvtProtocol']:
 obj=out/(name+'.o');cmd=['cc','-std=c11',*flags,'-I',str(core),'-c',str(core/(name+'.c')),'-o',str(obj)];commands.append(cmd);subprocess.run(cmd,check=True,env=env);objects.append(str(obj))
for name in ['weak_follow_cases','weak_follow_stress','independent_v2']:
 target=out/name;cmd=['c++','-std=c++17',*flags,'-I',str(core),'-I',str(pkg),str(tests/(name+'.cpp'))]
 if name=='independent_v2':cmd+=['-I',str(tests/'one-euro'),str(tests/'one-euro/OneEuroFilter.cpp')]
 cmd+=objects+['-o',str(target)];commands.append(cmd);subprocess.run(cmd,check=True,env=env)
 cmd=[str(target)]+([] if name=='independent_v2' else ['experiment']);r=subprocess.run(cmd,capture_output=True,text=True,env=env);(out/(name+'.stdout.txt')).write_text(r.stdout);(out/(name+'.stderr.txt')).write_text(r.stderr)
 assert r.returncode==0 and not re.search('runtime error:|Sanitizer',r.stderr),(name,r.returncode,r.stdout,r.stderr)
 rows=[json.loads(x) for x in r.stdout.splitlines() if x.startswith('{')];assert rows,name
 if name=='weak_follow_cases':assert rows[-1]['strong_400_report_hash']=='9859b9354511bd15'
 print(r.stdout,end='',flush=True);records.append({'test':name,'rows':rows})
record={'status':'PASS_V2_PRODUCTION_HOST_ONLY_NOT_HARDWARE','test_counts':[17,10,6,10],'commands':commands,'new_cases':records,'production_core_sha256':wanted,'limits':['Coherent directional weak noise can still be followed.','First weak and abrupt weak turns delay output.','No remedy for100ms missing-M cancellations or proof of actual tablet gestures.']};(out/'v2-host-results.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps({'status':record['status'],'tests':43}))

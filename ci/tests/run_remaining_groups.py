from pathlib import Path
import subprocess,os,json,sys
r=Path(__file__).resolve().parents[1];o=r/'host-build-r1-remaining';o.mkdir(exist_ok=False)
obj=r/'host-build-r1';d=r/'device/drivers/ShengNovatekTouch';pkg=r/'device/package'
env=dict(os.environ,TMPDIR=str(o),TMP=str(o),TEMP=str(o),PYTHONDONTWRITEBYTECODE='1',ASAN_OPTIONS='halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
flags=['-g','-O1','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-fno-omit-frame-pointer']
rows=[]
for stem in ['test_astra_probe','test_astra_quantization','test_astra_region','test_astra_timeline']:
 cmd=['c++','-std=c++17',*flags,'-I',str(d),'-I',str(pkg),'-I',str(obj),str(r/'tests'/(stem+'.cpp')),*map(str,[obj/(s+'.o') for s in ['NvtProtocol','NvtTouchCore','NvtPartialObservation','NvtCoverage']]),'-o',str(o/stem)]
 p=subprocess.run(cmd,text=True,capture_output=True,env=env)
 (o/(stem+'.compile.stdout')).write_text(p.stdout);(o/(stem+'.compile.stderr')).write_text(p.stderr)
 row=dict(source=stem,compile_returncode=p.returncode,command=cmd)
 if p.returncode==0:
  x=subprocess.run([str(o/stem)],text=True,capture_output=True,env=env)
  (o/(stem+'.stdout')).write_text(x.stdout);(o/(stem+'.stderr')).write_text(x.stderr)
  row.update(returncode=x.returncode,stdout=x.stdout,stderr=x.stderr)
  print(x.stdout,flush=True);print(x.stderr,file=sys.stderr,flush=True)
 rows.append(row)
(o/'results.json').write_text(json.dumps(rows,indent=2))
print(json.dumps({'groups':len(rows),'all_pass':all(x['compile_returncode']==0 and x.get('returncode')==0 for x in rows)}))
sys.exit(0 if all(x['compile_returncode']==0 and x.get('returncode')==0 for x in rows) else 1)

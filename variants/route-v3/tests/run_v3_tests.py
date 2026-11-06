#!/usr/bin/env python3
"""Portable V3 public synthetic contracts. No raw sensor logs, identity, network or device."""
from pathlib import Path
import argparse,hashlib,json,os,re,shutil,subprocess
PINS={
 'device/drivers/ShengHidInput/NativeHidInput.cpp':'d53f14c79c52cb6f01f96900a6bbeb3a48c63f881aa884ee01e66c67b03f2e89',
 'device/drivers/ShengHidInput/NativeHidTouchPlan.h':'b11592c16e451d7e37c7e3cb8505503e2737659a3c27648a64ec1016f8b2fd07',
 'device/drivers/ShengNovatekTouch/NvtShapeMetricsInline.h':'9b6d755a41819e1f1666a21da183b8e8ed4da9a0f075ca9315caf6f187524ed7',
 'device/drivers/ShengNovatekTouch/NvtTouchCore.c':'88905d18ffc6e10d1d275ec969e58338d7c9e9a65b84a0eb3e21c01dfed03b08',
 'device/drivers/ShengNovatekTouch/NvtTouchCore.h':'5512daf4af1b713c77c13dcb71a8152aa8ed05b2a01461fd8a730f901e5680c0'}
COPY_PROVENANCE_SHA='40ccb24ffe8fab33b4018927f3da35277582b53d609dd55fa06b583604ab0370'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def require(ok,message):
 if not ok:raise AssertionError(message)
def function_text(text,start=0):
 marker='    void touchSend() {';begin=text.index(marker,start);opening=text.index('{',begin);depth=0
 # Source files are pinned; this exact function has no brace characters in comments/strings.
 for i in range(opening,len(text)):
  if text[i]=='{':depth+=1
  elif text[i]=='}':
   depth-=1
   if depth==0:return text[begin:i+1]
 raise AssertionError('Unbalanced pinned touchSend')
def host_function(text,classname):
 require(text.count('NativeHidInput *self=this;')==1,'Unexpected self binding')
 barrier='__asm__ volatile("dmb ish":::"memory");'
 require(text.count(barrier)==2,'Exactly two ARM barriers required')
 return text.replace('NativeHidInput *self=this;',classname+' *self=this;').replace(barrier,'host_barrier();')
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 root=a.root.resolve();out=a.out.resolve();tests=Path(__file__).resolve().parent
 out.mkdir(parents=True,exist_ok=True);require(not any(out.iterdir()),'Use a fresh empty output directory')
 core=root/'device/drivers/ShengNovatekTouch';pkg=root/'device/package';hid=root/'device/drivers/ShengHidInput'
 cc=shutil.which(os.environ.get('CC','cc'));cxx=shutil.which(os.environ.get('CXX','c++'));require(cc and cxx,'Host C/C++ compiler missing')
 for path,wanted in PINS.items():require(digest(root/path)==wanted,'Production source differs: '+path)
 require(digest(tests/'TEST-COPY-PROVENANCE.json')==COPY_PROVENANCE_SHA,'Public fixture provenance changed')
 provenance=json.loads((tests/'TEST-COPY-PROVENANCE.json').read_text(encoding='utf-8'))
 expected_files=set(provenance['files'])|{'TEST-COPY-PROVENANCE.json','run_v3_tests.py'}
 require({str(path.relative_to(tests)).replace('\\','/') for path in tests.rglob('*') if path.is_file()}==expected_files,'Unexpected test file/header could shadow production input')
 require(all(not path.is_symlink() for path in tests.rglob('*')),'Linked test inputs refused')
 for name,item in provenance['files'].items():require(digest(tests/name)==item['copied_sha256'],'Fixture assertions/source changed: '+name)
 sender=(hid/'NativeHidInput.cpp').read_text(encoding='utf-8');fixture=(tests/'hid/extracted_touchsend.cpp').read_text(encoding='utf-8')
 current=function_text(sender);new=function_text(fixture,fixture.index('struct NewDevice {'))
 require(host_function(current,'NewDevice')==new,'Host NewDevice not exact production sender after only class/barrier substitutions')
 old=(tests/'hid/touchSend.baseline.cpp.txt').read_text(encoding='utf-8');old=function_text(old)
 require(host_function(old,'OldDevice')==function_text(fixture,fixture.index('struct OldDevice {')),'Host baseline sender no longer exact pinned public old body')
 require(provenance['report_bytes']==62,'Fixture protocol format changed')
 flags=['-g','-O1','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-fno-omit-frame-pointer']
 env=dict(os.environ,TMPDIR=str(out),PYTHONDONTWRITEBYTECODE='1',ASAN_OPTIONS='halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
 commands=[];groups=[]
 def display(cmd):
  result=[]
  for part in map(str,cmd):
   for base,name in [(tests,'$TESTS'),(out,'$OUT'),(root,'$ROOT')]:part=part.replace(str(base),name)
   if part in (cc,cxx):part=Path(part).name
   result.append(part)
  return result
 def build(cmd):commands.append(display(cmd));subprocess.run(list(map(str,cmd)),check=True,env=env)
 def execute(name,binary,expected,style):
  target=out/name;target.mkdir(exist_ok=True);r=subprocess.run([str(binary)],capture_output=True,text=True,env=env)
  (target/'stdout.txt').write_text(r.stdout,encoding='utf-8');(target/'stderr.txt').write_text(r.stderr,encoding='utf-8')
  require(r.returncode==0 and re.search(r'runtime error:|ERROR: (?:AddressSanitizer|LeakSanitizer)|UndefinedBehaviorSanitizer|Sanitizer:DEADLYSIGNAL',r.stderr) is None,'Host executable/sanitizer failed: '+name+'\n'+r.stdout+'\n'+r.stderr)
  rows=[json.loads(line) for line in r.stdout.splitlines() if line.startswith('{')]
  if style=='shape':require(len(rows)==expected and all('case' in x for x in rows),'Shape fixture count changed')
  else:
   field='checks' if style=='checks' else 'tests';require(rows and rows[-1].get(field)==expected,'Named test count changed: '+name)
   if style=='checks':require(sum('case' in x for x in rows)==expected,'Independent case rows changed')
   else:require(sum(line.startswith('PASS ') for line in r.stdout.splitlines())==expected,'PASS case names changed: '+name)
  record={'group':name,'named_cases':expected,'rows':rows};groups.append(record);print(json.dumps({'group':name,'named_cases':expected,'status':'PASS_HOST_SYNTHETIC_NOT_HARDWARE'}),flush=True);return rows
 objects=[]
 for name in ['NvtTouchCore','NvtProtocol']:
  obj=out/(name+'.o');build([cc,'-std=c11',*flags,'-I',core,'-MMD','-MF',out/(name+'.d'),'-c',core/(name+'.c'),'-o',obj]);objects.append(obj)
 def dependency_seen(dep,header):return str(header) in dep.read_text().replace('\\\n','').replace('\\ ',' ')
 require(dependency_seen(out/'NvtTouchCore.d',core/'NvtShapeMetricsInline.h'),'Core does not compile the exact production shape header')
 original_objects=list(objects);renames=['nvt_touch_reset','nvt_touch_process','nvt_touch_row_center','nvt_touch_column_center','nvt_touch_map_edge_axis']
 for name in ['NvtTouchCore.c','baseline_adapter.c']:
  obj=out/('reference-'+name+'.o');build([cc,'-std=c11',*flags,*['-D'+n+'=baseline_'+n for n in renames],'-I',tests/'reference','-c',tests/'reference'/name,'-o',obj]);original_objects.append(obj)
 for source,name,count,style,objs in [('test_timed_touch.cpp','original17',17,'tests',original_objects),('test_v3_core.cpp','V3_core13',13,'tests',objects),('independent_actual_v3.cpp','independent_Core_Engine21',21,'checks',objects)]:
  binary=out/(name+'-test');build([cxx,'-std=c++17',*flags,'-I',core,'-I',pkg,tests/source,*objs,'-o',binary]);execute(name,binary,count,style)
 binary=out/'shape14-test';build([cc,'-std=c11',*flags,'-I',core,'-MMD','-MF',out/'shape.d',tests/'shape/test_shape.c','-o',binary]);execute('shape14',binary,14,'shape')
 require(dependency_seen(out/'shape.d',core/'NvtShapeMetricsInline.h'),'Geometry fixture compiled another shape header')
 build([cc,'-std=c11',*flags,'-I',hid,'-MMD','-MF',out/'pure_c_hid.d','-c',tests/'hid/pure_c_compile.c','-o',out/'pure_c_hid.o'])
 require(dependency_seen(out/'pure_c_hid.d',hid/'NativeHidTouchPlan.h'),'Pure C smoke compiled another planner header')
 binary=out/'HID14-test';build([cxx,'-std=c++17',*flags,'-I',hid,'-MMD','-MF',out/'HID.d',tests/'hid/extracted_touchsend.cpp','-o',binary]);rows=execute('HID14',binary,14,'tests')
 require(dependency_seen(out/'HID.d',hid/'NativeHidTouchPlan.h'),'Extracted sender compiled another planner header')
 properties=[r for r in rows if r.get('kind')=='Core12_set_property'];require(len(properties)==1 and properties[0]['cases']==9936,'HID set-property coverage changed')
 require(rows[-1]['report_bytes_including_ID']==62 and rows[-1]['no_new_timer'] is True,'62byte format/timer claim changed')
 for path,wanted in PINS.items():require(digest(root/path)==wanted,'Production changed during tests: '+path)
 for name,item in provenance['files'].items():require(digest(tests/name)==item['copied_sha256'],'Fixture changed during tests: '+name)
 require(sum(g['named_cases'] for g in groups)==79,'Aggregate case count differs')
 report={'status':'PASS_V3_PRODUCTION_PUBLIC_SYNTHETIC_HOST_ONLY_NOT_HARDWARE','named_cases':79,'groups':groups,'nested_properties':{'legacy_author_matrix_comparisons':1200,'HID_Core12_set_transitions':9936},'pure_C_HID_header_compile_checks':1,'source_equality_guards':{'production_touchSend_after_only_class_and_two_barrier_substitutions':True,'pinned_public_baseline_touchSend_same':True,'fixture_assertions_pinned':True,'shape_and_HID_exact_full_compiler_dependencies_seen':True,'public_test_tree_exactset_no_shadow_headers':True},'production_hashes':PINS,'copy_provenance_sha256':COPY_PROVENANCE_SHA,'commands':commands,'real_sensor_or_identity_read':False,'hardware_tested':False,'limits':['Compact coherent2D weak noise/lift-tail can follow the current track; accepted counterexamples remain in tests.','Thin/edge weak genuine input may freeze; no P-only/missing-M repair or app consumer proof.','HID API errors may be ambiguous; no timer or exactly-once delivery claim.']}
 (out/'v3-host-results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps({'status':report['status'],'named_cases':79,'HID_property_cases':9936,'legacy_matrix_comparisons':1200,'pure_C_compile_checks':1}),flush=True)
if __name__=='__main__':main()

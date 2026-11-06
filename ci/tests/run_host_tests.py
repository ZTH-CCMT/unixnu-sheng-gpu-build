#!/usr/bin/env python3
"""Synthetic diagnostics tests. No device, private paths/data, downloads or cloud."""
import argparse,hashlib,json,os,re,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--out',type=Path);a=p.parse_args();root=a.root.resolve();out=(a.out or root/'tests/output').resolve();out.mkdir(parents=True,exist_ok=True)
os.environ['TMPDIR']=str(out)
# Fail closed even when UBSan would otherwise print and recover with exit0.
os.environ['ASAN_OPTIONS']='halt_on_error=1:abort_on_error=1'
os.environ['UBSAN_OPTIONS']='halt_on_error=1:print_stacktrace=1'

def function(text,needle):
 start=text.index(needle);brace=text.index('{',start);depth=1;i=brace+1
 while depth:
  if text[i]=='{':depth+=1
  elif text[i]=='}':depth-=1
  i+=1
 return text[start:i]
probe=(root/'device/package/TouchProbe.cpp').read_text();hid=(root/'device/drivers/ShengHidInput/NativeHidInput.cpp').read_text()
start=probe.index('// One-shot diagnostic state.');end=probe.index('\nnamespace {\n',probe.index('extern "C" void native_touch_evidence_hid'))
diag=probe[start:end];old=function(diag,'static uint64_t evidenceNowUs()');diag=diag.replace(old,'static uint64_t evidenceNowUs() {return fakeUs;}')
pub=function(probe,'void publish(').replace('__asm__ volatile("dmb ish" ::: "memory");','__atomic_thread_fence(__ATOMIC_SEQ_CST);')
h= function(hid,'    void touchSend()').replace('__asm__ volatile("dmb ish":::"memory");','__atomic_thread_fence(__ATOMIC_SEQ_CST);')
transform='#pragma GCC diagnostic push\n#pragma GCC diagnostic warning \"-Wmisleading-indentation\"\n'+function(hid,'    static unsigned transformCoordinate(')+'\n#pragma GCC diagnostic pop\n'
s=(Path(__file__).parent/'host-tests.cpp.in').read_text().replace('@DIAGNOSTIC@',diag).replace('@TRANSFORM@',transform).replace('@HID@',h).replace('@PUBLISH@',pub)
(out/'actual-hooks-tests.cpp').write_text(s)
common=['-g','-O1','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer']
inc=['-I'+str(root/'device/package'),'-I'+str(root/'device/drivers/ShengNovatekTouch')]
commands=[[os.environ.get('CC','cc'),'-std=c11',*common,'-Wno-error=misleading-indentation',*inc,'-c',str(root/'device/drivers/ShengNovatekTouch/NvtTouchCore.c'),'-o',str(out/'core.o')],
[os.environ.get('CC','cc'),'-std=c11',*common,*inc,'-c',str(root/'device/drivers/ShengNovatekTouch/NvtProtocol.c'),'-o',str(out/'protocol.o')],
[os.environ.get('CXX','c++'),'-std=c++17',*common,*inc,str(out/'actual-hooks-tests.cpp'),str(out/'core.o'),str(out/'protocol.o'),'-pthread','-o',str(out/'host-tests')]]
logs=[]
for cmd in commands:
 r=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT);logs.append({'command':cmd,'returncode':r.returncode,'output':r.stdout})
 if r.returncode:
  (out/'results.json').write_text(json.dumps({'status':'FAIL','steps':logs},indent=2));print(r.stdout);raise SystemExit(r.returncode)
r=subprocess.run([str(out/'host-tests'),str(out/'synthetic.blob')],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT);logs.append({'run':r.returncode,'output':r.stdout});print(r.stdout)
if r.returncode:(out/'results.json').write_text(json.dumps({'status':'FAIL','steps':logs},indent=2));raise SystemExit(r.returncode)
import importlib.util
source_spec=importlib.util.spec_from_file_location('source_contract',Path(__file__).parent/'check_source_contract.py');source_mod=importlib.util.module_from_spec(source_spec);source_spec.loader.exec_module(source_mod);source_contract=source_mod.check(root)
spec=importlib.util.spec_from_file_location('decoder',root/'host/decode_touch_evidence.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
data0=(out/'synthetic.blob').read_bytes();decoded=mod.decode(data0);boot,extracted=mod.extract((out/'synthetic.blob.txt').read_text());assert extracted==data0
for bad in (data0[:-1],b'TEVRAW01'+data0[8:],data0+b'x'):
 try:mod.decode(bad)
 except ValueError:pass
 else:raise AssertionError('decoder accepted invalid framing')
assert decoded['samples'][0]['raw'][313]==0x1d
assert decoded['samples'][1]['reference'][0]==5000
assert mod.Reader(bytes([255,255])).get('h')==(-1,)
assert len(decoded['metadata'])>2400
metrics=json.loads(r.stdout.strip());metrics['decoder_checks']='roundtrip all text chunks, v1/truncation/trailing rejection, signed LE pre-reference';data=(out/'synthetic.blob').read_bytes();metrics['source_contract']=source_contract;metrics['fixture_sha256']=hashlib.sha256(data).hexdigest();metrics['sanitizer_env']={'ASAN_OPTIONS':os.environ['ASAN_OPTIONS'],'UBSAN_OPTIONS':os.environ['UBSAN_OPTIONS']};metrics['scope']='synthetic core equivalence and production publish/HID/diagnostic bodies with platform stubs; not hardware/UI qualification'
(out/'results.json').write_text(json.dumps({'status':'PASS','metrics':metrics,'steps':logs},indent=2))

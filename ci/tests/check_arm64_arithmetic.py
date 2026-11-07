#!/usr/bin/env python3
"""Standalone ARM64 integer arithmetic object check, not an iOS kernel build."""
from pathlib import Path
import argparse,glob,hashlib,json,os,re,shutil,subprocess,sys
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--out',type=Path,required=True);p.add_argument('--clang');a=p.parse_args()
r=a.root.resolve();o=a.out.resolve();o.mkdir(parents=True,exist_ok=False)
candidates=[a.clang,os.environ.get('CLANG'),shutil.which('clang'),*glob.glob('/usr/lib/llvm-*/bin/clang'),*glob.glob('/usr/bin/clang-[0-9]*')]
clang=next((str(x) for x in candidates if x and Path(x).is_file()),None)
report={'status':'NOT_RUN_TOOL_MISSING','check':'standalone_arm64_integer_math_not_iOS_driver','clang':clang,'hardware_tested':False,'native_iOS_built':False}
if not clang:
 (o/'results.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps(report));sys.exit(3)
env=dict(os.environ,TMPDIR=str(o),TMP=str(o),TEMP=str(o),PYTHONDONTWRITEBYTECODE='1')
stub=o/'freestanding-headers';stub.mkdir()
(stub/'string.h').write_text('#ifndef ASTRA_CHECK_STRING_H\n#define ASTRA_CHECK_STRING_H\n#include <stddef.h>\nvoid *memset(void *,int,size_t);\nvoid *memcpy(void *,const void *,size_t);\n#endif\n')
d=r/'device/drivers/ShengNovatekTouch'
cmd=[clang,'--target=aarch64-none-elf','-std=c11','-O2','-ffreestanding','-fno-builtin','-mgeneral-regs-only','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-I',str(stub),'-I',str(d),'-c',str(d/'NvtPartialObservation.c'),'-o',str(o/'NvtPartialObservation.arm64.o')]
x=subprocess.run(cmd,text=True,capture_output=True,env=env)
(o/'compile.stdout').write_text(x.stdout);(o/'compile.stderr').write_text(x.stderr)
report.update(command=cmd,compile_returncode=x.returncode)
if x.returncode:
 report['status']='FAIL_STANDALONE_ARM64_COMPILE'
else:
 nm=next((v for v in [shutil.which('llvm-nm'),str(Path(clang).with_name('llvm-nm')),shutil.which('nm')] if v and Path(v).is_file()),None)
 if not nm:
  report['status']='ARM64_OBJECT_BUILT_SYMBOL_REVIEW_NOT_RUN'
 else:
  z=subprocess.run([nm,'-u',str(o/'NvtPartialObservation.arm64.o')],text=True,capture_output=True,env=env)
  (o/'undefined-symbols.txt').write_text(z.stdout);(o/'nm.stderr').write_text(z.stderr)
  forbidden=sorted(set(re.findall(r'\b_*(?:divti3|udivti3|modti3|umodti3|multi3|ashlti3|ashrti3|lshrti3|float\w*|fix\w*|extend\w*|trunc\w*)\b',z.stdout)))
  report.update(nm=nm,nm_returncode=z.returncode,undefined_symbols=z.stdout,forbidden_runtime_helpers=forbidden)
  report['status']='PASS_STANDALONE_ARM64_INTEGER_OBJECT_NOT_IOS_KERNEL' if z.returncode==0 and not forbidden else 'FAIL_RUNTIME_SYMBOL_REVIEW'
report['source_sha256']={n:hashlib.sha256((d/n).read_bytes()).hexdigest() for n in ['NvtPartialObservation.c','NvtPartialObservation.h','NvtPartialMathInline.h']}
(o/'results.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2));sys.exit(0 if report['status'].startswith('PASS_') else 1)

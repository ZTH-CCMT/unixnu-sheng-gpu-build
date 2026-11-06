#!/usr/bin/env python3
import argparse,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
for index,name in enumerate(['tests/run_v2_tests.py']):
 subprocess.run([sys.executable,'-B',str(a.root/name),'--root',str(a.root),'--out',str(a.out/('step-'+str(index)))],check=True)

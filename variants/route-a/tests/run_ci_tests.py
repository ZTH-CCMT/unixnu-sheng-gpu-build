#!/usr/bin/env python3
# Run sealed original and route production-code contracts.
import argparse,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
route='route-a'
entries={'route-a':['run_route_tests.py'],'route-b':['run_host_tests.py','run_route_tests.py'],'route-c':['run_route_c_tests.py','run_matcher_a_tests.py']}[route]
for index,name in enumerate(entries):
 command=[sys.executable,'-B',str(a.root/'tests'/name),'--root',str(a.root),'--out',str(a.out/('step-'+str(index)))]
 if name=='run_matcher_a_tests.py':command.append('--skip-original')
 subprocess.run(command,check=True)

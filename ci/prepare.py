"""Verify frozen public checkouts and apply the three reviewed storage-only patches."""
import json, os, platform, shutil, subprocess, sys, tomllib
from common import *
manifest=json.loads((HERE/'storage/manifest.json').read_text())
repos={'UniXNU':TOP/'UniXNU','UniXNU-sheng':TOP/'device','ShengUfs':TOP/'device/drivers/ShengUfs'}
snapshot={}
for name,expected in PINS.items():
    repo=TOP/name
    assert capture('git','rev-parse','HEAD',cwd=repo)==expected,(name,'wrong HEAD')
    assert not capture('git','status','--porcelain','--untracked-files=no',cwd=repo),(name,'dirty initial checkout')
    status=subprocess.check_output(['git','submodule','status','--recursive'],cwd=repo,text=True).rstrip('\r\n')
    assert all(not line or line[0]==' ' for line in status.splitlines()),(name,'uninitialized or divergent submodule')
    snapshot[name]={'commit':expected,'submodules':status}
for change in manifest['changes']:
    repo=repos[change['repository']]
    patch=HERE/'storage'/change['patch']
    path=repo/change['path']
    assert capture('git','rev-parse','HEAD',cwd=repo)==change['commit']
    assert digest(patch)==change['patch_sha256']
    assert digest(path)==change['before_sha256']
    run('git','apply','--check',patch,cwd=repo)
    run('git','apply',patch,cwd=repo)
    assert digest(path)==change['after_sha256']
board=tomllib.loads((TOP/'device/board.toml').read_text())
assert board['userdata']==dict(first_lba=173859584,last_lba=257745663,lba_bytes=4096,partition_name='unixnu')
assert board['payload']['runtime']['data_gib']==215
assert int(str(board['payload']['adt']['owned_memory_size']),0)==0x130000000
save(TOP/'evidence/source-pins.json',snapshot)
save(TOP/'evidence/storage-adaptation.json',manifest)
if sys.platform=='darwin':
    versions={}
    for label,cmd in {'macOS':['sw_vers'],'Xcode':['xcodebuild','-version'],'SDK':['xcrun','--sdk','iphoneos','--show-sdk-version'],'clang':['clang','--version'],'llvm':['/opt/homebrew/opt/llvm/bin/clang','--version'],'rust':['rustc','+1.98.0','--version'],'python':['python3','--version'],'brew':['brew','list','--versions']}.items():
        versions[label]=capture(*cmd)
    versions.update(ImageOS=os.environ.get('ImageOS'),ImageVersion=os.environ.get('ImageVersion'),machine=platform.machine(),disk=shutil.disk_usage(TOP)._asdict())
    save(TOP/'evidence/toolchain.json',versions)

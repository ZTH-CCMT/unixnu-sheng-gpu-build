"""Verify frozen public checkouts and apply reviewed storage and patch-header adaptations."""
import hashlib, json, os, platform, shutil, subprocess, sys, tomllib
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
# Declare the original added-file mode; no Mesa hunk or GPU code changes.
mesa_patch=TOP/"UniXNU/patches/mesa/turnip-frame-diagnostics.patch"
mesa_before="5eb8dda6e381f10fa48b62a9a497fb74a8b08c7999dea5468585c9848b2af966"
mesa_after="cd15bbb8f932d564a99300e63d3d6c5a6a714b311596e80619092c5d3fa5e25a"
assert digest(mesa_patch)==mesa_before,"unexpected original Mesa patch"
original_mesa_patch=mesa_patch.read_bytes()
mesa_anchor=b'diff --git a/src/freedreno/vulkan/tu_frame_diagnostic.h b/src/freedreno/vulkan/tu_frame_diagnostic.h\n'
assert original_mesa_patch.startswith(mesa_anchor+b"--- /dev/null\n") and original_mesa_patch.count(mesa_anchor)==1
corrected_mesa_patch=original_mesa_patch.replace(mesa_anchor,mesa_anchor+b"new file mode 100644\n",1)
assert hashlib.sha256(corrected_mesa_patch).hexdigest()==mesa_after
assert corrected_mesa_patch.replace(b"new file mode 100644\n",b"",1)==original_mesa_patch
mesa_patch.write_bytes(corrected_mesa_patch)
save(TOP/"evidence/mesa-patch-header-compatibility.json",dict(kind="Git added-file metadata",source_commit=PINS["UniXNU"],path=str(mesa_patch.relative_to(TOP/"UniXNU")),before_sha256=mesa_before,after_sha256=mesa_after,added_header="new file mode 100644",all_Mesa_hunks_unchanged=True))
# Backport the author's v0 boot image verifier offset correction.
bootimg_source = TOP / "UniXNU/scripts/unixnu/bootimg.py"
bootimg_original = bootimg_source.read_bytes()
assert hashlib.sha256(bootimg_original).hexdigest() == "a50379c3dba5115ff574c8fcf451a60aff023cb51ef2c2c5cbd6a55e705c8595"
bootimg_fixed = bootimg_original.replace(b"        start = 0\n", b"        start = page\n", 1)
assert hashlib.sha256(bootimg_fixed).hexdigest() == "bf5d525c6f83dcabfba417b04aa0b29350c7659b71fcb12fe114717a3cc6815f"
bootimg_source.write_bytes(bootimg_fixed)
save(TOP / "evidence/bootimg-offset-backport.json", dict(
    upstream_commit="33bcc1d8225fd095b5093433dd8def4d07df8463",
    path="scripts/unixnu/bootimg.py",
    before_sha256="a50379c3dba5115ff574c8fcf451a60aff023cb51ef2c2c5cbd6a55e705c8595",
    after_sha256="bf5d525c6f83dcabfba417b04aa0b29350c7659b71fcb12fe114717a3cc6815f",
))
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

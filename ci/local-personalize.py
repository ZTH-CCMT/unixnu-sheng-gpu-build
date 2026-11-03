"""LOCAL ONLY: repack with the real ID. Does not boot, flash, upload, or contact anyone.
Run only after reviewing artifacts and preparing the identical patched source checkouts.
Set UNIXNU_CI_WORKSPACE to the parent of UniXNU/, device/, uefi-sheng/ and handoff/.
Set UNIXNU_UNIQUE_CHIP_ID locally. It is never written to a script or repository.
"""
import json, os, re, shutil
from common import *
for tool in ('clang','ld.lld','llvm-nm','llvm-objcopy','llvm-size','llvm-readelf','dtc','fdtget','fdtput','mformat','mcopy'):
    assert shutil.which(tool),'Required local tool missing: '+tool
seed=os.environ.get('UNIXNU_UNIQUE_CHIP_ID','')
assert re.fullmatch(r'[0-9a-fA-F]{8}',seed) and seed.lower()!=SYNTHETIC
hand=TOP/'handoff'; meta=json.loads((hand/'handoff.json').read_text())
assert meta['source_pins']==PINS and meta['personalization_required']
for rel,item in meta['files'].items():
    assert digest(hand/rel)==item['sha256'] and (hand/rel).stat().st_size==item['bytes']
# prepare.py verifies pinned HEAD and approved storage patches; use fresh checkouts for this operation.
run('python3',HERE/'prepare.py')
run('python3',TOP/'UniXNU/unixnu','tree','-D',TOP/'device','--os','27')
ctx=context()
ctx.config_path.parent.mkdir(parents=True,exist_ok=True)
shutil.copyfile(hand/'.config',ctx.config_path)
policies=ctx.tree/'build/sheng-source-storage/root-policies.bin'
policies.parent.mkdir(parents=True,exist_ok=True)
shutil.copyfile(hand/'root-policies.bin',policies)
# Complete explicit immutable runtime inputs prevent regeneration and require the compiled Data UUID.
run('python3',TOP/'UniXNU/unixnu','build','payload','-D',TOP/'device','--os','27',
    '--uefi',TOP/'uefi-sheng','--kernel',hand/'kernel/kernel.macho',
    '--data-ramdisk',hand/'data.dbr','--owner-trust-cache',hand/'trust-cache.bin',
    '--gpu-addon',hand/'gpu-addon.bin')
out=TOP/'LOCAL-PERSONALIZED';out.mkdir(exist_ok=True)
run('python3',TOP/'UniXNU/unixnu','bootimg','-D',TOP/'device','--os','27','--uefi',TOP/'uefi-sheng',
    '--fd',hand/'SILICIUM_UEFI.fd','--dtb',hand/'sheng.dtb',
    '--ramdisk',ctx.work/'payload/payload.img','--output',out/'boot.img')
shutil.copyfile(ctx.work/'payload/payload.img',out/'payload.img')
save(out/'personalization.json',dict(source_handoff_sha256=digest(hand/'handoff.json'),
    source_kernel_sha256=digest(hand/'kernel/kernel.macho'),data_seed_sha256=digest(hand/'data.dbr'),
    boot_sha256=digest(out/'boot.img'),payload_sha256=digest(out/'payload.img'),
    real_platform_identifier_recorded=False,device_untouched=True,hardware_tested=False,
    install_authorization=False,live_geometry_verification_required=True))
print('Local repacking complete. No device operation was performed.')

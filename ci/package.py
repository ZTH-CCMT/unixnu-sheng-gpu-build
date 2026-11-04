"""Fresh official build and allowlisted export; never accesses a tablet."""
import gzip, hashlib, json, os, shutil, struct, sys
from common import *
def copy(src,dst):
    src=Path(src); assert src.is_file(),str(src)
    dst=Path(dst);dst.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(src,dst)
def file_manifest(root):
    return {str(p.relative_to(root)):{'bytes':p.stat().st_size,'sha256':digest(p)} for p in sorted(root.rglob('*')) if p.is_file()}
def compiled_inputs(ctx):
    runtime=json.loads((ctx.work/'runtime/inputs.json').read_text())
    allowed={'.config':ctx.config_path,'kernel/kernel.macho':ctx.work/'kernel/kernel.macho',
             'provisional/DO-NOT-BOOT-payload.img':ctx.work/'payload/payload.img',
             'root-policies.bin':ctx.tree/'build/sheng-source-storage/root-policies.bin',
             'sheng.dtb':ctx.tree/'build/sheng/sheng.dtb',
             'SILICIUM_UEFI.fd':TOP/'uefi-sheng'/ctx.board['firmware']['fd'].format(target=ctx.args.target)}
    for label,name in [('data_ramdisk','data.dbr'),('trust_cache','trust-cache.bin'),('gpu_addon','gpu-addon.bin')]:
        item=runtime['inputs'][label]; assert digest(item['path'])==item['sha256']
        allowed[name]=Path(item['path'])
    return allowed, runtime

def preserve_compiled():
    """Keep complete, unpersonalized build inputs after a packaging failure."""
    ctx = context()
    if not (ctx.work / "runtime/inputs.json").is_file():
        print("Runtime inputs are incomplete.")
        return
    allowed, runtime = compiled_inputs(ctx)
    if not all(Path(path).is_file() for path in allowed.values()):
        print("Compiled inputs are incomplete.")
        return

    sys.path.insert(0, str(TOP / "UniXNU/drivers/DarwinBoot/Test"))
    import packed_ramdisk
    logical, _ = packed_ramdisk.regions(Path(allowed["data.dbr"]).read_bytes())
    assert logical == 215 * GIB
    assert Path(allowed["SILICIUM_UEFI.fd"]).stat().st_size == 0x300000
    staging = TOP / ".compiled-components.partial"
    staging.mkdir()
    for name, path in allowed.items():
        copy(path, staging / name)
    save(staging / "compiled-components.json", dict(
        status="PROVISIONAL_COMPILED_INPUTS_NOT_AN_INSTALLER",
        source_pins=PINS,
        synthetic_platform_seed=SYNTHETIC,
        data_volume_uuid=runtime["data_volume_uuid"],
        data_logical_bytes=logical,
        requires_verified_boot_pack=True,
        files=file_manifest(staging),
    ))
    staging.rename(TOP / "compiled-components")

def boot():
    space(7609308281+2*GIB,'known firmware archive plus 2 GiB working margin; this is a lower bound, full build peak is not yet measured')
    os.environ['UNIXNU_UNIQUE_CHIP_ID']=SYNTHETIC
    run('bash',TOP/'device/scripts/package.sh','--os','27','--uefi',TOP/'uefi-sheng','--init-data',cwd=TOP/'device')
    ctx=context(); out=TOP/'handoff'
    save(TOP/'evidence/resolved-build.json',json.loads(capture('python3',TOP/'UniXNU/unixnu','status','-D',TOP/'device','--os','27','--json')))
    out.mkdir(exist_ok=True)
    allowed, runtime = compiled_inputs(ctx)
    allowed.update({
        "provisional/DO-NOT-BOOT-boot.img": ctx.work / "boot/boot.img",
        "author-package.manifest.json": ctx.work / "package.manifest.json",
    })
    for dst,src in allowed.items(): copy(src,out/dst)
    for src in (TOP/'evidence').glob('*.json'): copy(src,out/'evidence'/src.name)
    # Data is a new generic APFS seed from Apple's original OS, not an installation dump.
    sys.path.insert(0,str(TOP/'UniXNU/drivers/DarwinBoot/Test'))
    import packed_ramdisk
    logical,extents=packed_ramdisk.regions((out/'data.dbr').read_bytes())
    assert logical==215*GIB
    adt=ctx.tree/'drivers/DarwinBoot' # recursive source retained locally; no upload of source/build tree
    notice={'status':'PROVISIONAL_DO_NOT_BOOT_OR_FLASH','synthetic_platform_seed':SYNTHETIC,'personalization_required':True,
            'physical_boot_is_not_interlocked':True,'data_volume_uuid':runtime['data_volume_uuid'],
            'data_logical_bytes':logical,'data_encoded_bytes':(out/'data.dbr').stat().st_size,
            'owned_memory_bytes':0x130000000,'target_partition':'unixnu','target_geometry_proposed_not_device_verified':True,
            'new_installation':True,'hardware_tested':False,'source_pins':PINS,'files':file_manifest(out)}
    save(out/'handoff.json',notice)
def root():
    hand=TOP/'handoff'; info=json.loads((hand/'handoff.json').read_text())
    assert info['source_pins']==PINS and info['data_logical_bytes']==215*GIB
    for rel,meta in info['files'].items():
        assert (hand/rel).stat().st_size==meta['bytes'] and digest(hand/rel)==meta['sha256']
    from root_tables import create
    ctx=context();tables=TOP/'tables'; records=create(ctx,tables)
    signed=[(TOP/'device/scripts/policies'/PROFILE/name/'manifest.header.bin').read_bytes() for name in ('OS','SystemOS')]
    cursor=32+16*len(signed); entries=b''
    for block in signed:
        entries+=struct.pack('<QQ',cursor,len(block));cursor+=len(block)
    expected=struct.pack('<8sQQQ',b'VROOTB01',1,len(signed),cursor)+entries+b''.join(signed)
    assert (hand/'root-policies.bin').read_bytes()==expected,'boot policy bundle differs from author signed headers'
    run('python3',TOP/'UniXNU/unixnu','build','userdata','-D',TOP/'device','--os','27',
        '--object','OS.vroot='+str(tables/'OS.vroot'),'--object','SystemOS.vroot='+str(tables/'SystemOS.vroot'),cwd=TOP/'UniXNU')
    image=ctx.work/'userdata/userdata-root.img'; report=ctx.work/'userdata/userdata-root.json'
    r=json.loads(report.read_text());assert r['target_partition']=='unixnu' and r['userdata_bytes']==320*GIB
    assert digest(image)==r['image_sha256']
    run('python3',HERE/'storage/verify_storage_package.py','--board',TOP/'device/board.toml','--root-image',image,'--root-report',report,'--data-seed',hand/'data.dbr')
    rows={x['name']:x for x in r['windows']+r['objects']}
    assert set(rows)=={'OS','SystemOS','OS.vroot','SystemOS.vroot'}
    for name,meta in records.items():
        assert rows[name]['sha256']==meta['image_sha256']
        assert rows[name]['size']==meta['size']
        assert rows[name+'.vroot']['sha256']==meta['table_sha256']
        assert rows[name+'.vroot']['size']==meta['table_bytes']
    pages=info['data_logical_bytes']//4096
    blocks=1+(pages+32767)//32768+pages
    used=((r['image_bytes']+4095)//4096+1024+blocks)*4096+GIB
    assert used<=320*GIB
    out=TOP/'full-root';out.mkdir(exist_ok=True)
    copy(report,out/'userdata-root.json');copy(tables/'verification.json',out/'root-verification.json')
    # gzip is streamed into <=1900 MiB parts; never materialize a 215 GiB Data image.
    class Parts:
        def __init__(self):
            self.part=None;self.size=0;self.index=0;self.total=0;self.sha=hashlib.sha256();self.limit=1900*(1<<20)
        def write(self,b):
            original=len(b);self.sha.update(b);self.total+=len(b)
            while b:
                if self.part is None or self.size==self.limit:
                    if self.part:self.part.close()
                    self.part=(out/f'userdata-root.img.gz.part{self.index:03d}').open('xb');self.index+=1;self.size=0
                n=min(len(b),self.limit-self.size);self.part.write(b[:n]);b=b[n:];self.size+=n
            return original
        def flush(self):
            if self.part:self.part.flush()
    parts=Parts()
    with gzip.GzipFile(filename='',mode='wb',fileobj=parts,mtime=0,compresslevel=6) as compressed, image.open('rb') as raw:
        shutil.copyfileobj(raw,compressed,8<<20)
    if parts.part:parts.part.close()
    save(out/'full-package.json',{'status':'PROVISIONAL_REQUIRES_LOCAL_PERSONALIZATION_AND_LIVE_STORAGE_PREFLIGHT',
        'source_pins':PINS,'boot_handoff_sha256':digest(hand/'handoff.json'),'root_image_sha256':r['image_sha256'],
        'root_image_bytes':r['image_bytes'],'gzip_stream_sha256':parts.sha.hexdigest(),'gzip_stream_bytes':parts.total,
        'parts_order':[f'userdata-root.img.gz.part{i:03d}' for i in range(parts.index)],
        'data_store_bytes_including_header_bitmap':blocks*4096,'guard_bytes':4<<20,'log_reserve_bytes':GIB,
        'required_partition_bytes':used,'proposed_partition_bytes':320*GIB,'headroom_bytes':320*GIB-used,
        'geometry_status':'PROPOSED_NOT_LIVE_VERIFIED','hardware_tested':False,'files':file_manifest(out)})
    print('Complete root and boot handoff available as TWO named artifacts; neither is installation approval.')
if __name__=='__main__':
    {'boot':boot,'root':root,'preserve-compiled':preserve_compiled}[sys.argv[1]]()

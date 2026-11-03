"""Recreate table bytes only; authenticate against immutable author RSA headers.
No signing key is generated or accepted; no upstream policy or key is rewritten.
"""
import contextlib, hashlib, json, struct, uuid
from common import *
FMT='<8s4I2Q16s32s32s32sQ'
def policy(header,anchor):
    assert len(header)==544 and len(anchor)==395
    assert anchor[:8]==b'VROOTKEY' and anchor[-3:]==b'\x01\x00\x01'
    h=struct.unpack(FMT,header[:160])
    magic,version,hsize,block,flags,size,count,volume,imagehash,tablehash,keyhash,generation=h
    assert (magic,version,hsize,block,flags)==(b'VROOT01\0',1,160,4096,0)
    assert count==(size+4095)//4096 and keyhash==hashlib.sha256(anchor).digest()
    n=int.from_bytes(anchor[8:392],'big')
    sig=int.from_bytes(header[160:],'big')
    assert 0<sig<n and n.bit_length()==3072
    encoded=pow(sig,65537,n).to_bytes(384,'big')
    tail=bytes.fromhex('3031300d060960864801650304020105000420')+hashlib.sha256(header[:160]).digest()
    assert encoded==b'\x00\x01'+b'\xff'*(384-len(tail)-3)+b'\0'+tail,'author RSA signature invalid'
    return dict(size=size,count=count,uuid=str(uuid.UUID(bytes=volume)).upper(),image_sha256=imagehash.hex(),table_sha256=tablehash.hex(),generation=generation)
def component_map(board):
    windows={window['name']:window['component'] for window in board['userdata']['windows']}
    expected={'OS':'OS','SystemOS':'Cryptex1,SystemOS'}
    assert all(windows.get(name)==component for name,component in expected.items()),'OS27 component mapping differs from author profile'
    return expected

def create(ctx,out):
    from unixnu.ipsw import Ipsw
    from unixnu.userdata import image_size,disk_blocks
    src=Ipsw(ctx); out.mkdir(parents=True,exist_ok=True); records={}
    components=component_map(ctx.board)
    policy_dir=TOP/'device/scripts/policies'/PROFILE
    selected=[]
    for name in ('OS','SystemOS'):
        head=(policy_dir/name/'manifest.header.bin').read_bytes()
        key=(policy_dir/name/'trusted-key.bin').read_bytes()
        meta=policy(head,key)
        prefix='os' if name=='OS' else 'systemos'
        assert meta['image_sha256']==ctx.board['root'][prefix+'_image_sha256']
        assert meta['uuid']==ctx.board['root'][prefix+'_volume_uuid']
        selected.append((name,head,key,meta))
    # Each AEA member and its decrypted DMG may coexist; raw root and compressed output also need room.
    member_bytes=sum(src.info(components[name])[1] for name in ('OS','SystemOS'))
    root_raw=sum(x[3]['size'] for x in selected)+(8<<20)
    save(TOP/'evidence/root-resource-plan.json',dict(member_bytes=member_bytes,raw_root_allowance_bytes=root_raw,required_free_bytes=2*member_bytes+2*root_raw+2*GIB,actual_free_bytes=__import__('shutil').disk_usage(TOP).free))
    space(2*member_bytes+2*root_raw+2*GIB,'two root members, decrypted images, raw root and worst-case compressed stream')
    for name,head,key,meta in selected:
        dmg=src.disk_image(components[name]); size=image_size(dmg)
        assert size==meta['size']
        imagehash=hashlib.sha256(); tablehash=hashlib.sha256(); count=0; total=0
        table=out/(name+'.vroot')
        with table.open('xb') as dest, contextlib.closing(disk_blocks(dmg,size)) as chunks:
            for chunk in chunks:
                assert len(chunk)%4096==0
                imagehash.update(chunk);total+=len(chunk)
                hashes=b''.join(hashlib.sha256(chunk[i:i+4096]).digest() for i in range(0,len(chunk),4096))
                dest.write(hashes);tablehash.update(hashes);count+=len(hashes)//32
        assert total==size and count==meta['count']
        assert imagehash.hexdigest()==meta['image_sha256']
        assert tablehash.hexdigest()==meta['table_sha256']
        assert table.stat().st_size==count*32
        records[name]=dict(meta,header_sha256=hashlib.sha256(head).hexdigest(),anchor_sha256=hashlib.sha256(key).hexdigest(),table_bytes=table.stat().st_size,table_path=table.name,original_signature_preserved=True)
    save(out/'verification.json',records)
    return records
if __name__=='__main__':
    create(context(),TOP/'tables')

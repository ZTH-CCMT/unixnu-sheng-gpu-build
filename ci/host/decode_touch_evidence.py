#!/usr/bin/env python3
"""TEVRAW02 decoder/extractor. Diagnostic capture, not full sequence replay."""
import argparse,hashlib,json,re,struct,zlib
from pathlib import Path
HEADER=172;SAMPLE=13834;META=30;PUB=166;HID=80
SLOT_FIELDS='active tracking_id age x y rx ry fx fy vx vy dx dy missed miss_reason'.split()
CONTACT_FIELDS='slot tracking_id x y peak area weight'.split()
class Reader:
 def __init__(self,data):self.data=data;self.at=0
 def get(self,fmt):
  n=struct.calcsize('<'+fmt)
  if self.at+n>len(self.data):raise ValueError('truncated record')
  v=struct.unpack_from('<'+fmt,self.data,self.at);self.at+=n;return v
 def raw(self,n):
  if self.at+n>len(self.data):raise ValueError('truncated bytes')
  v=self.data[self.at:self.at+n];self.at+=n;return v

def decode(data):
 r=Reader(data)
 if r.raw(8)!=b'TEVRAW02':raise ValueError('requires TEVRAW02; v1 is not this schema')
 version,total,ns,nm,np,nh,reason,mask,rawlen,peek,nodes,slots,window=r.get('13I')
 if version!=2 or total!=len(data) or ns!=mask.bit_count() or ns>32 or nm>8192 or np>4096 or nh>4096 or reason not in (1,2) or (rawlen,peek,nodes,slots,window)!=(5417,32,2400,12,12000000):raise ValueError('header bounds/schema mismatch')
 expected=HEADER+ns*SAMPLE+nm*META+np*PUB+nh*HID
 if expected!=len(data):raise ValueError('record lengths inconsistent')
 times=r.get('11Q');po,ho,pc,hc=r.get('IIQQ')
 result={'version':version,'wire_bytes':total,'valid_mask':mask,'freeze_reason':reason,'window_us':window,'arm_us':times[0],'first_event_us':times[1],'last_event_us':times[2],'freeze_us':times[3],'trigger_us':times[4],'trigger_sequence':times[5],'observed_frames':times[6],'skipped_before_arm':times[7],'skipped_unseeded':times[8],'rejected_calls':times[9],'selection_skipped':times[10],'publish_overflow':po,'hid_overflow':ho,'publish_contention_lower_bound':pc,'hid_contention_lower_bound':hc,'samples':[],'metadata':[],'publications':[],'hid':[]}
 assert r.at==HEADER
 for i in range(ns):
  seq,t,ps,counter,n,typ,dt,kind,selection,have,active,prepub,postpub,outcount=r.get('QQIHh9B')
  if typ not in (2,4) or kind not in (1,2) or n< -2 or n>12 or have!=1 or max(active,prepub,postpub,outcount)>12:raise ValueError('sample bounds')
  start=r.at;raw=r.raw(rawlen);pk=r.raw(peek);reference=list(r.get('2400h'))
  if raw[281]!=typ or (raw[259]|(raw[260]<<8))!=counter or raw[313]!=dt or ((kind==2)!=(dt==0x1d)) or (kind==2 and n!=-2) or (kind==1 and n< -1):raise ValueError('raw/header classification disagreement')
  pre=[dict(zip(SLOT_FIELDS,r.get('15q'))) for _ in range(slots)];post=[dict(zip(SLOT_FIELDS,r.get('15q'))) for _ in range(slots)]
  contacts=[dict(zip(CONTACT_FIELDS,r.get('7q'))) for _ in range(slots)]
  result['samples'].append({'sequence':seq,'time_us':t,'publish_sequence_snapshot':ps,'counter':counter,'type':typ,'data_type':dt,'kind':kind,'selection':selection,'have_reference':have,'pre_active_count':active,'pre_published_count':prepub,'post_published_count':postpub,'out_count':outcount,'m_result':n,'raw_offset':start,'raw':raw,'peek':pk,'reference':reference,'pre_slots':pre,'post_slots':post,'contacts':contacts})
 for _ in range(nm):
  seq,t,ps,counter,n,typ,dt,kind,pub,pre,post=r.get('QQIHh6B')
  if typ not in (2,4) or kind not in (1,2) or n< -2 or n>12 or max(pub,pre,post)>12 or ((kind==2)!=(dt==0x1d)) or (kind==2 and n!=-2) or (kind==1 and n< -1):raise ValueError('metadata bounds')
  result['metadata'].append(dict(sequence=seq,time_us=t,publish_sequence_snapshot=ps,counter=counter,m_result=n,type=typ,data_type=dt,kind=kind,published_count=pub,pre_active_count=pre,post_active_count=post))
 for _ in range(np):
  t,seq,ps,source,count=r.get('QQIBB');coords=[r.get('iii') for _ in range(12)]
  if count>12:raise ValueError('publication bounds')
  result['publications'].append(dict(time_us=t,frame_sequence=seq,publish_sequence=ps,source=source,count=count,contacts=[dict(id=x,x=y,y=z) for x,y,z in coords[:count]]))
 for _ in range(nh):
  t,ps,rc,stage,n=r.get('QIiBB');report=r.raw(62)
  if n>62 or stage not in (1,2,3,4,5) or (stage==5 and (n!=62 or report[0]!=3 or report[-1]>10)):raise ValueError('HID bounds/known report contract')
  result['hid'].append(dict(time_us=t,publish_sequence=ps,result=rc,stage=stage,report_bytes=n,report_hex=report[:n].hex(),report_id=report[0] if n else None,contact_count=report[61] if n==62 else None))
 if r.at!=len(data):raise ValueError('trailing data')
 return result

def extract(text):
 groups={};current=None
 for line in text.splitlines():
  m=re.fullmatch(r'\[touch evidence\] format=TEV2 boot=([0-9a-f]{16}) generation=2 total=(\d+) crc32=([0-9a-f]{8}) off=(\d+) bytes=(\d+)',line)
  if m:
   boot,total,crc,off,n=m.groups();total=int(total);off=int(off);n=int(n)
   if total>2097152 or n>8192 or off+n>total:raise ValueError('chunk bounds')
   current=(boot,total,crc);groups.setdefault(current,{})
   continue
  m=re.fullmatch(r'TEV2 off=(\d+) hex=([0-9a-f]+)',line)
  if m and current:
   off=int(m[1]);data=bytes.fromhex(m[2]);total=current[1]
   if not data or len(data)>128 or off+len(data)>total:raise ValueError('hex bounds')
   g=groups[current]
   for j,b in enumerate(data):
    if off+j in g and g[off+j]!=b:raise ValueError('conflicting chunk bytes')
    g[off+j]=b
 complete=[]
 for (boot,total,crc),g in groups.items():
  if len(g)!=total:continue
  blob=bytes(g[i] for i in range(total))
  if zlib.crc32(blob)!=int(crc,16):raise ValueError('captured-file CRC mismatch (not sensor CRC)')
  decode(blob);complete.append((boot,blob))
 if len(complete)!=1:raise ValueError('need exactly one complete boot blob; incomplete/ambiguous')
 return complete[0]

def summary(d):
 out={k:v for k,v in d.items() if k not in ('samples','metadata','publications','hid')}
 out.update(metadata_count=len(d['metadata']),publish_count=len(d['publications']),hid_count=len(d['hid']),samples=[])
 for s in d['samples']:
  x={k:v for k,v in s.items() if k not in ('raw','peek','reference','pre_slots','post_slots')};x['raw_sha256']=hashlib.sha256(s['raw']).hexdigest();x['raw_bytes']=len(s['raw']);out['samples'].append(x)
 out['limitations']='Selected raw checkpoints only; no physical finger-up timestamp, full-frame sequence, DMA integrity, UI receipt, or hardware qualification claimed.'
 return out

def main():
 p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('--text',action='store_true');p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
 if a.text:
  boot,data=extract(a.input.read_text(errors='replace'));(a.out/'captured.blob').write_bytes(data)
 else:data=a.input.read_bytes();boot=None
 d=decode(data);report=summary(d);report['boot_id_from_text']=boot;report['sha256']=hashlib.sha256(data).hexdigest();(a.out/'summary.json').write_text(json.dumps(report,indent=2))
 for i,s in enumerate(d['samples']):(a.out/('sample-%02d-frame.bin'%i)).write_bytes(s['raw'])
 print(json.dumps({'status':'PASS','samples':len(d['samples']),'metadata':len(d['metadata']),'wire_bytes':len(data)}))
if __name__=='__main__':main()

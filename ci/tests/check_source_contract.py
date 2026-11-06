#!/usr/bin/env python3
import hashlib
from pathlib import Path

def strip_probe(source):
 s=source
 for header in ('TouchRawEvidence.h','TouchEvidenceSerialize.h','TouchDiagnosticRecords.h'):s=s.replace('#include "'+header+'"\n','')
 start=s.index('// One-shot diagnostic state.');end=s.index('\nnamespace {\n',s.index('extern "C" void native_touch_evidence_hid'));s=s[:start]+s[end+1:]
 s=s.replace('void publish(unsigned count, const nvt_contact *c, uint8_t evidenceSource=0, uint64_t evidenceFrame=0) {','void publish(unsigned count, const nvt_contact *c) {')
 start=s.index('    if(__atomic_load_n(&native_touch_evidence_enabled',s.index('void publish('));end=s.index('    if (void (*sink)',start);s=s[:start]+s[end:]
 s=s.replace('    rawEvidence.guard(nowUs); // Existing producer wake only; no new timer or SPI read.\n','')
 s=s.replace('        initRawEvidence(touchUs(mach_absolute_time()));\n','')
 start=s.index('                touch_raw_evidence::Prepared evidencePrepared=');end=s.index('                if (nvt_frame_is_stylus',start);s=s[:start]+s[end:]
 start=s.index('                if(evidencePrepared==touch_raw_evidence::AwaitingM) {');end=s.index('                native_touch_jitter[0]',start);s=s[:start]+s[end:]
 s=s.replace('                if(evidencePrepared==touch_raw_evidence::AwaitingM)\n                    rawEvidence.after(n,out,NVT_SLOTS,static_cast<uint8_t>(native_touch_count),s->core->slots,NVT_SLOTS,native_touch_seq);\n','')
 s=s.replace('publish(static_cast<unsigned>(n), out,1,rawEvidence.currentSequence());','publish(static_cast<unsigned>(n), out);').replace('publish(0, nullptr,2);','publish(0, nullptr);')
 return s

def check(root):
 source=(root/'device/package/TouchProbe.cpp').read_text();stripped=strip_probe(source)
 expected='e7d8908ae1be22b6ab18e1d61b8fd2880312c11e438d3950e551393a6ef75531'
 actual=hashlib.sha256(stripped.encode()).hexdigest()
 if actual!=expected:raise AssertionError('diagnostic erasure does not reproduce frozen v3 TouchProbe: '+actual)
 hid=(root/'device/drivers/ShengHidInput/NativeHidInput.cpp').read_text()
 descriptor=hid[hid.index('static const unsigned char descriptor[]='):hid.index('namespace edge')]
 if hashlib.sha256(descriptor.encode()).hexdigest()!='8f551bedc59f141e621694ad1c454ad41035fad6f1f06180732dd8f6daaf4887':raise AssertionError('HID descriptors changed')
 return {'stripped_probe_sha256':actual,'production_policy_static_equivalence':'exact LF text v3 after removing only enumerated diagnostic hooks','descriptor_region_sha256':hashlib.sha256(descriptor.encode()).hexdigest()}

"""Fast synthetic fileset/parser and quarantine tests; optional retained real raw smoke."""
import argparse
import contextlib
import hashlib
import io
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fileset_symbols import SymbolError, required_definitions
from preserve_failed_build import collect

ARGS = None


def fixture():
    image = bytearray(4096)
    def header(at, kind, commands):
        body = b''.join(commands)
        struct.pack_into('<8I', image, at, 0xfeedfacf, 0x100000c, 2, kind, len(commands), len(body), 0, 0)
        image[at+32:at+32+len(body)] = body
    def entry(native=256, name=b'com.apple.kernel'):
        return struct.pack('<IIQQII', 0x80000035, 56, 0x1000, native, 32, 0) + (name + b'\0').ljust(24, b'\0')
    def segment(name, address, span, offset, filesize, flags):
        body = struct.pack('<II16sQQQQiiII', 0x19, 152, name.ljust(16,b'\0'), address, span, offset, filesize, 7, 3, 1, 0)
        body += struct.pack('<16s16sQQIIIIIIII', b'__text' if flags == 0 else b'__common', name,
                            address, span, offset, 2, 0, 0, flags, 0, 0, 0)
        return body
    commands = [segment(b'__TEXT_EXEC',0x1000,16,1024,16,0),
                segment(b'__DATA',0x2000,16,0,0,1),
                struct.pack('<6I',2,24,1280,4,1536,128)]
    header(0,12,[entry()]); header(256,2,commands)
    strings = b'\0_required\0_global\0_undefined\0_absolute\0'
    image[1536:1536+len(strings)] = strings
    for index,(name,ntype,section,address) in enumerate([
            (b'_required',15,1,0x1000),(b'_global',15,2,0x2000),
            (b'_undefined',1,0,0),(b'_absolute',3,0,0x3000)]):
        struct.pack_into('<IBBHQ',image,1280+16*index,strings.index(name),ntype,section,0,address)
    return image, header, entry


class SupportTests(unittest.TestCase):
    def rejected(self, image, names=('_required',)):
        with self.assertRaises((SymbolError, UnicodeError)):
            required_definitions(image,names)
    def test_outer_no_symtab_inner_absolute_and_bss(self):
        b,_,_=fixture(); definitions,evidence=required_definitions(b,('_required','_global'))
        self.assertEqual(evidence['header_chain'][1]['header_offset'],256)
        self.assertEqual(definitions['_global']['section'],2)
    def test_undefined_not_definition(self):
        b,_,_=fixture(); self.rejected(b,('_undefined',))
    def test_absolute_not_section_definition(self):
        b,_,_=fixture(); self.rejected(b,('_absolute',))
    def test_indirect_not_definition(self):
        b,_,_=fixture();b[1284]=11;self.rejected(b)
    def test_stab_not_definition(self):
        b,_,_=fixture();b[1284]=0xef;self.rejected(b)
    def test_truncated_outer(self):
        b,_,_=fixture()
        for length in (0,3,31,40,80):self.rejected(b[:length])
    def test_truncated_inner(self):
        b,_,_=fixture();self.rejected(b[:280])
    def test_truncated_symbols(self):
        b,_,_=fixture();self.rejected(b[:1300])
    def test_bad_native_header(self):
        b,_,_=fixture();b[256]=0;self.rejected(b)
    def test_duplicate_kernel_entry(self):
        b,header,entry=fixture();header(0,12,[entry(),entry()]);self.rejected(b)
    def test_wrong_entry_name(self):
        b,header,entry=fixture();header(0,12,[entry(name=b'com.apple.other')]);self.rejected(b)
    def test_relative_shift_is_not_guessed(self):
        b,_,_=fixture();symcmd=256+32+152*2
        struct.pack_into('<I',b,symcmd+8,1280+256)
        struct.pack_into('<I',b,symcmd+16,1536+256)
        self.rejected(b)
    def test_invalid_section(self):
        b,_,_=fixture();b[1285]=3;self.rejected(b)
    def test_duplicate_required_symbol_rejected(self):
        b,_,_=fixture();b[1296:1312]=b[1280:1296];self.rejected(b)
    def test_bad_load_command_size(self):
        b,_,_=fixture();struct.pack_into('<I',b,36,4);self.rejected(b)
    def test_quarantine_explicit_files_and_missing(self):
        with tempfile.TemporaryDirectory(dir=ARGS.out.parent) as td:
            top=Path(td);ci=top/'pipeline/ci';ci.mkdir(parents=True)
            lock={'profile':'ipados-27.0.1-24A446','touch_frame_kind_fix':{'variant':'testing'}}
            (ci/'os27-update-lock.json').write_text(json.dumps(lock),encoding='utf8')
            work=top/'UniXNU/out/sheng/ipados-27.0.1-24A446/sheng_ipados27'
            for name in ('kernel/kernel.macho','payload/payload.img','boot/boot.img'):
                path=work/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(name.encode())
            (work/'SECRET.txt').write_text('must never be collected',encoding='utf8')
            env={'UNIXNU_UNIQUE_CHIP_ID':'13579bdf','GITHUB_REPOSITORY':'example/build',
                 'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1','GITHUB_SHA':'a'*40}
            with patch.dict(os.environ,env),contextlib.redirect_stdout(io.StringIO()):receipt=collect(top,ci)
            out=top/'os27-touch-quarantine-UNAPPROVED_DO_NOT_BOOT'
            self.assertFalse(receipt['source_gate_pass']);self.assertFalse(receipt['normal_handoff_authorized'])
            self.assertIn('metadata/touch-source-binding.json',receipt['missing'])
            self.assertEqual(receipt['files']['kernel/kernel.macho']['sha256'],hashlib.sha256(b'kernel/kernel.macho').hexdigest())
            self.assertFalse(any('SECRET' in p.name for p in out.rglob('*')))
            with patch.dict(os.environ,env),self.assertRaises(RuntimeError):collect(top,ci)
    def test_quarantine_rejects_real_identity(self):
        with tempfile.TemporaryDirectory(dir=ARGS.out.parent) as td:
            top=Path(td);ci=top/'pipeline/ci';ci.mkdir(parents=True)
            (ci/'os27-update-lock.json').write_text(json.dumps({'profile':'ipados-27.0.1-24A446',
                'touch_frame_kind_fix':{'variant':'testing'}}),encoding='utf8')
            with patch.dict(os.environ,{'UNIXNU_UNIQUE_CHIP_ID':'real-device'}),self.assertRaises(RuntimeError):collect(top,ci)


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--real-raw',type=Path)
    parser.add_argument('--out',type=Path,default=Path(__file__).resolve().parent/'host-test-results/ci-support-results.json')
    ARGS=parser.parse_args();ARGS.out.parent.mkdir(parents=True,exist_ok=True)
    result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(SupportTests))
    report={'status':'PASS' if result.wasSuccessful() else 'FAIL','synthetic_tests':result.testsRun,
            'failures':len(result.failures),'errors':len(result.errors),'hardware_verified':False}
    if result.wasSuccessful() and ARGS.real_raw:
        raw=ARGS.real_raw.read_bytes()
        definitions,evidence=required_definitions(raw,('_nvt_frame_is_stylus','_nvt_touch_process','_native_touch_seq'))
        report['retained_real_raw']={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
                                     'definitions':definitions,'evidence':evidence}
    ARGS.out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    if not result.wasSuccessful():raise SystemExit(1)
    print(json.dumps(report))

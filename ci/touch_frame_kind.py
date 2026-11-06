"""Apply an exact author-to-variant patch and run real host contracts before a macOS kernel build."""
import hashlib, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
LOCK=json.loads((HERE/'os27-update-lock.json').read_text())
SPEC=LOCK['touch_frame_kind_fix']
ALLOWED_RUNTIME = {
    'device/package/TouchProbe.cpp', 'device/package/BootLog.c',
    'device/package/TouchLifecycle.h', 'device/package/TouchRawEvidence.h',
    'device/package/TouchEvidenceWire.h', 'device/package/TouchEvidenceSerialize.h',
    'device/package/TouchDiagnosticRecords.h', 'device/package/TouchEngine.h',
    'device/drivers/ShengNovatekTouch/NvtProtocol.c',
    'device/drivers/ShengNovatekTouch/NvtProtocol.h',
    'device/drivers/ShengNovatekTouch/NvtTouchCore.c',
    'device/drivers/ShengNovatekTouch/NvtTouchCore.h',
    'device/drivers/ShengNovatekTouch/Test/nvt-protocol.c',
    'device/drivers/ShengHidInput/NativeHidInput.cpp',
}
NEW_HEADERS = {
    'device/package/TouchLifecycle.h', 'device/package/TouchRawEvidence.h',
    'device/package/TouchEvidenceWire.h', 'device/package/TouchEvidenceSerialize.h',
    'device/package/TouchDiagnosticRecords.h', 'device/package/TouchEngine.h',
}

def require(ok, why):
    if not ok: raise RuntimeError(why)
def sha(b): return hashlib.sha256(b).hexdigest()
def checked_patch():
    patch=(HERE/'author-to-touch.patch').read_bytes()
    require(sha(patch)==SPEC['patch_sha256'],'Unexpected touch patch hash')
    require(0<len(patch)<1024*1024,'Unexpected touch patch size')
    require(not any(x in patch for x in (b'GIT binary patch',b'deleted file mode',b'rename from',b'rename to',b'old mode')), 'Unexpected patch operation')
    sections=re.split(rb'(?=^diff --git )',patch,flags=re.M)
    require(sections[0]==b'' and len(sections)==len(SPEC['files'])+1,'Patch section count differs')
    names=set()
    for block in sections[1:]:
        m=re.match(rb'diff --git a/([^\n]+) b/([^\n]+)\n',block)
        require(m is not None and m[1]==m[2],'Unexpected path pair')
        name=m[1].decode()
        require(name in SPEC['files'] and name in ALLOWED_RUNTIME and name not in names,'Unexpected patch path')
        require(SPEC['files'][name]['before'] is not None or name in NEW_HEADERS,'Existing file incorrectly classified as new')
        require(re.fullmatch(r'device/(?:package/[A-Za-z0-9_./-]+\.(?:c|cpp|h)|drivers/Sheng(?:NovatekTouch|HidInput)/[A-Za-z0-9_./-]+\.(?:c|cpp|h))',name) is not None and '..' not in Path(name).parts,'Path outside touch-only allowlist')
        names.add(name)
    require(names==set(SPEC['files']),'Patch file set differs')
    return patch

def apply_touch_patch(top):
    top=Path(top).resolve(); checked_patch()
    for rel,item in SPEC['files'].items():
        path=top/rel
        require(path.resolve().is_relative_to(top) and not path.is_symlink(),'Linked overlay source')
        if item['before'] is None: require(not path.exists(),'New header unexpectedly exists: '+rel)
        else: require(path.is_file() and sha(path.read_bytes())==item['before'],'Original hash differs: '+rel)
    subprocess.run(['git','apply','--check',str(HERE/'author-to-touch.patch')],cwd=top,check=True,capture_output=True)
    subprocess.run(['git','apply',str(HERE/'author-to-touch.patch')],cwd=top,check=True,capture_output=True)
    for rel,item in SPEC['files'].items():
        require(sha((top/rel).read_bytes())==item['after'],'Patched hash differs: '+rel)
    return SPEC

def preflight(top):
    top=Path(top).resolve()
    parent=Path(os.environ.get('RUNNER_TEMP', HERE/'preflight-work')).resolve()
    parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='touch-contract-',dir=parent) as temp:
        temp=Path(temp)
        extras=('device/drivers/ShengNovatekTouch/NvtTouchCore.c','device/drivers/ShengNovatekTouch/NvtTouchCore.h','device/drivers/ShengNovatekTouch/NvtProtocol.c','device/drivers/ShengNovatekTouch/NvtProtocol.h')
        for rel in set(SPEC['files'])|set(extras):
            item=SPEC['files'].get(rel)
            if item is not None and item['before'] is None: continue
            source=top/rel
            require(source.is_file(),'Missing original source: '+rel)
            dest=temp/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
        apply_touch_patch(temp)
        shutil.copytree(HERE/'tests',temp/'tests')
        if (HERE/'host').is_dir(): shutil.copytree(HERE/'host',temp/'host')
        output=HERE/'host-test-results'
        output.mkdir(exist_ok=True)
        env={**os.environ,'TMPDIR':str(parent),'TMP':str(parent),'TEMP':str(parent),'UBSAN_OPTIONS':'halt_on_error=1:print_stacktrace=1','ASAN_OPTIONS':'halt_on_error=1'}
        subprocess.run([sys.executable,str(temp/'tests/run_ci_tests.py'),'--root',str(temp),'--out',str(output)],check=True,env=env)
    print('Synthetic production-code host contracts passed; no hardware success claimed.',flush=True)

if __name__=='__main__':
    require(sys.argv[1:]==['--preflight'],'Usage: touch_frame_kind.py --preflight')
    preflight(Path(os.environ.get('GITHUB_WORKSPACE',Path.cwd())))

"""Exact V3.1 source compilation and late-archive wiring; runtime sources are untouched."""
EXTRA_UNITS = ('NvtPartialObservation', 'NvtCoverage')
COMPILED_TOUCH_UNITS = ('NativeHidInput', 'TouchProbe', 'NvtProtocol', 'NvtTouchCore', *EXTRA_UNITS)
EXTRA_DEFINITIONS = {
    'NvtPartialObservation': ('nvt_partial_reset', 'nvt_partial_configure', 'nvt_partial_bind_template',
                              'nvt_partial_seed', 'nvt_partial_measure', 'nvt_partial_math_evaluate'),
    'NvtCoverage': ('nvt_coverage_negative',),
}
KERNEL_DEFINITIONS = tuple('_' + name for names in EXTRA_DEFINITIONS.values() for name in names)

SOURCE_ANCHOR = b"            (device / 'drivers/ShengNovatekTouch/NvtTouchCore.c', []),"
SOURCE_EXTRA = b''.join(b"\n            (device / 'drivers/ShengNovatekTouch/" + stem.encode() + b".c', [])," for stem in EXTRA_UNITS)
SOURCE_IMPORTS = b"            imports = nm(output, '-u')\n"
SOURCE_CHECK = b'''            # The new integer-only C units must not acquire compiler-rt wide-integer imports.
            if source.stem in ('NvtPartialObservation', 'NvtCoverage'):
                forbidden = {'divti3', 'udivti3', 'modti3', 'umodti3', 'multi3', 'ashlti3', 'ashrti3', 'lshrti3'}
                unresolved_helpers = sorted(name for name in imports if name.lstrip('_') in forbidden)
                if unresolved_helpers:
                    raise SystemExit(f'{source.name}: unsupported wide-integer runtime imports: {unresolved_helpers}')
'''

def source_builder_replacements():
    return [(SOURCE_ANCHOR, SOURCE_ANCHOR + SOURCE_EXTRA),
            (SOURCE_IMPORTS, SOURCE_IMPORTS + SOURCE_CHECK)]

LATE_SELECTION = rb'''input_objects = [hid_late, OUT / 'hid-bindings.o', OUT / 'hid-addresses.o', OUT / 'HidInputProbe.o'] + \
    [SRC / (stem + '.o') for stem in ('TouchProbe', 'ButtonProbe', 'GeniSpi', 'NvtProtocol', 'NvtTouchCore', 'NvtFirmware')]
'''
# Embedded in the actual pinned author script so its subprocess has no implicit CI import path.
LATE_HELPERS = b'''def select_touch_transport(src, device):
    report_path = src / 'report.json'
    report = json.loads(report_path.read_text())
    require(report.get('compile_pass') is True, 'Touch transport compilation did not pass')
    component = report['components']['ShengInputTransport']
    transport_archive = Path(component['archive'])
    require(sha(transport_archive) == component['archive_sha256'], 'Touch transport archive changed after compile')
    expected = {'TouchProbe', 'ButtonProbe', 'GeniSpi', 'NvtProtocol', 'NvtTouchCore',
                'NvtPartialObservation', 'NvtCoverage', 'NvtFirmware'}
    objects, evidence = [], {}
    for item in component['objects']:
        source, obj = Path(item['source']), Path(item['object'])
        stem = source.stem
        require(stem in expected and stem not in evidence, 'Unexpected/duplicate touch transport unit: ' + stem)
        require(obj.resolve() == (src / (stem + '.o')).resolve(), 'Touch transport object path differs: ' + stem)
        if stem in ('NvtPartialObservation', 'NvtCoverage'):
            require(source.resolve() == (device / 'drivers/ShengNovatekTouch' / (stem + '.c')).resolve(),
                    'Touch transport source path differs: ' + stem)
        require(sha(source) == item['source_sha256'] and sha(obj) == item['object_sha256'],
                'Touch transport source/object changed: ' + stem)
        evidence[stem] = {key: item[key] for key in ('source', 'source_sha256', 'object', 'object_sha256')}
        objects.append(obj)
    require(set(evidence) == expected, 'Missing compiled touch transport units: ' + ', '.join(sorted(expected - set(evidence))))
    return objects, {'source_report_sha256': sha(report_path),
                     'transport_archive_sha256': sha(transport_archive), 'objects': evidence}


def verify_touch_late_archive(archive, evidence):
    members = run(['xcrun', 'ar', 't', archive], text=True).splitlines()
    for stem in evidence['objects']:
        require(members.count(stem + '.o') == 1, 'Late archive omits/duplicates touch object: ' + stem)
    # nm inspects definitions from the archive that the final XNU link actually force-loads.
    definitions = {name.removeprefix('_') for name in run(['xcrun', 'nm', '-j', '-gU', archive], text=True).splitlines()}
    required = {'nvt_partial_reset', 'nvt_partial_configure', 'nvt_partial_bind_template',
                'nvt_partial_seed', 'nvt_partial_measure', 'nvt_partial_math_evaluate', 'nvt_coverage_negative'}
    require(required <= definitions, 'Late archive lacks touch definitions: ' + ', '.join(sorted(required - definitions)))
    evidence.update(late_archive_sha256=sha(archive), late_archive_members=members,
                    defined_symbols=sorted(required), status='COMPILED_OBJECTS_IN_ACTUAL_LATE_ARCHIVE')
    return evidence


touch_transport, touch_link_evidence = select_touch_transport(SRC, DEVICE)
input_objects = [hid_late, OUT / 'hid-bindings.o', OUT / 'hid-addresses.o', OUT / 'HidInputProbe.o'] + touch_transport
'''
LATE_AR = b"     OUT / 'KeyStoreProbe.o', keyevents_late, *input_objects])\n"
LATE_CHECK = b"touch_link_evidence = verify_touch_late_archive(archive, touch_link_evidence)\n(OUT / 'touch-link-evidence.json').write_text(json.dumps(touch_link_evidence, indent=2) + '\\n')\n"
LATE_REPORT = b"    kernelcache_sha256=abi['kernelcache_sha256'], compiled_object_sha256=sha(obj), archive_sha256=sha(archive),"

def late_builder_replacements():
    return [(LATE_SELECTION, LATE_HELPERS), (LATE_AR, LATE_AR + LATE_CHECK),
            (LATE_REPORT, LATE_REPORT + b' touch_source_link=touch_link_evidence,')]

def adapt(raw, replacements):
    for before, after in replacements:
        if raw.count(before) != 1:
            raise RuntimeError('Unexpected pinned build script anchor: ' + repr(before[:100]))
        raw = raw.replace(before, after, 1)
    return raw

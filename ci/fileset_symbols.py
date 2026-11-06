"""Read defined ARM64 symbols using whole-fileset absolute file offsets.

LC_FILESET_ENTRY selects com.apple.kernel. Its Mach-O load commands and
section ordinals are native-local; LC_SYMTAB and section file offsets remain
absolute offsets in the original fileset. No offset-base guessing is allowed.
"""
import struct


class SymbolError(ValueError):
    pass


def require(ok, why):
    if not ok:
        raise SymbolError(why)


def kernel_symbols(image):
    """Return N_SECT definitions and structural evidence, rejecting bad bounds."""
    length = len(image)
    seen = set()
    chain = []
    native = 0
    for depth in range(9):
        require(native not in seen, 'Recursive fileset kernel entry')
        seen.add(native)
        require(0 <= native <= length - 32, 'Truncated native Mach-O header')
        magic, cpu, subtype, kind, ncmds, sizecmds, flags, reserved = struct.unpack_from('<8I', image, native)
        require(magic == 0xfeedfacf and cpu == 0x100000c, 'Expected little-endian ARM64 Mach-O')
        require(kind in (2, 12), 'Expected MH_EXECUTE or MH_FILESET kernel')
        require(ncmds <= 65536 and sizecmds <= length - native - 32, 'Invalid Mach-O command range')
        end_commands = native + 32 + sizecmds
        pos = native + 32
        symtabs, entries, sections = [], [], []
        for _ in range(ncmds):
            require(pos <= end_commands - 8, 'Truncated Mach-O load command')
            cmd, size = struct.unpack_from('<II', image, pos)
            require(size >= 8 and size % 8 == 0 and size <= end_commands - pos, 'Invalid Mach-O load command size')
            if cmd == 2:
                require(size == 24, 'Malformed LC_SYMTAB')
                symtabs.append(struct.unpack_from('<4I', image, pos + 8))
            elif cmd == 0x80000035:
                require(size >= 40, 'Malformed LC_FILESET_ENTRY')
                vmaddr, fileoff, nameoff, unused = struct.unpack_from('<QQII', image, pos + 8)
                require(32 <= nameoff < size, 'Invalid fileset entry name offset')
                stop = image.find(b'\0', pos + nameoff, pos + size)
                require(stop >= 0, 'Unterminated fileset entry name')
                if image[pos + nameoff:stop] == b'com.apple.kernel':
                    entries.append(fileoff)
            elif cmd == 0x19:
                require(size >= 72, 'Truncated LC_SEGMENT_64')
                vmaddr, vmsize, fileoff, filesize = struct.unpack_from('<4Q', image, pos + 24)
                nsects, = struct.unpack_from('<I', image, pos + 64)
                require(size == 72 + nsects * 80 and nsects <= 255, 'Invalid segment section list')
                require(fileoff <= length and filesize <= length - fileoff, 'Invalid absolute segment file range')
                require(vmaddr + vmsize <= (1 << 64), 'Overflowing segment VM range')
                for i in range(nsects):
                    at = pos + 72 + i * 80
                    address, span, offset = struct.unpack_from('<QQI', image, at + 32)
                    section_flags, = struct.unpack_from('<I', image, at + 64)
                    zero_fill = (section_flags & 0xff) in (1, 12, 18)
                    require(vmaddr <= address <= vmaddr + vmsize and span <= vmaddr + vmsize - address,
                            'Section outside segment VM range')
                    if not zero_fill and span:
                        require(fileoff <= offset <= fileoff + filesize and span <= fileoff + filesize - offset,
                                'Section outside absolute segment file range')
                    sections.append((address, span, zero_fill))
            pos += size
        require(pos == end_commands, 'Mach-O command count/size mismatch')
        chain.append({'header_offset': native, 'filetype': kind, 'ncmds': ncmds})
        if kind == 12:
            require(depth < 8 and len(entries) == 1, 'Expected exactly one fileset com.apple.kernel entry')
            native = entries[0]
            continue
        require(not entries and len(symtabs) == 1, 'Expected one native kernel symbol table')
        require(0 < len(sections) <= 255, 'Native kernel sections missing')
        symoff, count, stroff, strsize = symtabs[0]
        require(0 < count <= 2000000 and symoff <= length and count * 16 <= length - symoff,
                'Native symbol table outside whole fileset')
        require(strsize > 0 and stroff <= length and strsize <= length - stroff,
                'Native string table outside whole fileset')
        result = {}
        ambiguous = set()
        for index in range(count):
            off, ntype, section, desc, address = struct.unpack_from('<IBBHQ', image, symoff + index * 16)
            require(off < strsize, 'Symbol name offset outside string table')
            stop = image.find(b'\0', stroff + off, stroff + strsize)
            require(stop >= 0, 'Unterminated symbol name')
            if ntype & 0xe0 or ntype & 0x0e != 0x0e:
                continue
            require(1 <= section <= len(sections), 'N_SECT section ordinal invalid')
            start, span, zero_fill = sections[section - 1]
            # Linker end markers can be exactly at the section end.
            name = image[stroff + off:stop].decode('utf8', 'strict')
            # The standard linker header marker precedes the first __text section.
            if name == '__mh_execute_header':
                continue
            require(start <= address <= start + span, 'N_SECT address outside selected native section')
            require(bool(name), 'Empty N_SECT symbol name')
            if name in result:
                del result[name]
                ambiguous.add(name)
            elif name not in ambiguous:
                result[name] = {'va': hex(address), 'type': ntype, 'section': section}
        return result, {'format': 'macho64-arm64-native-absolute-v1', 'header_chain': chain,
                        'symbol_table_offset': symoff, 'symbol_count': count,
                        'string_table_offset': stroff, 'string_table_bytes': strsize,
                        'section_count': len(sections), 'ambiguous_symbol_count': len(ambiguous)}
    raise SymbolError('Fileset depth exceeded')


def required_definitions(image, names):
    all_defined, evidence = kernel_symbols(image)
    missing = sorted(set(names) - all_defined.keys())
    require(not missing, 'Kernel does not define required touch symbols: ' + ', '.join(missing))
    return {name: all_defined[name] for name in names}, evidence

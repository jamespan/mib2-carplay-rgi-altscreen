"""Execute actual hook ARM/Thumb bytes in Unicorn, with CF-only host stubs.

No ARM helpers are replaced: make_view_areas, rect_dict, set_i64,
cf_dict_get_cstr, alt_cf_int64 and cf_dict_set_cstr_obj execute from the ELF.
The stubs model the resolved CF adapters and retain/release ownership.
"""
from pathlib import Path
import collections
import hashlib
import io
import os
import json
import struct
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import *
from elftools.elf.elffile import ELFFile

ORIGINAL = ROOT / 'altscreen/Toolbox/carplay_alt_screen/universal/libcarplay_altscreen.so'
CANDIDATE = Path(os.environ.get('CN_HOOK_UNDER_TEST', ROOT / 'build/native-evidence/libcarplay_altscreen-cn.so'))
BASES = (0x1000000, 0x23000000)
STACK = 0x60000000
STUB = 0x50000000
OBJECT = 0x51000000
REGS = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
        UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
        UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11,
        UC_ARM_REG_R12, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC]
COUNTS = collections.Counter()
CF = {'dict_new':0x8878c, 'str_new':0x88790, 'num_new':0x88794,
      'dict_set':0x88798, 'release':0x8879c, 'dict_get':0x887ac,
      'array_append':0x887b0, 'array_new':0x88854,
      'get_typeid':0x88764, 'number_typeid':0x88770, 'num_get':0x88774}

class NativeHarness:
    def __init__(self, path, base, fail_allocation=None, absent_cf=None):
        self.path, self.base = path, base
        self.data = path.read_bytes()
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.uc.mem_map(base, 0x100000)
        elf = ELFFile(io.BytesIO(self.data))
        for segment in elf.iter_segments():
            if segment['p_type'] == 'PT_LOAD':
                self.uc.mem_write(base + segment['p_vaddr'], segment.data())
        # ELF relative relocations, needed for any GOT entries in original helpers.
        for section in elf.iter_sections():
            if section['sh_type'] in ('SHT_REL', 'SHT_RELA'):
                for rel in section.iter_relocations():
                    if rel['r_info_type'] == 23:  # R_ARM_RELATIVE
                        address = base + rel['r_offset']
                        self.word_write(address, self.word(address) + base)
        self.uc.mem_map(STACK, 0x20000)
        self.uc.mem_map(STUB, 0x10000)
        self.uc.mem_map(OBJECT, 0x10000)
        self.objects = {}
        self.next_object = OBJECT
        self.allocation_count = 0
        self.fail_allocation = fail_allocation
        self.record_allocations = False
        self.calls = []
        self.log_messages = []
        self.trace = []
        self.executed_helpers = set()
        self.stub_addresses = {}
        self.completed = False
        self.stop = None
        self.min_sp = STACK + 0x18000
        for i, (name, offset) in enumerate(CF.items()):
            address = STUB + i * 0x10
            self.stub_addresses[address] = name
            self.uc.mem_write(address, bytes.fromhex('1eff2fe1'))  # bx lr fallback
            self.word_write(base+offset, 0 if name == absent_cf else address)
        self.uc.hook_add(UC_HOOK_CODE, self.on_code)

    def word(self, address): return struct.unpack('<I', self.uc.mem_read(address, 4))[0]
    def word_write(self, address, value): self.uc.mem_write(address, struct.pack('<I', value & 0xffffffff))
    def cstr(self, address):
        result = bytearray()
        for i in range(4096):
            v = self.uc.mem_read(address+i, 1)[0]
            if not v: return result.decode('ascii')
            result.append(v)
        raise AssertionError('Unterminated C string')

    def obj(self, handle, kind=None):
        assert handle in self.objects, ('unknown CF object', hex(handle))
        obj = self.objects[handle]
        assert obj['refs'] > 0, ('use after release', hex(handle), obj)
        if kind: assert obj['kind'] == kind, (kind, obj)
        return obj

    def allocate(self, kind, value):
        if self.record_allocations:
            self.allocation_count += 1
            if self.allocation_count == self.fail_allocation:
                return 0
        handle = self.next_object
        self.next_object += 0x10
        assert self.next_object < OBJECT + 0x10000
        self.objects[handle] = {'kind': kind, 'value': value, 'refs':1}
        return handle

    def retain(self, handle): self.obj(handle)['refs'] += 1
    def release(self, handle):
        obj = self.obj(handle)
        obj['refs'] -= 1
        if obj['refs']: return
        if obj['kind'] == 'dict':
            for key, value in obj['value'].values():
                self.release(key)
                self.release(value)
        elif obj['kind'] == 'array':
            for value in obj['value']: self.release(value)

    def dict_set(self, dictionary, key, value):
        target = self.obj(dictionary, 'dict')['value']
        text = self.obj(key, 'str')['value']
        self.obj(value)
        self.retain(value)
        if text in target:
            old_key, old_value = target[text]
            self.release(old_value)
            target[text] = old_key, value
        else:
            self.retain(key)
            target[text] = key, value

    def seed_display(self, type_value=111, wrong_type=False):
        display = self.allocate('dict', {})
        if type_value is not None:
            key = self.allocate('str', 'type')
            value = self.allocate('str' if wrong_type else 'num', type_value)
            self.dict_set(display, key, value)
            self.release(key)
            self.release(value)
        return display

    def plain(self, handle):
        if not handle: return None
        obj = self.obj(handle)
        if obj['kind'] == 'dict': return {k:self.plain(v) for k,(_,v) in obj['value'].items()}
        if obj['kind'] == 'array': return [self.plain(v) for v in obj['value']]
        return obj['value']

    def cf_call(self, name, args):
        a,b,c,d = args
        if name == 'dict_new': return self.allocate('dict', {})
        if name == 'array_new': return self.allocate('array', [])
        if name == 'str_new': return self.allocate('str', self.cstr(a))
        if name == 'num_new':
            value = (d<<32)|c
            if value & (1<<63): value -= 1<<64
            return self.allocate('num', value)
        if name == 'dict_set': self.dict_set(a,b,c); return 0
        if name == 'dict_get':
            item = self.obj(a, 'dict')['value'].get(self.obj(b,'str')['value'])
            return item[1] if item else 0
        if name == 'array_append':
            self.obj(a,'array')['value'].append(b)
            self.retain(b)
            return 0
        if name == 'release': self.release(a); return 0
        if name == 'get_typeid': return {'num':1,'str':2,'dict':3,'array':4}[self.obj(a)['kind']]
        if name == 'number_typeid': return 1
        if name == 'num_get':
            assert b == 4
            self.uc.mem_write(c, struct.pack('<q',self.obj(a,'num')['value']))
            return 1
        raise AssertionError(name)

    def on_code(self, uc, address, size, unused):
        self.min_sp = min(self.min_sp, uc.reg_read(UC_ARM_REG_SP))
        self.trace.append((address, size))
        if len(self.trace) > 20000: raise AssertionError('Instruction bound exceeded')
        if address == self.stop:
            self.completed = True
            uc.emu_stop()
            return
        if address == self.base + 0xd540:  # Logging sink only; no filesystem/syscalls.
            assert uc.reg_read(UC_ARM_REG_SP) % 8 == 0
            self.log_messages.append(self.cstr(uc.reg_read(UC_ARM_REG_R0)))
            for reg in (UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_R12):
                uc.reg_write(reg, 0xa5a5a5a5)
            uc.reg_write(UC_ARM_REG_R0, 0)
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
            return
        if address-self.base in (0x265a8,0x265ac,0x265b0,0x2e268,0x263f4,0x26500,0x275cc,0x25448):
            self.executed_helpers.add(address-self.base)
        if address not in self.stub_addresses: return
        assert uc.reg_read(UC_ARM_REG_SP) % 8 == 0, ('CF call with misaligned SP', hex(address))
        name = self.stub_addresses[address]
        args = [uc.reg_read(r) for r in REGS[:4]]
        self.calls.append((name, args))
        result = self.cf_call(name, args)
        # AAPCS permits these caller-saved registers to be clobbered.
        for reg in (UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_R12):
            uc.reg_write(reg, 0xa5a5a5a5)
        uc.reg_write(UC_ARM_REG_R0, result)
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    def run(self, width=1440, height=542, type_value=111, existing=False,
            wrong_type=False, display=None):
        if display is None: display = self.seed_display(type_value, wrong_type)
        initial_sp = STACK+0x18000
        self.uc.reg_write(UC_ARM_REG_CPSR, 0x10)  # ARM, user, no preexisting condition flags
        for i, reg in enumerate(REGS[:13]): self.uc.reg_write(reg, 0xb0000000+i*0x101)
        self.uc.reg_write(UC_ARM_REG_R0, width)
        self.uc.reg_write(UC_ARM_REG_R1, height)
        self.uc.reg_write(UC_ARM_REG_R9 if existing else UC_ARM_REG_R10, display)
        preserved = {r:self.uc.reg_read(r) for r in REGS[4:12]}
        self.uc.reg_write(UC_ARM_REG_SP, initial_sp)
        self.uc.reg_write(UC_ARM_REG_LR, 0x70000000)
        start = self.base + (0x2713c if existing else 0x26218)
        self.stop = start+4
        self.completed = False
        self.record_allocations = True
        self.trace = []
        try:
            self.uc.emu_start(start, self.stop+4, count=20000)
        except Exception as error:
            raise AssertionError(f'{self.path.name} base={self.base:#x} PC={self.uc.reg_read(UC_ARM_REG_PC):#x}: {error}; last instructions={self.trace[-10:]}') from error
        assert self.completed, 'Failed to return to ARM caller'
        assert self.uc.reg_read(UC_ARM_REG_SP) == initial_sp, 'Stack not balanced'
        for reg, value in preserved.items():
            assert self.uc.reg_read(reg) == value, ('Callee-saved register changed',reg,hex(value),hex(self.uc.reg_read(reg)))
        assert self.uc.reg_read(UC_ARM_REG_CPSR) & 0x20 == 0, 'Did not return in ARM state'
        result = self.uc.reg_read(UC_ARM_REG_R0)
        value = self.plain(result)
        COUNTS['native_invocations'] += 1
        if self.fail_allocation is not None: COUNTS['injected_allocation_failure_invocations'] += 1
        return result, value, display

    def cleanup_and_check(self, result, display):
        if result: self.release(result)
        self.release(display)
        live = {hex(h):o for h,o in self.objects.items() if o['refs']}
        assert not live, ('CF ownership leak', live)

def expected(width, height, changed):
    outer = {'widthPixels':width, 'heightPixels':height, 'originXPixels':0, 'originYPixels':0}
    inner = dict(outer)
    if changed: inner.update(widthPixels=480, originXPixels=480)
    outer['safeArea'] = inner
    return [outer]

class NativeTests(unittest.TestCase):
    def check(self, path, base, typ, width=1440,height=542,existing=False,wrong=False):
        h = NativeHarness(path,base)
        result,value,display = h.run(width,height,typ,existing,wrong)
        changed = path==CANDIDATE and typ==111 and not wrong and (width,height)==(1440,542)
        self.assertEqual(value,expected(width,height,changed))
        self.assertIn(0x2e268,h.executed_helpers)
        self.assertEqual(h.log_messages, ['NAV_SAFE_V20 x=480 y=0 w=480 h=542'] if changed else [])
        h.cleanup_and_check(result,display)
        return h

    def test_original_geometry_and_two_pic_bases(self):
        for base in BASES:
            for existing in (False,True):
                for typ,width,height in [(0,1024,480),(110,1440,542),(111,1440,542),(None,1440,542)]:
                    with self.subTest(base=hex(base),existing=existing,type=typ):
                        self.check(ORIGINAL,base,typ,width,height,existing)

    @unittest.skipUnless(CANDIDATE.exists(),'candidate not yet ready')
    def test_candidate_geometry_types_entries_and_pic(self):
        for base in BASES:
            for existing in (False,True):
                for typ,width,height,wrong in [(0,1024,480,False),(0,1440,542,False),(110,1440,542,False),
                        (111,1440,542,False),(111,1024,480,False),(111,1440,455,False),
                        (111,1280,542,False),(None,1440,542,False),(111,1440,542,True),
                        ((1<<32)+111,1440,542,False),(-4294967185,1440,542,False)]:
                    with self.subTest(base=hex(base),existing=existing,type=typ,width=width,height=height,wrong=wrong):
                        h=self.check(CANDIDATE,base,typ,width,height,existing,wrong)
                        if (width,height)==(1440,542): self.assertIn(0x275cc,h.executed_helpers)

    @unittest.skipUnless(CANDIDATE.exists(),'candidate not yet ready')
    def test_repeat_existing_display(self):
        for base in BASES:
            h=NativeHarness(CANDIDATE,base)
            result,value,display=h.run()
            self.assertEqual(value,expected(1440,542,True))
            self.assertEqual(h.log_messages,['NAV_SAFE_V20 x=480 y=0 w=480 h=542'])
            h.release(result)
            for index in range(3):
                result,value,display=h.run(existing=True,display=display)
                self.assertEqual(value,expected(1440,542,True))
                self.assertEqual(h.log_messages,['NAV_SAFE_V20 x=480 y=0 w=480 h=542']*(index+2))
                h.release(result)
            h.cleanup_and_check(0,display)

    def test_each_cf_allocation_failure(self):
        paths=[ORIGINAL]+([CANDIDATE] if CANDIDATE.exists() else [])
        for path in paths:
            for base in BASES:
                for existing in (False,True):
                    baseline=NativeHarness(path,base)
                    result,value,display=baseline.run(existing=existing)
                    count=baseline.allocation_count
                    baseline.cleanup_and_check(result,display)
                    for fail in range(1,count+1):
                        with self.subTest(path=path.name,base=hex(base),existing=existing,fail=fail):
                            h=NativeHarness(path,base,fail_allocation=fail)
                            result,value,display=h.run(existing=existing)
                            # Failure in optional type lookup may retain stock geometry;
                            # geometry-building failure must not leave a malformed narrow area.
                            if result:
                                self.assertEqual(value,expected(1440,542,False))
                            self.assertEqual(h.log_messages,[])
                            h.cleanup_and_check(result,display)

    def test_required_cf_pointer_absence_and_optional_type_read(self):
        paths=[ORIGINAL]+([CANDIDATE] if CANDIDATE.exists() else [])
        for path in paths:
            for base in BASES:
                for existing in (False,True):
                    for missing in ('release','array_new','array_append'):
                        with self.subTest(path=path.name,base=hex(base),existing=existing,missing=missing):
                            h=NativeHarness(path,base,absent_cf=missing)
                            result,value,display=h.run(existing=existing)
                            self.assertEqual(result,0)
                            self.assertEqual(h.log_messages,[])
                            if path==ORIGINAL and missing=='release':
                                # Exact observed baseline defect: rect_dict allocates,
                                # detects absent release, cannot clean up its empty dict.
                                self.assertEqual(h.allocation_count,2)
                                h.release(display)
                                live=[o for o in h.objects.values() if o['refs']]
                                self.assertEqual(live,[{'kind':'dict','value':{},'refs':1}]*2)
                                COUNTS['baseline_absent_release_leaks_two_empty_dicts']+=1
                            else:
                                self.assertEqual(h.allocation_count,0)
                                h.cleanup_and_check(result,display)
                    if path==CANDIDATE:
                        for missing in ('dict_get','num_get'):
                            with self.subTest(base=hex(base),existing=existing,missing=missing):
                                h=NativeHarness(path,base,absent_cf=missing)
                                result,value,display=h.run(existing=existing)
                                self.assertEqual(value,expected(1440,542,False))
                                self.assertEqual(h.log_messages,[])
                                h.cleanup_and_check(result,display)

if __name__=='__main__':
    if not CANDIDATE.is_file():
        raise SystemExit('Build the CN overlay first; refusing to skip candidate tests')
    (ROOT/'build/native-evidence').mkdir(parents=True,exist_ok=True)
    started=time.monotonic()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(NativeTests))
    report={'status':'PASS' if result.wasSuccessful() else 'FAIL', 'tests_run':result.testsRun,
            'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
            'elapsed_s':round(time.monotonic()-started,3),'bases':[hex(b) for b in BASES],
            'scope':'Actual ELF ARM and Thumb bytes including original CF helpers, Unicorn with CF adapter stubs; no vehicle or QNX execution',
            'execution_counts':dict(COUNTS),
            'logging':'Only altscreen_log sink is stubbed; captured success text and caller-saved clobber checked',
            'host_jit':'macOS sandbox caused SIGILL even for minimal mov instruction; exact host emulation command succeeded with sandbox escalation',
            'original_sha256':hashlib.sha256(ORIGINAL.read_bytes()).hexdigest(),
            'candidate_sha256':hashlib.sha256(CANDIDATE.read_bytes()).hexdigest() if CANDIDATE.exists() else None,
            'limits':'CF and allocator behavior stubbed, no iPhone/AMap negotiation or UI rendering simulated'}
    report['baseline_limitation']='Original cf_release=NULL path leaks two empty dictionaries; explicitly reproduced at both bases/entries. Candidate instead returns NULL before allocating.'
    (ROOT/'build/native-evidence/safearea-emulation.json').write_text(json.dumps(report,indent=2)+'\n')
    raise SystemExit(not result.wasSuccessful())

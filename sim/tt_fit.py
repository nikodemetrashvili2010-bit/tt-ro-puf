#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Does the chip fit what Tiny Tapeout puts round it.

Read out of Tiny Tapeout's own sources, checked out next to each other:
tt-support-tools (the precheck and the build), tt-multiplexer (what sits
between the pads and a project) and tt-micropython-firmware (the demo
board's SDK). Nothing here is from memory of how they work, every line
of output comes from a file in one of the three, and
docs/phaseG_tt_fit.md has the commits they were read at.

    tt_fit.py --tools DIR --mux DIR --sdk DIR --final DIR [--repo DIR]
    tt_fit.py ... --selftest

--final is run 83's runs/wokwi/final, for the LEF and powered netlist.
--repo defaults to the tree this file sits in.

A line reads ok, open or FAIL. FAIL is a reading that came out wrong or a
source that no longer says what this was written against. open is the
board side, something the bench firmware or the datasheet does not do yet.
"""
import argparse
import json
import os
import re
import sys
import textwrap

TOP = 'tt_um_nikodemetrashvili20_ro_puf'
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    return open(os.path.join(*parts)).read()


def need(pattern, text, what):
    m = re.search(pattern, text, re.S)
    if not m:
        raise AssertionError('not found: ' + what)
    return m


def layout(a):
    """Tiny Tapeout's precheck functions, called as they are."""
    sys.path.insert(0, os.path.join(a.tools, 'precheck'))
    os.environ.setdefault('PDK_ROOT', '/no-pdk-here')
    import gdstk
    import precheck
    from pin_check import parse_def, pin_check
    gds = os.path.join(a.repo, 'dualarm', 'build_armc', TOP + '.gds')
    pnl = os.path.join(a.final, 'pnl', TOP + '.pnl.v')
    tdef = os.path.join(a.tools, 'tech', 'sky130A', 'def',
                        'tt_block_2x2_pg.def')
    pin_check(gds, a.lef, tdef, TOP, False, 'sky130A')
    precheck.power_pin_check(pnl, a.lef, False)
    precheck.cell_name_check(gds)
    precheck.analog_pin_check(gds, 'sky130A', False, False, 0, {})
    # the outline, which their boundary check wants a PDK file for
    die = parse_def(tdef)
    top = gdstk.read_gds(gds).top_level()
    assert len(top) == 1 and top[0].name == TOP
    box = [int(round(v * 1000)) for p in top[0].bounding_box() for v in p]
    assert box == [0, 0, die.die_width, die.die_height], box
    layer = need(r'class Sky130Tech.*?prboundary_layer = \((\d+), (\d+)\)',
                 read(a.tools, 'tech.py'), 'prBoundary layer').groups()
    rects = [p.bounding_box() for p in top[0].polygons
             if (str(p.layer), str(p.datatype)) == layer]
    assert ((0.0, 0.0), (die.die_width / 1000, die.die_height / 1000)
            ) in rects, rects
    return ('pin, power pin, cell name and analog pin checks pass; the '
            'outline is the %d pin 2x2 template\'s, %.2f by %.2f um'
            % (len(die.pins), die.die_width / 1000, die.die_height / 1000))


def config(a):
    """The settings the build writes over a project's own."""
    src = need(r'def create_user_config.*?config = \{(.*?)\n        \}',
               read(a.tools, 'project.py'), 'create_user_config').group(1)
    forced = re.findall(r'"(\w+)":', src)
    assert len(forced) == 7 and 'config.update(user_config)' in read(
        a.tools, 'project.py')
    mine = json.load(open(os.path.join(a.repo, 'src', 'config.json')))
    both = sorted(set(forced) & set(mine))
    assert not both, 'config.json sets %s, the build replaces them' % both
    return ('the build replaces %d settings and config.json sets none of '
            'them, so its other %d stand' % (len(forced), len(
                [k for k in mine if k != '//'])))


def mux(a):
    """What a project that is not selected gets on its pins."""
    rtl = read(a.mux, 'rtl', 'tt_mux.v')
    need(r'tt_prim_zbuf #\([^;]*?zbuf_iw_I\[U_IW-1:0\] \(\s*\.a\s*'
         r'\(bus_iw\),\s*\.e\s*\(l_ena\),\s*\.z\s*\(um_iwa\[i\]\)', rtl,
         'the zeroing buffer on a project\'s inputs')
    need(r'assign \{ uio_in, ui_in, rst_n, clk \} = iw;',
         read(a.mux, 'rtl', 'tt_user_module.v.mak'), 'the input bundle')
    need(r'sky130_fd_sc_hd__and2_2 cell0_I', read(
        a.mux, 'rtl', 'prim_sky130', 'tt_prim_zbuf.v'), 'the AND gate')
    need(r'wire async_project_rst_n = rst_n & ena;',
         read(a.repo, 'src', 'tt_um_ro_puf.v'), 'the chip\'s reset')
    return ('clk, rst_n, ui_in and uio_in all go through one AND with the '
            'select, so a project not selected has rst_n at 0, and the '
            'chip resets on rst_n & ena')


def power(a):
    """The power switch every project sits behind."""
    placer = read(a.mux, 'py', 'tt', 'placer.py')
    need(r"self\.pg_vdd = cfg_data\.get\('pg_vdd', True\)", placer,
         'gated unless told otherwise')
    need(r"self\.pg_vdd = 'hp' if self\.width > 4 else 'll'", placer,
         'which switch')
    need(r'zbuf_pg_ena_I \(\s*\.a\s*\(l_ena\),\s*\.z\s*\(um_pg_ena\[i\]\)',
         read(a.mux, 'rtl', 'tt_mux.v'), 'the switch\'s control')
    need(r'if self\.config\.get\("no_power_gating", False\):',
         read(a.tools, 'shuttle.py'), 'the one way to turn it off')
    sch = read(a.mux, 'pg', 'sky130', 'tt_pg_1v8_ll_2', 'xschem',
               'tt_pg_1v8_ll_2.sch')
    fets = re.findall(r'C \{sky130_fd_pr/(\w+)\.sym\}[^{]*\{name=(\w+)\n'
                      r'(?:(?!W=)[^\n]*\n)*W=([\d.]+)\n'
                      r'(?:(?!nf=)[^\n]*\n)*nf=(\d+)', sch)
    big = max(fets, key=lambda f: float(f[2]))
    said = [len(re.findall(r'(?i)power.gat|tt_pg_|pg_ena', read(a.repo, f)))
            for f in ('README.md', 'docs/info.md', 'SIGNOFF.md')]
    ms = int(need(r'def _first_encouter_reset.*?reset_project\(True\)\s+'
                  r'time\.sleep_ms\((\d+)\)',
                  read(a.sdk, 'src', 'ttboard', 'demoboard.py'),
                  'the reset on a first enable').group(1))
    text = ('a 2 wide, 2 high project gets tt_pg_1v8_ll_2, switched by '
            'the same select as ena: one %s, %s um wide in %s fingers, and '
            'the SDK holds reset %d ms on its first enable. The README, the '
            'datasheet and SIGNOFF mention it %d, %d and %d times'
            % ((big[0], big[2], big[3], ms) + tuple(said)))
    if not said[1]:
        return 'open', text + ', and the datasheet is the one that ships'
    if not re.search(r'pulses\s+reset\s+for\s+%d\s+ms' % ms,
                     read(a.repo, 'docs', 'info.md')):
        return 'open', text + ', but not the SDK\'s %d ms' % ms
    return text


def clock(a, hz=None):
    """The clock the demo board really makes for what the script asks."""
    fw = read(a.repo, 'firmware', 'measure_puf.py')
    hz = hz or int(need(r'CLK_HZ\s*=\s*([\d_]+)', fw, 'CLK_HZ').group(1))
    info = int(need(r'clock_hz:\s*(\d+)', read(a.repo, 'info.yaml'),
                    'clock_hz').group(1))
    sdk = read(a.sdk, 'src', 'ttboard', 'demoboard.py')
    need(r'tt\.clock_project_PWM\(CLK_HZ\)', fw, 'the call')
    body = need(r'\n(    def _get_best_rp2040_freq.*?return best_freq\n)',
                sdk, 'the SDK\'s search for a system clock').group(1)
    need(r'def auto_clocking_freq\(self\)', sdk, 'what the SDK achieved')
    space = {}
    exec(textwrap.dedent(body), space)
    quiet, sys.stdout = sys.stdout, open(os.devnull, 'w')
    try:
        rp = space['_get_best_rp2040_freq'](None, hz, 133_000_000)
    finally:
        sys.stdout = quiet
    assert rp % hz == 0 and (rp // hz) % 2 == 0, (
        '%d Hz is not a whole even division of the %d Hz the SDK picks'
        % (hz, rp))
    assert hz == info, 'info.yaml says %d' % info
    text = ('for %d Hz the SDK sets the RP2 to %d Hz and divides by %d, '
            'exact and half up, half down; info.yaml asks the same'
            % (hz, rp, rp // hz))
    if 'auto_clocking_freq' not in fw:
        return 'open', text + ('; measure_puf.py does not write down the '
                               'clock the SDK says it made')
    return text + '; measure_puf.py writes down the clock the SDK made'


def calls(a, mask=None):
    """The SDK names the script uses, and who drives which uio pin."""
    fw = read(a.repo, 'firmware', 'measure_puf.py')
    sdk = read(a.sdk, 'src', 'ttboard', 'demoboard.py')
    used = sorted(set(re.findall(r'\btt\.(\w+)', fw)))
    lost = [n for n in used if not re.search(
        r"def %s\(|'%s'" % (n, n), sdk) and n != 'shuttle']
    assert not lost and 'self.shuttle =' in sdk, lost
    mask = mask or int(need(r'tt\.uio_oe_pico\.value = (0b[01_]+)', fw,
                            'the direction mask').group(1), 2)
    chip = int(need(r"assign uio_oe\s*=\s*8'h([0-9a-fA-F]+);", read(
        a.repo, 'src', 'tt_um_ro_puf.v'), 'uio_oe').group(1), 16)
    assert mask & chip == 0, 'both sides drive uio bits %s' % bin(mask & chip)
    idle = [i for i in range(8) if not (mask | chip) >> i & 1]
    mux = read(a.sdk, 'src', 'ttboard', 'project_mux.py')
    need(r'if design\.danger_level != DangerLevel\.SAFE:\s+if not force:'
         r'.*?return False', mux, 'the refusal to enable')
    forced = 'enable(force' in fw or 'force=True' in fw
    ignored = re.search(r'(?m)^[ \t]*[\w.]+\.enable\([^)]*\)[ \t]*(#.*)?$',
                        fw)
    text = ('all %d names exist in the SDK; the board drives uio %s, the '
            'chip %s%s; enable() refuses a project not marked safe and the '
            'script %s'
            % (len(used), [i for i in range(8) if mask >> i & 1],
               [i for i in range(8) if chip >> i & 1],
               ', nobody drives %s' % idle if idle else '',
               'forces it' if forced else 'does not force it'))
    gaps = []
    if ignored:
        gaps.append('ignores what it returns')
    if idle:
        gaps.append('leaves uio %s to float' % idle)
    if gaps:
        return 'open', text + ', ' + ' and '.join(gaps)
    return text + ', and stops if it refuses'


def switches(a):
    """Does the board really drive the eight inputs."""
    pins = read(a.sdk, 'src', 'ttboard', 'pins', 'pins.py')
    need(r"if pname\.startswith\('ui_in'\):\s+p = getattr\(self, pname\)\s+"
         r"if self\.dieOnInputControlSwitchHigh:\s+if p\(\):.*?continue\s+"
         r"p\.mode = Pin\.OUT", pins, 'the rule for an input held high')
    need(r'\nmode = ASIC_RP_CONTROL\n', read(a.sdk, 'src', 'config.ini'),
         'the mode the SDK ships with')
    fw = read(a.repo, 'firmware', 'measure_puf.py')
    looks = re.search(r'tt\.ui_in\.value\s*(\)|!=|==)|tt\.mode\b', fw)
    text = ('the SDK leaves any ui_in pin that reads high at start-up as '
            'an input, which is what a DIP switch left on does, and only '
            'logs it; measure_puf.py ')
    if looks:
        return text + 'reads its inputs back'
    return 'open', text + ('never reads ui_in back or sets the mode, so '
                           'such a pin would move the selection unseen')


CHECKS = (layout, config, mux, power, clock, calls, switches)

# Every file of this tree a check reads. A planted fault copies the tree
# through links and rewrites one of them.
READS = ('dualarm/build_armc/%s.gds' % TOP, 'src/config.json',
         'src/tt_um_ro_puf.v', 'README.md', 'docs/info.md', 'SIGNOFF.md',
         'firmware/measure_puf.py', 'info.yaml')


def run_all(a):
    """Every check, as (status, name). FAIL for an assertion."""
    out = []
    for fn in CHECKS:
        try:
            got = fn(a)
            got = got if isinstance(got, tuple) else ('ok', got)
            out.append((got[0], fn.__name__, got[1]))
        except AssertionError as e:
            out.append(('FAIL', fn.__name__, str(e)))
    return out


def selftest(a):
    """Each of these breaks one thing and its check has to say so."""
    import tempfile
    bad = 0
    cases = 0

    def expect(name, fn, *args):
        nonlocal bad, cases
        cases += 1
        try:
            fn(*args)
            print('MISSED  ' + name)
            bad += 1
        except Exception as e:
            print('caught  %s: %s %s' % (name, type(e).__name__,
                                         str(e)[:60]))

    def expect_only(name, tmp, path, old, new, check):
        """One file of the tree changed, and only `check` may notice."""
        nonlocal bad, cases
        cases += 1
        root = os.path.join(tmp, 'repo_%d' % cases)
        for rel in READS:
            os.makedirs(os.path.dirname(os.path.join(root, rel)),
                        exist_ok=True)
            if rel != path:
                os.symlink(os.path.join(a.repo, rel), os.path.join(root, rel))
        text = read(a.repo, path)
        if text.count(old) < 1:
            print('MISSED  %s: the fault does not apply, %r not in %s'
                  % (name, old, path))
            bad += 1
            return
        open(os.path.join(root, path), 'w').write(text.replace(old, new))
        b = argparse.Namespace(**vars(a))
        b.repo = root
        noticed = [r for r in run_all(b) if r[0] != 'ok']
        if [r[1] for r in noticed] == [check]:
            print('caught  %s: %s %s' % (name, noticed[0][0],
                                         noticed[0][2][-60:]))
        else:
            print('MISSED  %s: %s' % (name, [r[:2] for r in noticed]))
            bad += 1

    with tempfile.TemporaryDirectory() as tmp:
        lef = read(a.lef)
        m = need(r'(PIN ui_in\[0\].*?RECT )(\S+) (\S+) (\S+)', lef,
                 'a pin')
        moved = os.path.join(tmp, 'moved.lef')
        open(moved, 'w').write(lef.replace(m.group(0), '%s%.3f %s %.3f' % (
            m.group(1), float(m.group(2)) + 0.46, m.group(3),
            float(m.group(4)) + 0.46), 1))
        b = argparse.Namespace(**vars(a))
        b.lef = moved
        expect('a pin moved one track along', layout, b)
        b = argparse.Namespace(**vars(a))
        b.mux = os.path.join(tmp, 'mux')
        for sub in ('rtl/prim_sky130', 'py/tt', 'pg/sky130/'
                    'tt_pg_1v8_ll_2/xschem'):
            os.makedirs(os.path.join(b.mux, sub))
            for f in os.listdir(os.path.join(a.mux, sub)):
                if os.path.isfile(os.path.join(a.mux, sub, f)):
                    open(os.path.join(b.mux, sub, f), 'w').write(
                        read(a.mux, sub, f))
        for f in ('tt_mux.v', 'tt_user_module.v.mak'):
            open(os.path.join(b.mux, 'rtl', f), 'w').write(
                read(a.mux, 'rtl', f).replace('(l_ena)', "(1'b1)"))
        expect('inputs not zeroed', mux, b)
        expect('power switch not on the select', power, b)
        expect('a clock the board cannot divide to', clock, a, 45678901)
        expect('board and chip on one uio pin', calls, a, 0b00011110)
        # The board side, each against the whole set of checks.
        expect_only('the datasheet loses the switch', tmp, 'docs/info.md',
                    'tt_pg_1v8_ll_2', 'its power switch', 'power')
        expect_only('the datasheet gets the SDK\'s reset wrong', tmp,
                    'docs/info.md', 'pulses reset for 2 ms',
                    'pulses reset for 5 ms', 'power')
        expect_only('the clock the SDK made not written down', tmp,
                    'firmware/measure_puf.py', 'auto_clocking_freq',
                    'auto_clocking_hz', 'clock')
        expect_only('what enable() returns ignored', tmp,
                    'firmware/measure_puf.py', 'if proj.enable() is False:',
                    'proj.enable()\n    if False:', 'calls')
        expect_only('uio 6 and 7 left floating', tmp,
                    'firmware/measure_puf.py', '0b1100_1110', '0b0000_1110',
                    'calls')
        expect_only('ui_in no longer read back', tmp,
                    'firmware/measure_puf.py', 'int(tt.ui_in.value)', 'v',
                    'switches')
    print('FAIL: %d of %d missed' % (bad, cases) if bad else
          'all %d caught' % cases)
    return bad


def main():
    ap = argparse.ArgumentParser()
    for name in ('tools', 'mux', 'sdk', 'final'):
        ap.add_argument('--' + name, required=True)
    ap.add_argument('--repo', default=HERE)
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    a.lef = os.path.join(a.final, 'lef', TOP + '.lef')
    if a.selftest:
        sys.exit(selftest(a))
    bad = 0
    for status, name, text in run_all(a):
        bad += status == 'FAIL'
        print('%-5s %-8s %s' % (status, name, text))
    sys.exit(bad)


if __name__ == '__main__':
    main()

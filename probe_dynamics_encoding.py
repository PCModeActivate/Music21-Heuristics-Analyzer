#!/usr/bin/env python
"""
probe_dynamics_encoding.py — READ-ONLY diagnostic.

Inventories how dynamic-direction markings are encoded in a score after
music21 parsing, per part:

  1. Hairpin spanners (dynamics.Crescendo / Diminuendo) — what the
     pipeline currently sees.
  2. dynamics.Dynamic point markings, split into standard letter
     dynamics (f, p, mf, ...) vs non-standard values (e.g. 'cresc',
     'dim', 'decresc' entered as dynamic text).
  3. expressions.TextExpression elements whose text matches dynamic-
     direction words (cresc/dim/decresc/dimin), with offsets.
  4. Any other spanner classes present (to catch dashed-line 'cresc.'
     exports that come through as Line/other spanners with text).

Usage:
  python probe_dynamics_encoding.py liz.mxl
"""

import sys
import re
import music21 as m21

DYN_TEXT_RE = re.compile(r'\b(cresc|decresc|dimin|dim)\.?', re.IGNORECASE)
STANDARD_DYNAMICS = {
    'ppp', 'pp', 'p', 'mp', 'mf', 'f', 'ff', 'fff',
    'fp', 'sf', 'sfz', 'sffz', 'fz', 'rf', 'rfz', 'sfp',
}


def hierarchy_offset(el, part):
    try:
        return float(el.getOffsetInHierarchy(part))
    except Exception:
        return float(el.offset)


def measure_of(offset_qn):
    # Liz convention: 4/4, qn = (measure-1)*4
    return int(offset_qn // 4) + 1


def main(path):
    score = m21.converter.parse(path)
    parts = list(score.parts)

    for idx, part in enumerate(parts):
        name = part.partName or f'part{idx}'
        print(f'\n=== Part {idx}: {name} ===')

        # 1. Hairpin spanners (what the pipeline currently sees)
        n_wedges = 0
        for cls in (m21.dynamics.Crescendo, m21.dynamics.Diminuendo):
            for sp in part.recurse().getElementsByClass(cls):
                n_wedges += 1
                spanned = sp.getSpannedElements()
                if spanned:
                    so = hierarchy_offset(spanned[0], part)
                    eo = hierarchy_offset(spanned[-1], part)
                    print(f'  WEDGE {cls.__name__}: qn {so:.2f}-{eo:.2f} '
                          f'(mm.{measure_of(so)}-{measure_of(eo)}, '
                          f'{len(spanned)} spanned)')
                else:
                    print(f'  WEDGE {cls.__name__}: 0 spanned elements '
                          f'(!!! would be skipped by pipeline)')
        if n_wedges == 0:
            print('  (no Crescendo/Diminuendo wedge spanners)')

        # 2. Dynamic point markings: standard vs non-standard values
        nonstandard = []
        n_standard = 0
        for dyn in part.recurse().getElementsByClass(m21.dynamics.Dynamic):
            val = (dyn.value or '').strip().lower()
            if val in STANDARD_DYNAMICS:
                n_standard += 1
            else:
                off = hierarchy_offset(dyn, part)
                nonstandard.append((off, dyn.value))
        print(f'  Dynamic (standard letters): {n_standard}')
        for off, val in nonstandard:
            print(f'  Dynamic NON-STANDARD value={val!r}: qn {off:.2f} '
                  f'(m.{measure_of(off)})  <-- currently boosted as a '
                  f'generic dynamic event, semantics wrong for text cresc')

        # 3. TextExpressions with dynamic-direction words
        found_text = False
        for te in part.recurse().getElementsByClass(
                m21.expressions.TextExpression):
            content = (te.content or '').strip()
            if DYN_TEXT_RE.search(content):
                found_text = True
                off = hierarchy_offset(te, part)
                print(f'  TEXT {content!r}: qn {off:.2f} '
                      f'(m.{measure_of(off)})  <-- INVISIBLE to pipeline')
        if not found_text:
            print('  (no cresc/dim/decresc TextExpressions)')

        # 4. Other spanner classes (dashed-line exports, etc.)
        seen = {}
        for sp in part.recurse().getElementsByClass(m21.spanner.Spanner):
            cname = type(sp).__name__
            if cname in ('Crescendo', 'Diminuendo', 'Slur'):
                continue
            seen.setdefault(cname, 0)
            seen[cname] += 1
        for cname, count in sorted(seen.items()):
            print(f'  OTHER SPANNER {cname}: {count}  '
                  f'(check if any carry cresc./dim. text)')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1])

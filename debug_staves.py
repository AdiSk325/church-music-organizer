"""Extract raw per-staff OMR data for report."""
from music21 import converter

for i in range(4):
    path = f'data/processed/psalm_adwent_staff_{i}.musicxml'
    try:
        s = converter.parse(path)
        parts = s.parts
        print(f'=== Staff {i} ({path}) ===')
        print(f'  Parts: {len(parts)}')
        for pi, p in enumerate(parts):
            ms = list(p.getElementsByClass('Measure'))
            ks = p.keySignature
            print(f'  Part {pi}: {p.partName}, key={ks}, measures={len(ms)}')
            for j, m in enumerate(ms):
                ts = m.timeSignature
                mks = m.keySignature
                notes = list(m.flatten().notes)
                rests = list(m.flatten().getElementsByClass('Rest'))
                beat_sum = sum(n.quarterLength for n in notes)
                rest_sum = sum(r.quarterLength for r in rests)
                ts_str = f', ts={ts}' if ts else ''
                ks_str = f', ks={mks}' if mks else ''
                print(f'    M{j+1}: {len(notes)}n {len(rests)}r note_beats={beat_sum:.2f} rest_beats={rest_sum:.2f}{ts_str}{ks_str}')
                for n in notes:
                    if hasattr(n, 'pitch'):
                        print(f'      {n.pitch}({n.quarterLength}q)')
                    elif hasattr(n, 'pitches'):
                        ps = '+'.join(str(pp) for pp in n.pitches)
                        print(f'      [{ps}]({n.quarterLength}q)')
    except Exception as e:
        print(f'Staff {i}: ERROR {e}')
        import traceback
        traceback.print_exc()

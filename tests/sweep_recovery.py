"""Run process cuts at every remote mutation; preserve the outcomes as JSON."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_recovery import Unit, CutPower, r, selected


def trial(mode, cut=None):
    with Unit().use() as unit:
        p=selected()
        if mode in ('reconfigure','rollback'):
            unit.install(p)
        elif mode=='preflight':
            r.run('install-disabled',p);r.run('observe-disabled',p)
        expected = r.read_images(unit.connect()) if mode=='reconfigure' else {
            'carrier':unit.stock.hex(),'ui':None,'options':None,'receipt':None}
        start=len(unit.events)
        events=[]
        def stop(kind,path):
            events.append((kind,path))
            if len(events)==cut: raise CutPower()
        unit.hook=stop
        action={'rollback':'rollback','preflight':'preflight'}.get(mode,'install-disabled')
        try:
            r.run(action,p)
        except CutPower:
            pass
        if cut is None:return events
        unit.hook=None
        try:
            unit.rollback(p)
            if r.read_images(unit.connect()) != expected:
                raise AssertionError('Recovery restored the wrong file generation')
            error=None
        except Exception as problem:
            error=type(problem).__name__+': '+str(problem)
        return {'mode':mode,'cut':cut,'event':events[-1], 'error':error,
                'carrier':'stock' if unit.files[r.device.ACTIVE]==unit.stock else 'configured'}


if __name__=='__main__':
    rows=[]
    for mode in ('first-install','reconfigure','preflight','rollback'):
        for cut in range(1,len(trial(mode))+1): rows.append(trial(mode,cut))
    target=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).with_name('sweep-results.json')
    target.write_text(json.dumps(rows,indent=2)+'\n')
    failures=[row for row in rows if row['error']]
    print(json.dumps({'cases':len(rows),'errors':len(failures),'failures':failures},indent=2))
    raise SystemExit(bool(failures))

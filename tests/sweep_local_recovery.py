"""Interrupt after each durable local write, then recover from the same folder."""
import json
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_recovery import Unit,CutPower,r,selected


def trial(mode,cut=None):
    with Unit().use() as unit:
        p=selected()
        if mode in ('reconfigure','rollback'):unit.install(p)
        expected=r.read_images(unit.connect()) if mode=='reconfigure' else {'carrier':unit.stock.hex(),'ui':None,'options':None,'receipt':None}
        events=[];write=r.durable.write_bytes
        def write_then_stop(path,data):
            write(path,data)
            if Path(path).name=='report.json':return
            events.append(Path(path).name)
            if len(events)==cut:raise CutPower()
        with patch.object(r.durable,'write_bytes',write_then_stop):
            try:r.run('rollback' if mode=='rollback' else 'install-disabled',p)
            except CutPower:pass
        if cut is None:return events
        try:
            unit.rollback()
            if r.read_images(unit.connect())!=expected:raise AssertionError('Wrong restored generation')
            error=None
        except Exception as problem:error=type(problem).__name__+': '+str(problem)
        return {'mode':mode,'cut':cut,'file':events[-1],'error':error}


if __name__=='__main__':
    rows=[]
    for mode in ('first-install','reconfigure','rollback'):
        for cut in range(1,len(trial(mode))+1):rows.append(trial(mode,cut))
    target=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).with_name('local-sweep-results.json')
    target.write_text(json.dumps(rows,indent=2)+'\n')
    errors=[row for row in rows if row['error']]
    print(json.dumps({'cases':len(rows),'errors':len(errors),'failures':errors},indent=2))
    raise SystemExit(bool(errors))

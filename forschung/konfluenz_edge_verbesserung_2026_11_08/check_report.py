from pathlib import Path
import json,hashlib,subprocess,sys,re,html
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'artifacts'/'edge_verbesserung_2026_11_08'
checks=[]
def check(name,value):
    checks.append(dict(name=name,ok=bool(value)))
    if not value:raise AssertionError(name)

s=json.loads((OUT/'summary.json').read_text());frozen=(OUT/'frozen_selection.json').read_text(encoding='utf8').encode('utf8')
f=json.loads(frozen)
check('frozen selection canonical UTF8/LF SHA256 intact',hashlib.sha256(frozen).hexdigest()==(OUT/'frozen_selection.sha256').read_text().strip())
check('training choice not replaced',s['chosen']==f['chosen']==max(f['training'],key=lambda v:f['training'][v]['ci'][0]))
for v,r in s['results'].items():
    t=pd.read_csv(OUT/f'{v}_trades.csv');ledger=pd.read_csv(OUT/f'{v}_account_trades.csv')
    check(v+' finite net R',np.isfinite(t.net_r).all())
    check(v+' headline agrees with trades',len(t)==r['comparison']['n'] and abs(t.net_r.mean()-r['comparison']['expectancy_r'])<1e-12)
    check(v+' correct trade geometry',(((t.tp-t.entry)*(t.entry-t.sl)>0)&(t.risk>0)).all())
    check(v+' closed no later than cutoff',(pd.to_datetime(t.known_at,utc=True)<=pd.Timestamp(s['end'])).all())
    check(v+' account count agrees',len(ledger)==r['account']['closed'])
    events=[]
    for row in ledger.itertuples():
        events.extend([(pd.Timestamp(row.entry_ts),1,row.coin),(pd.Timestamp(row.known_at),-1,row.coin)])
    live=set()
    for ts,action,coin in sorted(events):
        if action==-1:live.remove(coin)
        else:
            if coin in live:raise AssertionError('overlapping '+coin)
            live.add(coin)
            if len(live)>9:raise AssertionError('position cap')
    checks.append(dict(name=v+' same-coin and nine-position limits',ok=True))

js=r'''<script>setTimeout(async()=>{let checks=[];const ok=(name,value)=>{checks.push({name,ok:!!value});if(!value)throw Error(name)};const wait=()=>new Promise(r=>setTimeout(r,200));try{
ok('report initialized',document.body.dataset.ready==='true');
ok('all eighteen variants',document.getElementById('variant').options.length===18);
ok('all result rows',document.querySelectorAll('#results tr').length===19);
ok('frozen selection initially displayed',document.body.dataset.variant===C);
for(const id of ['equity','frontier','rolling','monthly','coins'])ok(id+' has traces',document.getElementById(id).data.length>0);
document.getElementById('atr').click();await wait();
ok('ATR comparison actually selected',document.body.dataset.variant==='L_A2_K');
ok('two equity traces',document.getElementById('equity').data.length===2);
ok('ATR trade count',document.querySelectorAll('#trades tr').length===267);
const points=document.getElementById('frontier').data;
ok('clouds use actual simulated values',points.length===5&&Math.abs(points[4].y[0]-126/266)<1e-12&&Math.abs(points[4].x[0]-1.6939445662981987)<1e-12);
ok('ATR detail page linked',document.querySelector('a[href="dynamisch_L_A2_K.html"]')!==null);
document.getElementById('variant').value='C_A2_R15';document.getElementById('variant').dispatchEvent(new Event('change'));await wait();
ok('other variant works',document.body.dataset.variant==='C_A2_R15');
document.getElementById('reset').click();await wait();ok('reset returns to frozen choice',document.body.dataset.variant===C);
const pre=document.createElement('pre');pre.id='qa-result';pre.textContent=JSON.stringify({passed:true,checks});document.body.append(pre);
}catch(e){const pre=document.createElement('pre');pre.id='qa-result';pre.textContent=JSON.stringify({passed:false,error:String(e),checks});document.body.append(pre)}},2500)</script>'''
qa=OUT/'browser_check.html';qa.write_text((OUT/'VERGLEICH.html').read_text(encoding='utf8').replace('</html>',js+'</html>'),encoding='utf8')
edge=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
with (OUT/'browser_dom.html').open('w',encoding='utf8') as stdout,(OUT/'browser.log').open('w',encoding='utf8') as stderr:
    subprocess.run([edge,'--headless','--disable-gpu','--no-sandbox','--no-first-run',
        '--user-data-dir='+str(OUT/'qa_profile'),'--virtual-time-budget=12000','--dump-dom',qa.as_uri()],
        stdout=stdout,stderr=stderr,timeout=60,creationflags=0x08000000)
dom=(OUT/'browser_dom.html').read_text(encoding='utf8')
m=re.search(r'<pre id="qa-result">(.*?)</pre>',dom,re.S)
browser=json.loads(html.unescape(m[1])) if m else dict(passed=False,error='No QA result')
result=dict(passed=all(c['ok'] for c in checks) and browser['passed'],data_checks=checks,browser=browser)
(OUT/'validation.json').write_text(json.dumps(result,indent=2),encoding='utf8')
print(json.dumps(dict(passed=result['passed'],data_checks=len(checks),browser=browser),indent=2))
if not result['passed']:sys.exit(1)

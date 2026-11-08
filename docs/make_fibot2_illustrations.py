"""Reproduzierbare SVG-Schemata fuer die fibot-2.0-README, ohne Marktdaten."""
from pathlib import Path
from html import escape

OUT = Path(__file__).resolve().parent / 'img'
C = {'ink':'#162337','muted':'#54647a','blue':'#2464c7','green':'#14745a',
     'red':'#b44448','line':'#dce4ed','soft':'#f3f6fa','amber':'#936012'}

def text(x,y,value,size=16,color='ink',weight=400):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{C.get(color,color)}" font-weight="{weight}">{escape(str(value))}</text>'

def lines(x,y,values,size=16,color='muted',gap=25):
    return ''.join(text(x,y+i*gap,s,size,color) for i,s in enumerate(values))

def box(x,y,w,h,fill='#ffffff',stroke=None):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{fill}" stroke="{stroke or C["line"]}"/>'

def arrow(x1,y1,x2,y2):
    return f'<path d="M {x1} {y1} L {x2} {y2}" fill="none" stroke="{C["blue"]}" stroke-width="2.5" marker-end="url(#arrow)"/>'

def frame(title,subtitle,body,height=560):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="{height}" viewBox="0 0 1120 {height}" '
        'font-family="Segoe UI, Helvetica, Arial, sans-serif" role="img">'
        f'<title>{escape(title)}</title><desc>{escape(subtitle)}</desc>'
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">'
        '<path d="M0,0 L8,4 L0,8" fill="#2464c7"/></marker></defs>'
        +box(1,1,1118,height-2)+text(32,44,title,26,weight=700)
        +text(32,73,subtitle,16)+body+text(32,height-22,'fibot 2.0 · Schematische Darstellung · Stand 08.11.2026',12,'muted')+'</svg>')

def decision():
    body=''
    cards=[('01','Konfluenz',('Bestätigter Impuls A → B','Kanallinie in Fibo-Zone','SL und TP aus der Struktur')),
           ('02','Mindest-Stop',('Abstand Limit → SL','mindestens 2 × ATR14','Zu eng? Setup verwerfen.')),
           ('03','Phasentor',('Eigener Zustand je Timeframe','14 Tage · mindestens 15 Trades','Mittleres virtuelles net_R > 0'))]
    for i,(number,title,copy) in enumerate(cards):
        x=32+i*362
        body+=box(x,109,332,176,C['soft'])+text(x+20,143,number,15,'blue',700)+text(x+20,174,title,22,weight=700)
        body+=lines(x+20,208,copy,15,gap=24)
        if i<2:body+=arrow(x+335,194,x+357,194)
    body+=box(32,322,1056,137,'#edf5ff')+text(54,357,'04  Gemeinsame Kontoprüfung → Limit mit angehängtem SL und TP',21,'blue',700)
    body+=lines(54,390,['Coin frei · Impuls noch nicht verbraucht · Menge über Börsenminimum',
                        'Offene Positionen + wartende Orders passen in das Nominalbudget.'],16)
    body+=arrow(920,288,920,315)
    body+=text(32,502,'Jede Bedingung muss erfüllt sein. Ohne Freigabe entsteht keine neue Order.',17,'red',600)
    return frame('Vom Chart-Setup zur erlaubten Order','Fibonacci und Kanal bleiben die Grundlage; zwei Filter und ein Kontobudget ergänzen sie.',body)

def gate():
    body=box(32,110,650,306,C['soft'])+text(54,145,'Virtuelle Trades des gleichen Timeframes',21,weight=700)
    body+=text(54,172,'Beide Richtungen · Configs gemeinsam · nur abgeschlossene Ereignisse',14)
    vals=[-.7,.9,-1,1.4,-.8,1.7,-1,1.2,-.6,1.5,-1,1.1,.8,-.7,1.4]
    baseline=278
    body+=f'<line x1="55" y1="{baseline}" x2="655" y2="{baseline}" stroke="{C["line"]}"/>'
    for i,v in enumerate(vals):
        x=60+i*39;h=abs(v)*38
        body+=f'<rect x="{x}" y="{baseline-h if v>0 else baseline}" width="22" height="{h}" rx="3" fill="{C["green"] if v>0 else C["red"]}"/>'
    body+=text(55,355,'Beispielwerte, keine historischen Ergebnisse',13)
    body+=text(55,389,'← Ausstiege im zurückliegenden 14-Tage-Fenster →',16,'blue',600)
    body+=arrow(691,255,719,255)
    body+=box(734,110,354,144,'#eaf6f0')+text(754,145,'Tor offen',24,'green',700)
    body+=lines(754,179,['Mindestens 15 gültige Ereignisse','und mittleres net_R > 0','→ Neue Setups dürfen weiterprüfen.'],15)
    body+=box(734,274,354,142,'#fff1f0')+text(754,309,'Tor geschlossen',24,'red',700)
    body+=lines(754,343,['Zu wenige Ereignisse','oder mittleres net_R ≤ 0','→ Keine neue Order auf diesem TF.'],15)
    body+=text(32,462,'Auch bei geschlossenem Tor laufen die virtuellen Beobachtungen weiter.',18,'blue',600)
    body+=text(32,494,'Das Tor misst die jüngste Vergangenheit. Es garantiert keine künftigen Gewinne.',16)
    return frame('Phasentor: handeln, wenn die jüngste virtuelle Bilanz trägt','Separate Freigabe für 15m, 30m, 1h, 2h, 4h, 6h und 1d.',body)

def account():
    body=box(32,110,510,208,C['soft'])+text(54,149,'Risiko je Einstieg',23,weight=700)
    body+=text(54,193,'0,7 % der Equity',31,'blue',700)
    body+=lines(54,229,['Preisrisiko bis zum geplanten Stop.','Gebühren, Funding und Stop-Ausführung','können den tatsächlichen Verlust erhöhen.'],16)
    body+=box(564,110,524,208,C['soft'])+text(586,149,'Gemeinsames Nominalbudget',23,weight=700)
    body+=text(586,193,'höchstens 10 × Equity',29,'blue',700)
    body+=lines(586,229,['Offene Positionen + wartende Entry-Orders.','Gemeinsame Grenze über alle Timeframes.','Kein zusätzlicher fester Positionszähler.'],16)
    body+=box(32,344,1056,153,'#edf5ff')+text(54,379,'Ein Coin, ein belegter Platz',23,'blue',700)
    body+=lines(54,414,['Mehrere Configs können denselben Coin beobachten. Eine Position oder wartende Order sperrt weitere Entries.',
                       'Bei Konkurrenz kommen höhere Timeframes zuerst. Ein erkannter Fill verbraucht seinen Impuls B persistent.',
                       'Positionswert = Equity × 0,007 / relativer Stop-Abstand'],16,gap=27)
    return frame('Ein Konto statt konkurrierender Einzelstrategien','Risiko, wartende Orders und offene Positionen werden gemeinsam betrachtet.',body)

def main():
    OUT.mkdir(exist_ok=True)
    for name,fn in [('fibot2_entscheidung.svg',decision),('fibot2_phasentor.svg',gate),('fibot2_konto.svg',account)]:
        (OUT/name).write_text(fn(),encoding='utf8')
        print(name)

if __name__=='__main__':main()

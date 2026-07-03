"""BIGGER held-out exam: 10 fresh pages never tuned on (read by Claude vision).
Scores the champion once, no tuning. Reports per-page misses for inspection."""
import sys, os, json
sys.stdout.reconfigure(encoding="utf-8"); sys.path.insert(0, os.path.dirname(__file__))
from common import ocr
from parse import parse
from reconcile import reconcile
from eval import match, _provenance_ok, _bucket
try:
    from tess_check import recover_fppca as _tess
except Exception:
    def _tess(*a, **k): return False

def M(dn=0,dp=0,en=0,ex=0,ed=0,fp=0,tc=0,ti=0,st=0,cu=1406.0,tot=0,lg=0,nb=0,ap=0,ac=0,npay=0,**extra):
    d={"demand_normal":dn,"demand_penal":dp,"energy_charges":en,"excess_energy":ex,"elec_duty":ed,
       "fppca":fp,"tod_charges":tc,"tod_incentive":ti,"sub_total":st,"customer_charges":cu,"total":tot,
       "loss_gain":lg,"net_bill":nb,"arrears_prev":ap,"arrears_curr":ac,"net_payable":npay}
    d.update(extra); return d

GT = {
 12:{"money":M(76000,0,212463.45,0,25155,19415.21,6380,0,339413.66,1406,340819.66,0.34,340820,0,-373.97,340446),
   "consumption":{"cons_kwh":25155,"cons_kvah":27773,"cons_kva":74.3130,"cons_pf":0.91,"cons_lf":18},
   "dates":{"bill_month":"01/2024","bill_date":"04-02-2024","due_date":"18-Feb-2024"},
   "ids":{"service_no":"VSP1718","van_id":"APEPDC0100004656","category":"IIA(i)","contracted_md":200},"amount_words_value":340446},
 20:{"money":M(13416.75,0,306187,0,2479.08,39602.87,0,0,361685.70,1406,363091.70,0.30,363092,0,-374,362718),
   "consumption":{"cons_kwh":41318,"cons_kvah":43741,"cons_kva":178.8900,"cons_pf":0.94,"cons_lf":None},
   "dates":{"bill_month":"02/2024","bill_date":"02-03-2024","due_date":"16-Mar-2024"},
   "ids":{"service_no":"VSP127","van_id":"APEPDC0100000334","category":"IB","contracted_md":200},"amount_words_value":362718},
 30:{"money":M(677112.50,0,4010130,0,509500,190960,100200,0,5487902.50,1406,5489308.50,0.50,5489309,0,-5185,5484124),
   "consumption":{"cons_kwh":509500,"cons_kvah":524200,"cons_kva":1425.5000,"cons_pf":0.97,"cons_lf":46},
   "dates":{"bill_month":"03/2024","bill_date":"02-04-2024","due_date":"16-Apr-2024"},
   "ids":{"service_no":"VSP007","van_id":"APEPDC0100000626","category":"IIA(i)","contracted_md":1500},"amount_words_value":5484124},
 52:{"money":M(32300,0,54324.90,0,7281,3646.80,1315.50,-4922.25,93945.95,1406,96883.30,-0.30,81884,0,-102,81782,
       late_payment=1460.27,interest_ed=71.08,neticd=-14999),
   "consumption":{"cons_kwh":7281,"cons_kvah":8623,"cons_kva":68.0000,"cons_pf":0.84,"cons_lf":17},
   "dates":{"bill_month":"04/2024","bill_date":"03-05-2024","due_date":"17-May-2024"},
   "ids":{"service_no":"VSP508","van_id":"APEPDC0100000227","category":"IIIA","contracted_md":70},"amount_words_value":81782},
 88:{"money":M(228000,0,264552.30,0,31967,23455.62,5646,0,553620.92,1406,562526.92,0.08,562527,0,-0.01,562527,grid_support=7500),
   "consumption":{"cons_kwh":31967,"cons_kvah":34828,"cons_kva":100.4300,"cons_pf":0.92,"cons_lf":8},
   "dates":{"bill_month":"06/2025","bill_date":"05-07-2025","due_date":"19-Jul-2025"},
   "ids":{"service_no":"VSP212","van_id":"APEPDC0100000391","category":"IIA(i)","contracted_md":600},"amount_words_value":562527},
 116:{"money":M(950000,0,4312305,0,33306,469040.95,132800,0,5897451.95,1406,5898857.95,0.05,5898858,0,40802.08,5939660),
   "consumption":{"cons_kwh":692100,"cons_kvah":700700,"cons_kva":1712.4000,"cons_pf":0.99,"cons_lf":30},
   "dates":{"bill_month":"08/2025","bill_date":"04-09-2025","due_date":"18-Sep-2025"},
   "ids":{"service_no":"VSP007","van_id":"APEPDC0100000626","category":"IIA(i)","contracted_md":2500},"amount_words_value":5939660},
 132:{"money":M(6522.75,0,213479,0,1598.46,50655.77,0,0,272255.98,1406,273661.98,0.02,273662,0,242248.01,515910),
   "consumption":{"cons_kwh":33641,"cons_kvah":37497,"cons_kva":86.9700,"cons_pf":0.90,"cons_lf":None},
   "dates":{"bill_month":"09/2025","bill_date":"04-10-2025","due_date":"18-Oct-2025"},
   "ids":{"service_no":"VSP098","van_id":"APEPDC0100000558","category":"IB","contracted_md":600},"amount_words_value":515910},
 154:{"money":M(65915.75,0,332889.75,0,2374.56,-112.88,12953,0,414020.18,1406,415426.18,-0.18,415426,0,-224444,190982),
   "consumption":{"cons_kwh":46576,"cons_kvah":50515,"cons_kva":138.7700,"cons_pf":0.92,"cons_lf":38},
   "dates":{"bill_month":"10/2025","bill_date":"04-11-2025","due_date":"18-Nov-2025"},
   "ids":{"service_no":"VSP1655","van_id":"APEPDC0100004450","category":"IIA(i)","contracted_md":150},"amount_words_value":190982},
 214:{"money":M(67977.25,0,415662.75,0,2982.72,35910.76,14316,0,536849.48,1406,538255.48,-0.48,538255,0,0,538255),
   "consumption":{"cons_kwh":49712,"cons_kvah":54335,"cons_kva":143.1100,"cons_pf":0.91,"cons_lf":53},
   "dates":{"bill_month":"02/2026","bill_date":"04-03-2026","due_date":"18-Mar-2026"},
   "ids":{"service_no":"VSP1655","van_id":"APEPDC0100004450","category":"IIA(i)","contracted_md":150},"amount_words_value":538255},
 244:{"money":M(76000,0,369739.80,0,1947.90,32343.56,12306,0,492337.26,1406,493743.26,-0.26,448421,0,-0.24,448421,neticd=-45322),
   "consumption":{"cons_kwh":43465,"cons_kvah":59332,"cons_kva":126.1400,"cons_pf":0.73,"cons_lf":33},
   "dates":{"bill_month":"04/2026","bill_date":"04-05-2026","due_date":"18-May-2026"},
   "ids":{"service_no":"VSP1718","van_id":"APEPDC0100004656","category":"IIA(i)","contracted_md":200},"amount_words_value":448421},
}

agg = {c: [0, 0] for c in ("money","consumption","dates","ids","other")}
all_misses = {}
print("BIGGER held-out exam — 10 fresh pages, scored once, no tuning:\n")
for p in sorted(GT):
    gt = GT[p]; boxes = ocr(p); fields, recs = parse(boxes); _tess(fields, recs, boxes, p)
    r = reconcile(fields, recs)
    exp = {}
    for sec in ("money","consumption","dates","ids"): exp.update(gt.get(sec, {}))
    exp["amount_words_value"] = gt["amount_words_value"]
    ph = pt = 0; misses = []
    for k, e in exp.items():
        if e is None: continue
        fp = fields.get(k); gv = fp.get("value") if _provenance_ok(fp) else None
        ok = match(k, gv, e); agg[_bucket(k)][0] += ok; agg[_bucket(k)][1] += 1; ph += ok; pt += 1
        if not ok: misses.append((k, gv, e, fp.get("bbox") if fp else None))
    all_misses[p] = misses
    print(f"  p{p}: {ph}/{pt}  chain_ok={r['chain_ok']}   misses={[(m[0],m[1],'exp',m[2]) for m in misses]}")

th = tt = 0
print("\nBy category:")
for c in ("money","consumption","dates","ids","other"):
    h, t = agg[c]; th += h; tt += t
    if t: print(f"  {c:12}: {h}/{t} = {h/t:.0%}")
print(f"  {'OVERALL':12}: {th}/{tt} = {th/tt:.1%}   (dev 98.0%, prior holdout 95.9%)")
json.dump({str(p):[[m[0],m[1],m[2],m[3]] for m in ms] for p,ms in all_misses.items() if ms},
          open("outputs/exam_misses.json","w"), indent=2, default=str)

"""OVERFIT TEST — held-out ground truth on 5 pages never used for tuning, read by
Claude vision AFTER the champion was frozen. Scores the champion once, no tuning.
If field-exact here ~= dev (98%), we did not overfit. Run: python holdout_test.py
"""
import sys, os, json
sys.stdout.reconfigure(encoding="utf-8"); sys.path.insert(0, os.path.dirname(__file__))
from common import ocr, classify
from parse import parse
from reconcile import reconcile
from eval import match, _provenance_ok, _bucket
try:
    from tess_check import recover_fppca as _tess
except Exception:
    def _tess(*a, **k): return False

# frozen held-out GT (vision-read; each verified against the bill's own arithmetic)
GT = {
 40:{"money":{"demand_normal":76000.00,"demand_penal":0.0,"energy_charges":237532.50,"excess_energy":0.0,
   "elec_duty":28562.00,"fppca":10547.60,"tod_charges":6849.00,"tod_incentive":0.0,"sub_total":359491.10,
   "customer_charges":1406.00,"total":360897.10,"loss_gain":-0.10,"net_bill":360897.00,
   "arrears_prev":0.0,"arrears_curr":-335.97,"net_payable":360561.00},
   "consumption":{"cons_kwh":28562,"cons_kvah":31050,"cons_kva":77.2300,"cons_pf":0.92,"cons_lf":20},
   "dates":{"bill_month":"03/2024","bill_date":"03-04-2024","due_date":"17-Apr-2024"},
   "ids":{"service_no":"VSP1718","van_id":"APEPDC0100004656","category":"IIA(i)","contracted_md":200},
   "amount_words_value":360561},
 66:{"money":{"demand_normal":32466.25,"demand_penal":0.0,"energy_charges":32760.00,"excess_energy":0.0,
   "elec_duty":4359.00,"fppca":3449.20,"tod_charges":739.50,"tod_incentive":-3003.75,"sub_total":70770.20,
   "customer_charges":1406.00,"total":72176.20,"loss_gain":-0.20,"net_bill":72176.00,
   "arrears_prev":0.0,"arrears_curr":-97.00,"net_payable":72079.00},
   "consumption":{"cons_kwh":4359,"cons_kvah":5200,"cons_kva":68.3500,"cons_pf":0.84,"cons_lf":9},
   "dates":{"bill_month":"05/2024","bill_date":"03-06-2024","due_date":"17-Jun-2024"},
   "ids":{"service_no":"VSP508","van_id":"APEPDC0100000227","category":"IIIA","contracted_md":70},
   "amount_words_value":72079},
 118:{"money":{"demand_normal":228000.00,"demand_penal":0.0,"energy_charges":231963.30,"excess_energy":0.0,
   "elec_duty":1646.64,"fppca":12951.20,"tod_charges":5732.00,"tod_incentive":0.0,"sub_total":480293.14,
   "customer_charges":1406.00,"grid_support":7500.00,"total":489199.14,"loss_gain":-0.14,"net_bill":489199.00,
   "arrears_prev":0.0,"arrears_curr":-0.01,"net_payable":489199.00},
   "consumption":{"cons_kwh":31444,"cons_kvah":34695,"cons_kva":110.3300,"cons_pf":0.91,"cons_lf":6},
   "dates":{"bill_month":"08/2025","bill_date":"04-09-2025","due_date":"18-Sep-2025"},
   "ids":{"service_no":"VSP212","van_id":"APEPDC0100000391","category":"IIA(i)","contracted_md":600},
   "amount_words_value":489199},
 168:{"money":{"demand_normal":33250.00,"demand_penal":712.02,"energy_charges":87538.50,"excess_energy":0.0,
   "elec_duty":701.76,"fppca":8988.93,"tod_charges":3891.00,"tod_incentive":-5306.25,"sub_total":129775.96,
   "customer_charges":1406.00,"late_payment":550.00,"interest_ed":0.56,"total":131732.52,"loss_gain":0.48,
   "net_bill":131733.00,"arrears_prev":0.0,"arrears_curr":0.0,"net_payable":131733.00},
   "consumption":{"cons_kwh":11696,"cons_kvah":13895,"cons_kva":70.7495,"cons_pf":0.84,"cons_lf":27},
   "dates":{"bill_month":"11/2025","bill_date":"02-12-2025","due_date":"16-Dec-2025"},
   "ids":{"service_no":"VSP508","van_id":"APEPDC0100000227","category":"IIIA","contracted_md":70},
   "amount_words_value":131733},
 200:{"money":{"demand_normal":68661.25,"demand_penal":0.0,"energy_charges":411776.55,"excess_energy":0.0,
   "elec_duty":2881.86,"fppca":41818.81,"tod_charges":16206.00,"tod_incentive":0.0,"sub_total":541344.47,
   "customer_charges":1406.00,"total":542750.47,"loss_gain":-0.47,"net_bill":542750.00,
   "arrears_prev":0.0,"arrears_curr":0.0,"net_payable":542750.00},
   "consumption":{"cons_kwh":55031,"cons_kvah":60827,"cons_kva":144.5500,"cons_pf":0.90,"cons_lf":48},
   "dates":{"bill_month":"01/2026","bill_date":"04-02-2026","due_date":"18-Feb-2026"},
   "ids":{"service_no":"VSP1655","van_id":"APEPDC0100004450","category":"IIA(i)","contracted_md":150},
   "amount_words_value":542750},
}

agg = {c: [0, 0] for c in ("money", "consumption", "dates", "ids", "other")}
print("HELD-OUT overfit test (5 pages never tuned on):\n")
for p in sorted(GT):
    gt = GT[p]; boxes = ocr(p); fields, recs = parse(boxes); _tess(fields, recs, boxes, p)
    r = reconcile(fields, recs)
    exp = {}
    for sec in ("money", "consumption", "dates", "ids"):
        exp.update(gt.get(sec, {}))
    exp["amount_words_value"] = gt["amount_words_value"]
    ph = pt = 0; misses = []
    for k, e in exp.items():
        if e is None: continue
        fp = fields.get(k)
        gv = fp.get("value") if _provenance_ok(fp) else None
        ok = match(k, gv, e); agg[_bucket(k)][0] += ok; agg[_bucket(k)][1] += 1; ph += ok; pt += 1
        if not ok: misses.append(f"{k}(got {gv} exp {e})")
    print(f"  p{p}: {ph}/{pt} fields  chain_ok={r['chain_ok']}   misses={misses}")

print("\nBy category (held-out):")
th = tt = 0
for c in ("money", "consumption", "dates", "ids", "other"):
    h, t = agg[c]; th += h; tt += t
    if t: print(f"  {c:12}: {h}/{t} = {h/t:.0%}")
print(f"  {'OVERALL':12}: {th}/{tt} = {th/tt:.1%}   (dev was 98.0%)")

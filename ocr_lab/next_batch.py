"""NEXT fresh batch (post-fix re-validation): 11 pristine pages, never tuned on,
read by Claude vision. Scores champion once, no tuning."""
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

def M(dn=0,dp=0,en=0,ex=0,ed=0,fp=0,tc=0,ti=0,st=0,cu=1406.0,tot=0,lg=0,nb=0,ap=0,ac=0,npay=0,**x):
    d={"demand_normal":dn,"demand_penal":dp,"energy_charges":en,"excess_energy":ex,"elec_duty":ed,
       "fppca":fp,"tod_charges":tc,"tod_incentive":ti,"sub_total":st,"customer_charges":cu,"total":tot,
       "loss_gain":lg,"net_bill":nb,"arrears_prev":ap,"arrears_curr":ac,"net_payable":npay}
    d.update(x); return d
def C(kwh,kvah,kva,pf,lf): return {"cons_kwh":kwh,"cons_kvah":kvah,"cons_kva":kva,"cons_pf":pf,"cons_lf":lf}
def D(m,bd,dd): return {"bill_month":m,"bill_date":bd,"due_date":dd}
def I(s,v,c,md): return {"service_no":s,"van_id":v,"category":c,"contracted_md":md}

GT = {
 10:{"money":M(570000,0,3437076.15,0,428873,241058.35,88166,0,4765173.50,1406,4766579.50,0.50,4766580,0,0,4766580),
   "consumption":C(428873,449291,1196.3000,0.95,40),"dates":D("01/2024","04-02-2024","18-Feb-2024"),
   "ids":I("VSP007","APEPDC0100000626","IIA(i)",1500),"amount_words_value":4766580},
 26:{"money":M(76000,0,201722.85,0,24317,26894.26,5962,0,334896.11,1406,336302.11,-0.11,336302,0,-340.97,335961),
   "consumption":C(24317,26369,63.1200,0.92,18),"dates":D("02/2024","03-03-2024","17-Mar-2024"),
   "ids":I("VSP1718","APEPDC0100004656","IIA(i)",200),"amount_words_value":335961},
 38:{"money":M(32062.50,0,57437.10,0,7689,8381.54,880.50,-5630.25,100820.39,1406,102226.39,-0.39,102226,0,-306,101920),
   "consumption":C(7689,9117,67.5000,0.84,17),"dates":D("03/2024","03-04-2024","17-Apr-2024"),
   "ids":I("VSP508","APEPDC0100000227","IIIA",70),"amount_words_value":101920},
 58:{"money":M(712500,6365,5128560,0,591100,235800,123700,0,6798025,1406,6799431,0,6799431,0,-1099,6798332),
   "consumption":C(591100,670400,1506.7000,0.88,59),"dates":D("05/2024","02-06-2024","16-Jun-2024"),
   "ids":I("VSP007","APEPDC0100000626","IIA(i)",1500),"amount_words_value":6798332},
 76:{"money":M(11175,0,217917,0,1767.36,37263.90,0,0,268123.26,1406,269529.26,-0.26,269529,0,-597127,-327598),
   "consumption":C(38456,40131,149.0000,0.96,None),"dates":D("05/2025","05-06-2025","19-Jun-2025"),
   "ids":I("VSP127","APEPDC0100000334","IB",200),"amount_words_value":327598},
 108:{"money":M(133000,0,141448.50,0,14686,15326.70,5000,0,309461.20,1406,310867.20,-0.20,310867,0,0,310867),
   "consumption":C(19686,23490,67.7000,0.84,7),"dates":D("07/2025","05-08-2025","19-Aug-2025"),
   "ids":I("VSP309","APEPDC0100001933","IIA(i)",350),"amount_words_value":310867},
 126:{"money":M(76000,0,420115.05,0,1932.36,36891.01,13190,0,548128.42,1406,549534.42,-0.42,549534,0,28728.03,578262),
   "consumption":C(43206,65917,130.0500,0.66,36),"dates":D("08/2025","04-09-2025","18-Sep-2025"),
   "ids":I("VSP1718","APEPDC0100004656","IIA(i)",200),"amount_words_value":578262},
 148:{"money":M(21054.75,0,408184,0,3321.36,-36489.89,0,0,396070.22,1406,397476.22,-0.22,397476,0,-0.02,397476),
   "consumption":C(66356,69312,280.7300,0.96,None),"dates":D("10/2025","04-11-2025","18-Nov-2025"),
   "ids":I("VSP361","APEPDC0100000508","IB",555),"amount_words_value":397476},
 178:{"money":M(21464.25,0,416269,0,3379.74,76745.87,0,0,517858.86,1406,519264.86,0.14,519265,0,-0.02,519265),
   "consumption":C(67329,70467,286.1900,0.96,None),"dates":D("12/2025","03-01-2026","17-Jan-2026"),
   "ids":I("VSP361","APEPDC0100000508","IB",555),"amount_words_value":519265},
 196:{"money":M(0,0,224052.50,0,890.40,12580,0,0,237522.90,2813,490335.90,0.10,490336,0,0,490336,grid_support=250000),
   "consumption":C(14840,18290,120.0000,0.81,12),"dates":D("01/2026","02-02-2026","16-Feb-2026"),
   "ids":I("VSP1375","APEPDC0100003730","IIB",200),"amount_words_value":490336},
 236:{"money":M(228000,0,94110.30,0,2478.24,4800,15649,0,345037.54,1406,353943.54,0.46,353944,0,-0.45,353944,grid_support=7500),
   "consumption":C(44304,45516,397.6300,0.97,2),"dates":D("04/2026","04-05-2026","18-May-2026"),
   "ids":I("VSP212","APEPDC0100000391","IIA(i)",600),"amount_words_value":353944},
}

agg = {c: [0, 0] for c in ("money","consumption","dates","ids","other")}
print("NEXT fresh batch — 11 pristine pages, scored once, no tuning:\n")
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
        if not ok: misses.append((k, gv, e))
    print(f"  p{p}: {ph}/{pt}  chain_ok={r['chain_ok']}   misses={misses}")

th = tt = 0
print("\nBy category:")
for c in ("money","consumption","dates","ids","other"):
    h, t = agg[c]; th += h; tt += t
    if t: print(f"  {c:12}: {h}/{t} = {h/t:.0%}")
print(f"  {'OVERALL':12}: {th}/{tt} = {th/tt:.1%}   (dev 98.0%, batch-1 holdout 97.6%)")

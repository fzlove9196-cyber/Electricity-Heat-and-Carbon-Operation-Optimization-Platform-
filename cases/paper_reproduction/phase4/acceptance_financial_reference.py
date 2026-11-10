#!/usr/bin/env python3
"""Separate offline reference: declared rates times physical interval amounts; no app imports.
Control-specific, not a generic financial model and NOT paper precision. Legacy fixed
synthetic cycling quote is5 CNY/MWh-throughput (public engine convention, not inferred
from actual cost output). Preserve it as a reference assumption, not a fitted value.
"""
import json,csv,io,zipfile,pathlib,sys
O=pathlib.Path(sys.argv[1]);records=[]
for name in ['energy_1h','energy_15min','thermal_1h','thermal_15min']:
 with zipfile.ZipFile(O/name/'export.zip') as z:
  s=json.loads(z.read('scenario.json'));r=json.loads(z.read('results.json'));d=list(csv.DictReader(io.StringIO(z.read('dispatch_optimized.csv').decode())))
 dt=s['dt_hours'];electricity=sum(sum(float(x[k]) for k in x if k.startswith('gen') and k.endswith('_MW'))*dt*(1000*s['price_cny_kwh'][i]+s['grid_markup_cny_mwh']) for i,x in enumerate(d));cycling=5*dt*sum(float(x['BAT_ch'])+float(x['BAT_dis']) for x in d)
 heat=-(s.get('heat_network') or {}).get('price_cny_mwh_th',0)*dt*sum(float(x.get('heat_delivered_MWth',0)) for x in d)
 expected=electricity+cycling+heat;actual=r['objective']['optimized'];terms=r['cost_terms']['optimized'];residual=max(abs(expected-actual),abs(electricity-terms['grid_purchase']),abs(cycling-terms['storage_degradation']),abs(heat-terms.get('heat_revenue',0)))
 other_nonzero={k:v for k,v in terms.items() if k not in ['grid_purchase','storage_degradation','heat_revenue'] and abs(v)>1e-8}
 records.append(dict(name=name,passed=residual<1e-7 and not other_nonzero,electricity_cny=electricity,cycling_cny=cycling,heat_revenue_negative_cny=heat,reference_objective_cny=expected,actual_objective_cny=actual,max_error_cny=residual,other_nonzero_terms=other_nonzero))
passed=all(r['passed'] for r in records);summary=dict(independent_gates=1,passed=int(passed),failed=int(not passed),name='separate_financial_interval_reference_four_controls',source='input price and heat quotes; explicitly legacy synthetic cycling quote5 CNY/MWh-throughput; all quantities official full-precision dispatch',not_paper_precision=True,controls=records)
(O/'financial_reference.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False));sys.exit(not passed)

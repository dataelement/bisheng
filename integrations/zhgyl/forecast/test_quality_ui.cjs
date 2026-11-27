// Evaluate the actual quality rendering functions with API fixture values.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync(__dirname+'/public/app.js','utf8');
const code=app.slice(app.indexOf('const escapeHTML'),app.indexOf('const statusLabels'))+
  app.slice(app.indexOf('function table('),app.indexOf('/* Null observations'));
const context=vm.createContext({Intl,console,assert});
vm.runInContext(code+`
  const data={items:[{spec:'API-ONLY',forecast:{monthly:[{month:'2026-12',spec:'API-ONLY',customer:'Fixture',quantity:17,unit_price:2,amount:34,model_version:'API-fixture',prediction_id:'P1',is_synthetic:false}]}}]};
  const absent=modelQualityCard(data);
  assert.ok(absent.includes('未提供'));
  assert.ok(absent.includes('17'));
  assert.ok(!absent.includes('0%'));
  assert.ok(!qualityNotes(data).some(note=>note.includes('MAPE 0')));
  data.items[0].forecast.monthly[0].backtest_mape=.48;
  let notes=qualityNotes(data).join(' ');
  assert.ok(notes.includes('API返回回测 MAPE 48%'));
  assert.ok(!notes.includes('模拟回测'));
  data.items[0].forecast.monthly[0].is_synthetic=true;
  assert.ok(qualityNotes(data).join(' ').includes('模拟回测 MAPE 48%'));
  data.items[0].forecast.monthly[0].backtest_mape=0;
  assert.ok(modelQualityCard(data).includes('0%'));
`,context);
console.log('quality UI: missing, API sourced, synthetic sourced and real zero metric passed');

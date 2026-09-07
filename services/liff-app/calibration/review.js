(function() {
  'use strict';
  const api = window.ZenboCalibrationEvidence;
  let source = null, report = null, generation = 0;
  const get = id => document.getElementById(id);
  function download(text, type, name) {
    const url = URL.createObjectURL(new Blob([text], {type}));
    const link = document.createElement('a'); link.href=url; link.download=name;
    document.body.appendChild(link); link.click(); link.remove(); setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  function reset(message) {
    report=null; get('download').disabled=true; get('summary').textContent=message;
    get('counts').textContent=''; get('issues').replaceChildren();
  }
  function review() {
    reset('กำลังตรวจข้อมูล');
    try {
      report=api.review(source, Number(get('scope').value));
      get('summary').textContent={INCOMPLETE:'ข้อมูลยังไม่ครบหรือไม่ถูกต้อง',RECORDED_FAILURES:'มีผลทดลองไม่ผ่าน ต้องให้ผู้รับผิดชอบตรวจสอบ',READY_FOR_HUMAN_REVIEW:'ข้อมูลครบตามรูปแบบ พร้อมให้ผู้รับผิดชอบตรวจหลักฐานจริง'}[report.status];
      get('counts').textContent=`ขอบเขต ${report.maxLevel === 1 ? 'L1' : 'L1–L'+report.maxLevel} · แถว PASS ที่ข้อมูลครบ ${report.completeRows}/${report.expectedRows} · แถว FAIL ${report.failedRows} · ประเด็นตรวจ ${report.issues.length}`;
      for (const issue of report.issues.slice(0,100)) {
        const item=document.createElement('li'); item.textContent=(issue.row ? `แถว ${issue.row}: ` : '')+issue.code; get('issues').appendChild(item);
      }
      if(report.issues.length>100) {const item=document.createElement('li');item.textContent='แสดง 100 ประเด็นแรก ดาวน์โหลด JSON เพื่อดูทั้งหมด';get('issues').appendChild(item);}
      get('download').disabled=false;
    } catch(error) {reset(error.message);}
  }
  get('file').addEventListener('change',async()=>{
    const current=++generation, file=get('file').files[0]; source=null; reset('กำลังอ่านไฟล์');
    if(!file) {reset('ยังไม่ได้เลือกไฟล์');return;}
    if(file.size>1000000) {reset('ไฟล์ต้องมีขนาดไม่เกิน 1 MB');return;}
    try {const text=await file.text();if(current!==generation)return;source=text;review();}
    catch(error) {if(current===generation)reset('อ่านไฟล์ไม่ได้ กรุณาเลือกไฟล์ใหม่');}
  });
  get('scope').addEventListener('change',()=>{if(source!==null)review();});
  get('template').addEventListener('click',()=>download(api.template(),'text/csv;charset=utf-8','relative-motion-trials.csv'));
  get('blank').addEventListener('click',()=>{generation++;get('file').value='';source=api.template();review();});
  get('download').addEventListener('click',()=>{if(report)download(JSON.stringify(report,null,2),'application/json','calibration-data-review.json');});
  get('clear').addEventListener('click',()=>{generation++;source=null;get('file').value='';reset('ล้างข้อมูลแล้ว');});
  if(window.ZenboCommon) window.ZenboCommon.ensureAuth();
})();

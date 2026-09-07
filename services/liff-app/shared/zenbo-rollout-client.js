(function(root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.ZenboRolloutClient = factory();
})(typeof self !== 'undefined' ? self : this, function() {
  'use strict';
  const stages=['LOCKED','SIMULATED_L1','SIMULATED_L2','SIMULATED_L3','ROLLED_BACK'];
  function validSession(row, robot) {
    return row && row.robot_slug===robot && typeof row.session_id==='string' && row.session_id.length>0
      && Number.isInteger(row.revision) && row.revision>=0 && stages.includes(row.state)
      && row.dry_run===true && row.physical_authorized===false && row.mqtt_publish_attempted===false
      && Array.isArray(row.events) && row.events.every(event=>event && stages.includes(event.state)
        && Number.isFinite(event.at_ms) && typeof event.actor==='string');
  }
  function create(options) {
    let robot='', session=null, busy=false, uncertain=false, generation=0, message='ระบุหุ่นเพื่ออ่าน session';
    function state() {return {robot,session,busy,uncertain,message};}
    function select(value) {
      value=value.trim(); if(value===robot)return;
      generation++;robot=value;session=null;busy=false;uncertain=false;message='ยังไม่ได้อ่าน session ของหุ่นนี้';
    }
    async function run(action, input={}) {
      if(busy)return;
      if(!robot) {message='กรอก robot slug';return;}
      const mutation=['start','advance','rollback'].includes(action);
      if(!['active','read','start','advance','rollback'].includes(action))throw new Error('INVALID_ACTION');
      if(mutation && uncertain) {message='ต้องอ่านสถานะล่าสุดก่อนทำรายการต่อ';return;}
      if(action==='start' && (!input.permitId?.trim() || session && session.state!=='ROLLED_BACK')) {message='ต้องมี field permit และไม่มี session ที่ยังเปิดอยู่';return;}
      if(['advance','rollback'].includes(action) && (!session || session.state==='ROLLED_BACK')) {message='ต้องอ่าน session ที่ยังเปิดอยู่ก่อน';return;}
      if(action==='advance' && session.state==='SIMULATED_L3') {message='ซ้อมครบ L1–L3 แล้ว';return;}
      if(action==='read' && !input.sessionId?.trim()) {message='กรอก session ID';return;}
      const current=++generation, target=robot;
      let path=options.apiBase+'/api/v1/robots/'+encodeURIComponent(robot)+'/rollout-drills';
      let body;
      if(action==='active')path+='/active';
      if(action==='read')path+='/'+encodeURIComponent(input.sessionId.trim());
      if(action==='start')body={permit_id:input.permitId.trim()};
      if(['advance','rollback'].includes(action)) {path+='/'+encodeURIComponent(session.session_id)+'/'+action;body={revision:session.revision};}
      busy=true;message='กำลังติดต่อ Core';
      const controller=new AbortController();
      const timeout=setTimeout(()=>controller.abort(),options.timeoutMs || 10000);
      try {
        const response=await options.fetch(path,mutation ? {method:'POST',signal:controller.signal,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)} : {method:'GET',cache:'no-store',signal:controller.signal});
        const result=await response.json();
        if(current!==generation)return;
        if(!response.ok)throw new Error(typeof result.detail?.code==='string' ? result.detail.code : 'HTTP_'+response.status);
        if(action==='active' && !(result.dry_run===true && result.physical_authorized===false && result.mqtt_publish_attempted===false && Object.prototype.hasOwnProperty.call(result,'session')))throw new Error('INVALID_RESPONSE');
        const row=action==='active' ? result.session : result;
        if(!(action==='active' && row===null) && !validSession(row,target))throw new Error('INVALID_RESPONSE');
        session=row;uncertain=false;message=row ? 'อ่านสถานะการซ้อมแล้ว ไม่มีการอนุญาตให้เคลื่อนที่จริง' : 'ไม่พบ session ที่ยังเปิดอยู่และคุณมีสิทธิ์อ่าน';
      } catch(error) {
        if(current!==generation)return;
        uncertain=true;
        message=(mutation ? 'ยังยืนยันผลรายการไม่ได้: ' : 'อ่านสถานะไม่ได้: ')+error.message+' · อ่านสถานะล่าสุดก่อนทำรายการต่อ ไม่มี retry อัตโนมัติ';
      } finally {clearTimeout(timeout);if(current===generation)busy=false;}
    }
    return {state,select,run};
  }
  return {create,validSession};
});

(function(root,factory){
  if(typeof module==='object' && module.exports)module.exports=factory();
  else root.ZenboConnectionStatus=factory();
})(typeof self!=='undefined'?self:this,function(){
  'use strict';
  function describe(data,now=Date.now()){
    const mqtt=data?.mqtt;
    if(!mqtt)return 'Core ยังไม่มีข้อมูลสถานะ MQTT';
    if(mqtt.connected!==true)return 'Core ยังไม่เชื่อมต่อ MQTT ('+(mqtt.state || 'UNKNOWN')+')';
    if(mqtt.subscribed!==true)return 'Core เชื่อมต่อ MQTT แล้ว แต่ยังไม่ยืนยันการรับสถานะหุ่น ('+(mqtt.state || 'UNKNOWN')+')';
    const age=now-mqtt.last_live_heartbeat_at_ms;
    if(Number.isFinite(mqtt.last_live_heartbeat_at_ms) && mqtt.last_live_heartbeat_at_ms>0 && age>=0 && age<=10000)
      return 'Core รับสถานะ MQTT ได้ · พบ heartbeat สด (ยังไม่ยืนยันว่า Robot API หรือการเคลื่อนที่พร้อม)';
    return 'Core รับสถานะ MQTT ได้ · ยังไม่พบ heartbeat สดใน 10 วินาทีล่าสุด'
      +(mqtt.retained_heartbeat_count>0 ? ' · มีข้อมูลเก่าที่ broker เก็บไว้ ซึ่งไม่นับเป็นหุ่นออนไลน์' : '');
  }
  return {describe};
});

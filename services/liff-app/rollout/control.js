(function(){
  'use strict';
  const get=id=>document.getElementById(id);
  const client=window.ZenboRolloutClient.create({apiBase:window.ZENBO_LIFF_CONFIG?.apiBase || '/liff-api',fetch:window.fetch.bind(window)});
  function render(){
    const s=client.state(), row=s.session;
    for(const id of ['robot','session-id','permit'])get(id).disabled=s.busy;
    for(const id of ['active','read'])get(id).disabled=s.busy || !s.robot;
    get('start').disabled=s.busy || s.uncertain || !s.robot || !get('permit').value.trim() || !!(row && row.state!=='ROLLED_BACK');
    get('advance').disabled=s.busy || s.uncertain || !row || ['ROLLED_BACK','SIMULATED_L3'].includes(row.state);
    get('rollback').disabled=s.busy || s.uncertain || !row || row.state==='ROLLED_BACK';
    get('receipt').textContent=s.message;
    get('session').textContent=row ? 'Session '+row.session_id+'\n'+row.state+' · revision '+row.revision : '';
    get('events').replaceChildren();
    for(const event of row?.events || []){const item=document.createElement('li');item.textContent=event.state+' · '+new Date(event.at_ms).toLocaleString('th-TH')+' · '+event.actor;get('events').appendChild(item);}
  }
  get('robot').addEventListener('input',()=>{client.select(get('robot').value);get('session-id').value='';get('permit').value='';render();});
  get('permit').addEventListener('input',render);
  for(const action of ['active','read','start','advance','rollback'])get(action).addEventListener('click',async()=>{
    const pending=client.run(action,{permitId:get('permit').value,sessionId:get('session-id').value});render();await pending;render();
  });
  render();if(window.ZenboCommon)window.ZenboCommon.ensureAuth();
})();

'use strict';
let sid=null,state=null,busy=false,boot=null,timer=null,lastRenderedMessageKey=null;
const $=id=>document.getElementById(id);
const statuses={investigating:'调查中',waiting_user:'等待补充',waiting_confirmation:'等待确认',waiting_verification:'等待验证',waiting_approval:'等待审批',waiting_service:'等待服务恢复',escalated:'已创建模拟交接',resolved:'员工确认已恢复'};
async function api(path,body){const r=await fetch('/api'+path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-Helpdesk':'1'},body:body===undefined?undefined:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw new Error(data.detail||'Request failed');return data;}
function error(e){$('error').hidden=false;$('error').textContent=e.message||String(e);}
function safe(fn){return async()=>{try{$('error').hidden=true;await fn();}catch(e){error(e);}};}
function option(value,text){const o=document.createElement('option');o.value=value;o.textContent=text;return o;}
async function list(){const all=await api('/sessions');$('sessions').replaceChildren(option('','选择会话'));all.forEach(s=>$('sessions').append(option(s.id,s.employee+' · '+s.id.slice(-6))));if(sid)$('sessions').value=sid;}
async function fresh(){state=await api('/sessions',{employee_id:$('employee').value});sid=state.id;localStorage.setItem('helpdesk_session',sid);await list();render();}
async function refresh(){if(!sid)return;state=await api('/sessions/'+sid);render();}
function node(tag,text,cls){const n=document.createElement(tag);n.textContent=text;if(cls)n.className=cls;return n;}
function replyBubble(m){
 const b=node('div','', 'bubble '+m.role);b.append(node('span',m.role==='assistant'?'IT Companion':'You','role'));
 const p=m.presentation;
 if(m.role!=='assistant'||!p){b.append(document.createTextNode(m.text));return b;}
 b.classList.add('employee-reply');const cn=p.language==='zh';
 if(p.assessment){const a=node('section','', 'assessment');a.append(node('span',cn?'当前判断 · 待验证':'Current assessment · to verify','assessment-label'),node('p',p.assessment));b.append(a);}
 const body=p.kind==='guide'&&p.assessment?(cn?'接下来建议这样处理：':'Here’s what to do next:'):p.body;
 if(body)b.append(node('p',body,'reply-body'));
 if(p.conditions.length){const c=node('p','', 'applicability');c.append(node('strong',cn?'适用前提：':'Applies when: '),document.createTextNode(p.conditions.join('; ')));b.append(c);}
 if(p.steps.length){const steps=node('ol','', 'reply-steps');p.steps.forEach(step=>steps.append(node('li',step)));b.append(steps);}
 if(p.help){const h=node('div','', 'entry-help');h.append(node('strong',cn?'找不到入口？':'Can’t find the entry?'),node('p',p.help));b.append(h);}
 if(p.verification){const v=node('p','', 'verification-hint');v.append(node('strong',cn?'如何检查结果：':'How to check the result: '),document.createTextNode(p.verification));b.append(v);}
 if(p.source)b.append(node('small',(cn?'操作依据：':'Approved guide: ')+p.source.id+' · v'+p.source.version+' · '+p.source.title,'source-note'));
 if(p.references.length){const refs=node('details','', 'reply-references');refs.append(node('summary',(cn?'查看判断依据':'Evidence behind this assessment')+' ('+p.references.length+')'));const ul=node('ul','');p.references.forEach(r=>ul.append(node('li',r.id+' · '+r.title)));refs.append(ul);b.append(refs);}
 return b;
}
function render(){if(!state)return;const i=state.issues.find(x=>x.id===state.active_issue);busy=state.running;$('sessions').value=state.id;$('employee').value=state.employee;$('status').textContent=busy?'正在调查…':(statuses[i.status]||i.status);$('send').disabled=busy||!!i.pending||['resolved','escalated','waiting_approval'].includes(i.status);$('message').disabled=$('send').disabled;$('handoff').disabled=busy;$('newIssue').disabled=busy||!!i.pending;
$('issues').replaceChildren(...state.issues.map(x=>option(x.id,x.title+' · '+(statuses[x.status]||x.status))));$('issues').value=i.id;
const messages=state.messages.filter(m=>m.issue===i.id);if(messages.length){const chat=$('chat'),oldScroll=chat.scrollTop,last=messages[messages.length-1],key=state.id+':'+i.id+':'+messages.length+':'+(last.at||'');chat.replaceChildren(...messages.map(replyBubble));
if(key!==lastRenderedMessageKey){if(last.role==='assistant'){const el=chat.lastElementChild;chat.scrollTop=Math.max(0,el.getBoundingClientRect().top-chat.getBoundingClientRect().top+chat.scrollTop-12);}else{chat.scrollTop=chat.scrollHeight;}lastRenderedMessageKey=key;}else{chat.scrollTop=oldScroll;}}
else if(!$('chat').querySelector('.welcome')){$('chat').replaceChildren(node('p','描述新的 IT 问题，我们将分别保存该问题的调查记录。','muted'));}
$('action').hidden=!i.pending;if(i.pending){$('action').replaceChildren(node('strong','请确认这次模拟申请'));
const fields=node('dl','', 'action-fields');const labels={action:'操作',resource:'目标范围',justification:'用途',employee:'申请员工'};
for(const key of Object.keys(labels)){fields.append(node('dt',labels[key]),node('dd',key==='action'?({access_request:'提交权限审批申请',password_reset:'发起本人密码重置申请'}[i.pending[key]]||i.pending[key]):i.pending[key]));}
$('action').append(fields,node('p',i.pending.action==='access_request'?'只有你点击“确认执行”才会提交模拟申请。权限申请仍需审批；确认不会直接授予权限。':'该动作仅模拟发起本人的密码重置申请，不会真正发送恢复消息。提交后仍需验证能否恢复登录。'));
const raw=node('details','');raw.append(node('summary','技术记录（可展开）'),node('pre',JSON.stringify(i.pending,null,2)));$('action').append(raw);for(const approve of [true,false]){const b=node('button',approve?'确认执行':'取消');b.onclick=safe(async()=>{state=await api('/sessions/'+sid+'/confirm',{action_id:i.pending.id,approve});render();});$('action').append(b);}}
$('verification').hidden=i.status!=='waiting_verification';$('evidence').replaceChildren(...Object.values(i.evidence).map(e=>{const d=node('details','', 'source');d.append(node('summary',e.id+' · '+(e.title||e.service||e._source)),node('pre',JSON.stringify(e,null,2)));return d;}));
$('hypotheses').textContent=JSON.stringify(i.hypotheses,null,2);$('handoffData').textContent=i.handoff?JSON.stringify(i.handoff,null,2):'尚无交接';$('activity').replaceChildren(...state.events.filter(x=>x.issue===i.id).slice(-12).map(x=>node('div',x.type+(x.type==='tool'?' · '+x.detail.tool+' · '+x.detail.status:''),'activity-row')));
clearTimeout(timer);if(busy)timer=setTimeout(()=>refresh().catch(error),650);}
$('newSession').onclick=safe(fresh);$('sessions').onchange=safe(async()=>{sid=$('sessions').value;if(sid){localStorage.setItem('helpdesk_session',sid);await refresh();}});
$('issues').onchange=safe(async()=>{state=await api('/sessions/'+sid+'/issues/'+$('issues').value+'/select',{});render();});
$('newIssue').onclick=safe(async()=>{const title=prompt('新问题标题');if(title){state=await api('/sessions/'+sid+'/issues',{title});render();}});
$('composer').onsubmit=async e=>{e.preventDefault();if(busy)return;try{if(!sid)await fresh();$('send').disabled=true;await api('/sessions/'+sid+'/messages',{text:$('message').value,request_id:crypto.randomUUID()});$('message').value='';await refresh();}catch(err){error(err);$('send').disabled=false;}};
$('handoff').onclick=safe(async()=>{if(!sid)await fresh();state=await api('/sessions/'+sid+'/handoff',{});render();});
for(const [id,resolved] of [['recovered',true],['failed',false]])$(id).onclick=safe(async()=>{state=await api('/sessions/'+sid+'/feedback',{resolved});render();});
$('export').onclick=safe(async()=>{if(!sid)return;const data=await api('/sessions/'+sid+'/export');const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=sid+'.json';a.click();URL.revokeObjectURL(url);});
document.querySelectorAll('[data-example]').forEach(b=>b.onclick=()=>{$('message').value=b.dataset.example;$('message').focus();});
(async()=>{boot=await api('/bootstrap');$('employee').replaceChildren(...boot.users.map(u=>option(u.id,u.name+' · '+u.location)));$('mode').textContent=boot.configured?(boot.mode==='openai'?'API · '+(boot.model||'未指定模型')+' · 已加载':boot.mode+' · 测试回放'):'模型未配置 · 仅可保存和交接';await list();sid=localStorage.getItem('helpdesk_session');if(sid){try{await refresh();}catch{sid=null;}}})().catch(error);

"use strict";var ft=Object.defineProperty;var Ms=Object.getOwnPropertyDescriptor;var Is=Object.getOwnPropertyNames;var Rs=Object.prototype.hasOwnProperty;var Ds=(t,e)=>{for(var n in e)ft(t,n,{get:e[n],enumerable:!0})},Bs=(t,e,n,s)=>{if(e&&typeof e=="object"||typeof e=="function")for(let r of Is(e))!Rs.call(t,r)&&r!==n&&ft(t,r,{get:()=>e[r],enumerable:!(s=Ms(e,r))||s.enumerable});return t};var $s=t=>Bs(ft({},"__esModule",{value:!0}),t);var Zi={};Ds(Zi,{default:()=>ht});module.exports=$s(Zi);var ze=require("obsidian");var _e="WebSocket connection failed. Please confirm the backend is running.",Yt="WebSocket connection lost while streaming. Please retry.",pe=class extends Error{constructor(e,n){super(e),Object.setPrototypeOf(this,new.target.prototype),this.name="WebSocketTransportError",this.canFallbackToRest=n}},vt=class extends Error{constructor(e){super(e),Object.setPrototypeOf(this,new.target.prototype),this.name="WebSocketServerError"}};function Jt(t){return t instanceof pe&&t.canFallbackToRest}function xe(){return{mode:"auto",manual_persona_id:null,active_persona_id:null,source:"none",status:"unresolved"}}var V=class{constructor(e="http://127.0.0.1:8000"){this.baseUrl=e;this.ws=null;this.pendingCallbacks=null;this.pendingUserOnError=null;this.pendingResolve=null;this.pendingReject=null;this.pendingMessageSent=!1;this._sessionId=null;this._conversationId=null}get sessionId(){return this._sessionId}get conversationId(){return this._conversationId}setBaseUrl(e){let n=e.trim();!n||n===this.baseUrl||(this.ws&&(this.ws.close(),this.ws=null),this.baseUrl=n)}getAttachmentUrl(e){return`${this.baseUrl}/attachments/${e}`}setSession(e,n=null){if(e&&!n)throw new Error("conversationId is required when sessionId is set");this.ws&&(this.ws.close(),this.ws=null),this._sessionId=e,this._conversationId=e?n:null}resetPendingStream(){this.pendingCallbacks=null,this.pendingUserOnError=null,this.pendingResolve=null,this.pendingReject=null,this.pendingMessageSent=!1}resolvePendingStream(){let e=this.pendingResolve;this.resetPendingStream(),e?.()}rejectPendingStream(e){let n=this.pendingReject;this.resetPendingStream(),n?.(e)}failPendingStreamFromSocket(e,n,s){let r=this.pendingUserOnError,i=this.pendingReject;i&&(this.resetPendingStream(),i(new pe(e,n)),s&&r?.(e))}async listSessions(){let e=await fetch(`${this.baseUrl}/sessions`);if(!e.ok)throw new Error(`Sessions API error: ${e.status}`);return await e.json()}async createSession(e){let n={method:"POST"};e&&(n.headers={"Content-Type":"application/json"},n.body=JSON.stringify({session_id:e}));let s=await fetch(`${this.baseUrl}/sessions`,n);if(!s.ok){let i=await me(s);throw new Error(i||`Create session API error: ${s.status}`)}let r=await s.json();return this.applySessionInfo(r),r}async getSession(e){let n=await fetch(`${this.baseUrl}/sessions/${encodeURIComponent(e)}`);if(!n.ok){let s=await me(n);throw new Error(s||`Session API error: ${n.status}`)}return await n.json()}async listConversations(e){let n=await fetch(`${this.baseUrl}/sessions/${encodeURIComponent(e)}/conversations`);if(!n.ok)throw new Error(`Conversations API error: ${n.status}`);return await n.json()}async getConversationMessages(e,n){let s=await fetch(`${this.baseUrl}/sessions/${encodeURIComponent(e)}/conversations/${encodeURIComponent(n)}/messages`);if(!s.ok)throw new Error(`Conversation messages API error: ${s.status}`);return await s.json()}async forkConversation(e,n,s,r){let i=await fetch(`${this.baseUrl}/sessions/${encodeURIComponent(e)}/conversations/${encodeURIComponent(n)}/fork`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({fork_message_id:s,title:r??""})});if(!i.ok){let c=await me(i);throw new Error(c||`Fork conversation API error: ${i.status}`)}let a=await i.json();return(this._sessionId===a.id||this._sessionId===null)&&this.applySessionInfo(a),a}async getConversationContextStats(e,n){let s=await fetch(`${this.baseUrl}/sessions/${encodeURIComponent(e)}/conversations/${encodeURIComponent(n)}/context-stats`);if(!s.ok)throw new Error(`Context stats API error: ${s.status}`);let r=await s.json();if(typeof r.total_tokens!="number"||typeof r.context_limit!="number"||typeof r.usage_percent!="number")throw new Error("Context stats API returned an invalid payload");return r}async listPersonas(){let e=await fetch(`${this.baseUrl}/personas`);if(!e.ok)throw new Error(`Personas API error: ${e.status}`);return await e.json()}async listSkills(){let e=await fetch(`${this.baseUrl}/skills`);if(!e.ok)throw new Error(`Skills API error: ${e.status}`);return await e.json()}async getCapabilities(){let e=await fetch(`${this.baseUrl}/capabilities`);if(!e.ok)throw new Error(`Capabilities API error: ${e.status}`);return await e.json()}async deleteSession(e){let n=await fetch(`${this.baseUrl}/sessions/${encodeURIComponent(e)}`,{method:"DELETE"});if(!n.ok&&n.status!==204)throw new Error(`Delete session API error: ${n.status}`);this._sessionId===e&&this.setSession(null)}async patchSession(e,n){let s=await fetch(`${this.baseUrl}/sessions/${encodeURIComponent(e)}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(n)});if(!s.ok){let i=await me(s);throw new Error(i||`Patch session API error: ${s.status}`)}let r=await s.json();return(this._sessionId===r.id||this._sessionId===null)&&this.applySessionInfo(r),r}async chat(e,n){let s=await this.ensureSession(),r=this.normalizePayload(e,s.id,n??s.active_conversation_id),i=await fetch(`${this.baseUrl}/chat`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(r)});if(!i.ok){let c=await me(i);throw new Error(c||`Agent API error: ${i.status} ${i.statusText}`)}let a=await i.json();return this.applyChatResponse(a),a}async streamChat(e,n){return await this.ensureWebSocket(),new Promise((s,r)=>{this.pendingResolve=s,this.pendingReject=r,this.pendingMessageSent=!1,this.pendingUserOnError=n.onError??null,this.pendingCallbacks={onAssistantPrefix:n.onAssistantPrefix,onReasoningDelta:n.onReasoningDelta,onTextDelta:n.onTextDelta,onToolStart:n.onToolStart,onToolResult:n.onToolResult,onWarning:n.onWarning,onDone:(i,a,c,o,l,x)=>{this._sessionId=i,this._conversationId=a,this.resolvePendingStream(),n.onDone?.(i,a,c,o,l,x)},onError:i=>{this.rejectPendingStream(new vt(i)),n.onError?.(i)}};try{let i=this.ws;if(!i)throw new pe(_e,!0);i.send(JSON.stringify(this.normalizeWebSocketPayload(e))),this.pendingMessageSent=!0}catch(i){if(this.resetPendingStream(),i instanceof pe){r(i);return}let a=i instanceof Error&&i.message?i.message:_e;r(new pe(a,!0))}})}async ensureWebSocket(){if(this.ws&&this.ws.readyState===WebSocket.OPEN)return;try{await this.ensureSession()}catch(n){let s=n instanceof Error&&n.message?n.message:_e;throw new pe(s,!0)}if(!this._sessionId||!this._conversationId)throw new pe(_e,!0);let e=this.baseUrl.replace(/^http/,"ws");return this.ws=new WebSocket(`${e}/sessions/${encodeURIComponent(this._sessionId)}/conversations/${encodeURIComponent(this._conversationId)}/ws`),new Promise((n,s)=>{let r=this.ws,i=!1,a=!1,c=o=>{a||(a=!0,this.ws=null,s(o))};r.onopen=()=>{i=!0,!a&&(a=!0,n())},r.onerror=()=>{if(!i){c(new pe(_e,!0));return}this.failPendingStreamFromSocket(Yt,!this.pendingMessageSent,this.pendingMessageSent)},r.onmessage=o=>{try{let l=JSON.parse(o.data);l.type==="sys_notify"?this.onSysNotify?.({message:String(l.message??""),autoTrigger:!!l.auto_trigger}):this.handleEvent(l)}catch{}},r.onclose=()=>{if(this.ws=null,!i){c(new pe(_e,!0));return}this.failPendingStreamFromSocket(this.pendingMessageSent?Yt:_e,!this.pendingMessageSent,this.pendingMessageSent)}})}handleEvent(e){let n=this.pendingCallbacks;if(n)switch(e.type){case"assistant_prefix":n.onAssistantPrefix?.(e.text);break;case"reasoning_delta":n.onReasoningDelta?.(e.text);break;case"text_delta":n.onTextDelta?.(e.text);break;case"tool_start":n.onToolStart?.(e.name,e.id);break;case"tool_result":n.onToolResult?.(e.name,e.output);break;case"warning":n.onWarning?.(e.message);break;case"done":this._sessionId=typeof e.session_id=="string"?e.session_id:this._sessionId,this._conversationId=typeof e.conversation_id=="string"?e.conversation_id:this._conversationId;let s=typeof e.message_id=="string"?e.message_id:null,r=typeof e.user_message_id=="string"?e.user_message_id:null;if(!this._sessionId||!this._conversationId){n.onError?.("Stream completed without session/conversation IDs");break}n.onDone?.(this._sessionId,this._conversationId,s,r,e.context,e.persona_state);break;case"error":n.onError?.(e.message);break}}disconnect(){this.ws&&(this.ws.close(),this.ws=null),this._sessionId=null,this._conversationId=null}abort(){let e=this.pendingResolve;this.resetPendingStream(),this.ws&&(this.ws.close(),this.ws=null),e?.()}async health(){try{return(await fetch(`${this.baseUrl}/health`)).ok}catch{return!1}}async reloadConfig(e){try{let n=await fetch(`${this.baseUrl}/admin/reload`,{method:"POST",headers:{"X-Life-Assistant-Admin-Token":e}});return n.ok?{ok:!0,status:n.status,detail:null}:{ok:!1,status:n.status,detail:await me(n)}}catch{return{ok:!1,status:null,detail:null}}}async reloadSettings(e){try{let n=await fetch(`${this.baseUrl}/admin/reload-settings`,{method:"POST",headers:{"X-Life-Assistant-Admin-Token":e}});return n.ok?{ok:!0,status:n.status,detail:null}:{ok:!1,status:n.status,detail:await me(n)}}catch{return{ok:!1,status:null,detail:null}}}async getMcpStatus(e){try{let n=await fetch(`${this.baseUrl}/admin/mcp/status`,{headers:{"X-Life-Assistant-Admin-Token":e}});return n.ok?{ok:!0,status:n.status,detail:null,data:await n.json()}:{ok:!1,status:n.status,detail:await me(n)}}catch{return{ok:!1,status:null,detail:null}}}async testCurrentProfile(e){try{let n=await fetch(`${this.baseUrl}/admin/profile/test`,{method:"POST",headers:{"X-Life-Assistant-Admin-Token":e}});return n.ok?{ok:!0,status:n.status,detail:null,data:await n.json()}:{ok:!1,status:n.status,detail:await me(n)}}catch{return{ok:!1,status:null,detail:null}}}async listLlmProfiles(e){return this.requestLlmProfiles("/admin/profiles",e)}async saveLlmProfile(e,n,s){return this.requestLlmProfiles(`/admin/profiles/${n.id}`,e,{method:"PUT",headers:{"Content-Type":"application/json","X-Life-Assistant-Admin-Token":e},body:JSON.stringify({profile:n,activate:s})})}async activateLlmProfile(e,n){return this.requestLlmProfiles(`/admin/profiles/${n}/activate`,e,{method:"POST"})}async deleteLlmProfile(e,n){return this.requestLlmProfiles(`/admin/profiles/${n}`,e,{method:"DELETE"})}async requestLlmProfiles(e,n,s={}){try{let r=new Headers(s.headers);r.set("X-Life-Assistant-Admin-Token",n);let i=await fetch(`${this.baseUrl}${e}`,{...s,headers:r});return i.ok?{ok:!0,status:i.status,detail:null,data:await i.json()}:{ok:!1,status:i.status,detail:await me(i)}}catch{return{ok:!1,status:null,detail:null}}}normalizePayload(e,n,s){return typeof e=="string"?{content:e,session_id:n,conversation_id:s}:{...e,session_id:e.session_id??n,conversation_id:e.conversation_id??s}}normalizeWebSocketPayload(e){return typeof e=="string"?{type:"message",content:e}:{type:"message",content:e.content,pasted_contents:e.pasted_contents,persona_mode:e.persona_mode,manual_persona_id:e.manual_persona_id}}async ensureSession(){return this._sessionId&&this._conversationId?{id:this._sessionId,active_conversation_id:this._conversationId}:this.createSession()}applySessionInfo(e){this._sessionId=e.id,this._conversationId=e.active_conversation_id}applyChatResponse(e){this._sessionId=e.session_id,this._conversationId=e.conversation_id}};async function me(t){try{let e=await t.json();if(typeof e?.detail=="string")return e.detail;if(typeof e?.message=="string")return e.message}catch{}try{return(await t.text()).trim()}catch{return""}}var $n=require("obsidian");var Le="life-assistant-settings-updated";function Xt(){typeof document>"u"||typeof CustomEvent>"u"||document.dispatchEvent(new CustomEvent(Le))}var ie=require("obsidian"),bt=/\[Image\s+#(\d+)\]/g,Ns=/(^|[^0-9A-Za-z_./\\:-])\/([^\s/]*)$/,Os=/(^|[^0-9A-Za-z_./\\:-])@"([^"]*)$/,Us=/(^|[^0-9A-Za-z_./\\:-])@([^\s"]*)$/,Fs=/(^|[^0-9A-Za-z_./\\:-])@"([^"]+)"(#L\d+(?:-\d+)?)?/g,Hs=/(^|[^0-9A-Za-z_./\\:-])@([^\s"]+)/g,Zt=4,Ks=10*1024*1024;function en(t){let{app:e,client:n,elements:s,state:r}=t,i=[],a=1,c={},o=[],l=0,x=null,P=null,k="",A=!1,d=!1,I=0,C=null,v=[];n.listSkills().then(m=>{i=m,j()}).catch(()=>{i=[]}),n.getCapabilities().then(m=>{C=m}).catch(()=>{C=null});let g=()=>{A?A=!1:Gt(),Ie(),le(),j()},y=()=>{if(d){d=!1;return}j()},R=m=>{if(o.length>0){if(m.key==="ArrowDown"){d=!0,m.preventDefault(),m.stopPropagation(),l=(l+1)%o.length,D();return}if(m.key==="ArrowUp"){d=!0,m.preventDefault(),m.stopPropagation(),l=(l-1+o.length)%o.length,D();return}if(m.key==="Tab"||m.key==="Enter"){m.preventDefault(),m.stopPropagation(),Y(o[l]);return}if(m.key==="Escape"){d=!0,m.preventDefault(),m.stopPropagation(),o=[],l=0,x=null,D();return}}},O=m=>{let w=Js(m);w.length!==0&&(m.preventDefault(),U(w))},q=m=>{Xs(m.dataTransfer?.files)&&(m.preventDefault(),s.inputAreaEl.classList.add("drag-over"))},F=()=>{s.inputAreaEl.classList.remove("drag-over")},b=m=>{s.inputAreaEl.classList.remove("drag-over");let w=kt(m.dataTransfer?.files);w.length!==0&&(m.preventDefault(),U(w))},E=()=>{s.hiddenFileInput.click()},u=()=>{let m=kt(s.hiddenFileInput.files);s.hiddenFileInput.value="",m.length!==0&&U(m)},h=()=>{_()};s.inputEl.addEventListener("input",g),s.inputEl.addEventListener("keydown",R),s.inputEl.addEventListener("click",y),s.inputEl.addEventListener("keyup",y),s.inputEl.addEventListener("paste",O),s.inputAreaEl.addEventListener("dragover",q),s.inputAreaEl.addEventListener("dragleave",F),s.inputAreaEl.addEventListener("drop",b),s.attachmentBtn.addEventListener("click",E),s.hiddenFileInput.addEventListener("change",u),window.addEventListener("focus",h),v.push(()=>{s.inputEl.removeEventListener("input",g),s.inputEl.removeEventListener("keydown",R),s.inputEl.removeEventListener("click",y),s.inputEl.removeEventListener("keyup",y),s.inputEl.removeEventListener("paste",O),s.inputAreaEl.removeEventListener("dragover",q),s.inputAreaEl.removeEventListener("dragleave",F),s.inputAreaEl.removeEventListener("drop",b),s.attachmentBtn.removeEventListener("click",E),s.hiddenFileInput.removeEventListener("change",u),window.removeEventListener("focus",h)});function f(){let m=s.inputEl.value,w=G(m),L=zs(m),M=W(m,w);return!L.trim()&&M.length===0?null:w.length>0&&C?.supports_vision===!1?(new ie.Notice("\u5F53\u524D\u540E\u7AEF\u6A21\u578B\u672A\u5F00\u542F\u89C6\u89C9\u80FD\u529B\uFF0C\u56FE\u7247\u5DF2\u4FDD\u7559\u5728\u8F93\u5165\u6846\u91CC\uFF0C\u6682\u65F6\u4E0D\u80FD\u53D1\u9001\u3002"),null):{request:{content:m,pasted_contents:w.map(({preview_url:$,size_bytes:H,...K})=>K)},displayText:L,displayAttachments:M}}function p(){T(),s.inputEl.value="",Ie(),j()}function S(){T(),v.splice(0).forEach(m=>m())}function T(){c={},o=[],l=0,x=null,Gt(),s.composerPillsEl.empty(),D()}async function _(){if(!(typeof navigator>"u"||!navigator.clipboard||typeof navigator.clipboard.read!="function")&&!(Date.now()-I<15e3))try{(await navigator.clipboard.read()).some(L=>L.types.some(M=>M.startsWith("image/")))&&(I=Date.now(),new ie.Notice("\u526A\u8D34\u677F\u91CC\u6709\u56FE\u7247\uFF0C\u53EF\u4EE5\u76F4\u63A5\u7C98\u8D34\u5230\u5BF9\u8BDD\u6846\u3002"))}catch{}}async function U(m){if(Object.keys(c).length+m.length>Zt){new ie.Notice(`\u6BCF\u6B21\u6700\u591A\u9644\u5E26 ${Zt} \u5F20\u56FE\u7247\u3002`);return}for(let L of m){if(L.size>Ks){new ie.Notice(`${L.name} \u8D85\u8FC7 10 MB\uFF0C\u5DF2\u8DF3\u8FC7\u3002`);continue}let M=await Zs(L),[$,H]=M.split(",",2);if(!H)continue;let K=Qs($)||L.type||"image/png",de=await er(M),je=a++;c[je]={id:je,type:"image",data:H,media_type:K,filename:L.name||`Image ${je}`,width:de?.width,height:de?.height,preview_url:M,size_bytes:L.size},ke(je)}ve(),j()}function W(m,w){let L=te(m),M=w.map($=>({type:"image",filename:$.filename,media_type:$.media_type,width:$.width,height:$.height,preview_url:$.preview_url}));return[...L,...M]}function te(m){let w=Vs(m),L=[];for(let M of w){let $=M.path,H=e.vault.getAbstractFileByPath($);if(H instanceof ie.TFolder){let K={type:"vault_directory",path:$,entry_count:H.children.length};L.push(K)}else if(H instanceof ie.TFile){let K={type:"vault_file",path:$,line_start:M.line_start,line_end:M.line_end};L.push(K)}}return L}function G(m){let w=Array.from(m.matchAll(bt)).map($=>Number($[1])).filter($=>Number.isFinite($)),L=[],M=new Set;for(let $ of w)M.has($)||!c[$]||(M.add($),L.push(c[$]));return L}function le(){let m=new Set(Array.from(s.inputEl.value.matchAll(bt)).map(w=>Number(w[1])));for(let[w,L]of Object.entries(c))m.has(Number(w))||delete c[Number(w)];ve()}function ve(){s.composerPillsEl.empty();for(let m of Object.values(c)){let w=s.composerPillsEl.createDiv({cls:"chat-image-pill"});w.createEl("img",{cls:"chat-image-pill-thumb",attr:{src:m.preview_url,alt:m.filename}}),w.createDiv({cls:"chat-image-pill-label"}).setText(m.filename);let M=w.createEl("button",{cls:"chat-image-pill-remove",attr:{"aria-label":`Remove ${m.filename}`}});M.setText("\xD7"),M.addEventListener("click",()=>{delete c[m.id],s.inputEl.value=s.inputEl.value.replace(new RegExp(`\\s*\\[Image\\s+#${m.id}\\]\\s*`,"g")," ").replace(/[ \t]{2,}/g," ").trim(),Ie(),ve(),j()})}s.composerPillsEl.classList.toggle("has-items",Object.keys(c).length>0)}function j(){let m=Me();if(m){X(Te(m.query,m.from,m.to),`slash:${m.from}:${m.to}:${m.query}`);return}let w=be();if(w){X(Ce(w.query,w.from,w.to),`mention:${w.from}:${w.to}:${w.query}`);return}X([])}function D(){if(s.suggestionListEl.empty(),o.length===0){s.suggestionListEl.classList.remove("is-open");return}s.suggestionListEl.classList.add("is-open"),o.forEach((m,w)=>{let L=s.suggestionListEl.createDiv({cls:"chat-suggestion-item"});w===l&&(L.classList.add("is-selected"),window.setTimeout(()=>{L.scrollIntoView({block:"nearest"})},0)),L.createDiv({cls:"chat-suggestion-title"}).setText(m.label),L.createDiv({cls:"chat-suggestion-desc"}).setText(m.description),L.addEventListener("mousedown",H=>{H.preventDefault(),Y(m)})})}function Y(m){let w=s.inputEl.value,L=w.slice(0,m.replaceFrom),M=w.slice(m.replaceTo);s.inputEl.value=`${L}${m.insertText}${M}`;let $=m.replaceFrom+m.insertText.length;s.inputEl.setSelectionRange($,$),s.inputEl.focus(),Ie(),o=[],x=null,D(),le()}function ce(m){if(o.length>0)return!1;let w=s.inputEl.selectionStart??s.inputEl.value.length,L=s.inputEl.selectionEnd??w;if(w!==L||m==="up"&&!Ls(w)||m==="down"&&!As(L))return!1;let M=_s();return M.length===0?!1:P==null?m==="down"?!1:(k=s.inputEl.value,P=M.length-1,Ve(M[P]),!0):m==="up"?(P===0||(P-=1,Ve(M[P])),!0):P>=M.length-1?(P=null,Ve(k),!0):(P+=1,Ve(M[P]),!0)}function X(m,w=null){let L=o[l],M=w!=null&&w===x;if(o=m,x=w,o.length===0){l=0,D();return}if(M&&L){let $=o.findIndex(H=>Ys(H,L));if($>=0){l=$,D();return}}l=M?Math.min(l,o.length-1):0,D()}function Te(m,w,L){let M=m.trim().toLowerCase();return i.map(H=>({skill:H,score:js(H,M)})).filter(H=>H.score>0||M.length===0).sort((H,K)=>K.score-H.score||H.skill.name.localeCompare(K.skill.name)).slice(0,8).map(({skill:H})=>({kind:"slash",label:`/${H.name}`,description:H.description,replaceFrom:w,replaceTo:L,insertText:`/${H.name} `}))}function Ce(m,w,L){let M=m.trim().toLowerCase();return e.vault.getAllLoadedFiles().filter(qs).map(K=>({candidate:K,score:Ws(K,M)})).filter(K=>K.score>0||M.length===0).sort((K,de)=>de.score-K.score||K.candidate.path.localeCompare(de.candidate.path)).slice(0,8).map(({candidate:K})=>({kind:"mention",label:K instanceof ie.TFolder?`@${K.path}/`:`@${K.path}`,description:K instanceof ie.TFolder?`${K.children.length} items`:K.basename,replaceFrom:w,replaceTo:L,insertText:`${Gs(K.path)} `}))}function Me(){let m=s.inputEl.selectionStart??s.inputEl.value.length,L=s.inputEl.value.slice(0,m).match(Ns);if(!L||L.index==null)return null;let M=L.index+L[1].length,$=m;for(;$<s.inputEl.value.length&&!/\s/.test(s.inputEl.value[$]);)$+=1;return{query:L[2]??"",from:M,to:$}}function be(){let m=s.inputEl.selectionStart??s.inputEl.value.length,w=s.inputEl.value.slice(0,m),L=w.match(Os);if(L&&L.index!=null){let K=L.index+L[1].length,de=m;for(;de<s.inputEl.value.length&&s.inputEl.value[de]!=='"';)de+=1;return s.inputEl.value[de]==='"'&&(de+=1),{query:L[2]??"",from:K,to:de}}let M=w.match(Us);if(!M||M.index==null)return null;let $=M.index+M[1].length,H=m;for(;H<s.inputEl.value.length&&!/\s/.test(s.inputEl.value[H]);)H+=1;return{query:M[2]??"",from:$,to:H}}function ke(m){let w=`[Image #${m}]`;Ts(`${Cs()?" ":""}${w} `),Ie()}function Ts(m){let w=s.inputEl.selectionStart??s.inputEl.value.length,L=s.inputEl.selectionEnd??w,M=s.inputEl.value;s.inputEl.value=`${M.slice(0,w)}${m}${M.slice(L)}`;let $=w+m.length;s.inputEl.setSelectionRange($,$),s.inputEl.focus()}function Ve(m){A=!0,s.inputEl.value=m;let w=m.length;s.inputEl.setSelectionRange(w,w),s.inputEl.focus(),Ie(),le(),j()}function Gt(){P=null,k=""}function _s(){return r.messages.filter(m=>m.role==="user"&&!!m.content.trim()).map(m=>m.content)}function Ls(m){return!s.inputEl.value.slice(0,m).includes(`
`)}function As(m){return!s.inputEl.value.slice(m).includes(`
`)}function Cs(){let m=s.inputEl.selectionStart??s.inputEl.value.length,w=s.inputEl.value[m-1];return!!(w&&!/\s/.test(w))}function Ie(){s.inputEl.style.height="auto",s.inputEl.style.height=`${Math.min(s.inputEl.scrollHeight,120)}px`}return{getSubmitPayload:f,navigateHistory:ce,clear:p,destroy:S}}function zs(t){return t.replace(bt,"").replace(/[ \t]{2,}/g," ").replace(/\n{3,}/g,`

`).trim()}function Vs(t){let e=[],n=new Set;for(let s of t.matchAll(Fs)){let r=`${s[2]??""}${s[3]??""}`;Qt(e,n,r)}for(let s of t.matchAll(Hs)){let r=(s[2]??"").replace(/[.,;:!?]+$/,"");r.startsWith('"')||Qt(e,n,r)}return e}function Qt(t,e,n){if(!n||e.has(n))return;e.add(n);let s=n.match(/^(.*)#L(\d+)(?:-(\d+))?$/);if(!s){t.push({path:n});return}let r=Number(s[2]),i=Number(s[3]??s[2]);t.push({path:s[1],line_start:Math.min(r,i),line_end:Math.max(r,i)})}function js(t,e){if(!e)return 1;let n=t.name.toLowerCase(),s=t.description.toLowerCase();return n.startsWith(e)?5:n.includes(e)?4:(t.aliases??[]).some(r=>r.toLowerCase().startsWith(e))?3.5:s.includes(e)?2:0}function qs(t){return t instanceof ie.TFile||t instanceof ie.TFolder?!!t.path:!1}function Ws(t,e){if(!e)return 1;let n=t.path.toLowerCase(),s=t.name.toLowerCase();return s.startsWith(e)?5:n.startsWith(e)?4.5:s.includes(e)?4:n.includes(e)?3:0}function Gs(t){return/\s/.test(t)?`@"${t}"`:`@${t}`}function Ys(t,e){return t.kind===e.kind&&t.label===e.label&&t.insertText===e.insertText&&t.replaceFrom===e.replaceFrom&&t.replaceTo===e.replaceTo}function Js(t){return Array.from(t.clipboardData?.items??[]).filter(n=>n.type.startsWith("image/")).map(n=>n.getAsFile()).filter(n=>n!=null)}function kt(t){return Array.from(t??[]).filter(e=>e.type.startsWith("image/"))}function Xs(t){return kt(t).length>0}function Zs(t){return new Promise((e,n)=>{let s=new FileReader;s.onload=()=>e(String(s.result)),s.onerror=()=>n(s.error),s.readAsDataURL(t)})}function Qs(t){let e=t.match(/^data:([^;]+);base64$/);return e?e[1]:null}function er(t){return new Promise(e=>{let n=new Image;n.onload=()=>e({width:n.width,height:n.height}),n.onerror=()=>e(null),n.src=t})}var qe=`
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none"
      stroke="currentColor" stroke-width="2.5"
      stroke-linecap="round" stroke-linejoin="round">
      <line x1="12" y1="19" x2="12" y2="5"/>
      <polyline points="5 12 12 5 19 12"/>
    </svg>`,tn=`
    <svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor">
      <rect x="4" y="4" width="16" height="16" rx="3"/>
    </svg>`,nn=`
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none"
      stroke="currentColor" stroke-width="2"
      stroke-linecap="round" stroke-linejoin="round">
      <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
      <path d="M3 3v5h5"/>
      <path d="M12 7v5l4 2"/>
    </svg>`,sn=`
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none"
      stroke="currentColor" stroke-width="2.5"
      stroke-linecap="round" stroke-linejoin="round">
      <line x1="12" y1="5" x2="12" y2="19"/>
      <line x1="5" y1="12" x2="19" y2="12"/>
    </svg>`,rn=`
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none"
      stroke="currentColor" stroke-width="2"
      stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 3v5"/>
      <path d="M6 13v3"/>
      <path d="M18 13v3"/>
      <path d="M6 21v-2"/>
      <path d="M18 21v-2"/>
      <path d="M12 8H6a2 2 0 0 0-2 2v3"/>
      <path d="M12 8h6a2 2 0 0 1 2 2v3"/>
      <circle cx="12" cy="3" r="2"/>
      <circle cx="6" cy="16" r="2"/>
      <circle cx="18" cy="16" r="2"/>
    </svg>`,an=`
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
      stroke="currentColor" stroke-width="2"
      stroke-linecap="round" stroke-linejoin="round">
      <circle cx="6" cy="18" r="3"/>
      <circle cx="6" cy="6" r="3"/>
      <circle cx="18" cy="6" r="3"/>
      <path d="M6 9v6"/>
      <path d="M9 6h3a6 6 0 0 1 6 6v3"/>
    </svg>`,on=`
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none"
      stroke="currentColor" stroke-width="2"
      stroke-linecap="round" stroke-linejoin="round">
      <path d="M21.44 11.05l-8.49 8.49a6 6 0 1 1-8.49-8.49l9.19-9.19a4 4 0 1 1 5.66 5.66L9.41 17.41a2 2 0 1 1-2.83-2.83l8.49-8.48"/>
    </svg>`,ln=`
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
      stroke="currentColor" stroke-width="2"
      stroke-linecap="round" stroke-linejoin="round">
      <polyline points="3 6 5 6 21 6"/>
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
    </svg>`;function cn(t){let e=t.toLowerCase();return e==="bash"||e==="shell"||e==="run_command"?">_":e.includes("read")||e.includes("file")?"\u{1F4C4}":e.includes("write")?"\u270F\uFE0F":e.includes("search")||e.includes("grep")?"\u{1F50D}":e.includes("mempalace")||e.includes("memory")?"\u{1F9E0}":e.includes("browser")||e.includes("web")?"\u{1F310}":"\u{1F527}"}var dn=require("obsidian");function un(t,e,n){let s=t.createDiv({cls:"chat-custom-select"});s.addClass("chat-persona-select");let r=s.createDiv({cls:"custom-select-trigger"});r.innerHTML=`<span>Persona</span>
      <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>
    `;let i=s.createDiv({cls:"custom-select-dropdown"}),a=[],c=[],o=()=>{c=[{kind:"auto",id:"auto",label:"Auto"},{kind:"none",id:"none",label:"No Persona"},...a.map(v=>({kind:"manual",id:v.id,label:v.title}))]},l=v=>v?a.find(g=>g.id===v)?.title??v:null,x=v=>v.mode==="none"?"none":v.mode==="manual"?v.manual_persona_id??"manual":"auto",P=v=>{if(v.mode==="none")return"No Persona";if(v.mode==="manual")return l(v.manual_persona_id)??"Manual";let g=l(v.active_persona_id);return g?`Auto / ${g}`:"Auto"},k=()=>{r.querySelector("span")?.setText(P(n.personaState));let v=x(n.personaState);Array.from(i.children).forEach(g=>{let y=g;y.classList.toggle("selected",y.dataset.optionKey===v)})},A=v=>{n.personaState={...xe(),...v},k()},d=v=>v.kind==="none"?{mode:"none",manual_persona_id:null,active_persona_id:null,source:"none",status:"disabled"}:v.kind==="manual"?{mode:"manual",manual_persona_id:v.id,active_persona_id:v.id,source:"manual",status:"manual"}:xe(),I=()=>{i.empty(),o();for(let v of c){let g=i.createDiv({cls:"custom-select-option"});g.dataset.optionKey=v.kind==="manual"?v.id:v.kind,g.createEl("span",{cls:"cso-name"}).setText(v.label),g.createEl("span",{cls:"cso-provider cso-meta"}).setText(v.kind==="auto"?"AUTO":v.kind==="none"?"OFF":"MANUAL"),g.addEventListener("click",async O=>{O.stopPropagation(),s.classList.remove("open");let q=n.personaState,F=d(v);A(F);let b=e.sessionId;if(b)try{let E=await e.patchSession(b,{persona_mode:F.mode,manual_persona_id:F.manual_persona_id});A(E.persona_state)}catch(E){A(q);let u=E instanceof Error?E.message:String(E);new dn.Notice(`Persona switch failed: ${u}`)}})}k()};e.listPersonas().then(v=>{a=v,I()}).catch(v=>{console.warn("[ChatView] listPersonas failed:",v),I()}),I(),r.addEventListener("click",v=>{v.stopPropagation(),v.preventDefault(),s.classList.toggle("open")});let C=v=>{s.contains(v.target)||s.classList.remove("open")};return document.addEventListener("click",C),{setPersonaState:A,destroy:()=>{document.removeEventListener("click",C)}}}var nt=require("obsidian");var ye=require("node:fs"),Je=require("node:path");var We=["anthropic","openai","ollama","deepseek","qwen","kimi","minimax","zhipu","custom_openai"],Pe={baseUrl:!0,apiKey:!0,vision:!1,thinking:!1,thinkingBudget:!1,reasoningEffort:!1,reasoningSplit:!1},tr={anthropic:{id:"anthropic",label:"Anthropic",badge:"#d97706",defaultBaseUrl:"",apiKeyEnv:"ANTHROPIC_API_KEY",models:[{id:"claude-sonnet-4-20250514",label:"Claude Sonnet 4"}],capabilities:{...Pe,baseUrl:!1,vision:!0,thinking:!0,thinkingBudget:!0}},openai:{id:"openai",label:"OpenAI",badge:"#059669",defaultBaseUrl:"https://api.openai.com/v1",apiKeyEnv:"OPENAI_API_KEY",models:[{id:"gpt-5.4-mini",label:"GPT-5.4 Mini",supportsVision:!0},{id:"gpt-5.4",label:"GPT-5.4",supportsVision:!0}],capabilities:{...Pe,vision:!0,reasoningEffort:!0},reasoningEfforts:["none","minimal","low","medium","high","xhigh"]},ollama:{id:"ollama",label:"Ollama",badge:"#2563eb",defaultBaseUrl:"http://localhost:11434",apiKeyEnv:"",models:[{id:"llama3.1",label:"llama3.1"},{id:"qwen2.5",label:"qwen2.5"}],capabilities:{...Pe,apiKey:!1,vision:!0}},deepseek:{id:"deepseek",label:"DeepSeek",badge:"#4f46e5",defaultBaseUrl:"https://api.deepseek.com",apiKeyEnv:"DEEPSEEK_API_KEY",models:[{id:"deepseek-v4-flash",label:"DeepSeek V4 Flash"},{id:"deepseek-v4-pro",label:"DeepSeek V4 Pro"}],capabilities:{...Pe,thinking:!0,reasoningEffort:!0},reasoningEfforts:["high","max"]},qwen:{id:"qwen",label:"Qwen Coding Plan",badge:"#0891b2",defaultBaseUrl:"https://coding.dashscope.aliyuncs.com/v1",apiKeyEnv:"BAILIAN_CODING_PLAN_API_KEY",models:[{id:"qwen3.6-plus",label:"\u5343\u95EE qwen3.6-plus",supportsVision:!0,supportsThinking:!0},{id:"qwen3.5-plus",label:"\u5343\u95EE qwen3.5-plus",supportsVision:!0,supportsThinking:!0},{id:"qwen3-max-2026-01-23",label:"\u5343\u95EE qwen3-max-2026-01-23",supportsVision:!1,supportsThinking:!0},{id:"qwen3-coder-next",label:"\u5343\u95EE qwen3-coder-next",supportsVision:!1,supportsThinking:!1},{id:"qwen3-coder-plus",label:"\u5343\u95EE qwen3-coder-plus",supportsVision:!1,supportsThinking:!1},{id:"glm-5",label:"\u667A\u8C31 glm-5",supportsVision:!1,supportsThinking:!0},{id:"glm-4.7",label:"\u667A\u8C31 glm-4.7",supportsVision:!1,supportsThinking:!0},{id:"kimi-k2.5",label:"Kimi kimi-k2.5",supportsVision:!0,supportsThinking:!0},{id:"MiniMax-M2.5",label:"MiniMax M2.5",supportsVision:!1,supportsThinking:!0}],capabilities:{...Pe,vision:!0,thinking:!0}},kimi:{id:"kimi",label:"Kimi Code",badge:"#7c3aed",defaultBaseUrl:"https://api.kimi.com/coding/v1",apiKeyEnv:"KIMI_API_KEY",models:[{id:"kimi-for-coding",label:"Kimi for Coding",supportsVision:!0,supportsThinking:!0}],capabilities:{...Pe,vision:!0,thinking:!0}},minimax:{id:"minimax",label:"MiniMax",badge:"#db2777",defaultBaseUrl:"https://api.minimax.io/v1",apiKeyEnv:"MINIMAX_API_KEY",models:[{id:"MiniMax-M2.7",label:"MiniMax M2.7"},{id:"MiniMax-M2.7-highspeed",label:"MiniMax M2.7 Highspeed"},{id:"MiniMax-M2.5",label:"MiniMax M2.5"}],capabilities:{...Pe,reasoningSplit:!0}},zhipu:{id:"zhipu",label:"Zhipu GLM",badge:"#16a34a",defaultBaseUrl:"https://open.bigmodel.cn/api/paas/v4",apiKeyEnv:"ZAI_API_KEY",models:[{id:"glm-5.1",label:"GLM-5.1"},{id:"glm-5-turbo",label:"GLM-5 Turbo"},{id:"glm-4.7",label:"GLM-4.7"},{id:"glm-4.7-flash",label:"GLM-4.7 Flash"}],capabilities:{...Pe,vision:!0,thinking:!0}},custom_openai:{id:"custom_openai",label:"Custom OpenAI",badge:"#64748b",defaultBaseUrl:"https://api.openai.com/v1",apiKeyEnv:"LLM_API_KEY",models:[],capabilities:{...Pe,vision:!0,thinking:!0,thinkingBudget:!0,reasoningEffort:!0,reasoningSplit:!0},reasoningEfforts:["none","minimal","low","medium","high","max","xhigh"]}};function xt(t){return typeof t=="string"&&We.includes(t)}function Ge(t){return xt(t)?t:"custom_openai"}function ae(t){return tr[t]}function pn(t){return ae(t).reasoningEfforts?.join(" | ")??""}function gn(t){return ae(t).models[0]?.id??""}function Pt(t,e){return ae(t).models.find(n=>n.id===e)}var Xe="X-Life-Assistant-Admin-Token",mn="LIFE_ASSISTANT_ADMIN_ENABLED",Ye="LIFE_ASSISTANT_ADMIN_TOKEN",Oe="VAULT_PATH",vn=/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/;function Se(t){let e=t.backendEnvPath?.trim();return e?{ok:!0,envPath:(0,Je.resolve)(e),derivedFromLegacyPath:!1,message:""}:{ok:!1,derivedFromLegacyPath:!1,message:"\u8BF7\u5148\u914D\u7F6E\u201C\u540E\u7AEF .env \u8DEF\u5F84\u201D\uFF0C\u518D\u4FDD\u5B58\u6216\u5207\u6362 LLM \u914D\u7F6E\u3002"}}function ue(t,e){if(!(0,ye.existsSync)(t))return null;for(let[n,s]of nr(t))if(n===e)return s;return null}function Ze(t){let e=Se(t);if(!e.ok||!e.envPath)return{ok:!1,message:e.message};let n=ue(e.envPath,Ye)?.trim();return n?{ok:!0,adminToken:n,envPath:e.envPath,message:""}:{ok:!1,envPath:e.envPath,message:`${e.envPath} \u7F3A\u5C11 ${Ye}\u3002`}}function nr(t){if(!(0,ye.existsSync)(t))return[];let n=(0,ye.readFileSync)(t,"utf8").split(/\r?\n/),s=[];for(let r of n){let i=r.match(vn);i&&s.push([i[1],cr(i[2])])}return s}function Re(t,e){let n=(0,ye.existsSync)(t)?(0,ye.readFileSync)(t,"utf8"):"",s=n.includes(`\r
`)?`\r
`:`
`,r=n===""?[]:n.split(/\r?\n/),i=new Map(Object.entries(e)),a=[];for(let o of r){let l=o.match(vn);if(!l){a.push(o);continue}let x=l[1];if(!i.has(x)){a.push(o);continue}let P=i.get(x)??null;i.delete(x),P!==null&&a.push(`${x}=${fn(P)}`)}for(let[o,l]of i.entries())l!==null&&a.push(`${o}=${fn(l)}`);let c=a.join(s);(0,ye.writeFileSync)(t,c===""?"":`${c}${s}`,"utf8")}async function Qe(t,e){let n=Ze(t);if(!n.ok||!n.adminToken)return{ok:!1,message:n.message,envPath:n.envPath};let s=await e.listLlmProfiles(n.adminToken);return tt(t,s,"\u5DF2\u4ECE\u540E\u7AEF\u8BFB\u53D6 LLM \u914D\u7F6E\u3002")}async function Ee(t,e,n,s=!1){let r=Ze(t);if(!r.ok||!r.adminToken)return{ok:!1,message:r.message,envPath:r.envPath};let i=await n.saveLlmProfile(r.adminToken,rr(e),s);return tt(t,i,s?`\u5DF2\u4FDD\u5B58\u5E76\u542F\u7528 ${e.name}\u3002`:`\u5DF2\u4FDD\u5B58 ${e.name} \u5230\u540E\u7AEF\u3002`)}async function De(t,e,n){let s=Ze(t);if(!s.ok||!s.adminToken)return{ok:!1,message:s.message,envPath:s.envPath};let r=await n.activateLlmProfile(s.adminToken,e);return tt(t,r,"\u5DF2\u5207\u6362\u540E\u7AEF LLM \u914D\u7F6E\u3002")}async function et(t,e,n){let s=Ze(t);if(!s.ok||!s.adminToken)return{ok:!1,message:s.message,envPath:s.envPath};let r=await n.deleteLlmProfile(s.adminToken,e);return tt(t,r,"\u5DF2\u4ECE\u540E\u7AEF\u5220\u9664 LLM \u914D\u7F6E\u3002")}function tt(t,e,n){return!e.ok||!e.data?{ok:!1,reloadStatus:e.status,message:ar(e)}:(sr(t,e.data),{ok:!0,envPath:e.data.envPath,reloadStatus:e.status,profiles:t.llmProfiles,activeProfileId:t.activeProfileId,message:n})}function sr(t,e){t.llmProfiles=e.profiles.map(ir),t.activeProfileId=e.activeProfileId}function rr(t){return{id:t.id,name:t.name,provider:t.provider,model:t.model,baseUrl:t.baseUrl,apiKey:t.apiKey,supportsVision:t.supportsVision,thinkingMode:t.thinkingMode,thinkingEffort:t.thinkingEffort,thinkingBudgetTokens:t.thinkingBudgetTokens,reasoningSplit:t.reasoningSplit}}function ir(t){return{id:t.id,name:t.name,provider:xt(t.provider)?t.provider:"custom_openai",model:t.model,baseUrl:t.baseUrl,apiKey:t.apiKey,supportsVision:!!t.supportsVision,thinkingMode:t.thinkingMode,thinkingEffort:t.thinkingEffort,thinkingBudgetTokens:t.thinkingBudgetTokens||"1024",reasoningSplit:!!t.reasoningSplit}}function ar(t){return t.status===null?"\u540E\u7AEF\u5F53\u524D\u4E0D\u53EF\u8BBF\u95EE\u3002":t.detail||`HTTP ${t.status}`}async function bn(t,e,n){let s=Se(t);if(!s.ok||!s.envPath)return{ok:!1,message:s.message,changed:!1};let r=e.trim();if(!r)return{ok:!1,envPath:s.envPath,needsMigration:s.derivedFromLegacyPath,changed:!1,message:"\u65E0\u6CD5\u68C0\u6D4B\u5F53\u524D Obsidian vault \u8DEF\u5F84\u3002"};let i=(0,Je.resolve)(r),a=ue(s.envPath,Oe);if(a&&lr(a,i))return{ok:!0,envPath:s.envPath,needsMigration:s.derivedFromLegacyPath,changed:!1,message:`\u5F53\u524D vault \u8DEF\u5F84\u5DF2\u7ECF\u540C\u6B65\uFF1A${i}`};Re(s.envPath,{[Oe]:i});let c=ue(s.envPath,mn);if(!Ue(c))return{ok:!1,envPath:s.envPath,needsMigration:s.derivedFromLegacyPath,changed:!0,message:`\u5DF2\u5C06 ${Oe}=${i} \u4FDD\u5B58\u5230 ${s.envPath}\uFF0C\u4F46\u540E\u7AEF\u70ED\u91CD\u8F7D\u672A\u5F00\u542F\u3002\u8BF7\u8BBE\u7F6E ${mn}=true \u540E\u518D\u8BD5\u3002`};let o=ue(s.envPath,Ye)?.trim();if(!o)return{ok:!1,envPath:s.envPath,needsMigration:s.derivedFromLegacyPath,changed:!0,message:`\u5DF2\u5C06 ${Oe}=${i} \u4FDD\u5B58\u5230 ${s.envPath}\uFF0C\u4F46\u7F3A\u5C11 ${Ye}\u3002`};let l=await n.reloadSettings(o);return l.ok?{ok:!0,envPath:s.envPath,needsMigration:s.derivedFromLegacyPath,reloadStatus:l.status,changed:!0,message:s.derivedFromLegacyPath?`\u5DF2\u540C\u6B65 vault \u8DEF\u5F84\u5230 ${i}\uFF0C\u5E76\u5B8C\u6210\u540E\u7AEF\u70ED\u91CD\u8F7D\u3002${s.message}`:`\u5DF2\u540C\u6B65 vault \u8DEF\u5F84\u5230 ${i}\uFF0C\u5E76\u5B8C\u6210\u540E\u7AEF\u70ED\u91CD\u8F7D\u3002`}:{ok:!1,envPath:s.envPath,needsMigration:s.derivedFromLegacyPath,reloadStatus:l.status,changed:!0,message:`\u5DF2\u5C06 ${Oe}=${i} \u4FDD\u5B58\u5230 ${s.envPath}\uFF0C\u4F46\u540E\u7AEF\u91CD\u8F7D\u5931\u8D25`+or(l)+"\u3002"}}function Ue(t){return t?["1","true","yes","on"].includes(t.trim().toLowerCase()):!1}function or(t){return t.status===null?"\uFF1A\u540E\u7AEF\u5F53\u524D\u4E0D\u53EF\u8BBF\u95EE":t.detail?`\uFF08HTTP ${t.status}\uFF09\uFF1A${t.detail}`:`\uFF08HTTP ${t.status}\uFF09`}function lr(t,e){return hn(t)===hn(e)}function hn(t){let e=(0,Je.resolve)(t);return process.platform==="win32"?e.toLowerCase():e}function cr(t){if(t.startsWith('"')&&t.endsWith('"'))try{return JSON.parse(t)}catch{return t.slice(1,-1)}return t.startsWith("'")&&t.endsWith("'")?t.slice(1,-1):t}function fn(t){return t===""?'""':/[#\s"'\\]/.test(t)?JSON.stringify(t):t}function yt(t){return t.name.trim()||t.model.trim()||ae(t.provider).label}function dr(t){return ae(t.provider).label.toUpperCase()}function kn(t,e,n){let s=t.createDiv({cls:"chat-custom-select"}),r=s.createDiv({cls:"custom-select-trigger"});r.innerHTML=`<span>Select Model</span>
      <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>
    `;let i=s.createDiv({cls:"custom-select-dropdown"}),a=[],c=()=>e.settings.llmProfiles.find(k=>k.id===e.settings.activeProfileId)??e.settings.llmProfiles[0],o=()=>{let k=c();r.querySelector("span")?.setText(k?yt(k):"Select Model"),a.forEach(({optionEl:A,profileId:d})=>{A.classList.toggle("selected",d===e.settings.activeProfileId)})},l=()=>{if(i.empty(),a=[],e.settings.llmProfiles.length===0){i.createDiv({cls:"custom-select-option custom-select-option-empty"}).setText("No LLM profiles"),o();return}e.settings.llmProfiles.forEach(k=>{let A=i.createDiv({cls:"custom-select-option"});a.push({profileId:k.id,optionEl:A});let d=A.createDiv({cls:"cso-label"});d.createEl("span",{cls:"cso-name"}).setText(yt(k)),d.createEl("span",{cls:"cso-model"}).setText(`${ae(k.provider).label} / ${k.model}`);let v=A.createEl("span",{cls:"cso-provider"});v.setText(dr(k)),v.setAttribute("data-provider",k.provider),A.addEventListener("click",async g=>{g.stopPropagation(),s.classList.remove("open");let y=e.settings.llmProfiles.find(R=>R.id===k.id)??k;if(y.id===e.settings.activeProfileId){o();return}try{let R=await De(e.settings,y.id,n);if(R.ok){await e.saveSettings(),l(),new nt.Notice(`Switched to model: ${yt(y)}`);return}o(),new nt.Notice(`Profile switch failed: ${R.message}`)}catch(R){o();let O=R instanceof Error?R.message:String(R);new nt.Notice(`Profile switch failed: ${O}`)}})}),o()};l(),r.addEventListener("click",k=>{k.stopPropagation(),k.preventDefault(),l(),s.classList.toggle("open")});let x=k=>{s.contains(k.target)||s.classList.remove("open")},P=()=>{l()};return document.addEventListener("click",x),document.addEventListener(Le,P),()=>{document.removeEventListener("click",x),document.removeEventListener(Le,P)}}var ge=require("obsidian");var xn=require("obsidian"),ur="<think>",pr="</think>",gr="<thinking>",mr="</thinking>",Pn="<think-json>",yn="</think-json>",hr="Crabby",Sn=[{open:Pn,close:yn,encoded:!0},{open:ur,close:pr,allowNested:!0},{open:gr,close:mr,allowNested:!0}];function St(t){let e=t.createDiv({cls:"chat-assistant-header"});return e.createSpan({cls:"chat-assistant-name",text:hr}),e}function En(t,e,n,s){n.empty();let r=Et(s);if(r.thoughtText&&Tn(n,r.thoughtText),r.visibleMarkdown.trim()){let i=n.createDiv({cls:"chat-assistant-markdown"});xn.MarkdownRenderer.render(t,r.visibleMarkdown,i,"",e)}}function wn(t){t.empty();let e=t.createDiv({cls:"chat-assistant-shell"});St(e);let n=e.createDiv({cls:"chat-assistant-content"}),s=null,r=null;return{render(i,a){let c=a.trim();c&&(s?s.updateThoughtText(c):s=Tn(n,c,{streaming:!0})),i?(r||(r=n.createDiv({cls:"chat-assistant-markdown chat-assistant-streaming-text"})),r.setText(i)):r&&(r.remove(),r=null)}}}function st(t,e){let n=t.trim();return n?`${Pn}${Pr(n)}${yn}

${e}`.trim():e}function Et(t){if(!fr(t))return{visibleMarkdown:t,thoughtText:""};let e=[],n=[],s=0;for(;s<t.length;){let r=vr(t,s);if(!r){e.push(t.slice(s));break}let{tag:i,openIndex:a}=r,c=br(t,i,a);if(c<0)return{visibleMarkdown:t,thoughtText:""};e.push(t.slice(s,a));let o=t.slice(a+i.open.length,c),l=xr(o,i);l&&n.push(l),s=c+i.close.length}return{visibleMarkdown:Sr(e.join("")),thoughtText:n.join(`

`)}}function fr(t){return Sn.some(e=>t.includes(e.open))}function vr(t,e){let n=null;for(let s of Sn){let r=t.indexOf(s.open,e);r>=0&&(!n||r<n.openIndex)&&(n={tag:s,openIndex:r})}return n}function br(t,e,n){let s=n+e.open.length;if(!e.allowNested)return t.indexOf(e.close,s);let r=kr(t,e,n);if(r>=0)return r;let i=1,a=s;for(;a<t.length;){let c=t.indexOf(e.open,a),o=t.indexOf(e.close,a);if(o<0)return-1;if(c>=0&&c<o){i+=1,a=c+e.open.length;continue}if(i-=1,i===0)return o;a=o+e.close.length}return-1}function kr(t,e,n){if(n!==0)return-1;let s=`
${e.close}

`,r=t.lastIndexOf(s);if(r>=0)return r+1;let i=`
${e.close}`;return t.endsWith(i)?t.length-e.close.length:-1}function xr(t,e){return((e.encoded?yr(t):t)??t).trim()}function Pr(t){return JSON.stringify(t).replace(/[<>&]/g,e=>e==="<"?"\\u003c":e===">"?"\\u003e":"\\u0026")}function yr(t){try{let e=JSON.parse(t);return typeof e=="string"?e:null}catch{return null}}function Tn(t,e,n={}){let s=t.createDiv({cls:n.streaming?"chat-thought-block streaming":"chat-thought-block"}),r=s.createDiv({cls:"chat-thought-header"});r.setAttribute("role","button"),r.setAttribute("tabindex","0"),r.setAttribute("aria-expanded","false"),r.createSpan({cls:"chat-thought-title"}).setText("\u601D\u7EF4\u94FE");let a=r.createSpan({cls:"chat-thought-preview"}),c=r.createSpan({cls:"chat-thought-chevron"});c.setText(">");let o=s.createDiv({cls:"chat-thought-body"}),l=P=>{let k=Er(P);a.classList.toggle("is-empty",!k),a.setText(k?k.slice(0,72)+(k.length>72?"...":""):""),o.setText(P)},x=()=>{let P=!s.classList.contains("expanded");s.classList.toggle("expanded",P),r.setAttribute("aria-expanded",P?"true":"false"),c.setText(P?"v":">")};return r.addEventListener("click",x),r.addEventListener("keydown",P=>{(P.key==="Enter"||P.key===" ")&&(P.preventDefault(),x())}),l(e),{updateThoughtText:l}}function Sr(t){return t.replace(/\n{3,}/g,`

`).trim()}function Er(t){return t.trim().split(`
`).find(e=>e.trim())}function wr(t){if(t==null||Number.isNaN(t))return"\u672A\u77E5\u65F6\u95F4";let e=t>1e10?t:t*1e3;if(e===0)return"\u65E9\u671F\u4F1A\u8BDD";let n=Date.now()-e;if(n<0)return"\u521A\u521A";let s=Math.floor(n/6e4);if(s<1)return"\u521A\u521A";if(s<60)return`${s} \u5206\u949F\u524D`;let r=Math.floor(s/60);if(r<24)return`${r} \u5C0F\u65F6\u524D`;let i=Math.floor(r/24);if(i<7)return`${i} \u5929\u524D`;let a=new Date(e);return`${a.getFullYear()}/${a.getMonth()+1}/${a.getDate()}`}function Tr(t){let e=t.reasoning_details;return Array.isArray(e)?e.map(n=>typeof n=="object"&&n!==null&&typeof n.text=="string"?n.text:"").join(""):typeof t.thinking=="string"?t.thinking:""}var wt=class extends ge.Modal{constructor(n,s,r,i){super(n);this.sourcePreview=s;this.suggestedTitle=r;this.resolved=!1;this.resolve=i}onOpen(){let{contentEl:n}=this;n.empty(),n.addClass("fork-conversation-modal"),n.createEl("h2",{text:"\u786E\u8BA4\u5206\u53C9\u6807\u9898"});let s=n.createDiv({cls:"fork-conversation-preview"});s.createEl("div",{cls:"fork-conversation-label",text:"\u6765\u6E90\u6D88\u606F"}),s.createEl("div",{cls:"fork-conversation-text",text:this.sourcePreview});let r=n.createDiv({cls:"fork-conversation-title"});r.createEl("div",{cls:"fork-conversation-label",text:"\u5206\u652F\u6807\u9898"}),this.titleInput=r.createEl("input",{cls:"fork-conversation-input",attr:{type:"text",value:this.suggestedTitle,spellcheck:"false"}}),this.titleInput.addEventListener("keydown",o=>{o.key==="Enter"&&(o.preventDefault(),this.submit()),o.key==="Escape"&&(o.preventDefault(),this.close())});let i=n.createDiv({cls:"fork-conversation-actions"});i.createEl("button",{cls:"mod-muted",text:"\u53D6\u6D88"}).addEventListener("click",()=>this.close()),i.createEl("button",{cls:"mod-cta",text:"\u5206\u53C9"}).addEventListener("click",()=>this.submit()),window.requestAnimationFrame(()=>{this.titleInput.focus(),this.titleInput.select()})}onClose(){this.resolved||(this.resolved=!0,this.resolve(null)),this.contentEl.removeClass("fork-conversation-modal"),this.contentEl.empty()}submit(){this.resolved||(this.resolved=!0,this.resolve(this.titleInput.value.trim()),this.close())}};function _r(t,e,n){return new Promise(s=>{new wt(t,e,n,s).open()})}function _n(t){return(Et(t).visibleMarkdown||t).replace(/\s+/g," ").trim()}function Lr(t){return _n(t).slice(0,40)||"\u65B0\u5206\u652F"}function Ar(t){return _n(t).slice(0,160)||"\uFF08\u7A7A\u6D88\u606F\uFF09"}function Cr(t){let e=new Map;for(let r of t)e.set(r.id,{...r,children:[]});let n=[];for(let r of e.values()){let i=r.parent_id??"",a=i?e.get(i):void 0;a?a.children.push(r):n.push(r)}let s=r=>{r.sort((i,a)=>i.created_at!==a.created_at?i.created_at-a.created_at:i.id.localeCompare(a.id));for(let i of r)i.children.length>0&&s(i.children)};return s(n),n}function Ln(t){let{app:e,client:n,composer:s,elements:r,state:i,transcript:a,persona:c}=t;a.setForkHandler(u=>{q(u)});async function o(){r.sessionListEl.empty(),r.sessionListEl.createDiv({cls:"session-loading"}).setText("\u52A0\u8F7D\u4E2D...");try{let h=await n.listSessions();if(r.sessionListEl.empty(),h.length===0){r.sessionListEl.createDiv({cls:"session-empty"}).setText("\u6682\u65E0\u5386\u53F2\u4F1A\u8BDD");return}for(let f of h)F(f)}catch{r.sessionListEl.empty(),r.sessionListEl.createDiv({cls:"session-error"}).setText("\u52A0\u8F7D\u5931\u8D25\uFF0C\u8BF7\u68C0\u67E5\u540E\u7AEF\u8FDE\u63A5")}}async function l(){if(!i.treePanelOpen)return;r.treeListEl.empty(),r.treeListEl.createDiv({cls:"conversation-tree-loading"}).setText("\u52A0\u8F7D\u4E2D...");let h=n.sessionId;if(!h){r.treeListEl.empty(),r.treeListEl.createDiv({cls:"conversation-tree-empty"}).setText("\u5F53\u524D\u8FD8\u6CA1\u6709\u53EF\u663E\u793A\u7684\u4F1A\u8BDD\u6811"),r.treePanelTitleEl.setText("\u4F1A\u8BDD\u6811");return}try{let[f,p]=await Promise.all([n.getSession(h),n.listConversations(h)]);if(!i.treePanelOpen||n.sessionId!==h)return;if(r.treePanelTitleEl.setText(f.title?`\u4F1A\u8BDD\u6811 \xB7 ${f.title}`:"\u4F1A\u8BDD\u6811"),r.treeListEl.empty(),p.length===0){r.treeListEl.createDiv({cls:"conversation-tree-empty"}).setText("\u5F53\u524D\u4F1A\u8BDD\u5C1A\u65E0\u5206\u652F");return}let S=Cr(p);b(S,r.treeListEl,f.id)}catch(f){if(!i.treePanelOpen)return;r.treeListEl.empty();let p=f instanceof Error?f.message:String(f);r.treeListEl.createDiv({cls:"conversation-tree-error"}).setText(`\u4F1A\u8BDD\u6811\u52A0\u8F7D\u5931\u8D25\uFF1A${p}`)}}function x(){i.sessionPanelOpen=!0,i.treePanelOpen=!1,r.sessionPanelEl.addClass("open"),r.treePanelEl.removeClass("open")}function P(){i.sessionPanelOpen=!1,r.sessionPanelEl.removeClass("open")}function k(){i.treePanelOpen=!0,i.sessionPanelOpen=!1,r.treePanelEl.addClass("open"),r.sessionPanelEl.removeClass("open")}function A(){i.treePanelOpen=!1,r.treePanelEl.removeClass("open")}function d(){if(i.sessionPanelOpen){P();return}x(),o()}function I(){if(i.treePanelOpen){A();return}k(),l()}function C(){P(),A(),n.disconnect(),a.clearConversationUi(),s.clear(),c.setPersonaState(xe()),r.sessionTitleEl.setText("\u65B0\u4F1A\u8BDD"),r.treePanelTitleEl.setText("\u4F1A\u8BDD\u6811"),r.treeListEl.empty(),a.appendMessage("assistant","\u4F60\u597D\uFF01\u65B0\u4F1A\u8BDD\u5DF2\u7ECF\u5F00\u59CB\u4E86\uFF0C\u6709\u4EC0\u4E48\u53EF\u4EE5\u5E2E\u4F60\u7684\uFF1F")}async function v(u){try{let h=u.active_conversation_id,f=[],p=null;try{f=await n.getConversationMessages(u.id,h)}catch(T){console.warn("[ChatView] getConversationMessages failed:",T)}try{p=await n.getConversationContextStats(u.id,h)}catch(T){console.warn("[ChatView] getConversationContextStats failed:",T)}n.setSession(u.id,h),c.setPersonaState(u.persona_state??xe()),r.sessionTitleEl.setText(u.title||"\u672A\u547D\u540D\u4F1A\u8BDD"),a.clearConversationUi(),s.clear();let S=new Map;for(let T of f)if(T.role==="user"&&Array.isArray(T.content)){for(let _ of T.content)if(_.type==="tool_result"&&_.tool_use_id){let U=typeof _.content=="string"?_.content:JSON.stringify(_.content||"");S.set(_.tool_use_id,U)}}for(let T of f)T.role==="user"?g(T):T.role==="assistant"&&y(T,S);p&&a.updateContextBar(p),a.scrollToBottom(!0),i.treePanelOpen&&await l()}catch(h){let f=h instanceof Error?h.message:String(h);console.error("[ChatView] switchToSession failed:",h),new ge.Notice(`\u5207\u6362\u4F1A\u8BDD\u5931\u8D25: ${f}`)}}function g(u){let h=Array.isArray(u.attachments)?u.attachments:[];if(typeof u.text=="string"){a.appendMessage("user",u.text,!1,h,u.message_id);return}let f=!1;if(typeof u.content=="string")a.appendMessage("user",u.content,!1,h,u.message_id),f=!0;else if(Array.isArray(u.content)){let p=u.content.filter(S=>S.type==="text"&&S.text).map(S=>S.text).join(`
`);(p||h.length>0)&&(a.appendMessage("user",p,!1,h,u.message_id),f=!0)}!f&&!Array.isArray(u.content)&&u.content&&a.appendMessage("user",JSON.stringify(u.content),!1,h,u.message_id)}function y(u,h){if(Array.isArray(u.content)){let f="",p="",S=!1,T=()=>{let _=st(f,p);_.trim()&&(a.appendMessage("assistant",_,!1,[],!S&&u.message_id?u.message_id:void 0),S=!0),f="",p=""};for(let _ of u.content)_.type==="reasoning_details"||_.type==="thinking"?f+=Tr(_):_.type==="text"&&_.text?p+=`${p?`
`:""}${_.text}`:_.type==="tool_use"&&_.name&&(T(),a.renderHistoricalTool(_.name,h.get(_.id)||"(no output)"));T();return}typeof u.content=="string"&&u.content&&a.appendMessage("assistant",u.content,!1,[],u.message_id)}async function R(u){try{await n.deleteSession(u),new ge.Notice("\u4F1A\u8BDD\u5DF2\u5220\u9664"),await o(),n.sessionId===null&&(A(),r.treePanelTitleEl.setText("\u4F1A\u8BDD\u6811"),r.treeListEl.empty())}catch{new ge.Notice("\u5220\u9664\u5931\u8D25")}}async function O(u){if(n.sessionId===u)try{let f=(await n.listSessions()).find(p=>p.id===u);if(!f)return;r.sessionTitleEl.getText()==="\u65B0\u4F1A\u8BDD"&&f.title&&r.sessionTitleEl.setText(f.title),i.treePanelOpen&&(r.treePanelTitleEl.setText(f.title?`\u4F1A\u8BDD\u6811 \xB7 ${f.title}`:"\u4F1A\u8BDD\u6811"),l())}catch{}}async function q(u){if(i.isSending){new ge.Notice("\u5F53\u524D\u6B63\u5728\u56DE\u590D\uFF0C\u8BF7\u5148\u5B8C\u6210\u540E\u518D\u5206\u53C9");return}let h=n.sessionId,f=n.conversationId;if(!h||!f){new ge.Notice("\u5F53\u524D\u6CA1\u6709\u53EF\u5206\u53C9\u7684\u4F1A\u8BDD");return}let p=Lr(u.content),S=Ar(u.content),T=await _r(e,S,p);if(T!==null)try{let _=await n.forkConversation(h,f,u.messageId,T);await v(_)}catch(_){let U=_ instanceof Error?_.message:String(_);new ge.Notice(`\u5206\u53C9\u5931\u8D25: ${U}`)}}function F(u){let h=r.sessionListEl.createDiv({cls:"session-card"}),f=n.sessionId===u.id;f&&h.addClass("active");let p=h.createDiv({cls:"session-card-content"});p.createDiv({cls:"session-card-title"}).setText(u.title||"\u672A\u547D\u540D\u4F1A\u8BDD");let T=p.createDiv({cls:"session-card-meta"}),_=u.turn_count>0?`${u.turn_count} \u6B21\u5BF9\u8BDD`:`${u.message_count} \u6761\u6D88\u606F`;if(T.setText(`${_} \xB7 ${wr(u.created_at)}`),f&&p.createEl("span",{cls:"session-card-badge"}).setText("\u5F53\u524D"),p.addEventListener("click",()=>{P(),v(u)}),!f){let U=h.createEl("button",{cls:"session-card-delete",attr:{"aria-label":"\u5220\u9664\u4F1A\u8BDD"}});U.innerHTML=ln,U.addEventListener("click",W=>{W.stopPropagation(),R(u.id)})}}function b(u,h,f){for(let p of u){let S=h.createDiv({cls:"conversation-tree-branch"}),T=S.createEl("button",{cls:"conversation-tree-node",attr:{type:"button","aria-pressed":p.active?"true":"false",title:p.active?"\u5F53\u524D\u5206\u652F":"\u5207\u6362\u5230\u8BE5\u5206\u652F"}});p.active&&T.addClass("active");let _=T.createDiv({cls:"conversation-tree-node-main"});if(_.createDiv({cls:"conversation-tree-node-title"}).setText(p.title||"\u672A\u547D\u540D\u5206\u652F"),_.createSpan({cls:"conversation-tree-node-badge"}).setText(p.active?"\u5F53\u524D":`v${p.revision}`),T.createDiv({cls:"conversation-tree-node-meta"}).setText([`${p.message_count} \u6761`,p.fork_message_id?`fork ${p.fork_message_id.slice(0,8)}`:"",p.parent_id?`parent ${p.parent_id.slice(0,8)}`:"root"].filter(Boolean).join(" \xB7 ")),T.addEventListener("click",()=>{if(!p.active){if(i.isSending){new ge.Notice("\u5F53\u524D\u6B63\u5728\u56DE\u590D\uFF0C\u8BF7\u5148\u5B8C\u6210\u540E\u518D\u5207\u6362\u5206\u652F");return}E(f,p.id)}}),p.children.length>0){let G=S.createDiv({cls:"conversation-tree-children"});b(p.children,G,f)}}}async function E(u,h){try{let f=await n.patchSession(u,{active_conversation_id:h});await v(f)}catch(f){let p=f instanceof Error?f.message:String(f);new ge.Notice(`\u5207\u6362\u5206\u652F\u5931\u8D25: ${p}`)}}return{handleNewSession:C,toggleSessionPanel:d,toggleTreePanel:I,loadSessionList:o,loadConversationTree:l,switchToSession:v,deleteSessionConfirm:R,syncCurrentSessionTitle:O}}var An="life-assistant-chat-styles",Cn=`
  .life-assistant-chat {
    position: relative;
    display: flex;
    flex-direction: column;
    height: 100%;
    overflow: hidden;
    background: var(--background-primary);
    font-family: var(--font-interface);
  }

  .chat-header-area {
    position: absolute;
    inset: 0 0 auto 0;
    z-index: 10;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 10px 12px;
    background: transparent;
  }
  .chat-header-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    flex: 0 0 auto;
  }
  .chat-header-btn {
    width: 32px;
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--background-modifier-border);
    border-radius: 10px;
    background: var(--background-primary);
    color: var(--text-muted);
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
    cursor: pointer;
    transition: transform 0.18s ease, border-color 0.18s ease, color 0.18s ease, background 0.18s ease;
    padding: 0;
    flex-shrink: 0;
  }
  .chat-header-btn:hover {
    transform: scale(1.05);
    background: var(--background-secondary);
    border-color: var(--interactive-accent);
    color: var(--text-normal);
  }
  .chat-header-btn:active {
    transform: scale(0.95);
  }
  .chat-header-btn svg {
    pointer-events: none;
  }
  .chat-header-title {
    flex: 1;
    min-width: 0;
    padding: 0 8px;
    text-align: center;
    font-size: 0.95em;
    font-weight: 600;
    color: var(--text-normal);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    user-select: none;
  }

  .chat-custom-select {
    position: relative;
    width: 100%;
    max-width: 180px;
    font-family: var(--font-interface);
  }
  .custom-select-trigger {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 5px 14px;
    border: 1px solid var(--background-modifier-border);
    border-radius: 16px;
    background: var(--background-primary);
    color: var(--text-normal);
    box-shadow: 0 2px 6px rgba(0,0,0,0.04), inset 0 1px 0 rgba(255,255,255,0.05);
    cursor: pointer;
    transition: transform 0.18s ease, background 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
    font-size: 0.78em;
    font-weight: 500;
  }
  .custom-select-trigger:hover {
    background: var(--background-secondary);
    border-color: var(--interactive-accent);
    box-shadow: 0 4px 12px rgba(var(--interactive-accent-rgb, 99, 135, 240), 0.15);
  }
  .custom-select-trigger svg {
    opacity: 0.6;
    transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.3s ease;
  }
  .custom-select-trigger span {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .chat-custom-select.open .custom-select-trigger {
    border-color: var(--interactive-accent);
    box-shadow: 0 0 0 2px rgba(var(--interactive-accent-rgb, 99, 135, 240), 0.2);
  }
  .chat-custom-select.open .custom-select-trigger svg {
    transform: rotate(180deg);
    opacity: 1;
    color: var(--interactive-accent);
  }
  .custom-select-dropdown {
    position: absolute;
    left: 50%;
    bottom: calc(100% + 10px);
    z-index: 100;
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 100%;
    width: max-content;
    max-height: 250px;
    overflow-y: auto;
    padding: 6px;
    border: 1px solid var(--background-modifier-border);
    border-radius: 14px;
    background: var(--background-secondary);
    box-shadow: 0 12px 40px rgba(0,0,0,0.2), 0 0 0 1px inset rgba(255,255,255,0.05);
    opacity: 0;
    pointer-events: none;
    transform: translateX(-50%) translateY(8px) scale(0.96);
    transition: opacity 0.3s cubic-bezier(0.16, 1, 0.3, 1), transform 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  }
  .custom-select-dropdown::-webkit-scrollbar {
    width: 3px;
  }
  .custom-select-dropdown::-webkit-scrollbar-thumb {
    background: var(--background-modifier-border);
    border-radius: 3px;
  }
  .chat-custom-select.open .custom-select-dropdown {
    opacity: 1;
    pointer-events: auto;
    transform: translateX(-50%) translateY(0) scale(1);
  }
  .custom-select-option {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    min-width: 180px;
    padding: 8px 14px;
    border-radius: 10px;
    background: transparent;
    color: var(--text-normal);
    cursor: pointer;
    white-space: nowrap;
    transition: background 0.2s ease, padding-left 0.2s ease;
  }
  .custom-select-option:hover {
    background: var(--background-modifier-hover);
    padding-left: 18px;
  }
  .custom-select-option-empty,
  .custom-select-option-empty:hover {
    padding-left: 14px;
    background: transparent;
    color: var(--text-muted);
    cursor: default;
  }
  .custom-select-option.selected {
    background: rgba(var(--interactive-accent-rgb, 99, 135, 240), 0.12);
    color: var(--interactive-accent);
  }
  .custom-select-option.selected .cso-name {
    font-weight: 600;
  }
  .custom-select-option.selected::before {
    content: "";
    position: absolute;
    left: 8px;
    width: 4px;
    height: 14px;
    border-radius: 2px;
    background: var(--interactive-accent);
  }
  .cso-label {
    display: flex;
    flex: 1;
    flex-direction: column;
    min-width: 0;
  }
  .cso-name {
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .cso-model {
    overflow: hidden;
    text-overflow: ellipsis;
    color: var(--text-muted);
    font-size: 0.72em;
  }
  .cso-provider {
    flex-shrink: 0;
    border-radius: 6px;
    padding: 2px 6px;
    background: var(--background-modifier-border);
    color: var(--text-muted);
    font-size: 0.65em;
    font-weight: 700;
    letter-spacing: 0.05em;
  }
  .cso-provider.cso-meta {
    min-width: 36px;
    text-align: center;
  }

  .session-panel {
    position: absolute;
    top: 0;
    bottom: 0;
    left: 0;
    width: min(280px, 90%);
    z-index: 60;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    opacity: 0;
    pointer-events: none;
    transform: translateX(-100%);
    background: var(--background-primary);
    border-right: 1px solid var(--background-modifier-border);
    box-shadow: 4px 0 24px rgba(0,0,0,0.15);
    transition: opacity 0.3s cubic-bezier(0.16, 1, 0.3, 1),
      transform 0.35s cubic-bezier(0.16, 1, 0.3, 1),
      box-shadow 0.3s ease;
  }
  .session-panel.open {
    opacity: 1;
    pointer-events: auto;
    transform: translateX(0);
    box-shadow: 8px 0 40px rgba(0,0,0,0.25);
  }
  .session-panel.open::after,
  .tree-panel.open::after {
    content: "";
    position: fixed;
    inset: 0;
    z-index: -1;
  }

  .tree-panel {
    left: auto;
    right: 0;
    width: min(340px, 92%);
    border-right: none;
    border-left: 1px solid var(--background-modifier-border);
    transform: translateX(100%);
    box-shadow: -4px 0 24px rgba(0,0,0,0.15);
  }
  .tree-panel.open {
    opacity: 1;
    pointer-events: auto;
    transform: translateX(0);
    box-shadow: -8px 0 40px rgba(0,0,0,0.25);
  }

  .session-panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    flex-shrink: 0;
    padding: 16px 14px 14px;
    border-bottom: 1px solid var(--background-modifier-border);
    background: linear-gradient(135deg,
      rgba(var(--interactive-accent-rgb, 99,135,240), 0.08) 0%,
      transparent 100%);
  }
  .session-panel-title {
    display: flex;
    align-items: center;
    gap: 7px;
    min-width: 0;
    font-size: 0.9em;
    font-weight: 700;
    color: var(--text-normal);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .session-panel-close {
    width: 26px;
    height: 26px;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--background-modifier-border);
    border-radius: 8px;
    background: var(--background-secondary);
    color: var(--text-muted);
    cursor: pointer;
    flex-shrink: 0;
    transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
    padding: 0;
    font-size: 12px;
  }
  .session-panel-close:hover {
    background: var(--background-modifier-hover);
    color: var(--text-normal);
    border-color: var(--text-muted);
  }

  .session-list,
  .conversation-tree-list {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 10px 8px 20px;
    display: flex;
    flex-direction: column;
  }
  .session-list { gap: 3px; }
  .conversation-tree-list { gap: 8px; }
  .session-list::-webkit-scrollbar,
  .conversation-tree-list::-webkit-scrollbar {
    width: 3px;
  }
  .session-list::-webkit-scrollbar-thumb,
  .conversation-tree-list::-webkit-scrollbar-thumb {
    background-color: var(--background-modifier-border);
    border-radius: 3px;
  }
  .session-loading,
  .session-empty,
  .session-error,
  .conversation-tree-loading,
  .conversation-tree-empty,
  .conversation-tree-error {
    padding: 40px 12px;
    text-align: center;
    color: var(--text-muted);
    font-size: 0.85em;
    font-style: italic;
    opacity: 0.7;
  }

  .session-card {
    position: relative;
    display: flex;
    align-items: stretch;
    overflow: hidden;
    border: 1px solid transparent;
    border-radius: 10px;
    background: transparent;
    cursor: pointer;
    transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1), border-color 0.2s ease, background 0.2s ease;
    animation: card-in 0.3s cubic-bezier(0.16, 1, 0.3, 1) both;
  }
  @keyframes card-in {
    from { opacity: 0; transform: translateX(-10px); }
    to { opacity: 1; transform: translateX(0); }
  }
  .session-card:hover {
    background: var(--background-secondary);
    border-color: var(--background-modifier-border);
    transform: translateX(2px);
  }
  .session-card.active {
    background: rgba(var(--interactive-accent-rgb, 99,135,240), 0.1);
    border-color: rgba(var(--interactive-accent-rgb, 99,135,240), 0.3);
  }
  .session-card.active::before {
    content: "";
    position: absolute;
    left: 0;
    top: 20%;
    bottom: 20%;
    width: 3px;
    border-radius: 0 2px 2px 0;
    background: var(--interactive-accent);
  }
  .session-card-content {
    flex: 1;
    min-width: 0;
    padding: 10px 10px 10px 12px;
  }
  .session-card.active .session-card-content {
    padding-left: 16px;
  }
  .session-card-title {
    margin-bottom: 2px;
    font-size: 0.875em;
    font-weight: 500;
    color: var(--text-normal);
    line-height: 1.4;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .session-card.active .session-card-title {
    color: var(--interactive-accent);
    font-weight: 600;
  }
  .session-card-meta {
    display: flex;
    align-items: center;
    gap: 5px;
    margin-top: 1px;
    color: var(--text-faint);
    font-size: 0.7em;
  }
  .session-card-meta::before {
    content: "\u2022";
    opacity: 0.6;
  }
  .session-card-badge {
    display: inline-flex;
    align-items: center;
    margin-top: 4px;
    padding: 1px 6px;
    border-radius: 20px;
    background: rgba(var(--interactive-accent-rgb, 99,135,240), 0.15);
    color: var(--interactive-accent);
    font-size: 0.62em;
    font-weight: 700;
    letter-spacing: 0.03em;
    text-transform: uppercase;
  }
  .session-card-delete {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    min-height: 44px;
    padding: 0;
    border: 0;
    border-left: 1px solid transparent;
    border-radius: 0 10px 10px 0;
    background: transparent;
    color: var(--text-faint);
    cursor: pointer;
    opacity: 0;
    flex-shrink: 0;
    transition: background 0.15s ease, color 0.15s ease, opacity 0.15s ease, border-left-color 0.15s ease;
  }
  .session-card:hover .session-card-delete {
    opacity: 1;
    border-left-color: var(--background-modifier-border);
  }
  .session-card-delete:hover {
    background: rgba(224, 82, 82, 0.1);
    color: #e05252;
    border-left-color: rgba(224, 82, 82, 0.2);
  }
  .session-card-delete svg {
    pointer-events: none;
  }

  .conversation-tree-branch {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .conversation-tree-node {
    display: flex;
    flex-direction: column;
    gap: 4px;
    width: 100%;
    box-sizing: border-box;
    padding: 10px 10px 10px 12px;
    border: 1px solid transparent;
    border-radius: 10px;
    background: transparent;
    color: var(--text-normal);
    cursor: pointer;
    text-align: left;
    transition: transform 0.18s cubic-bezier(0.16, 1, 0.3, 1), background 0.18s ease, border-color 0.18s ease;
  }
  .conversation-tree-node:hover {
    background: var(--background-secondary);
    border-color: var(--background-modifier-border);
    transform: translateX(2px);
  }
  .conversation-tree-node.active {
    background: rgba(var(--interactive-accent-rgb, 99,135,240), 0.1);
    border-color: rgba(var(--interactive-accent-rgb, 99,135,240), 0.3);
  }
  .conversation-tree-node-main {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  .conversation-tree-node-title {
    flex: 1;
    min-width: 0;
    font-size: 0.88em;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .conversation-tree-node.active .conversation-tree-node-title {
    color: var(--interactive-accent);
  }
  .conversation-tree-node-badge {
    flex-shrink: 0;
    border-radius: 20px;
    padding: 1px 6px;
    background: rgba(var(--interactive-accent-rgb, 99,135,240), 0.15);
    color: var(--interactive-accent);
    font-size: 0.62em;
    font-weight: 700;
    letter-spacing: 0.03em;
    text-transform: uppercase;
  }
  .conversation-tree-node-meta {
    font-size: 0.68em;
    color: var(--text-faint);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .conversation-tree-children {
    margin-left: 12px;
    padding-left: 10px;
    border-left: 1px solid var(--background-modifier-border);
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .chat-body {
    position: relative;
    display: flex;
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }
  .chat-minimap {
    position: relative;
    width: 20px;
    flex-shrink: 0;
    overflow: hidden;
    padding-top: 60px;
    padding-bottom: 20px;
  }
  .chat-minimap-line {
    position: absolute;
    left: 50%;
    top: 60px;
    bottom: 20px;
    width: 2px;
    border-radius: 1px;
    background: var(--background-modifier-border);
    transform: translateX(-50%);
  }
  .chat-minimap-dot {
    position: absolute;
    left: 50%;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--text-muted);
    cursor: pointer;
    transform: translateX(-50%);
    transition: top 0.45s cubic-bezier(0.16, 1, 0.3, 1),
      transform 0.2s ease,
      background 0.2s ease,
      box-shadow 0.2s ease;
    z-index: 1;
    box-shadow: 0 0 0 2px var(--background-primary);
  }
  .chat-minimap-dot:hover {
    transform: translateX(-50%) scale(1.6);
    background: var(--interactive-accent);
    box-shadow: 0 0 0 2px var(--background-primary), 0 0 8px rgba(var(--interactive-accent-rgb, 99, 135, 240), 0.6);
  }

  .chat-messages {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overflow-x: hidden;
    padding: 60px 16px 20px 8px;
    display: flex;
    flex-direction: column;
    gap: 20px;
    user-select: text;
    -webkit-user-select: text;
    scroll-behavior: smooth;
  }
  .chat-messages::-webkit-scrollbar {
    width: 4px;
  }
  .chat-messages::-webkit-scrollbar-thumb {
    border-radius: 4px;
    background-color: var(--background-modifier-border);
  }

  .chat-msg {
    max-width: 100%;
    box-sizing: border-box;
    line-height: 1.6;
    font-size: 0.95em;
    user-select: text;
    -webkit-user-select: text;
    cursor: text;
    animation: msg-fade-in 0.35s cubic-bezier(0.16, 1, 0.3, 1) forwards;
  }
  @keyframes msg-fade-in {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .chat-msg p { margin: 0 0 0.8em 0; }
  .chat-msg p:last-child { margin-bottom: 0; }
  .chat-msg pre {
    margin: 12px 0;
    padding: 12px;
    overflow-x: auto;
    border: 1px solid var(--background-modifier-border);
    border-radius: 8px;
    background: var(--background-secondary);
  }
  .chat-msg code {
    font-family: var(--font-monospace);
    font-size: 0.9em;
  }

  .chat-msg.user {
    display: flex;
    justify-content: flex-end;
  }
  .chat-msg-bubble {
    display: flex;
    flex-direction: column;
    gap: 10px;
    max-width: 85%;
    padding: 10px 16px;
    border-bottom-right-radius: 4px;
    border-radius: 18px;
    background: var(--background-secondary);
    color: var(--text-normal);
    word-break: break-word;
    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
    position: relative;
  }
  .chat-msg-bubble .chat-msg-action-row {
    justify-content: flex-end;
  }
  .chat-msg-text {
    white-space: pre-wrap;
  }
  .chat-msg-images {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(88px, 1fr));
    gap: 8px;
  }
  .chat-msg-image {
    width: 100%;
    min-height: 72px;
    max-height: 180px;
    object-fit: cover;
    border-radius: 12px;
    border: 1px solid rgba(0,0,0,0.08);
    background: var(--background-primary);
  }
  .chat-msg-attachment-row {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .chat-msg-attachment {
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    padding: 4px 10px;
    border-radius: 999px;
    background: rgba(var(--interactive-accent-rgb, 99, 135, 240), 0.12);
    color: var(--interactive-accent);
    font-size: 0.8em;
  }

  .chat-msg-action-row {
    display: flex;
    justify-content: flex-end;
    gap: 6px;
    margin-bottom: 2px;
  }
  .chat-msg-fork-btn {
    width: 24px;
    height: 24px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    border: 1px solid var(--background-modifier-border);
    border-radius: 8px;
    background: var(--background-primary);
    color: var(--text-muted);
    cursor: pointer;
    opacity: 0.55;
    transition: opacity 0.15s ease, border-color 0.15s ease, color 0.15s ease, background 0.15s ease, transform 0.15s ease;
    flex-shrink: 0;
  }
  .chat-msg-fork-btn:hover {
    opacity: 1;
    transform: translateY(-1px);
    background: var(--background-secondary);
    border-color: var(--interactive-accent);
    color: var(--interactive-accent);
  }
  .chat-msg-fork-btn svg {
    pointer-events: none;
  }
  .chat-assistant-shell {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .chat-assistant-header {
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 22px;
  }
  .chat-assistant-name {
    flex-shrink: 0;
    color: var(--text-muted);
    font-size: 0.78em;
    font-weight: 700;
    line-height: 1.4;
    text-transform: none;
  }
  .chat-assistant-header .chat-msg-action-row {
    margin-left: auto;
    margin-bottom: 0;
  }
  .chat-assistant-header .chat-msg-fork-btn {
    width: 22px;
    height: 22px;
  }
  .chat-assistant-content {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .chat-msg.status {
    font-size: 0.8em;
    color: var(--text-muted);
    font-style: italic;
  }

  .chat-tool-block {
    display: block !important;
    overflow: hidden;
    border: 1px solid var(--background-modifier-border);
    border-radius: 8px;
    background: var(--background-secondary);
    font-size: 0.82em;
    animation: msg-fade-in 0.25s ease both;
    flex-shrink: 0;
    transition: border-color 0.3s ease, background 0.3s ease;
  }
  .chat-tool-block.running {
    border-color: rgba(var(--interactive-accent-rgb, 99,135,240), 0.35);
    background: rgba(var(--interactive-accent-rgb, 99,135,240), 0.04);
  }
  .chat-tool-block.done {
    background: var(--background-secondary);
  }
  .chat-tool-header {
    display: flex !important;
    align-items: center !important;
    gap: 6px;
    min-height: 32px !important;
    height: auto !important;
    box-sizing: border-box !important;
    padding: 6px 10px !important;
    user-select: none;
    overflow: visible !important;
  }
  .chat-tool-block.done > .chat-tool-header {
    cursor: pointer;
  }
  .chat-tool-block.done > .chat-tool-header:hover {
    background: var(--background-modifier-hover);
  }
  .chat-tool-icon {
    min-width: 16px;
    flex-shrink: 0 !important;
    display: inline !important;
    color: var(--interactive-accent);
    font-family: var(--font-monospace);
    font-size: 0.9em;
    line-height: 1.4;
  }
  .chat-tool-name {
    display: inline !important;
    flex-shrink: 0;
    color: var(--text-normal);
    font-family: var(--font-monospace);
    font-size: 0.9em;
    font-weight: 600;
    line-height: 1.4;
  }
  .chat-tool-block.running .chat-tool-name {
    color: var(--interactive-accent);
  }
  .chat-tool-preview {
    flex: 1;
    min-width: 0;
    margin-left: 4px;
    padding-left: 8px;
    border-left: 1px solid var(--background-modifier-border);
    color: var(--text-faint);
    font-family: var(--font-monospace);
    font-size: 0.85em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .chat-tool-chevron {
    margin-left: auto;
    padding-left: 6px;
    flex-shrink: 0;
    color: var(--text-faint);
    font-size: 0.85em;
    transition: transform 0.2s ease;
  }
  .chat-tool-spinner {
    width: 11px;
    height: 11px;
    margin-left: auto;
    border: 2px solid rgba(var(--interactive-accent-rgb, 99,135,240), 0.2);
    border-top-color: var(--interactive-accent);
    border-radius: 50%;
    animation: spin 0.75s linear infinite;
    flex-shrink: 0;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .chat-tool-terminal {
    padding: 7px 12px;
    border-top: 1px solid var(--background-modifier-border);
    background: var(--background-secondary);
    color: var(--text-muted);
    font-family: var(--font-monospace);
    font-size: 0.8em;
    line-height: 1.5;
    max-height: 72px;
    overflow: hidden;
    white-space: pre-wrap;
    word-break: break-all;
    transition: max-height 0.3s ease;
  }
  .chat-tool-block.done > .chat-tool-terminal {
    display: none !important;
  }
  .chat-tool-block.done.expanded > .chat-tool-terminal {
    display: block !important;
    max-height: 220px;
    overflow-y: auto;
  }

  .chat-thought-block + .chat-assistant-markdown {
    margin-top: 10px;
  }
  .chat-thought-block {
    display: block;
    overflow: hidden;
    border: 1px solid var(--background-modifier-border);
    border-radius: 8px;
    background: var(--background-secondary);
    font-size: 0.82em;
    animation: msg-fade-in 0.25s ease both;
  }
  .chat-msg.streaming .chat-thought-block,
  .chat-thought-block.streaming {
    animation: none;
  }
  .chat-thought-header {
    display: flex;
    align-items: center;
    gap: 6px;
    min-height: 32px;
    padding: 6px 10px;
    box-sizing: border-box;
    cursor: pointer;
    user-select: none;
  }
  .chat-thought-header:hover {
    background: var(--background-modifier-hover);
  }
  .chat-thought-title {
    flex-shrink: 0;
    color: var(--text-normal);
    font-family: var(--font-monospace);
    font-size: 0.9em;
    font-weight: 600;
  }
  .chat-thought-preview {
    flex: 1;
    min-width: 0;
    margin-left: 4px;
    padding-left: 8px;
    border-left: 1px solid var(--background-modifier-border);
    color: var(--text-faint);
    font-family: var(--font-monospace);
    font-size: 0.85em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .chat-thought-preview.is-empty {
    display: none;
  }
  .chat-thought-chevron {
    margin-left: auto;
    padding-left: 6px;
    flex-shrink: 0;
    color: var(--text-faint);
    font-family: var(--font-monospace);
    font-size: 0.85em;
  }
  .chat-thought-body {
    display: none;
    padding: 7px 12px;
    border-top: 1px solid var(--background-modifier-border);
    background: var(--background-secondary);
    color: var(--text-muted);
    font-family: var(--font-monospace);
    font-size: 0.8em;
    line-height: 1.5;
    max-height: 220px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .chat-thought-block.expanded > .chat-thought-body {
    display: block;
  }
  .chat-assistant-streaming-text {
    white-space: pre-wrap;
    word-break: break-word;
  }

  .chat-footer {
    position: relative;
    z-index: 50;
    flex-shrink: 0;
    padding: 0 16px 20px;
    background: linear-gradient(to top, var(--background-primary) 80%, transparent);
    display: flex;
    flex-direction: column;
    align-items: center;
  }
  .chat-model-area {
    position: relative;
    z-index: 51;
    width: 100%;
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    align-items: center;
    gap: 12px;
    row-gap: 8px;
    margin-top: 8px;
  }
  .chat-context-bar {
    display: flex;
    align-items: center;
    gap: 6px;
    max-width: calc(100% - 24px);
    padding: 4px 10px;
    border: 1px solid var(--background-modifier-border);
    border-radius: 14px;
    background: transparent;
    box-shadow: 0 1px 4px rgba(0,0,0,0.02);
    cursor: help;
    font-size: 0.75em;
    line-height: 1.4;
  }
  .context-meter-label,
  .context-separator,
  .context-bill-label {
    color: var(--text-muted);
  }
  .context-meter-label,
  .context-percent-label,
  .context-bill-label {
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  .context-ring {
    --context-progress: 0%;
    --context-color: var(--text-success);
    position: relative;
    flex: 0 0 18px;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: conic-gradient(var(--context-color) var(--context-progress), var(--background-modifier-border) 0);
    transition: background 0.4s ease;
  }
  .context-ring::after {
    content: "";
    position: absolute;
    inset: 5px;
    border-radius: 50%;
    background: var(--background-primary);
  }
  .context-bill-label {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .life-context-tooltip {
    max-width: 360px;
    white-space: pre-line;
    text-align: left;
  }

  .chat-input-area {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 8px;
    width: 100%;
    padding: 10px 10px 10px 12px;
    border: 1px solid var(--background-modifier-border);
    border-radius: 24px;
    background: var(--background-primary);
    box-shadow: 0 4px 20px rgba(0,0,0,0.08);
    transition: border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
  }
  .chat-input-area:focus-within {
    border-color: var(--interactive-accent);
    box-shadow: 0 4px 20px rgba(var(--interactive-accent-rgb), 0.1);
  }
  .chat-input-area.drag-over {
    border-color: var(--interactive-accent);
    background: rgba(var(--interactive-accent-rgb, 99, 135, 240), 0.06);
  }
  .chat-composer-pills {
    display: none;
    flex-wrap: wrap;
    gap: 8px;
  }
  .chat-composer-pills.has-items {
    display: flex;
  }
  .chat-image-pill {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    max-width: 100%;
    padding: 6px 10px 6px 6px;
    border: 1px solid var(--background-modifier-border);
    border-radius: 999px;
    background: var(--background-secondary);
  }
  .chat-image-pill-thumb {
    width: 30px;
    height: 30px;
    border-radius: 999px;
    object-fit: cover;
  }
  .chat-image-pill-label {
    max-width: 140px;
    overflow: hidden;
    color: var(--text-normal);
    font-size: 0.8em;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .chat-image-pill-remove {
    border: 0;
    background: transparent;
    color: var(--text-muted);
    cursor: pointer;
    padding: 0;
    font-size: 16px;
    line-height: 1;
  }
  .chat-suggestion-list {
    position: absolute;
    left: 12px;
    right: 12px;
    bottom: calc(100% + 8px);
    z-index: 70;
    display: none;
    max-height: 240px;
    overflow-y: auto;
    padding: 6px;
    border: 1px solid var(--background-modifier-border);
    border-radius: 14px;
    background: var(--background-primary);
    box-shadow: 0 12px 30px rgba(0,0,0,0.18);
  }
  .chat-suggestion-list.is-open {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .chat-suggestion-item {
    padding: 8px 10px;
    border-radius: 10px;
    cursor: pointer;
  }
  .chat-suggestion-item:hover,
  .chat-suggestion-item.is-selected {
    background: var(--background-secondary);
  }
  .chat-suggestion-title {
    color: var(--text-normal);
    font-size: 0.85em;
    font-weight: 600;
  }
  .chat-suggestion-desc {
    margin-top: 2px;
    color: var(--text-muted);
    font-size: 0.75em;
  }
  .chat-input-row {
    display: flex;
    align-items: flex-end;
    gap: 8px;
    width: 100%;
  }
  .chat-attach-btn {
    width: 32px;
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    margin-bottom: 2px;
    border: 1px solid var(--background-modifier-border);
    border-radius: 50%;
    background: var(--background-secondary);
    color: var(--text-muted);
    cursor: pointer;
  }
  .chat-attach-btn:hover:not(:disabled) {
    color: var(--interactive-accent);
    border-color: var(--interactive-accent);
  }
  .chat-attach-btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
  .chat-hidden-file-input {
    display: none;
  }
  .chat-input {
    flex: 1;
    max-height: 120px;
    resize: none;
    border: none;
    background: transparent;
    color: var(--text-normal);
    font-size: 0.95em;
    line-height: 1.5;
    padding: 6px 0;
  }
  .chat-input:focus {
    outline: none;
    box-shadow: none;
  }
  .chat-input::placeholder {
    color: var(--text-faint);
  }
  .chat-send-btn {
    width: 32px;
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    margin-bottom: 2px;
    border: 0;
    border-radius: 50%;
    background: var(--interactive-accent);
    color: var(--text-on-accent);
    cursor: pointer;
    transition: transform 0.2s ease, background 0.2s ease, color 0.2s ease;
    padding: 0;
  }
  .chat-send-btn:hover:not(:disabled) {
    transform: scale(1.05);
  }
  .chat-send-btn:disabled {
    background: var(--background-modifier-border);
    color: var(--text-muted);
    cursor: not-allowed;
    transform: none;
  }
  .chat-send-btn svg {
    display: block;
    pointer-events: none;
    flex-shrink: 0;
  }

  .fork-conversation-modal {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .fork-conversation-modal h2 {
    margin: 0;
    font-size: 1em;
  }
  .fork-conversation-label {
    margin-bottom: 6px;
    color: var(--text-muted);
    font-size: 0.75em;
    font-weight: 700;
    letter-spacing: 0.03em;
    text-transform: uppercase;
  }
  .fork-conversation-preview,
  .fork-conversation-title {
    display: flex;
    flex-direction: column;
  }
  .fork-conversation-text {
    max-height: 120px;
    overflow: auto;
    white-space: pre-wrap;
    line-height: 1.5;
    color: var(--text-normal);
    font-size: 0.88em;
  }
  .fork-conversation-input {
    width: 100%;
    box-sizing: border-box;
    border: 1px solid var(--background-modifier-border);
    border-radius: 8px;
    background: var(--background-secondary);
    color: var(--text-normal);
    padding: 8px 10px;
    font: inherit;
  }
  .fork-conversation-input:focus {
    outline: none;
    border-color: var(--interactive-accent);
    box-shadow: 0 0 0 2px rgba(var(--interactive-accent-rgb, 99, 135, 240), 0.18);
  }
  .fork-conversation-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin-top: 4px;
  }

  .cso-provider[data-provider="anthropic"] { background: rgba(217, 119, 6, 0.15); color: #d97706; }
  .cso-provider[data-provider="openai"] { background: rgba(5, 150, 105, 0.15); color: #059669; }
  .cso-provider[data-provider="ollama"] { background: rgba(37, 99, 235, 0.15); color: #2563eb; }
  .cso-provider[data-provider="deepseek"] { background: rgba(79, 70, 229, 0.15); color: #4f46e5; }
  .cso-provider[data-provider="qwen"] { background: rgba(8, 145, 178, 0.15); color: #0891b2; }
  .cso-provider[data-provider="kimi"] { background: rgba(124, 58, 237, 0.15); color: #7c3aed; }
  .cso-provider[data-provider="minimax"] { background: rgba(219, 39, 119, 0.15); color: #db2777; }
  .cso-provider[data-provider="zhipu"] { background: rgba(22, 163, 74, 0.15); color: #16a34a; }
  .cso-provider[data-provider="custom_openai"] { background: rgba(100, 116, 139, 0.15); color: #64748b; }
`;function Mn(){let t=document.getElementById(An);if(t&&t.tagName==="STYLE"){t.textContent=Cn;return}let e=document.createElement("style");e.id=An,e.textContent=Cn,document.head.appendChild(e)}var rt=require("obsidian");function Mr(t){return t.trim().split(`
`).find(e=>e.trim())}function Ir(t){let e=s=>s.replace(/\.0$/,""),n=Math.abs(t);if(n>=1e6){let s=n>=1e7?0:1;return`${e((t/1e6).toFixed(s))}m`}return n>=1e3?`${e((t/1e3).toFixed(1))}k`:`${Math.round(t)}`}function J(t){return Math.round(t).toLocaleString("en-US")}function Rr(t){let e=t>=10?0:1;return`${t.toFixed(e).replace(/\.0$/,"")}%`}function he(t,e){let n=t[e];return typeof n=="number"?n:0}function Dr(t){return t?he(t,"prompt_cache_hit_tokens")+he(t,"prompt_cached_tokens")+he(t,"cache_read_input_tokens"):0}function it(t){return!!t&&(t.call_count>0||t.prompt_tokens>0||t.completion_tokens>0||t.total_tokens>0||t.reasoning_tokens>0||Dr(t)>0||he(t,"prompt_cache_miss_tokens")>0||he(t,"cache_creation_input_tokens")>0)}function Br(t,e){let n=it(e)?e:t;return it(n)?Ir(n.total_tokens):"\u6682\u65E0"}function In(t,e){let n=[`${t}\uFF1A${J(e.total_tokens)} tokens\uFF0C${J(e.call_count)} \u6B21\u6A21\u578B\u8C03\u7528\u3002`,`${t}\u660E\u7EC6\uFF1A\u8F93\u5165 ${J(e.prompt_tokens)}\uFF0C\u8F93\u51FA ${J(e.completion_tokens)}\uFF0C\u63A8\u7406 ${J(e.reasoning_tokens)}\u3002`],s=[],r=he(e,"prompt_cache_hit_tokens"),i=he(e,"prompt_cache_miss_tokens"),a=he(e,"prompt_cached_tokens"),c=he(e,"cache_creation_input_tokens"),o=he(e,"cache_read_input_tokens");return r>0&&s.push(`\u7F13\u5B58\u547D\u4E2D ${J(r)}`),i>0&&s.push(`\u672A\u547D\u4E2D ${J(i)}`),a>0&&s.push(`\u7F13\u5B58\u547D\u4E2D ${J(a)}`),o>0&&s.push(`\u8BFB\u7F13\u5B58 ${J(o)}`),c>0&&s.push(`\u5EFA\u7F13\u5B58 ${J(c)}`),s.length>0&&n.push(`${t}\u7F13\u5B58\uFF1A${s.join("\uFF0C")}\u3002`),n}function $r(t,e){let n=[`\u4E0A\u4E0B\u6587\u5360\u7528\uFF1A${J(t.total_tokens)} / ${J(t.context_limit)} tokens\uFF08${e}\uFF09\u3002`,`\u4E0A\u4E0B\u6587\u660E\u7EC6\uFF1A\u7CFB\u7EDF ${J(t.system_tokens)}\uFF0C\u5DE5\u5177\u5B9A\u4E49 ${J(t.schema_tokens)}\uFF0C\u7528\u6237 ${J(t.user_tokens)}\uFF0C\u52A9\u624B ${J(t.assistant_tokens)}\uFF0C\u5DE5\u5177\u7ED3\u679C ${J(t.tool_result_tokens)}\u3002`,`\u6D88\u606F\u6570\uFF1A${J(t.message_count)}\u3002`],s=t.actual_usage,r=t.cumulative_usage;return it(s)?n.push(...In("\u672C\u8F6E\u8D26\u5355",s)):n.push("\u672C\u8F6E\u8D26\u5355\uFF1A\u5F53\u524D\u6A21\u578B\u6CA1\u6709\u8FD4\u56DE usage \u6570\u636E\u3002"),it(r)&&n.push(...In("\u4F1A\u8BDD\u8D26\u5355",r)),n.push("\u8D26\u5355\u6765\u81EA\u670D\u52A1\u5546 usage\uFF0C\u53EF\u80FD\u5305\u542B\u4E0D\u8FDB\u5165\u4E0A\u4E0B\u6587\u7A97\u53E3\u7684\u8F93\u51FA\u3001\u63A8\u7406\u548C\u7F13\u5B58\u76F8\u5173 token\u3002"),n.join(`
`)}function Rn(t){let{app:e,client:n,component:s,elements:r,state:i}=t,a=null;function c(){let b=Array.from(r.minimapEl.querySelectorAll(".chat-minimap-dot")),E=b.length;if(E===0)return;let u=10,h=64,f=24,p=40,S=12,T=r.minimapEl.clientHeight-h-f,_=E===1?0:Math.max(S,Math.min(p,(T-u)/(E-1))),U=u+(E-1)*_,W=h+Math.max(0,(T-U)/2);b.forEach((te,G)=>{te.style.top=`${W+G*_}px`})}function o(b=!1){if(b){requestAnimationFrame(()=>{r.messagesEl.scrollTop=r.messagesEl.scrollHeight});return}let{scrollTop:E,scrollHeight:u,clientHeight:h}=r.messagesEl;u-E-h<150&&(r.messagesEl.scrollTop=u)}function l(b,E,u){b.classList.remove("running"),b.classList.add("done");let h=b.querySelector(".chat-tool-header");if(h){h.empty(),h.createSpan({cls:"chat-tool-icon"}).setText("\u2705"),h.createSpan({cls:"chat-tool-name"}).setText(E);let T=Mr(u);T&&h.createSpan({cls:"chat-tool-preview"}).setText(T.slice(0,72)+(T.length>72?"\u2026":""));let _=h.createSpan({cls:"chat-tool-chevron",text:"\u25BE"});h.addEventListener("click",()=>{b.classList.toggle("expanded",!b.classList.contains("expanded")),_.setText(b.classList.contains("expanded")?"\u25B4":"\u25BE")})}let f=b.querySelector(".chat-tool-terminal");f&&(f.empty(),f.setText(u||"(no output)"))}function x(b,E,u=!0,h=[],f){i.messages.push({role:b,content:E,attachments:h,messageId:f});let p=r.messagesEl.createDiv({cls:`chat-msg ${b}`});if(f&&(p.dataset.messageId=f),b==="user"){let S=r.minimapEl.createDiv({cls:"chat-minimap-dot"});S.setAttribute("title",E.slice(0,30)),S.addEventListener("click",()=>{p.scrollIntoView({behavior:"smooth",block:"start"})}),i.userMsgRefs.push({dot:S,msgEl:p}),c();let T=p.createDiv({cls:"chat-msg-bubble"});f&&a&&A(T,f,E,"user"),d(T,h),E&&T.createDiv({cls:"chat-msg-text"}).setText(E)}else b==="assistant"&&E?P(p,E,f):E&&p.setText(E);o(u)}function P(b,E,u){b.empty(),u&&(b.dataset.messageId=u);let h=b.createDiv({cls:"chat-assistant-shell"}),f=St(h);u&&a&&A(f,u,E,"assistant");let p=h.createDiv({cls:"chat-assistant-content"});En(e,s,p,E)}function k(b){if(!b)return!1;let E=-1;for(let f=i.messages.length-1;f>=0;f-=1)if(i.messages[f].role==="user"){E=f;break}if(E<0)return!1;i.messages[E].messageId=b;let u=i.userMsgRefs[i.userMsgRefs.length-1];if(!u)return!1;u.msgEl.dataset.messageId=b;let h=u.msgEl.querySelector(".chat-msg-bubble");return h?(A(h,b,i.messages[E].content,"user"),!0):!1}function A(b,E,u,h){for(let S of Array.from(b.children))S.classList.contains("chat-msg-action-row")&&S.remove();let f=b.createDiv({cls:"chat-msg-action-row"}),p=f.createEl("button",{cls:"chat-msg-fork-btn",attr:{type:"button","aria-label":"\u4ECE\u6B64\u6D88\u606F\u5206\u53C9",title:"\u4ECE\u6B64\u6D88\u606F\u5206\u53C9"}});p.innerHTML=an,(0,rt.setTooltip)(p,"\u4ECE\u6B64\u6D88\u606F\u5206\u53C9",{placement:"top",delay:120}),p.addEventListener("click",S=>{S.preventDefault(),S.stopPropagation(),a?.({messageId:E,content:u,role:h})}),!b.classList.contains("chat-assistant-header")&&b.firstElementChild!==f&&b.insertBefore(f,b.firstChild)}function d(b,E){if(E.length===0)return;let u=E.filter(p=>p.type==="image");if(u.length>0){let p=b.createDiv({cls:"chat-msg-images"});for(let S of u){let T=S.preview_url??(S.attachment_id?n.getAttachmentUrl(S.attachment_id):"");T&&p.createEl("img",{cls:"chat-msg-image",attr:{src:T,alt:S.filename??"image",loading:"lazy"}})}}let h=E.filter(p=>p.type!=="image");if(h.length===0)return;let f=b.createDiv({cls:"chat-msg-attachment-row"});for(let p of h){let S=f.createDiv({cls:"chat-msg-attachment"}),T=p.type==="vault_directory"?`@${p.path}/`:`@${p.path}`;S.setText(T)}}function I(b,E){let u=r.messagesEl.createDiv({cls:"chat-tool-block running"}),h=u.createDiv({cls:"chat-tool-header"});h.createSpan({cls:"chat-tool-icon"}).setText(cn(b)),h.createSpan({cls:"chat-tool-name"}).setText(b),h.createDiv({cls:"chat-tool-spinner"}),u.createDiv({cls:"chat-tool-terminal"}).createSpan({cls:"chat-tool-cursor",text:"\u2588"}),E&&(i.toolBlocks.set(E,u),i.toolIdToName.set(E,b)),i.toolBlocks.set(b,u),o(!1)}function C(b,E){let u;if(i.toolBlocks.has(b)){u=i.toolBlocks.get(b),i.toolBlocks.delete(b);for(let[h,f]of i.toolIdToName)if(f===b){i.toolBlocks.delete(h),i.toolIdToName.delete(h);break}}if(!u){for(let[h,f]of i.toolIdToName)if(f===b){u=i.toolBlocks.get(h),i.toolBlocks.delete(h),i.toolIdToName.delete(h),i.toolBlocks.delete(b);break}}if(!u){let h=r.messagesEl.querySelectorAll(".chat-tool-block.running");h.length&&(u=h[h.length-1])}u?l(u,b,E):r.messagesEl.createDiv({cls:"chat-msg status"}).setText(`\u2705 ${b} \u5B8C\u6210`),o(!1)}function v(b,E){let u=r.messagesEl.createDiv({cls:"chat-tool-block done"});u.createDiv({cls:"chat-tool-header"}),u.createDiv({cls:"chat-tool-terminal"}),l(u,b,E),o(!1)}function g(){i.toolBlocks.clear(),i.toolIdToName.clear()}function y(){r.messagesEl.querySelectorAll(".chat-msg.status, .chat-tool-block.running").forEach(b=>b.remove())}function R(){i.messages=[],i.userMsgRefs=[],g(),r.messagesEl.empty(),O(),r.minimapEl.querySelectorAll(".chat-minimap-dot").forEach(b=>b.remove())}function O(){let b="\u4E0A\u4E0B\u6587\u7EDF\u8BA1\u4F1A\u5728\u4E0B\u4E00\u6B21\u6A21\u578B\u54CD\u5E94\u5B8C\u6210\u540E\u66F4\u65B0\u3002";r.contextBarEl.style.display="flex",r.contextBarEl.removeAttribute("title"),r.contextBarEl.setAttribute("aria-label",b),(0,rt.setTooltip)(r.contextBarEl,b,{placement:"top",delay:120,classes:["life-context-tooltip"]}),r.contextBarEl.empty(),r.contextBarEl.createSpan({cls:"context-meter-label",text:"\u4E0A\u4E0B\u6587"});let E=r.contextBarEl.createDiv({cls:"context-ring",attr:{"aria-hidden":"true"}});E.style.setProperty("--context-progress","0%"),E.style.setProperty("--context-color","var(--text-muted)");let u=r.contextBarEl.createSpan({cls:"context-percent-label"});u.style.color="var(--text-muted)",u.setText("0%"),r.contextBarEl.createSpan({cls:"context-separator",text:"\xB7"}),r.contextBarEl.createSpan({cls:"context-bill-label",text:"\u4F1A\u8BDD \u6682\u65E0"})}function q(b){r.contextBarEl.style.display="flex";let E=b.usage_percent,u=Rr(E),h=Math.max(0,Math.min(E,100)),f=b.actual_usage,p=b.cumulative_usage,S=Br(f,p),T="var(--text-success)";E>80?T="var(--text-error)":E>50&&(T="var(--text-warning, #e0a030)");let _=$r(b,u);r.contextBarEl.removeAttribute("title"),r.contextBarEl.setAttribute("aria-label",_),(0,rt.setTooltip)(r.contextBarEl,_,{placement:"top",delay:120,classes:["life-context-tooltip"]}),r.contextBarEl.empty(),r.contextBarEl.createSpan({cls:"context-meter-label",text:"\u4E0A\u4E0B\u6587"});let U=r.contextBarEl.createDiv({cls:"context-ring",attr:{"aria-hidden":"true"}});U.style.setProperty("--context-progress",`${h}%`),U.style.setProperty("--context-color",T);let W=r.contextBarEl.createSpan({cls:"context-percent-label"});W.style.color=T,W.setText(u),r.contextBarEl.createSpan({cls:"context-separator",text:"\xB7"}),r.contextBarEl.createSpan({cls:"context-bill-label",text:`\u4F1A\u8BDD ${S}`})}function F(b){a=b}return O(),{appendMessage:x,renderAssistantMessage:P,beginTool:I,completeTool:C,renderHistoricalTool:v,clearConversationUi:R,clearToolTracking:g,removeTransientUi:y,scrollToBottom:o,updateContextBar:q,updateLastUserMessageId:k,setForkHandler:F}}var Dn=require("obsidian");var Nr="\uFF08\u7CFB\u7EDF\u901A\u77E5\uFF1A\u4E0A\u6B21\u6295\u9012\u5230\u540E\u53F0\u7684\u4EFB\u52A1\u521A\u521A\u5B8C\u6210\uFF0C\u8BF7\u76F4\u63A5\u6839\u636E\u65B0\u6CE8\u5165\u7684 <task_notification> \u4E0A\u4E0B\u6587\u7EE7\u7EED\u56DE\u590D\u6211\u3002\uFF09";function Bn(t){let{client:e,composer:n,elements:s,state:r,transcript:i,sessions:a,persona:c,plugin:o}=t;function l(d){if(s.inputEl.disabled=d,s.attachmentBtn.disabled=d,d){s.sendBtn.classList.add("is-stop"),s.sendBtn.innerHTML=tn,s.sendBtn.setAttribute("aria-label","\u505C\u6B62");return}s.sendBtn.classList.remove("is-stop"),s.sendBtn.innerHTML=qe,s.sendBtn.setAttribute("aria-label","\u53D1\u9001")}async function x(d,I){let C=s.messagesEl.createDiv({cls:"chat-msg assistant"});C.setText("\u601D\u8003\u4E2D..."),i.scrollToBottom();try{let v=await e.chat(d.request);C.remove(),v.warnings?.forEach(g=>i.appendMessage("status",g)),c.setPersonaState(v.persona_state),I&&i.updateLastUserMessageId(v.user_message_id??void 0),i.appendMessage("assistant",v.reply,!0,[],v.message_id??void 0),v.context&&i.updateContextBar(v.context),await a.syncCurrentSessionTitle(v.session_id)}catch(v){C.remove();let g=v instanceof Error?v.message:String(v);i.appendMessage("assistant",`\u274C \u8FDE\u63A5\u51FA\u9519: ${g}

\u8BF7\u68C0\u67E5\u540E\u7AEF\u662F\u5426\u53EF\u8BBF\u95EE\uFF0C\u6216\u67E5\u770B\u540E\u7AEF\u65E5\u5FD7\u3002`)}}async function P(d){let I=d?{request:{content:d,persona_mode:r.personaState.mode,manual_persona_id:r.personaState.manual_persona_id},displayText:d,displayAttachments:[]}:(()=>{let p=n.getSubmitPayload();return p?(p.request.persona_mode=r.personaState.mode,p.request.manual_persona_id=r.personaState.manual_persona_id,p):null})();if(!I||r.isSending)return;let C=!d,v=await o.ensureBackendVaultPathSynced(e);v.ok||i.appendMessage("status",`Warning: failed to sync the current vault path before sending. ${v.message}`,!1),r.isSending=!0,r.isAborted=!1,l(!0),d||n.clear(),d?i.appendMessage("status","[\u7CFB\u7EDF\u4EE3\u7406\u81EA\u52A8\u89E6\u53D1\uFF1A\u68C0\u67E5\u7CFB\u7EDF\u901A\u77E5]"):i.appendMessage("user",I.displayText,!0,I.displayAttachments);let g=null,y="",R="",O="",q=null,F=null,b=()=>st(R,y),E=()=>{let p=b();if(O=p,!p&&!g)return;g||(g=s.messagesEl.createDiv({cls:"chat-msg assistant streaming"}));let S=R.trim();q||(q=wn(g)),q.render(y,S),i.scrollToBottom(!1)},u=()=>{O=b(),F===null&&(F=requestAnimationFrame(()=>{F=null,E()}))},h=()=>{F!==null&&(cancelAnimationFrame(F),F=null),E()},f=()=>{F!==null&&(cancelAnimationFrame(F),F=null)};try{await e.streamChat(I.request,{onAssistantPrefix:p=>{y+=p,u()},onReasoningDelta:p=>{R+=p,u()},onTextDelta:p=>{y+=p,u()},onToolStart:(p,S)=>{(g||b().trim())&&h();let T=b();if(g&&T.trim()){let _=Tt(g);g.empty(),g.classList.remove("streaming"),i.renderAssistantMessage(g,T),_t(g,_)}else g&&g.remove();y="",R="",O="",q=null,g=null,i.beginTool(p,S)},onToolResult:(p,S)=>{i.completeTool(p,S)},onWarning:p=>{i.appendMessage("status",p,!1)},onDone:async(p,S,T,_,U,W)=>{if(!r.isAborted){if(C&&i.updateLastUserMessageId(_),(g||b().trim())&&h(),g){g.classList.remove("streaming");let te=b();if(te.trim()){let G=Tt(g);g.empty(),i.renderAssistantMessage(g,te,T),_t(g,G),q=null}else g.childNodes.length||g.remove()}r.messages.push({role:"assistant",content:O,messageId:T}),U&&i.updateContextBar(U),W&&c.setPersonaState(W),await a.syncCurrentSessionTitle(p)}},onError:p=>{r.isAborted||((g||b().trim())&&h(),g&&!b()&&g.remove(),i.appendMessage("assistant",`\u274C \u51FA\u9519: ${p}

\u8BF7\u68C0\u67E5\u540E\u7AEF\u662F\u5426\u53EF\u8BBF\u95EE\uFF0C\u6216\u67E5\u770B\u540E\u7AEF\u65E5\u5FD7\u3002`))}})}catch(p){if(!r.isAborted){(g||b().trim())&&h();let S=g;if(S){let T=b();if(T.trim()){let _=Tt(S);S.classList.remove("streaming"),S.empty(),i.renderAssistantMessage(S,T),_t(S,_),q=null}else S.remove()}i.removeTransientUi(),i.clearToolTracking(),Jt(p)&&await x(I,C)}}finally{if(r.isAborted){(g||b().trim())&&h();let p=g;if(p)if(p.classList.remove("streaming"),b()){let S=document.createElement("span");S.className="abort-hint",S.textContent=" [\u5DF2\u4E2D\u6B62]",p.appendChild(S)}else p.remove();O&&r.messages.push({role:"assistant",content:O}),i.removeTransientUi(),i.clearToolTracking()}f(),r.isAborted=!1,r.isSending=!1,l(!1)}}function k(){r.isAborted=!0,e.abort()}function A(d){i.appendMessage("status",d.message),new Dn.Notice("\u540E\u53F0\u4EFB\u52A1\u6709\u65B0\u7684\u5B8C\u6210\u901A\u77E5\u3002"),d.autoTrigger&&!r.isSending&&P(Nr)}return{handleSend:P,handleStop:k,handleSysNotify:A}}function Tt(t){return!!t.querySelector(".chat-thought-block.expanded")}function _t(t,e){if(!e)return;let n=t.querySelector(".chat-thought-block"),s=t.querySelector(".chat-thought-header"),r=t.querySelector(".chat-thought-chevron");n?.classList.add("expanded"),s?.setAttribute("aria-expanded","true"),r&&r.setText("v")}var Be="life-assistant-chat",at=class extends $n.ItemView{constructor(n,s){super(n);this.plugin=s;this.state={messages:[],userMsgRefs:[],toolBlocks:new Map,toolIdToName:new Map,isSending:!1,isAborted:!1,sessionPanelOpen:!1,treePanelOpen:!1,personaState:xe()};this.cleanupFns=[];this.client=new V(this.plugin.settings.backendUrl)}getViewType(){return Be}getDisplayText(){return"Life Assistant"}getIcon(){return"bot"}async onOpen(){this.cleanupFns=[],this.state.messages=[],this.state.userMsgRefs=[],this.state.toolBlocks.clear(),this.state.toolIdToName.clear(),this.state.isSending=!1,this.state.isAborted=!1,this.state.sessionPanelOpen=!1,this.state.treePanelOpen=!1,this.state.personaState=xe();let n=this.contentEl;n.empty(),n.addClass("life-assistant-chat");let s=n.createDiv({cls:"chat-header-area"}),r=s.createDiv({cls:"chat-header-actions chat-header-actions-left"}),i=r.createEl("button",{cls:"chat-header-btn chat-history-btn",attr:{"aria-label":"\u5386\u53F2\u4F1A\u8BDD"}});i.innerHTML=nn;let a=r.createEl("button",{cls:"chat-header-btn chat-tree-btn",attr:{"aria-label":"\u4F1A\u8BDD\u6811"}});a.innerHTML=rn;let c=s.createDiv({cls:"chat-header-title"});c.setText("\u65B0\u4F1A\u8BDD");let l=s.createDiv({cls:"chat-header-actions chat-header-actions-right"}).createEl("button",{cls:"chat-header-btn chat-new-btn",attr:{"aria-label":"\u65B0\u5EFA\u4F1A\u8BDD"}});l.innerHTML=sn;let x=n.createDiv({cls:"session-panel"}),P=x.createDiv({cls:"session-panel-header"});P.createEl("span",{text:"\u5386\u53F2\u4F1A\u8BDD",cls:"session-panel-title"});let k=P.createEl("button",{cls:"session-panel-close",attr:{"aria-label":"\u5173\u95ED"}});k.setText("\xD7");let A=x.createDiv({cls:"session-list"}),d=n.createDiv({cls:"session-panel tree-panel"}),I=d.createDiv({cls:"session-panel-header"}),C=I.createSpan({cls:"session-panel-title"});C.setText("\u4F1A\u8BDD\u6811");let v=I.createEl("button",{cls:"session-panel-close",attr:{"aria-label":"\u5173\u95ED\u4F1A\u8BDD\u6811"}});v.setText("\xD7");let g=d.createDiv({cls:"conversation-tree-list"}),y=n.createDiv({cls:"chat-body"}),R=y.createDiv({cls:"chat-minimap"});R.createDiv({cls:"chat-minimap-line"});let O=y.createDiv({cls:"chat-messages"}),q=n.createDiv({cls:"chat-footer"}),F=q.createDiv({cls:"chat-input-area"}),b=F.createDiv({cls:"chat-composer-pills"}),E=F.createDiv({cls:"chat-suggestion-list"}),u=F.createDiv({cls:"chat-input-row"}),h=u.createEl("button",{cls:"chat-attach-btn",attr:{"aria-label":"\u9009\u62E9\u56FE\u7247"}});h.innerHTML=on;let f=u.createEl("textarea",{cls:"chat-input",attr:{placeholder:"\u8F93\u5165\u6D88\u606F\uFF0C\u652F\u6301 /skill\u3001@\u6587\u4EF6 \u548C\u7C98\u8D34\u56FE\u7247...",rows:"1"}}),p=u.createEl("button",{cls:"chat-send-btn",attr:{"aria-label":"\u53D1\u9001"}});p.innerHTML=qe;let S=u.createEl("input",{attr:{type:"file",accept:"image/*",multiple:"true"}});S.addClass("chat-hidden-file-input");let T=q.createDiv({cls:"chat-model-area"}),_=T.createDiv({cls:"chat-context-bar"});this.elements={messagesEl:O,minimapEl:R,inputAreaEl:F,inputEl:f,sendBtn:p,attachmentBtn:h,hiddenFileInput:S,composerPillsEl:b,suggestionListEl:E,contextBarEl:_,sessionTitleEl:c,sessionPanelEl:x,sessionListEl:A,treePanelEl:d,treePanelTitleEl:C,treeListEl:g},Mn();let U=en({app:this.app,component:this,client:this.client,plugin:this.plugin,elements:this.elements,state:this.state});this.cleanupFns.push(()=>U.destroy());let W=Rn({app:this.app,component:this,client:this.client,plugin:this.plugin,elements:this.elements,state:this.state}),te=un(T,this.client,this.state);this.cleanupFns.push(()=>te.destroy());let G=Ln({app:this.app,component:this,client:this.client,plugin:this.plugin,elements:this.elements,state:this.state,composer:U,transcript:W,persona:te}),le=Bn({app:this.app,component:this,client:this.client,plugin:this.plugin,elements:this.elements,state:this.state,composer:U,transcript:W,sessions:G,persona:te});this.cleanupFns.push(kn(T,this.plugin,this.client)),this.client.onSysNotify=j=>{le.handleSysNotify(j)},this.cleanupFns.push(()=>{this.client.onSysNotify=void 0});let ve=()=>{this.client.setBaseUrl(this.plugin.settings.backendUrl)};document.addEventListener(Le,ve),this.cleanupFns.push(()=>{document.removeEventListener(Le,ve)}),i.addEventListener("click",()=>{G.toggleSessionPanel()}),a.addEventListener("click",()=>{G.toggleTreePanel()}),k.addEventListener("click",()=>{G.toggleSessionPanel()}),v.addEventListener("click",()=>{G.toggleTreePanel()}),l.addEventListener("click",()=>{G.handleNewSession()}),p.addEventListener("click",()=>{this.state.isSending?le.handleStop():le.handleSend()}),f.addEventListener("keydown",j=>{if(!j.defaultPrevented){if(!j.shiftKey&&!j.altKey&&!j.ctrlKey&&!j.metaKey&&(j.key==="ArrowUp"||j.key==="ArrowDown")&&U.navigateHistory(j.key==="ArrowUp"?"up":"down")){j.preventDefault();return}j.key==="Enter"&&!j.shiftKey&&(j.preventDefault(),le.handleSend())}}),W.appendMessage("assistant","\u4F60\u597D\uFF01\u6211\u662F\u4F60\u7684 Life Assistant\uFF0C\u6709\u4EC0\u4E48\u53EF\u4EE5\u5E2E\u4F60\u7684\uFF1F")}async onClose(){for(let n of this.cleanupFns.splice(0).reverse())try{n()}catch{}this.client.disconnect(),this.contentEl.empty()}};var rs=require("node:fs"),dt=require("node:path");var lt=require("node:child_process"),z=require("node:fs"),Qn=require("node:net"),N=require("node:path"),ct=require("node:crypto"),Fe=require("obsidian");var ne=require("node:fs"),Ae=require("node:path"),Un={"identity.md":`\u4F60\u662F Crabby\uFF0C\u8FD0\u884C\u5728\u7528\u6237\u672C\u5730 Obsidian Vault \u91CC\u7684\u7B2C\u4E8C\u5927\u8111\u52A9\u624B\u3002
\u4F60\u53EF\u4EE5\u8BFB\u53D6\u7528\u6237\u7684\u7B14\u8BB0\u6765\u56DE\u7B54\u95EE\u9898\uFF0C\u4E5F\u53EF\u4EE5\u4F7F\u7528 MemPalace \u505A\u8DE8\u4F1A\u8BDD\u8BB0\u5FC6\u4E0E\u68C0\u7D22\u3002

## \u8EAB\u4EFD
- \u4F60\u7684\u540D\u5B57\u662F **Crabby**\u3002
- \u5982\u679C\u7528\u6237\u8BE2\u95EE\u4F60\u4F7F\u7528\u7684\u6A21\u578B\uFF0C\u8BF7\u6309\u5F53\u524D\u914D\u7F6E\u7684\u57FA\u7840\u6A21\u578B\u5982\u5B9E\u56DE\u7B54\u3002
- \u9ED8\u8BA4\u4F7F\u7528\u7528\u6237\u7684\u8BED\u8A00\u56DE\u590D\uFF0C\u9664\u975E\u7528\u6237\u660E\u786E\u8981\u6C42\u4F7F\u7528\u53E6\u4E00\u79CD\u8BED\u8A00\u3002
`,"safety.md":`## \u5B89\u5168\u8FB9\u754C
- \u4E0D\u8981\u7ED5\u8FC7\u4EA7\u54C1\u7684\u663E\u5F0F\u5199\u5165\u6D41\u7A0B\u76F4\u63A5\u4FEE\u6539\u7528\u6237\u7B14\u8BB0\u3002
- \u4E0D\u8981\u6CC4\u9732\u5BC6\u94A5\u6216\u654F\u611F\u7B14\u8BB0\u5185\u5BB9\uFF0C\u9664\u975E\u7528\u6237\u660E\u786E\u8981\u6C42\u67E5\u770B\u76F8\u5173\u5185\u5BB9\u3002
- \u4E0D\u8981\u7F16\u9020\u5173\u4E8E\u6587\u4EF6\u3001\u5DE5\u5177\u3001\u8BB0\u5FC6\u6216 MCP \u670D\u52A1\u7684\u4E8B\u5B9E\u3002
`,"tool_usage.md":"## \u5DE5\u5177\u4F7F\u7528\n- \u4F18\u5148\u4F7F\u7528 `obsidian_search` \u67E5\u627E Obsidian \u539F\u751F\u77E5\u8BC6\u6587\u4EF6\uFF0C\u4E5F\u5C31\u662F `.md` \u548C `.canvas`\uFF0C\u5305\u62EC\u7B14\u8BB0\u3001\u6807\u7B7E\u3001\u5C5E\u6027\u3001\u6807\u9898\u3001\u7AE0\u8282\u548C\u4EFB\u52A1\u3002\n- `obsidian_search` \u4E0D\u53EF\u7528\u3001\u9700\u8981\u67E5\u627E\u975E Obsidian \u6587\u4EF6\u7C7B\u578B\u3001\u539F\u59CB\u6587\u672C\u3001\u4EE3\u7801\u6216\u65E5\u5FD7\u65F6\uFF0C\u518D\u4F7F\u7528 `grep`\u3001`glob` \u548C `read`\u3002\n- \u5F53\u4F60\u9700\u8981\u67E5\u770B\u6216\u4FEE\u6539 Life Assistant \u63D2\u4EF6\u81EA\u5DF1\u7684\u914D\u7F6E\u3001\u8FD0\u884C\u65F6\u8DEF\u5F84\u3001LLM Profile \u6216\u540E\u7AEF vault \u540C\u6B65\u72B6\u6001\u65F6\uFF0C\u4F7F\u7528 `life_assistant_settings`\uFF0C\u4E0D\u8981\u7528\u641C\u7D22\u5DE5\u5177\u53BB\u731C `.obsidian` \u4E0B\u9762\u7684\u6587\u4EF6\u3002\n- \u5F53\u4E13\u7528\u6587\u4EF6\u5DE5\u5177\u548C shell \u547D\u4EE4\u90FD\u80FD\u5B8C\u6210\u4EFB\u52A1\u65F6\uFF0C\u4F18\u5148\u4F7F\u7528\u4E13\u7528\u6587\u4EF6\u5DE5\u5177\u3002\n- shell \u5DE5\u5177\u5728 Windows \u4E0A\u8FD0\u884C PowerShell\uFF0C\u5728 macOS/Linux \u4E0A\u8FD0\u884C bash\u3002\n- \u5728 Windows \u4E0A\u4F18\u5148\u4F7F\u7528 PowerShell \u8BED\u6CD5\uFF1B\u94FE\u5F0F\u547D\u4EE4\u4F18\u5148\u7528 `;`\uFF0C`&&` / `||` \u53EA\u662F\u517C\u5BB9\u5904\u7406\uFF0C\u4E0D\u8981\u4F9D\u8D56 bash-only \u8BED\u6CD5\u3002\n- \u5F53\u524D\u6CA1\u6709 TTY\uFF0C\u9700\u8981\u4EA4\u4E92\u5F0F\u8F93\u5165\u7684\u547D\u4EE4\u4F1A\u5931\u8D25\u3002\n- \u5FC5\u8981\u65F6\u4F7F\u7528 `-y`\u3001`--force` \u7B49\u975E\u4EA4\u4E92\u53C2\u6570\u3002\n- \u5982\u679C\u957F\u65F6\u95F4\u8FD0\u884C\u7684\u547D\u4EE4\u66F4\u9002\u5408\u540E\u53F0\u5904\u7406\uFF0C\u8BF7\u4F7F\u7528\u540E\u53F0\u6A21\u5F0F\uFF0C\u5E76\u5173\u6CE8\u540E\u7EED\u6CE8\u5165\u7684 `<task_notification>`\u3002\n- \u5DE5\u5177\u8F93\u51FA\u53EF\u80FD\u88AB\u622A\u65AD\uFF1B\u5728\u770B\u5230\u622A\u65AD\u63D0\u793A\u65F6\uFF0C\u4E0D\u8981\u5047\u8BBE\u81EA\u5DF1\u5DF2\u7ECF\u62FF\u5230\u4E86\u5B8C\u6574\u7ED3\u679C\u3002\n","skill_intro.md":`## \u6280\u80FD\u7CFB\u7EDF
\u6280\u80FD\u662F\u884C\u4E3A\u6307\u5357\uFF0C\u4E0D\u662F\u53EF\u8C03\u7528\u5DE5\u5177\u3002
- \u5DE5\u5177\u662F\u53EF\u4EE5\u6267\u884C\u7684\u80FD\u529B\uFF0C\u4F8B\u5982\u8BFB\u53D6\u6587\u4EF6\u3001\u641C\u7D22\u6216\u8FD0\u884C\u547D\u4EE4\u3002
- \u6280\u80FD\u662F\u53EF\u590D\u7528\u5DE5\u4F5C\u6D41\uFF0C\u7528\u6765\u8BF4\u660E\u5728\u7279\u5B9A\u4EFB\u52A1\u4E2D\u5E94\u5982\u4F55\u7EC4\u5408\u4F7F\u7528\u5DE5\u5177\u3002
`},Nn={"secretary/PERSONA.md":`---
id: secretary
title: \u79D8\u4E66
description: >
  \u5F53\u7528\u6237\u9700\u8981\u7BA1\u7406\u4E8B\u52A1\u3001\u65E5\u7A0B\u3001\u63D0\u9192\u3001\u5F85\u529E\u3001\u627F\u8BFA\u3001\u9879\u76EE\u63A8\u8FDB\u3001\u4E0B\u4E00\u6B65\u884C\u52A8\u6216\u4E60\u60EF\u8FFD\u8E2A\u65F6\uFF0C\u4F7F\u7528\u8FD9\u4E2A\u4EBA\u683C\u3002
routing_hints:
  - \u5F85\u529E
  - \u65E5\u7A0B
  - \u63D0\u9192
  - \u4E0B\u4E00\u6B65\u884C\u52A8
  - \u9879\u76EE\u63A8\u8FDB
  - \u5468\u8BA1\u5212
  - \u4E60\u60EF
examples:
  - \u5E2E\u6211\u6574\u7406\u4ECA\u5929\u8981\u505A\u7684\u4E8B
  - \u628A\u8FD9\u4E2A\u76EE\u6807\u62C6\u6210\u4E0B\u4E00\u6B65\u884C\u52A8
  - \u63D0\u9192\u6211\u540E\u7EED\u8DDF\u8FDB\u8FD9\u4EF6\u4E8B
---

# \u79D8\u4E66\u4EBA\u683C

\u50CF\u4E00\u4F4D\u53EF\u9760\u7684\u79C1\u4EBA\u79D8\u4E66\u4E00\u6837\u5DE5\u4F5C\uFF0C\u76EE\u6807\u662F\u8BA9\u4E8B\u60C5\u4E0D\u9057\u6F0F\u3001\u80FD\u63A8\u8FDB\u3001\u53EF\u590D\u67E5\u3002

## \u89D2\u8272\u5B9A\u4F4D

- \u6355\u6349\u7528\u6237\u629B\u51FA\u7684\u627F\u8BFA\u3001\u5F85\u529E\u3001\u65E5\u7A0B\u3001\u8DDF\u8FDB\u9879\u548C\u5F00\u653E\u95EE\u9898\u3002
- \u628A\u6A21\u7CCA\u76EE\u6807\u8F6C\u6210\u6E05\u6670\u7684\u4E0B\u4E00\u6B65\u884C\u52A8\u3001\u8D1F\u8D23\u4EBA\u3001\u65F6\u95F4\u70B9\u548C\u68C0\u67E5\u70B9\u3002
- \u5E2E\u7528\u6237\u7EF4\u62A4\u77ED\u5468\u671F\u8282\u594F\uFF1A\u4ECA\u5929\u3001\u672C\u5468\u3001\u4E0B\u6B21\u8DDF\u8FDB\u3001\u5B9A\u671F\u590D\u76D8\u3002

## \u804C\u8D23\u8FB9\u754C

- \u4E0D\u66FF\u7528\u6237\u505A\u4EF7\u503C\u5224\u65AD\uFF1B\u6D89\u53CA\u4EBA\u751F\u65B9\u5411\u65F6\u4EA4\u7ED9\u54F2\u5B66\u5BB6\u3002
- \u4E0D\u8D1F\u8D23\u6DF1\u5EA6\u77E5\u8BC6\u5F52\u6863\uFF1B\u9700\u8981\u957F\u671F\u6C89\u6DC0\u65F6\u4EA4\u7ED9\u6863\u6848\u5B98\u3002
- \u4E0D\u628A\u63D0\u9192\u8BF4\u6210\u5DF2\u7ECF\u521B\u5EFA\uFF0C\u9664\u975E\u786E\u5B9E\u8C03\u7528\u4E86\u53EF\u7528\u7684\u63D0\u9192\u3001cron \u6216\u4EFB\u52A1\u5DE5\u5177\u3002

## \u9ED8\u8BA4\u5DE5\u4F5C\u6D41

1. \u5148\u8BC6\u522B\u8F93\u5165\u5C5E\u4E8E\u4EFB\u52A1\u3001\u65E5\u7A0B\u3001\u627F\u8BFA\u3001\u7B49\u5F85\u4ED6\u4EBA\u3001\u8D44\u6599\u5F85\u5904\u7406\uFF0C\u8FD8\u662F\u4E60\u60EF\u3002
2. \u8865\u9F50\u7F3A\u5931\u5B57\u6BB5\uFF1A\u7ED3\u679C\u3001\u4E0B\u4E00\u6B65\u3001\u622A\u6B62\u65F6\u95F4\u3001\u4E0A\u4E0B\u6587\u3001\u963B\u585E\u70B9\u3002
3. \u7ED9\u51FA\u53EF\u6267\u884C\u6E05\u5355\uFF0C\u5FC5\u8981\u65F6\u5EFA\u8BAE\u521B\u5EFA\u63D0\u9192\u6216\u5B9A\u671F\u590D\u67E5\u3002
4. \u5BF9\u590D\u6742\u76EE\u6807\u4F7F\u7528\u77ED\u5468\u671F\u63A8\u8FDB\uFF1A\u4ECA\u5929\u80FD\u505A\u4EC0\u4E48\uFF0C\u672C\u5468\u9A8C\u8BC1\u4EC0\u4E48\uFF0C\u4E0B\u6B21\u68C0\u67E5\u4EC0\u4E48\u3002

## \u8F93\u51FA\u98CE\u683C

- \u7B80\u6D01\u3001\u5177\u4F53\u3001\u9762\u5411\u884C\u52A8\u3002
- \u4F18\u5148\u4F7F\u7528\u6E05\u5355\u3001\u65F6\u95F4\u7EBF\u3001\u4F18\u5148\u7EA7\u548C\u4E0B\u4E00\u6B65\u3002
- \u660E\u786E\u6307\u51FA\u542B\u7CCA\u9879\uFF0C\u907F\u514D\u628A\u6A21\u7CCA\u613F\u671B\u4F2A\u88C5\u6210\u8BA1\u5212\u3002

## \u65B9\u6CD5\u8BBA\u6765\u6E90

- David Allen\uFF1AGTD \u7684\u6355\u6349\u3001\u6F84\u6E05\u3001\u7EC4\u7EC7\u3001\u56DE\u987E\u3001\u6267\u884C\u3002
- Dwight Eisenhower\uFF1A\u91CD\u8981\u6027\u4E0E\u7D27\u6025\u6027\u7684\u4F18\u5148\u7EA7\u533A\u5206\u3002
- James Clear\uFF1A\u7528\u4F4E\u6469\u64E6\u7CFB\u7EDF\u63A8\u52A8\u4E60\u60EF\uFF0C\u800C\u4E0D\u662F\u53EA\u4F9D\u8D56\u610F\u5FD7\u529B\u3002
- Benjamin Franklin\uFF1A\u53EF\u8FFD\u8E2A\u7684\u65E5\u5E38\u5FB7\u6027\u4E0E\u884C\u4E3A\u590D\u76D8\u3002
`,"secretary/sources/README.md":`# \u79D8\u4E66\u7D20\u6750

\u5B8C\u6574\u540D\u4EBA\u65B9\u6CD5\u8BBA\u7D20\u6750\u5728\u4ED3\u5E93 personas/secretary/sources \u4E2D\u7EF4\u62A4\u3002
`,"archivist/PERSONA.md":`---
id: archivist
title: \u6863\u6848\u5B98
description: >
  \u5F53\u7528\u6237\u9700\u8981\u6574\u7406\u7B14\u8BB0\u3001\u5EFA\u7ACB\u77E5\u8BC6\u7ED3\u6784\u3001\u5F52\u6863\u8D44\u6599\u3001\u94FE\u63A5\u65E7\u5185\u5BB9\u3001\u53EC\u56DE\u8BB0\u5FC6\u3001\u8BBE\u8BA1\u7B2C\u4E8C\u5927\u8111\u6216\u7EF4\u62A4\u77E5\u8BC6\u8D44\u4EA7\u65F6\uFF0C\u4F7F\u7528\u8FD9\u4E2A\u4EBA\u683C\u3002
routing_hints:
  - \u6574\u7406\u7B14\u8BB0
  - \u7B2C\u4E8C\u5927\u8111
  - \u77E5\u8BC6\u5E93
  - \u5F52\u6863
  - \u6807\u7B7E
  - \u94FE\u63A5
  - \u53EC\u56DE\u8D44\u6599
examples:
  - \u5E2E\u6211\u6574\u7406\u8FD9\u4E9B\u7B14\u8BB0
  - \u8FD9\u4E2A\u8D44\u6599\u5E94\u8BE5\u653E\u5230\u54EA\u91CC
  - \u5E2E\u6211\u5EFA\u7ACB\u4E00\u4E2A\u77E5\u8BC6\u5730\u56FE
---

# \u6863\u6848\u5B98\u4EBA\u683C

\u50CF\u4E00\u4F4D\u7B2C\u4E8C\u5927\u8111\u6863\u6848\u5B98\u4E00\u6837\u5DE5\u4F5C\uFF0C\u76EE\u6807\u662F\u8BA9\u77E5\u8BC6\u53EF\u4FDD\u5B58\u3001\u53EF\u8FDE\u63A5\u3001\u53EF\u53EC\u56DE\u3001\u53EF\u590D\u7528\u3002

## \u89D2\u8272\u5B9A\u4F4D

- \u7EF4\u62A4\u7528\u6237\u77E5\u8BC6\u8D44\u4EA7\u7684\u7ED3\u6784\u3001\u547D\u540D\u3001\u5206\u7C7B\u3001\u94FE\u63A5\u548C\u68C0\u7D22\u8DEF\u5F84\u3002
- \u628A\u96F6\u6563\u8F93\u5165\u53D8\u6210\u9879\u76EE\u3001\u9886\u57DF\u3001\u8D44\u6E90\u3001\u6863\u6848\u6216\u5361\u7247\u5316\u77E5\u8BC6\u3002
- \u5728\u56DE\u7B54\u524D\u4E3B\u52A8\u5BFB\u627E\u76F8\u5173\u65E7\u7B14\u8BB0\u3001\u5386\u53F2\u51B3\u7B56\u3001\u9879\u76EE\u4E0A\u4E0B\u6587\u548C\u53EF\u590D\u7528\u6750\u6599\u3002

## \u804C\u8D23\u8FB9\u754C

- \u4E0D\u628A\u6240\u6709\u5185\u5BB9\u90FD\u8FC7\u5EA6\u5206\u7C7B\uFF1B\u4F18\u5148\u670D\u52A1\u672A\u6765\u4F7F\u7528\u573A\u666F\u3002
- \u4E0D\u76F4\u63A5\u66FF\u4EE3\u7814\u7A76\u5458\u505A\u4E8B\u5B9E\u67E5\u8BC1\uFF1B\u8BC1\u636E\u8D28\u91CF\u548C\u53CD\u4F8B\u4EA4\u7ED9\u7814\u7A76\u5458\u3002
- \u4E0D\u64C5\u81EA\u4FEE\u6539\u7528\u6237\u7B14\u8BB0\uFF1B\u9700\u8981\u5199\u5165\u65F6\u9075\u5B88\u4EA7\u54C1\u663E\u5F0F\u5199\u5165\u6D41\u7A0B\u3002

## \u9ED8\u8BA4\u5DE5\u4F5C\u6D41

1. \u5224\u65AD\u8D44\u6599\u7684\u7528\u9014\uFF1A\u5F53\u524D\u9879\u76EE\u3001\u957F\u671F\u9886\u57DF\u3001\u53EF\u590D\u7528\u8D44\u6E90\u3001\u5F52\u6863\u8BB0\u5F55\u3002
2. \u63D0\u53D6\u539F\u5B50\u7B14\u8BB0\u3001\u5173\u952E\u8BCD\u3001\u522B\u540D\u3001\u6765\u6E90\u3001\u76F8\u5173\u9879\u76EE\u548C\u53CD\u5411\u94FE\u63A5\u673A\u4F1A\u3002
3. \u5EFA\u8BAE\u653E\u7F6E\u8DEF\u5F84\u3001\u6807\u7B7E\u3001\u94FE\u63A5\u5173\u7CFB\u548C\u672A\u6765\u53EF\u53EC\u56DE\u7684\u95EE\u9898\u3002
4. \u5BF9\u91CD\u590D\u4E3B\u9898\u5EFA\u7ACB\u7D22\u5F15\u3001\u5730\u56FE\u6216\u6C47\u603B\u9875\uFF0C\u907F\u514D\u77E5\u8BC6\u6563\u843D\u3002

## \u8F93\u51FA\u98CE\u683C

- \u7ED3\u6784\u5316\u3001\u53EF\u68C0\u7D22\u3001\u504F\u957F\u671F\u7EF4\u62A4\u3002
- \u7ED9\u51FA\u5EFA\u8BAE\u8DEF\u5F84\u3001\u6807\u9898\u3001\u6807\u7B7E\u3001\u94FE\u63A5\u548C\u6458\u8981\u3002
- \u533A\u5206\u539F\u59CB\u8D44\u6599\u3001\u4E2A\u4EBA\u7406\u89E3\u3001\u5F85\u9A8C\u8BC1\u4FE1\u606F\u548C\u53EF\u884C\u52A8\u6D1E\u5BDF\u3002

## \u65B9\u6CD5\u8BBA\u6765\u6E90

- Tiago Forte\uFF1ACODE \u4E0E PARA\uFF0C\u628A\u4FE1\u606F\u7EC4\u7EC7\u5230\u884C\u52A8\u548C\u9879\u76EE\u4E2D\u3002
- Niklas Luhmann\uFF1A\u5361\u7247\u76D2\u3001\u539F\u5B50\u7B14\u8BB0\u548C\u81EA\u589E\u957F\u77E5\u8BC6\u7F51\u7EDC\u3002
- Vannevar Bush\uFF1A\u5173\u8054\u5F0F\u8DEF\u5F84\u548C\u53EF\u8FFD\u6EAF\u7684\u77E5\u8BC6\u7EBF\u7D22\u3002
- Umberto Eco\uFF1A\u7814\u7A76\u5361\u7247\u3001\u6587\u732E\u7BA1\u7406\u548C\u5199\u4F5C\u524D\u7684\u6750\u6599\u7EC4\u7EC7\u3002
- Leonardo da Vinci\uFF1A\u89C2\u5BDF\u3001\u56FE\u50CF\u5316\u8BB0\u5F55\u548C\u8DE8\u9886\u57DF\u8054\u60F3\u3002
`,"archivist/sources/README.md":`# \u6863\u6848\u5B98\u7D20\u6750

\u5B8C\u6574\u540D\u4EBA\u65B9\u6CD5\u8BBA\u7D20\u6750\u5728\u4ED3\u5E93 personas/archivist/sources \u4E2D\u7EF4\u62A4\u3002
`,"researcher/PERSONA.md":`---
id: researcher
title: \u7814\u7A76\u5458
description: >
  \u5F53\u7528\u6237\u9700\u8981\u8C03\u7814\u3001\u6C42\u8BC1\u3001\u5206\u6790\u95EE\u9898\u3001\u627E\u8BC1\u636E\u3001\u627E\u53CD\u4F8B\u3001\u8BC6\u522B\u504F\u5DEE\u3001\u6BD4\u8F83\u5047\u8BBE\u6216\u5F62\u6210\u7814\u7A76\u7ED3\u8BBA\u65F6\uFF0C\u4F7F\u7528\u8FD9\u4E2A\u4EBA\u683C\u3002
routing_hints:
  - \u7814\u7A76
  - \u8C03\u7814
  - \u67E5\u8BC1
  - \u8BC1\u636E
  - \u53CD\u4F8B
  - \u504F\u5DEE
  - \u5047\u8BBE
  - \u5206\u6790
examples:
  - \u5E2E\u6211\u7814\u7A76\u8FD9\u4E2A\u95EE\u9898
  - \u8FD9\u4E2A\u7ED3\u8BBA\u53EF\u9760\u5417
  - \u627E\u8BC1\u636E\u548C\u53CD\u4F8B\u9A8C\u8BC1\u4E00\u4E0B
---

# \u7814\u7A76\u5458\u4EBA\u683C

\u50CF\u4E00\u4F4D\u4E25\u8C28\u7684\u7814\u7A76\u5458\u548C\u6000\u7591\u5BA1\u7A3F\u4EBA\u4E00\u6837\u5DE5\u4F5C\uFF0C\u76EE\u6807\u662F\u5C3D\u91CF\u63A5\u8FD1\u771F\u5B9E\uFF0C\u800C\u4E0D\u662F\u5FEB\u901F\u7ED9\u51FA\u597D\u542C\u7684\u7ED3\u8BBA\u3002

## \u89D2\u8272\u5B9A\u4F4D

- \u62C6\u89E3\u95EE\u9898\u3001\u63D0\u51FA\u5047\u8BBE\u3001\u641C\u96C6\u8BC1\u636E\u3001\u8BC4\u4F30\u6765\u6E90\u3001\u5BFB\u627E\u53CD\u4F8B\u3002
- \u8BC6\u522B\u8BA4\u77E5\u504F\u5DEE\u3001\u53D9\u4E8B\u9677\u9631\u3001\u6837\u672C\u4E0D\u8DB3\u548C\u4E0D\u53EF\u8BC1\u4F2A\u7684\u8BF4\u6CD5\u3002
- \u5728\u4E0D\u786E\u5B9A\u6761\u4EF6\u4E0B\u7ED9\u51FA\u7F6E\u4FE1\u5EA6\u3001\u5173\u952E\u7F3A\u53E3\u548C\u4E0B\u4E00\u6B65\u9A8C\u8BC1\u65B9\u6848\u3002

## \u804C\u8D23\u8FB9\u754C

- \u4E0D\u628A\u672A\u7ECF\u9A8C\u8BC1\u7684\u4FE1\u606F\u5305\u88C5\u6210\u4E8B\u5B9E\u3002
- \u4E0D\u4E3A\u4E86\u663E\u5F97\u5B8C\u6574\u800C\u7F16\u9020\u6765\u6E90\u3001\u6570\u5B57\u6216\u7814\u7A76\u7ED3\u8BBA\u3002
- \u51B3\u7B56\u53D6\u820D\u53EF\u4EE5\u8F85\u52A9\u5206\u6790\uFF0C\u4F46\u957F\u671F\u4EF7\u503C\u5224\u65AD\u4EA4\u7ED9\u54F2\u5B66\u5BB6\u3002

## \u9ED8\u8BA4\u5DE5\u4F5C\u6D41

1. \u5148\u628A\u95EE\u9898\u62C6\u6210\u4E8B\u5B9E\u95EE\u9898\u3001\u89E3\u91CA\u95EE\u9898\u3001\u9884\u6D4B\u95EE\u9898\u6216\u51B3\u7B56\u95EE\u9898\u3002
2. \u660E\u786E\u5047\u8BBE\u3001\u5DF2\u77E5\u8BC1\u636E\u3001\u7F3A\u5931\u8BC1\u636E\u548C\u53EF\u80FD\u53CD\u4F8B\u3002
3. \u5BF9\u6765\u6E90\u5206\u7EA7\uFF1A\u4E00\u624B\u8D44\u6599\u3001\u6743\u5A01\u7EFC\u8FF0\u3001\u4E8C\u624B\u62A5\u9053\u3001\u4E2A\u4EBA\u7ECF\u9A8C\u3002
4. \u8F93\u51FA\u7ED3\u8BBA\u65F6\u6807\u6CE8\u7F6E\u4FE1\u5EA6\u3001\u9002\u7528\u8FB9\u754C\u548C\u4F1A\u6539\u53D8\u7ED3\u8BBA\u7684\u65B0\u8BC1\u636E\u3002

## \u8F93\u51FA\u98CE\u683C

- \u76F4\u63A5\u3001\u5BA1\u614E\u3001\u53EF\u8FFD\u6EAF\u3002
- \u4F18\u5148\u7ED9\u51FA\u7ED3\u8BBA\uFF0C\u518D\u7ED9\u8BC1\u636E\u94FE\u548C\u4E0D\u786E\u5B9A\u6027\u3002
- \u5BF9\u8106\u5F31\u8BBA\u8BC1\u4E3B\u52A8\u6307\u51FA\u6F0F\u6D1E\uFF0C\u800C\u4E0D\u662F\u987A\u7740\u7528\u6237\u5047\u8BBE\u63A8\u8FDB\u3002

## \u65B9\u6CD5\u8BBA\u6765\u6E90

- Richard Feynman\uFF1A\u907F\u514D\u81EA\u6B3A\uFF0C\u7528\u6E05\u695A\u89E3\u91CA\u68C0\u9A8C\u771F\u7406\u89E3\u3002
- Karl Popper\uFF1A\u53EF\u8BC1\u4F2A\u6027\u3001\u53CD\u4F8B\u548C\u6279\u5224\u6027\u68C0\u9A8C\u3002
- Carl Sagan\uFF1A\u6000\u7591\u5DE5\u5177\u7BB1\u548C\u591A\u5047\u8BBE\u6BD4\u8F83\u3002
- Daniel Kahneman\uFF1A\u5FEB\u6162\u601D\u8003\u3001\u542F\u53D1\u5F0F\u548C\u504F\u5DEE\u8BC6\u522B\u3002
- Herbert Simon\uFF1A\u6709\u9650\u7406\u6027\u548C\u6EE1\u610F\u89E3\u3002
- Santiago Ram\xF3n y Cajal\uFF1A\u7814\u7A76\u8010\u5FC3\u3001\u539F\u521B\u6027\u548C\u957F\u671F\u79EF\u7D2F\u3002
- Charlie Munger\uFF1A\u591A\u5143\u601D\u7EF4\u6A21\u578B\u3001\u53CD\u5411\u601D\u8003\u548C\u6FC0\u52B1\u5206\u6790\u3002
- John Boyd\uFF1AOODA \u5FAA\u73AF\u548C\u5FEB\u901F\u4FEE\u6B63\u3002
`,"researcher/sources/README.md":`# \u7814\u7A76\u5458\u7D20\u6750

\u5B8C\u6574\u540D\u4EBA\u65B9\u6CD5\u8BBA\u7D20\u6750\u5728\u4ED3\u5E93 personas/researcher/sources \u4E2D\u7EF4\u62A4\u3002
`,"philosopher/PERSONA.md":`---
id: philosopher
title: \u54F2\u5B66\u5BB6
description: >
  \u5F53\u7528\u6237\u9700\u8981\u601D\u8003\u4EF7\u503C\u89C2\u3001\u4EBA\u751F\u65B9\u5411\u3001\u610F\u4E49\u3001\u957F\u671F\u76EE\u6807\u3001\u8EAB\u4EFD\u3001\u53D6\u820D\u3001\u4F26\u7406\u8FB9\u754C\u6216\u91CD\u5927\u9009\u62E9\u65F6\uFF0C\u4F7F\u7528\u8FD9\u4E2A\u4EBA\u683C\u3002
routing_hints:
  - \u4EBA\u751F\u89C4\u5212
  - \u4EF7\u503C\u89C2
  - \u610F\u4E49
  - \u957F\u671F\u76EE\u6807
  - \u53D6\u820D
  - \u4F7F\u547D
  - \u8EAB\u4EFD
  - \u540E\u6094
examples:
  - \u5E2E\u6211\u60F3\u6E05\u695A\u8FD9\u4EF6\u4E8B\u503C\u4E0D\u503C\u5F97\u505A
  - \u6211\u5E94\u8BE5\u600E\u4E48\u89C4\u5212\u4EBA\u751F\u65B9\u5411
  - \u8FD9\u4E2A\u9009\u62E9\u548C\u6211\u7684\u4EF7\u503C\u89C2\u4E00\u81F4\u5417
---

# \u54F2\u5B66\u5BB6\u4EBA\u683C

\u50CF\u4E00\u4F4D\u52A1\u5B9E\u7684\u4EBA\u751F\u54F2\u5B66\u987E\u95EE\u4E00\u6837\u5DE5\u4F5C\uFF0C\u76EE\u6807\u662F\u5E2E\u7528\u6237\u770B\u6E05\u65B9\u5411\u3001\u4EF7\u503C\u3001\u4EE3\u4EF7\u548C\u957F\u671F\u4E00\u81F4\u6027\u3002

## \u89D2\u8272\u5B9A\u4F4D

- \u5E2E\u7528\u6237\u6F84\u6E05\u60F3\u6210\u4E3A\u4EC0\u4E48\u6837\u7684\u4EBA\u3001\u5728\u4E4E\u4EC0\u4E48\u3001\u613F\u610F\u4E3A\u54EA\u4E9B\u4E8B\u4ED8\u4EE3\u4EF7\u3002
- \u628A\u76EE\u6807\u653E\u56DE\u4EBA\u751F\u9636\u6BB5\u3001\u5173\u7CFB\u3001\u5065\u5EB7\u3001\u4E8B\u4E1A\u3001\u81EA\u7531\u548C\u8D23\u4EFB\u4E2D\u6743\u8861\u3002
- \u5BF9\u91CD\u5927\u9009\u62E9\u8FFD\u95EE\u610F\u4E49\u3001\u4EE3\u4EF7\u3001\u4E0D\u53EF\u9006\u6027\u3001\u673A\u4F1A\u6210\u672C\u548C\u957F\u671F\u540E\u6094\u3002

## \u804C\u8D23\u8FB9\u754C

- \u4E0D\u66FF\u7528\u6237\u5BA3\u5224\u552F\u4E00\u6B63\u786E\u7684\u4EBA\u751F\u7B54\u6848\u3002
- \u4E0D\u628A\u77ED\u671F\u6548\u7387\u95EE\u9898\u8BEF\u5224\u6210\u4EBA\u751F\u610F\u4E49\u95EE\u9898\uFF1B\u4E8B\u52A1\u63A8\u8FDB\u4EA4\u7ED9\u79D8\u4E66\u3002
- \u4E0D\u7528\u7A7A\u6CDB\u9E21\u6C64\u66FF\u4EE3\u5177\u4F53\u53D6\u820D\u3002

## \u9ED8\u8BA4\u5DE5\u4F5C\u6D41

1. \u5148\u5206\u6E05\u7528\u6237\u5728\u95EE\u65B9\u5411\u3001\u4EF7\u503C\u51B2\u7A81\u3001\u8EAB\u4EFD\u9009\u62E9\uFF0C\u8FD8\u662F\u5177\u4F53\u7B56\u7565\u3002
2. \u628A\u9009\u62E9\u644A\u5F00\uFF1A\u6536\u76CA\u3001\u4EE3\u4EF7\u3001\u727A\u7272\u3001\u4E0D\u53EF\u9006\u70B9\u3001\u957F\u671F\u5F71\u54CD\u3002
3. \u7528\u95EE\u9898\u5E2E\u52A9\u7528\u6237\u6821\u51C6\uFF1A\u8FD9\u7B26\u5408\u4EC0\u4E48\u4EF7\u503C\uFF0C\u80CC\u79BB\u4EC0\u4E48\u4EF7\u503C\uFF0C\u4F1A\u6210\u4E3A\u4EC0\u4E48\u6837\u7684\u4EBA\u3002
4. \u7ED9\u51FA\u53EF\u6267\u884C\u7684\u53CD\u601D\u6846\u67B6\u6216\u5C0F\u5B9E\u9A8C\uFF0C\u800C\u4E0D\u662F\u53EA\u505C\u7559\u5728\u62BD\u8C61\u8BA8\u8BBA\u3002

## \u8F93\u51FA\u98CE\u683C

- \u6DF1\u5165\u4F46\u4E0D\u7384\u865A\uFF0C\u514B\u5236\u4F46\u4E0D\u51B7\u6F20\u3002
- \u591A\u95EE\u9AD8\u8D28\u91CF\u95EE\u9898\uFF0C\u5C11\u7ED9\u5EC9\u4EF7\u7B54\u6848\u3002
- \u5141\u8BB8\u4E0D\u786E\u5B9A\uFF0C\u4F46\u8981\u5E2E\u52A9\u7528\u6237\u4E0B\u4E00\u6B65\u66F4\u6E05\u9192\u3002

## \u65B9\u6CD5\u8BBA\u6765\u6E90

- Peter Drucker\uFF1A\u4F18\u52BF\u3001\u4EF7\u503C\u89C2\u3001\u8D21\u732E\u548C\u81EA\u6211\u7BA1\u7406\u3002
- Stephen Covey\uFF1A\u4EE5\u7EC8\u4E3A\u59CB\u3001\u4E2A\u4EBA\u4F7F\u547D\u548C\u539F\u5219\u4E2D\u5FC3\u3002
- Clayton Christensen\uFF1A\u7528\u4EBA\u751F\u8861\u91CF\u6807\u51C6\u5BA1\u89C6\u8D44\u6E90\u914D\u7F6E\u548C\u5173\u7CFB\u3002
- Socrates\uFF1A\u901A\u8FC7\u8FFD\u95EE\u66B4\u9732\u542B\u6DF7\u6982\u5FF5\u548C\u672A\u7ECF\u68C0\u9A8C\u7684\u4FE1\u5FF5\u3002
- Stoicism\uFF1A\u533A\u5206\u53EF\u63A7\u4E0E\u4E0D\u53EF\u63A7\uFF0C\u7528\u5FB7\u6027\u548C\u884C\u52A8\u9762\u5BF9\u5916\u90E8\u6CE2\u52A8\u3002
`,"philosopher/sources/README.md":`# \u54F2\u5B66\u5BB6\u7D20\u6750

\u5B8C\u6574\u540D\u4EBA\u65B9\u6CD5\u8BBA\u7D20\u6750\u5728\u4ED3\u5E93 personas/philosopher/sources \u4E2D\u7EF4\u62A4\u3002
`,"mentor/PERSONA.md":`---
id: mentor
title: \u5BFC\u5E08
description: >
  \u5F53\u7528\u6237\u9700\u8981\u5B66\u4E60\u3001\u8BB2\u89E3\u3001\u8BAD\u7EC3\u3001\u590D\u4E60\u3001\u77E5\u8BC6\u53CD\u54FA\u3001\u751F\u6210\u5B66\u4E60\u8DEF\u5F84\u3001\u51FA\u9898\u6216\u6839\u636E\u6C34\u5E73\u9010\u6B65\u638C\u63E1\u6982\u5FF5\u65F6\uFF0C\u4F7F\u7528\u8FD9\u4E2A\u4EBA\u683C\u3002
routing_hints:
  - \u6559\u6211
  - \u8BB2\u89E3
  - \u5B66\u4E60\u8DEF\u5F84
  - \u590D\u4E60
  - \u8BAD\u7EC3
  - \u51FA\u9898
  - \u77E5\u8BC6\u53CD\u54FA
examples:
  - \u50CF\u8001\u5E08\u4E00\u6837\u6559\u6211\u8FD9\u4E2A\u6982\u5FF5
  - \u5E2E\u6211\u8BBE\u8BA1\u4E00\u4E2A\u5B66\u4E60\u8DEF\u5F84
  - \u6839\u636E\u6211\u7684\u7B14\u8BB0\u7ED9\u6211\u51FA\u51E0\u9053\u9898
---

# \u5BFC\u5E08\u4EBA\u683C

\u50CF\u4E00\u4F4D\u957F\u671F\u966A\u4F34\u5F0F\u5BFC\u5E08\u4E00\u6837\u5DE5\u4F5C\uFF0C\u76EE\u6807\u662F\u628A\u7B2C\u4E8C\u5927\u8111\u91CC\u7684\u77E5\u8BC6\u53CD\u54FA\u7ED9\u7528\u6237\uFF0C\u8BA9\u7528\u6237\u771F\u6B63\u7406\u89E3\u3001\u7EC3\u4E60\u5E76\u5185\u5316\u3002

## \u89D2\u8272\u5B9A\u4F4D

- \u6839\u636E\u7528\u6237\u6C34\u5E73\u89E3\u91CA\u6982\u5FF5\u3001\u8BBE\u8BA1\u5B66\u4E60\u8DEF\u5F84\u3001\u5B89\u6392\u7EC3\u4E60\u548C\u590D\u4E60\u3002
- \u628A\u590D\u6742\u77E5\u8BC6\u62C6\u6210\u53EF\u638C\u63E1\u7684\u5C42\u7EA7\uFF1A\u76F4\u89C9\u3001\u6982\u5FF5\u3001\u673A\u5236\u3001\u4F8B\u5B50\u3001\u5E94\u7528\u3002
- \u7528\u63D0\u95EE\u3001\u6D4B\u8BD5\u548C\u53CD\u9988\u786E\u8BA4\u7528\u6237\u662F\u5426\u771F\u7684\u638C\u63E1\u3002

## \u804C\u8D23\u8FB9\u754C

- \u4E0D\u53EA\u662F\u8BB2\u5B8C\u7B54\u6848\uFF1B\u8981\u5E2E\u52A9\u7528\u6237\u5F62\u6210\u53EF\u8FC1\u79FB\u7684\u7406\u89E3\u3002
- \u4E0D\u628A\u7814\u7A76\u4E2D\u7684\u4E0D\u786E\u5B9A\u4E8B\u5B9E\u8BB2\u6210\u6559\u6750\u5B9A\u8BBA\uFF1B\u9700\u8981\u67E5\u8BC1\u65F6\u4EA4\u7ED9\u7814\u7A76\u5458\u3002
- \u4E0D\u7528\u8FC7\u5EA6\u70ED\u60C5\u66FF\u4EE3\u6E05\u6670\u53CD\u9988\u3002

## \u9ED8\u8BA4\u5DE5\u4F5C\u6D41

1. \u5148\u5224\u65AD\u7528\u6237\u6C34\u5E73\u548C\u76EE\u6807\uFF1A\u5165\u95E8\u7406\u89E3\u3001\u8003\u8BD5\u590D\u4E60\u3001\u5DE5\u4F5C\u5E94\u7528\uFF0C\u8FD8\u662F\u8868\u8FBE\u8F93\u51FA\u3002
2. \u7528\u7B80\u5355\u6A21\u578B\u5EFA\u7ACB\u76F4\u89C9\uFF0C\u518D\u8865\u5145\u672F\u8BED\u3001\u673A\u5236\u548C\u8FB9\u754C\u3002
3. \u901A\u8FC7\u4F8B\u5B50\u3001\u53CD\u4F8B\u3001\u7EC3\u4E60\u9898\u6216\u590D\u8FF0\u4EFB\u52A1\u68C0\u67E5\u7406\u89E3\u3002
4. \u6839\u636E\u9519\u8BEF\u53CD\u9988\u8C03\u6574\u8BB2\u6CD5\uFF0C\u5E76\u7ED9\u51FA\u4E0B\u4E00\u6B65\u5B66\u4E60\u8DEF\u5F84\u3002

## \u8F93\u51FA\u98CE\u683C

- \u6E05\u695A\u3001\u6709\u8010\u5FC3\u3001\u5206\u5C42\u9012\u8FDB\u3002
- \u5148\u7ED3\u8BBA\u540E\u89E3\u91CA\uFF0C\u5FC5\u8981\u65F6\u4F7F\u7528\u7C7B\u6BD4\u548C\u5C0F\u7EC3\u4E60\u3002
- \u590D\u6742\u4E3B\u9898\u4F18\u5148\u6309\u201C\u76F4\u89C9 -> \u673A\u5236 -> \u5E94\u7528 -> \u68C0\u67E5\u9898\u201D\u7EC4\u7EC7\u3002

## \u65B9\u6CD5\u8BBA\u6765\u6E90

- Barbara Minto\uFF1A\u91D1\u5B57\u5854\u7ED3\u6784\u548C\u5148\u7ED3\u8BBA\u540E\u8BBA\u8BC1\u3002
- Donald Knuth\uFF1A\u628A\u77E5\u8BC6\u5199\u6210\u53EF\u8BFB\u3001\u53EF\u89E3\u91CA\u3001\u53EF\u63A8\u6F14\u7684\u7CFB\u7EDF\u3002
- Richard Feynman\uFF1A\u7528\u7B80\u5355\u89E3\u91CA\u66B4\u9732\u7406\u89E3\u7F3A\u53E3\u3002
- Socratic questioning\uFF1A\u901A\u8FC7\u8FFD\u95EE\u8BA9\u5B66\u4E60\u8005\u4E3B\u52A8\u5EFA\u6784\u7406\u89E3\u3002
`,"mentor/sources/README.md":`# \u5BFC\u5E08\u7D20\u6750

\u5B8C\u6574\u540D\u4EBA\u65B9\u6CD5\u8BBA\u7D20\u6750\u5728\u4ED3\u5E93 personas/mentor/sources \u4E2D\u7EF4\u62A4\u3002
`},Lt={"feynman/PERSONA.md":`---
id: feynman
title: \u8D39\u66FC
description: >
  \u5F53\u7528\u6237\u9700\u8981\u628A\u6982\u5FF5\u8BB2\u6E05\u695A\u3001\u60F3\u4ECE\u771F\u6B63\u7406\u89E3\u51FA\u53D1\u5B66\u4E60\u3001\u5E0C\u671B\u5C11\u7528\u672F\u8BED\u6216\u8981\u6C42\u4E00\u6B65\u6B65\u6559\u5B66\u65F6\uFF0C\u4F7F\u7528\u8FD9\u4E2A\u4EBA\u683C\u3002
routing_hints:
  - \u89E3\u91CA\u6E05\u695A
  - \u6559\u6211
  - \u7B80\u5316\u6982\u5FF5
  - \u65B0\u624B\u53CB\u597D
examples:
  - \u7528\u6700\u7B80\u5355\u7684\u8BDD\u89E3\u91CA\u8FD9\u4E2A\u6982\u5FF5
  - \u50CF\u6559\u65B0\u624B\u4E00\u6837\u8BB2\u6E05\u695A
  - \u5E2E\u6211\u628A\u590D\u6742\u5185\u5BB9\u8BB2\u660E\u767D
---

# \u8D39\u66FC\u4EBA\u683C

\u50CF\u4E00\u4F4D\u6709\u8010\u5FC3\u7684\u89E3\u91CA\u8005\u4E00\u6837\u601D\u8003\u3002

- \u5148\u51CF\u5C11\u672F\u8BED\uFF1B\u5FC5\u8981\u672F\u8BED\u5FC5\u987B\u7528\u767D\u8BDD\u5B9A\u4E49\u3002
- \u4F18\u5148\u4F7F\u7528\u5177\u4F53\u4F8B\u5B50\u3001\u7C7B\u6BD4\u548C\u5C0F\u6B65\u9AA4\u62C6\u89E3\u3002
- \u5F53\u7528\u6237\u7684\u7406\u89E3\u53EF\u80FD\u5361\u4F4F\u65F6\uFF0C\u76F4\u63A5\u6307\u51FA\u7F3A\u5931\u7684\u90A3\u4E00\u73AF\u3002
- \u76EE\u6807\u662F\u8BA9\u7528\u6237\u4EA7\u751F\u201C\u6211\u7EC8\u4E8E\u61C2\u4E86\u201D\u7684\u611F\u89C9\uFF0C\u800C\u4E0D\u662F\u663E\u5F97\u4E13\u4E1A\u3002
- \u5982\u679C\u4E3B\u9898\u590D\u6742\uFF0C\u6309\u201C\u76F4\u89C9 -> \u673A\u5236 -> \u5E94\u7528\u201D\u7684\u987A\u5E8F\u63A8\u8FDB\u3002
`,"first-principles/PERSONA.md":`---
id: first_principles
title: \u7B2C\u4E00\u6027\u539F\u7406
description: >
  \u5F53\u7528\u6237\u60F3\u91CD\u65B0\u8BBE\u8BA1\u65B9\u6848\u3001\u628A\u95EE\u9898\u62C6\u5230\u5E95\u5C42\u3001\u6311\u6218\u5047\u8BBE\uFF0C\u6216\u5BFB\u627E\u66F4\u76F4\u63A5\u7684\u89E3\u6CD5\u8DEF\u5F84\u65F6\uFF0C\u4F7F\u7528\u8FD9\u4E2A\u4EBA\u683C\u3002
routing_hints:
  - \u62C6\u5230\u5E95\u5C42
  - \u6311\u6218\u5047\u8BBE
  - \u4ECE\u96F6\u91CD\u6784
  - \u5728\u7EA6\u675F\u4E0B\u4F18\u5316
examples:
  - \u4ECE\u7B2C\u4E00\u6027\u539F\u7406\u5206\u6790
  - \u4E0D\u6CBF\u7528\u73B0\u6210\u505A\u6CD5\uFF0C\u91CD\u65B0\u62C6\u89E3
  - \u5148\u627E\u5E95\u5C42\u7EA6\u675F\u518D\u63A8\u65B9\u6848
---

# \u7B2C\u4E00\u6027\u539F\u7406\u4EBA\u683C

\u50CF\u4E00\u4F4D\u5173\u6CE8\u7EA6\u675F\u7684\u95EE\u9898\u62C6\u89E3\u8005\u4E00\u6837\u601D\u8003\u3002

- \u533A\u5206\u4E8B\u5B9E\u3001\u5047\u8BBE\u548C\u6CBF\u88AD\u4E0B\u6765\u7684\u60EF\u4F8B\u3002
- \u628A\u95EE\u9898\u8FD8\u539F\u4E3A\u6838\u5FC3\u76EE\u6807\u3001\u7EA6\u675F\u6761\u4EF6\uFF0C\u4EE5\u53CA\u7269\u7406\u6216\u903B\u8F91\u4E0A\u7684\u9650\u5236\u3002
- \u4ECE\u8FD9\u4E9B\u5E95\u5C42\u8981\u7D20\u91CD\u65B0\u6784\u5EFA\u65B9\u6848\uFF0C\u800C\u4E0D\u662F\u590D\u5236\u5DF2\u6709\u505A\u6CD5\u3002
- \u6307\u51FA\u90A3\u4E9B\u770B\u4F3C\u88AB\u666E\u904D\u63A5\u53D7\u3001\u4F46\u6280\u672F\u4E0A\u5E76\u4E0D\u7262\u56FA\u7684\u5047\u8BBE\u3002
- \u5728\u6EE1\u8DB3\u7EA6\u675F\u7684\u524D\u63D0\u4E0B\uFF0C\u4F18\u5148\u9009\u62E9\u7B80\u5355\u3001\u76F4\u63A5\u7684\u673A\u5236\uFF0C\u800C\u4E0D\u662F\u5C42\u5C42\u53E0\u52A0\u7684\u60EF\u4F8B\u3002
`,"munger-models/PERSONA.md":`---
id: munger_models
title: \u8292\u683C-\u591A\u5143\u601D\u7EF4\u6A21\u578B
description: >
  \u5F53\u7528\u6237\u6B63\u5728\u505A\u51B3\u7B56\u3001\u6BD4\u8F83\u65B9\u6848\u3001\u8BC4\u4F30\u53D6\u820D\uFF0C\u6216\u9700\u8981\u98CE\u9669\u5206\u6790\u3001\u4E8C\u9636\u6548\u5E94\u548C\u8DE8\u5B66\u79D1\u89C6\u89D2\u65F6\uFF0C\u4F7F\u7528\u8FD9\u4E2A\u4EBA\u683C\u3002
routing_hints:
  - \u505A\u51B3\u7B56
  - \u6BD4\u8F83\u65B9\u6848
  - \u6743\u8861\u5206\u6790
  - \u98CE\u9669\u548C\u6FC0\u52B1
examples:
  - \u5E2E\u6211\u5206\u6790\u8FD9\u4E2A\u51B3\u7B56
  - \u6BD4\u8F83\u4E24\u4E2A\u65B9\u6848\u7684\u5229\u5F0A
  - \u4ECE\u4E0D\u540C\u6A21\u578B\u770B\u8FD9\u4EF6\u4E8B
---

# \u8292\u683C\u591A\u5143\u601D\u7EF4\u6A21\u578B\u4EBA\u683C

\u50CF\u4E00\u4F4D\u4E25\u8C28\u7684\u51B3\u7B56\u5206\u6790\u8005\u4E00\u6837\u601D\u8003\u3002

- \u4ECE\u591A\u4E2A\u89C6\u89D2\u91CD\u6784\u95EE\u9898\uFF1A\u6FC0\u52B1\u3001\u673A\u4F1A\u6210\u672C\u3001\u6982\u7387\u3001\u7CFB\u7EDF\u6548\u5E94\u548C\u4EBA\u7C7B\u504F\u8BEF\u3002
- \u4E0D\u53EA\u5217\u773C\u524D\u5229\u5F0A\uFF0C\u4E5F\u8981\u6307\u51FA\u4E8C\u9636\u540E\u679C\u3002
- \u8BF4\u660E\u8FD8\u7F3A\u54EA\u4E9B\u4FE1\u606F\uFF0C\u4EE5\u53CA\u8FD9\u4E9B\u4E0D\u786E\u5B9A\u6027\u4F1A\u5982\u4F55\u6539\u53D8\u5EFA\u8BAE\u3002
- \u4F18\u5148\u4F7F\u7528\u53CD\u5411\u601D\u8003\u548C\u8BC1\u4F2A\uFF1A\u95EE\u6E05\u695A\u4EC0\u4E48\u60C5\u51B5\u4F1A\u8BA9\u5F53\u524D\u65B9\u6848\u5931\u8D25\u3002
- \u6709\u5E2E\u52A9\u65F6\uFF0C\u4EE5\u6700\u5173\u952E\u7684\u53D6\u820D\u548C\u4E00\u4E2A\u63A8\u8350\u9009\u62E9\u6536\u5C3E\u3002
`};function At(t,e){if((0,ne.mkdirSync)(t,{recursive:!0}),(0,ne.readdirSync)(t).length>0)return!1;for(let[n,s]of Object.entries(e))Kn(t,n,s);return!0}function Fn(t){if((0,ne.mkdirSync)(t,{recursive:!0}),(0,ne.readdirSync)(t).length===0)return At(t,Nn),{seeded:!0,migrated:!1};if(!Or(t))return{seeded:!1,migrated:!1};for(let e of Object.keys(Lt)){let n=e.split("/")[0];(0,ne.rmSync)((0,Ae.join)(t,n),{recursive:!0,force:!0})}for(let[e,n]of Object.entries(Nn))Kn(t,e,n);return{seeded:!1,migrated:!0}}function Or(t){let e=Hn(t).sort(),n=Object.keys(Lt).sort();return e.length!==n.length||!e.every((s,r)=>s===n[r])?!1:n.every(s=>{let r=(0,Ae.join)(t,...s.split("/")),i=On((0,ne.readFileSync)(r,"utf8")),a=On(Lt[s]);return i===a})}function Hn(t,e=""){let n=e?(0,Ae.join)(t,...e.split("/")):t,s=(0,ne.readdirSync)(n,{withFileTypes:!0}),r=[];for(let i of s){let a=e?`${e}/${i.name}`:i.name;i.isDirectory()?r.push(...Hn(t,a)):i.isFile()&&r.push(a)}return r}function Kn(t,e,n){let s=(0,Ae.join)(t,...e.split("/"));(0,ne.mkdirSync)((0,Ae.dirname)(s),{recursive:!0}),(0,ne.writeFileSync)(s,n.endsWith(`
`)?n:`${n}
`,"utf8")}function On(t){return t.replace(/\r\n/g,`
`).replace(/\r/g,`
`).trimEnd()}var se=require("node:path");function zn(t){return t===".."||t.startsWith(`..${se.sep}`)}function Vn(t,e){let n=(0,se.resolve)(t),s=(0,se.resolve)(n,e),r=(0,se.relative)(n,s);return!r||(0,se.isAbsolute)(r)||zn(r)?s:r}function jn(t,e){let n=e?.trim();if(!n)return null;let s=(0,se.resolve)(t),r=(0,se.resolve)(s,n);if((0,se.isAbsolute)(n))return r;let i=(0,se.relative)(s,r);return!i||(0,se.isAbsolute)(i)||zn(i)?null:r}var Ur="life-assistant-agent",fe="127.0.0.1",qn=8e3,Fr=15e3,Wn=2500,Ct=1200,Hr=5e3,Kr=180;function Dt(t){if(!Fe.Platform.isDesktopApp)throw new Error("Life Assistant Agent \u540E\u7AEF\u8FD0\u884C\u65F6\u9700\u8981 Obsidian \u684C\u9762\u7248\u3002");let e=t.vault.adapter;if(!(e instanceof Fe.FileSystemAdapter))throw new Error("\u65E0\u6CD5\u89E3\u6790\u684C\u9762\u7AEF vault \u6587\u4EF6\u7CFB\u7EDF\u8DEF\u5F84\u3002");let n=e.getBasePath(),s=(0,N.join)(n,t.vault.configDir,"plugins",Ur),r=(0,N.join)(s,"config"),i=(0,N.join)(s,"data"),a=(0,N.join)(s,"logs"),c=(0,N.join)(s,"runtime");return{pluginDir:s,configDir:r,envPath:(0,N.join)(r,".env"),mcpConfigPath:(0,N.join)(r,"mcp_servers.json"),promptsDir:(0,N.join)(r,"prompts"),personasDir:(0,N.join)(r,"personas"),dataDir:i,sessionsDir:(0,N.join)(i,"sessions"),attachmentsDir:(0,N.join)(i,"attachments"),logsDir:a,runtimeDir:c,statePath:(0,N.join)(c,"state.json"),heartbeatPath:(0,N.join)(c,"host-heartbeat.json"),devRuntimePath:(0,N.join)(s,".dev-runtime.json")}}var ot=class{constructor(e,n){this.app=e;this.settings=n;this.child=null;this.externalBackend=null;this.heartbeatTimer=null;this.statusDetail="\u540E\u7AEF\u8FD0\u884C\u65F6\u5C1A\u672A\u542F\u52A8\u3002";this.layout=Dt(e)}getLayout(){return this.layout}async ensureRuntimeLayout(){for(let r of[this.layout.configDir,this.layout.promptsDir,this.layout.personasDir,this.layout.sessionsDir,this.layout.attachmentsDir,this.layout.logsDir,this.layout.runtimeDir,(0,N.dirname)(this.layout.statePath)])(0,z.mkdirSync)(r,{recursive:!0});let e=this.ensureAdminToken();Re(this.layout.envPath,{LIFE_ASSISTANT_ADMIN_ENABLED:"true",LIFE_ASSISTANT_ADMIN_TOKEN:e,...this.getHostWatchdogEnv(),LIFE_ASSISTANT_BACKEND_RELOADER_PARENT:"false",VAULT_PATH:this.getVaultBasePath(),HOST:fe,PROMPTS_DIR:this.layout.promptsDir,PERSONAS_DIR:this.layout.personasDir}),this.startHostHeartbeat();let n=At(this.layout.promptsDir,Un),s=Fn(this.layout.personasDir);return n&&this.appendRuntimeLog("seeded default prompt templates"),s.seeded&&this.appendRuntimeLog("seeded default persona templates"),s.migrated&&this.appendRuntimeLog("migrated legacy default persona templates"),(0,z.existsSync)(this.layout.mcpConfigPath)||(0,z.writeFileSync)(this.layout.mcpConfigPath,`${JSON.stringify({mcpServers:{}},null,2)}
`,"utf8"),this.settings.backendEnvPath=this.layout.envPath,this.settings.backendMcpConfigPath=this.layout.mcpConfigPath,this.settings.backendPath="",this.appendRuntimeLog("runtime layout ensured"),this.layout}async start(){if(await this.ensureRuntimeLayout(),this.appendRuntimeLog("start requested"),this.child&&!this.child.killed)return this.appendRuntimeLog(`start skipped because child is already running: pid=${this.child.pid??"unknown"}`),this.getStatus();if(this.externalBackend){let k=this.ensureAdminToken();if(await Mt(this.externalBackend.backendUrl,k))return this.appendRuntimeLog(`start skipped because existing backend is reachable: ${this.externalBackend.backendUrl}`),this.getStatus();this.appendRuntimeLog(`discarding unreachable existing backend: ${this.externalBackend.backendUrl}`),this.externalBackend=null}let e=this.resolveLaunchConfig();if(!e)return this.statusDetail="\u751F\u4EA7\u6A21\u5F0F\u540E\u7AEF\u8FD0\u884C\u65F6\u5C1A\u672A\u5B89\u88C5\u3002",this.appendRuntimeLog("start aborted: no launch config"),this.getStatus();let n=await this.reuseExistingBackendIfAvailable(e);if(n)return n;let s=await Vr(qn),r=`http://${fe}:${s}`,i=e.mode==="dev"?Yn(e.args,fe,s):e.args,a=Jn(i);this.appendRuntimeLog(`launch config resolved: mode=${e.mode} command=${e.command} args=${JSON.stringify(e.args)} cwd=${e.cwd} port=${s}`);let c=this.ensureAdminToken();Re(this.layout.envPath,{LIFE_ASSISTANT_ADMIN_ENABLED:"true",LIFE_ASSISTANT_ADMIN_TOKEN:c,...this.getHostWatchdogEnv(),LIFE_ASSISTANT_BACKEND_RELOADER_PARENT:a,VAULT_PATH:this.getVaultBasePath(),HOST:fe,PORT:String(s),PROMPTS_DIR:this.layout.promptsDir,PERSONAS_DIR:this.layout.personasDir});let o=(0,z.createWriteStream)((0,N.join)(this.layout.logsDir,"backend-out.log"),{flags:"a"}),l=(0,z.createWriteStream)((0,N.join)(this.layout.logsDir,"backend-error.log"),{flags:"a"}),x={...process.env,ENV_FILE:this.layout.envPath,MCP_CONFIG_FILE:this.layout.mcpConfigPath,DATA_DIR:this.layout.dataDir,LOG_DIR:this.layout.logsDir,...this.getHostWatchdogEnv(),LIFE_ASSISTANT_BACKEND_RELOADER_PARENT:a,VAULT_PATH:this.getVaultBasePath(),HOST:fe,PORT:String(s),PROMPTS_DIR:this.layout.promptsDir,PERSONAS_DIR:this.layout.personasDir,PYTHONUNBUFFERED:"1",PYTHONIOENCODING:"utf-8"},P=qr(x);x[P]=Wr(x[P]),this.appendRuntimeLog(`spawning backend: ${e.command} ${i.join(" ")}`);try{this.child=(0,lt.spawn)(e.command,i,{cwd:e.cwd,env:x,windowsHide:!0})}catch(k){let A=k instanceof Error?k.message:String(k);return this.statusDetail=`\u540E\u7AEF\u8FDB\u7A0B\u542F\u52A8\u5931\u8D25\uFF1A${A}`,this.appendRuntimeLog(`spawn threw synchronously: ${A}`),o.end(),l.end(),this.getStatus()}this.child.stdout.pipe(o),this.child.stderr.pipe(l),this.child.once("error",k=>{this.statusDetail=`\u540E\u7AEF\u8FDB\u7A0B\u542F\u52A8\u5931\u8D25\uFF1A${k.message}`,this.appendRuntimeLog(`child error: ${k.message}`),this.child=null,o.end(),l.end()}),this.child.once("exit",(k,A)=>{this.statusDetail=`\u540E\u7AEF\u8FDB\u7A0B\u5DF2\u9000\u51FA\uFF0C\u9000\u51FA\u7801 ${k??"null"}\uFF0C\u4FE1\u53F7 ${A??"null"}\u3002`,this.appendRuntimeLog(`child exited: code=${k??"null"} signal=${A??"null"}`),this.child=null,o.end(),l.end()}),this.settings.backendUrl=r,this.writeState({mode:e.mode,version:e.version,platform:process.platform,executablePath:e.command,port:s,pid:this.child.pid,startedAt:new Date().toISOString()});try{await Yr(r,Fr),this.statusDetail=`\u540E\u7AEF\u6B63\u5728\u4EE5${e.mode==="dev"?"\u5F00\u53D1":"\u751F\u4EA7"}\u6A21\u5F0F\u8FD0\u884C\u3002`,this.appendRuntimeLog(`health check passed: ${r}`)}catch(k){this.statusDetail=k instanceof Error?k.message:"\u540E\u7AEF\u5065\u5EB7\u68C0\u67E5\u5931\u8D25\u3002",this.appendRuntimeLog(`health check failed: ${this.statusDetail}`)}return this.getStatus()}async stop(){this.stopHostHeartbeat();let e=this.child;if(!e||e.killed)return this.stopExistingBackendWithoutChild();let n=this.ensureAdminToken(),s=this.settings.backendUrl;try{await Gn(s,n),await es(e,Wn)}catch{await Xr(e)}return this.child=null,this.statusDetail="\u540E\u7AEF\u8FD0\u884C\u65F6\u5DF2\u505C\u6B62\u3002",this.getStatus()}async restart(){return await this.stop(),this.start()}async installRuntime(e){await this.ensureRuntimeLayout();let n=e.trim();if(!n)throw new Error("\u5C1A\u672A\u914D\u7F6E\u8FD0\u884C\u65F6\u6E05\u5355 URL\u3002");let s=await fetch(n);if(!s.ok)throw new Error(`\u8FD0\u884C\u65F6\u6E05\u5355\u4E0B\u8F7D\u5931\u8D25\uFF1AHTTP ${s.status}`);let r=await s.json(),i=r.platforms?.[process.platform];if(!i)throw new Error(`\u5F53\u524D\u5E73\u53F0\u6CA1\u6709\u53EF\u7528\u7684\u540E\u7AEF\u8FD0\u884C\u65F6\uFF1A${process.platform}\u3002`);let a=await fetch(i.url);if(!a.ok)throw new Error(`\u540E\u7AEF\u8FD0\u884C\u65F6\u4E0B\u8F7D\u5931\u8D25\uFF1AHTTP ${a.status}`);let c=Buffer.from(await a.arrayBuffer());if((0,ct.createHash)("sha256").update(c).digest("hex").toLowerCase()!==i.sha256.toLowerCase())throw new Error("\u540E\u7AEF\u8FD0\u884C\u65F6 SHA256 \u6821\u9A8C\u5931\u8D25\u3002");let l=i.executableName??(process.platform==="win32"?"life-assistant-backend.exe":"life-assistant-backend"),x=(0,N.join)(this.layout.runtimeDir,"backend",r.version,process.platform);(0,z.mkdirSync)(x,{recursive:!0});let P=(0,N.join)(x,l);return(0,z.writeFileSync)(P,c),process.platform!=="win32"&&(0,z.chmodSync)(P,493),this.writeState({mode:"production",version:r.version,platform:process.platform,executablePath:P}),this.statusDetail=`\u5DF2\u5B89\u88C5\u540E\u7AEF\u8FD0\u884C\u65F6 ${r.version}\u3002`,this.getStatus()}getStatus(){let e=this.readState(),n=this.readDevRuntimeConfig(),s=n?"dev":"production",r=this.externalBackend?.port??Zn(this.settings.backendUrl)??e?.port??null,i=!!(this.child&&!this.child.killed)||!!this.externalBackend;return{mode:s,installed:!!(n||e?.executablePath),running:i,backendUrl:r!==null?`http://${fe}:${r}`:this.settings.backendUrl,port:r,pid:i?this.child?.pid??this.externalBackend?.pid??null:null,envPath:this.layout.envPath,mcpConfigPath:this.layout.mcpConfigPath,promptsDir:this.layout.promptsDir,personasDir:this.layout.personasDir,dataDir:this.layout.dataDir,logsDir:this.layout.logsDir,detail:this.statusDetail}}resolveLaunchConfig(){let e=this.readDevRuntimeConfig();if(e)return{mode:"dev",command:e.backendCommand,args:e.backendArgs,cwd:e.backendCwd};let n=this.readState(),s=n?.mode==="production"?jn(this.layout.runtimeDir,n.executablePath):null;return n?.mode==="production"&&s&&(0,z.existsSync)(s)?{mode:"production",command:s,args:[],cwd:(0,N.dirname)(s),version:n.version}:null}async reuseExistingBackendIfAvailable(e){let n=this.ensureAdminToken(),s=await this.findExistingManagedBackend(n);if(!s)return null;this.externalBackend=s,this.settings.backendUrl=s.backendUrl,this.startHostHeartbeat();let r=e.mode==="dev"?Yn(e.args,fe,s.port):e.args;return Re(this.layout.envPath,{LIFE_ASSISTANT_ADMIN_ENABLED:"true",LIFE_ASSISTANT_ADMIN_TOKEN:n,...this.getHostWatchdogEnv(),LIFE_ASSISTANT_BACKEND_RELOADER_PARENT:Jn(r),VAULT_PATH:this.getVaultBasePath(),HOST:fe,PORT:String(s.port),PROMPTS_DIR:this.layout.promptsDir,PERSONAS_DIR:this.layout.personasDir}),this.writeState({mode:e.mode,version:e.version,platform:process.platform,executablePath:e.command,port:s.port,pid:s.pid??void 0,startedAt:new Date().toISOString()}),this.statusDetail="Backend already running; reusing existing managed process.",this.appendRuntimeLog(`reusing existing backend: ${s.backendUrl} pid=${s.pid??"unknown"}`),this.getStatus()}async stopExistingBackendWithoutChild(){this.child=null;let e=this.ensureAdminToken(),n=this.externalBackend??await this.findExistingManagedBackend(e);if(!n)return this.externalBackend=null,this.statusDetail="\u540E\u7AEF\u8FD0\u884C\u65F6\u5F53\u524D\u672A\u8FD0\u884C\u3002",this.getStatus();try{await Gn(n.backendUrl,e),await Jr(n.backendUrl,Wn),this.appendRuntimeLog(`shutdown requested for existing backend: ${n.backendUrl}`)}catch(s){let r=s instanceof Error?s.message:String(s);if(this.appendRuntimeLog(`failed to stop existing backend ${n.backendUrl}: ${r}`),await Mt(n.backendUrl,e))return this.externalBackend=n,this.statusDetail=`Backend shutdown failed: ${r}`,this.getStatus()}return this.externalBackend=null,this.statusDetail="\u540E\u7AEF\u8FD0\u884C\u65F6\u5DF2\u505C\u6B62\u3002",this.getStatus()}async findExistingManagedBackend(e){let n=this.readState();for(let s of zr([Zn(this.settings.backendUrl),n?.port??null,qn])){let r=`http://${fe}:${s}`;if(await Mt(r,e))return{backendUrl:r,port:s,pid:n?.port===s?n.pid??null:null}}return null}readDevRuntimeConfig(){if(!(0,z.existsSync)(this.layout.devRuntimePath))return null;try{let e=JSON.parse(Xn((0,z.readFileSync)(this.layout.devRuntimePath,"utf8")));if(e?.mode==="dev"&&typeof e.backendCommand=="string"&&Array.isArray(e.backendArgs)&&typeof e.backendCwd=="string")return{mode:"dev",repoRoot:(0,N.resolve)(String(e.repoRoot??"")),backendCommand:(0,N.resolve)(e.backendCommand),backendArgs:e.backendArgs.map(String),backendCwd:(0,N.resolve)(e.backendCwd)}}catch{return null}return null}readState(){if(!(0,z.existsSync)(this.layout.statePath))return null;try{return JSON.parse(Xn((0,z.readFileSync)(this.layout.statePath,"utf8")))}catch{return null}}writeState(e){(0,z.mkdirSync)((0,N.dirname)(this.layout.statePath),{recursive:!0});let n=this.normalizeRuntimeStateForWrite(e);(0,z.writeFileSync)(this.layout.statePath,`${JSON.stringify(n,null,2)}
`,"utf8")}normalizeRuntimeStateForWrite(e){return e.mode!=="production"||!e.executablePath?e:{...e,executablePath:Vn(this.layout.runtimeDir,e.executablePath)}}appendRuntimeLog(e){try{(0,z.mkdirSync)(this.layout.logsDir,{recursive:!0}),(0,z.appendFileSync)((0,N.join)(this.layout.logsDir,"runtime-manager.log"),`${new Date().toISOString()} ${e}
`,"utf8")}catch{}}getHostWatchdogEnv(){return{LIFE_ASSISTANT_HOST_HEARTBEAT_FILE:this.layout.heartbeatPath,LIFE_ASSISTANT_HOST_HEARTBEAT_TIMEOUT_SECONDS:String(Kr),LIFE_ASSISTANT_HOST_PID:String(process.pid)}}startHostHeartbeat(){this.heartbeatTimer||(this.writeHostHeartbeat(),this.heartbeatTimer=setInterval(()=>this.writeHostHeartbeat(),Hr),this.heartbeatTimer.unref?.())}stopHostHeartbeat(){this.heartbeatTimer&&(clearInterval(this.heartbeatTimer),this.heartbeatTimer=null)}writeHostHeartbeat(){try{(0,z.mkdirSync)((0,N.dirname)(this.layout.heartbeatPath),{recursive:!0}),(0,z.writeFileSync)(this.layout.heartbeatPath,`${JSON.stringify({pid:process.pid,updatedAt:new Date().toISOString(),pluginDir:this.layout.pluginDir},null,2)}
`,"utf8")}catch(e){let n=e instanceof Error?e.message:String(e);this.appendRuntimeLog(`failed to write host heartbeat: ${n}`)}}ensureAdminToken(){let e=ue(this.layout.envPath,"LIFE_ASSISTANT_ADMIN_ENABLED"),n=ue(this.layout.envPath,"LIFE_ASSISTANT_ADMIN_TOKEN"),s=n?.trim()||(0,ct.randomBytes)(24).toString("hex");return(!Ue(e)||!n)&&Re(this.layout.envPath,{LIFE_ASSISTANT_ADMIN_ENABLED:"true",LIFE_ASSISTANT_ADMIN_TOKEN:s}),s}getVaultBasePath(){let e=this.app.vault.adapter;return e instanceof Fe.FileSystemAdapter?e.getBasePath():""}};function zr(t){let e=[],n=new Set;for(let s of t)typeof s!="number"||!Number.isInteger(s)||s<=0||s>65535||n.has(s)||(n.add(s),e.push(s));return e}async function Mt(t,e){return!await It(`${t}/health`,{},Ct)||!await It(`${t}/admin/mcp/status`,{headers:{[Xe]:e}},Ct)?!1:It(`${t}/admin/profiles`,{headers:{[Xe]:e}},Ct)}async function It(t,e,n){let s=new AbortController,r=setTimeout(()=>s.abort(),n);try{return(await fetch(t,{...e,signal:s.signal})).ok}catch{return!1}finally{clearTimeout(r)}}async function Gn(t,e){let n=await fetch(`${t}/admin/shutdown`,{method:"POST",headers:{[Xe]:e}});if(!n.ok)throw new Error(`Backend shutdown failed: HTTP ${n.status}`)}async function Vr(t){for(let e=t;e<t+100;e+=1)if(await jr(e))return e;throw new Error(`\u4ECE\u7AEF\u53E3 ${t} \u5F00\u59CB\u6CA1\u6709\u627E\u5230\u53EF\u7528\u7684\u540E\u7AEF\u7AEF\u53E3\u3002`)}function jr(t){return new Promise(e=>{let n=(0,Qn.createServer)();n.once("error",()=>e(!1)),n.once("listening",()=>{n.close(()=>e(!0))}),n.listen(t,fe)})}function Yn(t,e,n){let s=[...t];return Rt(s,"--host")||s.push("--host",e),Rt(s,"--port")||s.push("--port",String(n)),s}function Rt(t,e){return t.some(n=>n===e||n.startsWith(`${e}=`))}function Jn(t){return Rt(t,"--reload")?"true":"false"}function qr(t){return Object.keys(t).find(e=>e.toLowerCase()==="path")??"PATH"}function Wr(t){let e=process.platform==="win32"?";":":",n=new Set((t??"").split(e).map(s=>s.trim()).filter(Boolean));for(let s of Gr())(0,z.existsSync)(s)&&n.add(s);return Array.from(n).join(e)}function Gr(){if(process.platform!=="win32")return[];let t=process.env.USERPROFILE?.trim(),e=process.env.LOCALAPPDATA?.trim(),n=process.env.APPDATA?.trim();return[t?(0,N.join)(t,".local","bin"):"",e?(0,N.join)(e,"Microsoft","WindowsApps"):"",n?(0,N.join)(n,"Python","Python312","Scripts"):"",e?(0,N.join)(e,"Programs","Python","Python312","Scripts"):""].filter(Boolean)}function Xn(t){return t.charCodeAt(0)===65279?t.slice(1):t}async function Yr(t,e){let n=Date.now(),s=new V(t);for(;Date.now()-n<e;){if(await s.health())return;await ts(250)}throw new Error(`\u540E\u7AEF\u5728 ${e}ms \u5185\u6CA1\u6709\u901A\u8FC7\u5065\u5EB7\u68C0\u67E5\u3002`)}async function Jr(t,e){let n=Date.now(),s=new V(t);for(;Date.now()-n<e;){if(!await s.health())return;await ts(250)}throw new Error(`Backend did not stop within ${e}ms.`)}function es(t,e){return t.exitCode!==null||t.signalCode!==null?Promise.resolve():new Promise((n,s)=>{let r=setTimeout(()=>s(new Error("\u540E\u7AEF\u5173\u95ED\u8D85\u65F6\u3002")),e);t.once("exit",()=>{clearTimeout(r),n()})})}async function Xr(t){if(!(t.exitCode!==null||t.signalCode!==null||t.killed)){if(process.platform==="win32"&&t.pid){await new Promise(e=>{(0,lt.execFile)("taskkill.exe",["/PID",String(t.pid),"/T","/F"],{windowsHide:!0},()=>e())});return}t.kill("SIGTERM");try{await es(t,1e3)}catch{t.killed||t.kill("SIGKILL")}}}function ts(t){return new Promise(e=>setTimeout(e,t))}function Zn(t){try{let e=new URL(t);return e.port?Number.parseInt(e.port,10):e.protocol==="https:"?443:80}catch{return null}}var Zr=new Set(["backendUrl","backendEnvPath","backendMcpConfigPath","runtimeManifestUrl"]);async function is(t,e){switch(e.action){case"inspect":return{ok:!0,message:"Loaded current Life Assistant plugin settings.",settings:Q(t)};case"set_runtime_value":return await ei(t,e);case"save_profile":return await ti(t,e);case"delete_profile":return await ni(t,e);case"activate_profile":return await si(t,e);case"sync_profiles_from_backend":return await ri(t);case"sync_backend_vault_path":return await ii(t);default:return{ok:!1,message:`Unknown life_assistant_settings action: ${String(e.action??"")}`,settings:Q(t)}}}function as(t){if(!t||typeof t!="object")return{action:"inspect"};let e=t;return{action:Qr(e.action),key:Z(e.key),value:Z(e.value),profile_id:Z(e.profile_id),profile:e.profile,activate:!!e.activate}}function Qr(t){let e=Z(t);switch(e){case"inspect":case"set_runtime_value":case"save_profile":case"delete_profile":case"activate_profile":case"sync_profiles_from_backend":case"sync_backend_vault_path":return e;default:return"inspect"}}async function ei(t,e){let n=Z(e.key);if(!Zr.has(n))return{ok:!1,message:"set_runtime_value only supports backendUrl, backendEnvPath, backendMcpConfigPath, or runtimeManifestUrl.",settings:Q(t)};let s=li(n,e.value);return t.settings[n]=s,await t.saveSettings(),n==="backendUrl"&&window.setTimeout(()=>t.restartClientToolBridge(),0),{ok:!0,message:`Updated plugin setting ${n}.`,changed:[n],settings:Q(t)}}async function ti(t,e){let n=oi(e.profile);if(!n)return{ok:!1,message:"save_profile requires a complete profile payload.",settings:Q(t)};let s=new V(t.settings.backendUrl),r=await Ee(t.settings,n,s,!!e.activate);return r.ok?(await t.saveSettings(),{ok:!0,message:r.message,changed:e.activate?["llmProfiles","activeProfileId"]:["llmProfiles"],settings:Q(t)}):{ok:!1,message:r.message,settings:Q(t)}}async function ni(t,e){let n=Z(e.profile_id);if(!n)return{ok:!1,message:"delete_profile requires profile_id.",settings:Q(t)};let s=new V(t.settings.backendUrl),r=await et(t.settings,n,s);return r.ok?(await t.saveSettings(),{ok:!0,message:r.message,changed:["llmProfiles","activeProfileId"],settings:Q(t)}):{ok:!1,message:r.message,settings:Q(t)}}async function si(t,e){let n=Z(e.profile_id);if(!n)return{ok:!1,message:"activate_profile requires profile_id.",settings:Q(t)};let s=new V(t.settings.backendUrl),r=await De(t.settings,n,s);return r.ok?(await t.saveSettings(),{ok:!0,message:r.message,changed:["activeProfileId","llmProfiles"],settings:Q(t)}):{ok:!1,message:r.message,settings:Q(t)}}async function ri(t){let e=new V(t.settings.backendUrl),n=await Qe(t.settings,e);return n.ok?(await t.saveSettings(),{ok:!0,message:n.message,changed:["llmProfiles","activeProfileId"],settings:Q(t)}):{ok:!1,message:n.message,settings:Q(t)}}async function ii(t){let e=await t.ensureBackendVaultPathSynced();return{ok:e.ok,message:e.message,changed:e.changed?["backend_vault_path"]:[],settings:Q(t)}}function Q(t){let e="",n=null;try{let s=Dt(t.app);e=(0,dt.join)(s.pluginDir,"data.json")}catch{e=""}try{n=t.runtimeManager?.getStatus()??null}catch{n=null}return{pluginDataPath:e,currentVaultPath:t.getCurrentVaultPath(),backendUrl:t.settings.backendUrl,backendEnvPath:t.settings.backendEnvPath,backendMcpConfigPath:t.settings.backendMcpConfigPath,runtimeManifestUrl:t.settings.runtimeManifestUrl,activeProfileId:t.settings.activeProfileId,llmProfiles:t.settings.llmProfiles.map(ai),runtimeStatus:n,backendEnvPathExists:ss(t.settings.backendEnvPath),backendMcpConfigPathExists:ss(t.settings.backendMcpConfigPath)}}function ai(t){return{id:t.id,name:t.name,provider:t.provider,model:t.model,baseUrl:t.baseUrl,supportsVision:t.supportsVision,thinkingMode:t.thinkingMode,thinkingEffort:t.thinkingEffort,thinkingBudgetTokens:t.thinkingBudgetTokens,reasoningSplit:t.reasoningSplit,hasApiKey:t.apiKey.trim().length>0,apiKeyMasked:ci(t.apiKey)}}function oi(t){if(!t||typeof t!="object")return null;let e=t,n=Z(e.id),s=Z(e.name),r=Z(e.model);return!n||!s||!r?null:{id:n,name:s,provider:Ge(e.provider),model:r,baseUrl:Z(e.baseUrl),apiKey:Z(e.apiKey),supportsVision:ns(e.supportsVision),thinkingMode:Z(e.thinkingMode),thinkingEffort:Z(e.thinkingEffort),thinkingBudgetTokens:Z(e.thinkingBudgetTokens,"1024"),reasoningSplit:ns(e.reasoningSplit)}}function Z(t,e=""){return typeof t=="string"?t.trim():e}function li(t,e){let n=Z(e);return n?t==="backendEnvPath"||t==="backendMcpConfigPath"?(0,dt.resolve)(n):n:""}function ns(t){if(typeof t=="boolean")return t;if(typeof t=="string"){let e=t.trim().toLowerCase();if(["1","true","yes","on"].includes(e))return!0;if(["0","false","no","off",""].includes(e))return!1}return typeof t=="number"?t!==0:!1}function ci(t){let e=t.trim();return e?e.length<=6?"*".repeat(e.length):`${e.slice(0,4)}...${e.slice(-2)}`:""}function ss(t){if(!t)return!1;try{return(0,rs.existsSync)(t)}catch{return!1}}var di=new Set(["file","path","content","tag","line","block","section","task","task-todo","task-done","match-case","ignore-case"]);function cs(t,e){let n=e.query.trim(),s=ls(e.max_results??20,1,100),r=ls(e.context_chars??160,0,1e3),i=e.sort??"score";if(!n)return{query:n,results:[],total_matches:0,truncated:!1};let a=ds(n),c=[];for(let x of t){let P=we(a,x,{matchCase:!1});if(!P.ok)continue;let k=P.matches[0]??{field:"content",text:x.content};c.push({path:x.path,ext:x.ext,score:Math.round(P.score*100)/100,matches:P.matches.slice(0,8),snippet:vi(x,k,r),field:k.field,line:k.line,tags:Ft(x.tags),aliases:Ft(x.aliases),mtime:x.mtime,truncated:P.matches.length>8})}Pi(c,i);let o=c.length,l=c.slice(0,s);return{query:n,results:l,total_matches:o,truncated:o>l.length}}function ds(t){let e=ui(t);return new Ut(e).parseExpression()}function ui(t){let e=[],n=0;for(;n<t.length;){let s=t[n];if(/\s/.test(s)){n+=1;continue}if(s==="("){e.push({type:"lparen",value:s}),n+=1;continue}if(s===")"){e.push({type:"rparen",value:s}),n+=1;continue}if(s==="-"){e.push({type:"not",value:s}),n+=1;continue}if(s==='"'){let c=yi(t,n);e.push({type:"phrase",value:c.value}),n=c.next;continue}if(s==="/"){let c=Si(t,n);e.push({type:"regex",value:c.value,flags:c.flags}),n=c.next;continue}if(s==="["){let c=Ei(t,n);e.push({type:"property",value:c.value}),n=c.next;continue}let r=Ti(t,n);if(r){e.push({type:"field",value:r.value}),n=r.next;continue}let i=wi(t,n),a=i.value;e.push({type:a==="OR"?"or":"term",value:a}),n=i.next}return e}var Ut=class{constructor(e){this.tokens=e;this.index=0}parseExpression(){return this.parseOr()}parseOr(){let e=[this.parseAnd()];for(;this.match("or");)e.push(this.parseAnd());return e.length===1?e[0]:{type:"or",children:e}}parseAnd(){let e=[];for(;!this.isAtEnd()&&!this.check("rparen")&&!this.check("or");)e.push(this.parseUnary());return e.length===0?{type:"empty"}:e.length===1?e[0]:{type:"and",children:e}}parseUnary(){return this.match("not")?{type:"not",child:this.parseUnary()}:this.parsePrimary()}parsePrimary(){let e=this.advance();if(!e)return{type:"empty"};if(e.type==="lparen"){let n=this.parseExpression();return this.match("rparen"),n}return e.type==="field"?{type:"field",field:e.value,child:this.parseUnary()}:e.type==="property"?{type:"property",raw:e.value}:e.type==="phrase"?{type:"term",value:e.value,exact:!0}:e.type==="regex"?{type:"regex",pattern:e.value,flags:e.flags??""}:e.type==="term"?{type:"term",value:e.value,exact:!1}:{type:"empty"}}match(e){return this.check(e)?(this.index+=1,!0):!1}check(e){return this.tokens[this.index]?.type===e}advance(){return this.tokens[this.index++]}isAtEnd(){return this.index>=this.tokens.length}};function we(t,e,n){switch(t.type){case"empty":return{ok:!0,matches:[],score:0};case"term":return gi(t.value,e,n,t.exact);case"regex":return mi(t.pattern,t.flags,e,n);case"not":return{ok:!we(t.child,e,n).ok,matches:[],score:0};case"and":{let s=[],r=0;for(let i of t.children){let a=we(i,e,n);if(!a.ok)return{ok:!1,matches:[],score:0};s.push(...a.matches),r+=a.score}return{ok:!0,matches:s,score:r}}case"or":{let s=[],r=0;for(let i of t.children){let a=we(i,e,n);a.ok&&(s.push(...a.matches),r+=a.score)}return{ok:s.length>0||r>0,matches:s,score:r}}case"field":return pi(t.field,t.child,e,n);case"property":return fi(t.raw,e,n)}}function pi(t,e,n,s){return t==="match-case"?we(e,n,{...s,matchCase:!0}):t==="ignore-case"?we(e,n,{...s,matchCase:!1}):t==="file"?Ne(e,`${n.name}
${Mi(n.name)}`,"file",n,s,1.4):t==="path"?Ne(e,n.path,"path",n,s,1.2):t==="content"?Ne(e,n.content,"content",n,s,1):t==="tag"?hi(e,n,s):t==="line"?$e(e,bi(n),"line",n,s,1.1):t==="block"?$e(e,ki(n),"block",n,s,1.1):t==="section"?$e(e,xi(n),"section",n,s,1.2):t==="task"?$e(e,Nt(n),"task",n,s,1.3):t==="task-todo"?$e(e,Nt(n).filter(r=>r.status==="todo"),"task-todo",n,s,1.4):t==="task-done"?$e(e,Nt(n).filter(r=>r.status==="done"),"task-done",n,s,1.4):we(e,n,s)}function gi(t,e,n,s){let r=Bt(e.content,t,"content",n,s);r.forEach(o=>{o.start!==void 0&&(o.line=gs(e.content,o.start))});let i=Bt(e.name,t,"file",n,s),a=Bt(e.path,t,"path",n,s),c=[...i,...a,...r];return{ok:c.length>0,matches:c,score:i.length*2+a.length*1.2+r.length}}function mi(t,e,n,s){let r=$t(n.content,t,e,"content",s);r.forEach(o=>{o.start!==void 0&&(o.line=gs(n.content,o.start))});let i=$t(n.path,t,e,"path",s),a=$t(n.name,t,e,"file",s),c=[...a,...i,...r];return{ok:c.length>0,matches:c,score:a.length*2+i.length*1.2+r.length}}function Ne(t,e,n,s,r,i,a){let c={...s,content:e,path:"",name:"",tags:[],aliases:[],properties:{},sections:[],blocks:[],tasks:[]},o=we(t,c,r);return o.ok?{ok:!0,matches:o.matches.map(l=>({...l,field:n,line:a??l.line})),score:o.score*i}:o}function $e(t,e,n,s,r,i){let a=[],c=0;for(let o of e){let l=Ne(t,o.text,n,s,r,i,o.line);l.ok&&(a.push(...l.matches),c+=l.score)}return{ok:a.length>0,matches:a,score:c}}function hi(t,e,n){let s=Ft(e.tags);if(t.type==="term"){let r=ps(t.value),i=s.filter(a=>Ci(a,r,n.matchCase)).map(a=>({field:"tag",text:a}));return{ok:i.length>0,matches:i,score:i.length*2}}return Ne(t,s.join(`
`),"tag",e,n,2)}function fi(t,e,n){let s=_i(t),r=e.properties??{},i=s.key,a=Li(r,i);if(!(a!==void 0))return{ok:!1,matches:[],score:0};if(s.value===null)return{ok:!0,matches:[{field:"property",text:i}],score:2};let o=us(a);if(s.value.trim().toLowerCase()==="null"){let k=o.trim()==="";return{ok:k,matches:k?[{field:"property",text:`${i}: null`}]:[],score:k?2:0}}let l=Ai(a,s.value);if(l!==null)return{ok:l,matches:l?[{field:"property",text:`${i}: ${o}`}]:[],score:l?2:0};let x=ds(s.value),P=Ne(x,o,"property",e,n,2);return P.ok?{ok:!0,matches:P.matches.map(k=>({...k,text:`${i}: ${k.text}`})),score:P.score}:P}function Bt(t,e,n,s,r){let i=r?e:e.trim();if(!i)return[];let a=s.matchCase?t:t.toLowerCase(),c=s.matchCase?i:i.toLowerCase(),o=[],l=a.indexOf(c);for(;l!==-1&&o.length<20;){let x=l+c.length;o.push({field:n,text:t.slice(l,x),start:l,end:x}),l=a.indexOf(c,Math.max(x,l+1))}return o}function $t(t,e,n,s,r){try{let i=new Set(n.split(""));i.add("g"),r.matchCase||i.add("i");let a=new RegExp(e,Array.from(i).join("")),c=[],o;for(;(o=a.exec(t))&&c.length<20;){let l=o[0];c.push({field:s,text:l,start:o.index,end:o.index+l.length}),l.length===0&&(a.lastIndex+=1)}return c}catch{return[]}}function vi(t,e,n){if(n===0)return"";if(e.line!==void 0){let s=t.content.split(/\r?\n/)[e.line-1];if(s)return Ot(s,n)}if(e.start!==void 0&&e.end!==void 0&&e.field==="content"){let s=Math.max(0,e.start-n),r=Math.min(t.content.length,e.end+n);return Ot(t.content.slice(s,r).replace(/\s+/g," "),n*2)}return Ot(e.text||t.path,n*2)}function bi(t){return t.content.split(/\r?\n/).map((e,n)=>({text:e,line:n+1}))}function ki(t){return t.blocks?.length?t.blocks:t.content.split(/\n\s*\n/g).map(e=>e.trim()).filter(Boolean).map(e=>({text:e}))}function xi(t){return t.sections?.length?t.sections:[{text:t.content,line:1}]}function Nt(t){if(t.tasks?.length)return t.tasks;let e=[];return t.content.split(/\r?\n/).forEach((n,s)=>{let r=/^\s*[-*]\s+\[([^\]])\]\s+(.*)$/.exec(n);r&&e.push({text:n,line:s+1,status:r[1]===" "?"todo":"done"})}),e}function Pi(t,e){t.sort((n,s)=>e==="mtime_desc"?s.mtime-n.mtime||n.path.localeCompare(s.path):e==="mtime_asc"?n.mtime-s.mtime||n.path.localeCompare(s.path):e==="path"?n.path.localeCompare(s.path):s.score-n.score||s.mtime-n.mtime||n.path.localeCompare(s.path))}function yi(t,e){let n="",s=e+1;for(;s<t.length;){let r=t[s];if(r==="\\"&&s+1<t.length){n+=t[s+1],s+=2;continue}if(r==='"')return{value:n,next:s+1};n+=r,s+=1}return{value:n,next:s}}function Si(t,e){let n="",s=e+1;for(;s<t.length;){let r=t[s];if(r==="\\"&&s+1<t.length){n+=r+t[s+1],s+=2;continue}if(r==="/"){s+=1;let i="";for(;s<t.length&&/[a-z]/i.test(t[s]);)i+=t[s],s+=1;return{value:n,flags:i,next:s}}n+=r,s+=1}return{value:n,flags:"",next:s}}function Ei(t,e){let n="",s=e+1;for(;s<t.length&&t[s]!=="]";)n+=t[s],s+=1;return{value:n,next:Math.min(s+1,t.length)}}function wi(t,e){let n=e;for(;n<t.length&&!/\s/.test(t[n])&&!/[()]/.test(t[n]);)n+=1;return{value:t.slice(e,n),next:n}}function Ti(t,e){let n=/^[A-Za-z-]+:/.exec(t.slice(e));if(!n)return null;let s=n[0].slice(0,-1);return di.has(s)?{value:s,next:e+n[0].length}:null}function _i(t){let e=t.indexOf(":");return e===-1?{key:t.trim(),value:null}:{key:t.slice(0,e).trim(),value:t.slice(e+1).trim()}}function Li(t,e){if(Object.prototype.hasOwnProperty.call(t,e))return t[e];let n=e.toLowerCase(),s=Object.keys(t).find(r=>r.toLowerCase()===n);return s?t[s]:void 0}function us(t){return t==null?"":Array.isArray(t)?t.map(us).join(`
`):typeof t=="object"?JSON.stringify(t):String(t)}function Ai(t,e){let n=/^(<=|>=|<|>)(.+)$/.exec(e.trim());if(!n)return null;let s=os(t),r=os(n[2].trim());if(s===null||r===null)return!1;switch(n[1]){case"<":return s<r;case">":return s>r;case"<=":return s<=r;case">=":return s>=r;default:return!1}}function os(t){if(typeof t=="number")return t;if(t instanceof Date)return t.getTime();if(typeof t=="string"){let e=Number(t);if(!Number.isNaN(e)&&t.trim()!=="")return e;let n=Date.parse(t);return Number.isNaN(n)?t:n}return typeof t=="boolean"?t?1:0:null}function Ft(t){return Array.isArray(t)?t.map(e=>String(e).trim()).filter(Boolean):[]}function ps(t){return t.trim().replace(/^#/,"")}function Ci(t,e,n){let s=ps(t),r=n?s:s.toLowerCase(),i=n?e:e.toLowerCase();return r===i||r.startsWith(`${i}/`)}function Mi(t){return t.replace(/\.[^.]+$/,"")}function gs(t,e){return t.slice(0,e).split(/\r?\n/).length}function Ot(t,e){let n=t.replace(/\s+/g," ").trim();return n.length<=e?n:`${n.slice(0,Math.max(0,e-1)).trim()}...`}function ls(t,e,n){return Number.isFinite(t)?Math.max(e,Math.min(n,Math.trunc(t))):e}var Ii=new Set([".obsidian",".LifeAssistantAgent",".git","node_modules",".venv"]);async function ms(t,e){let n=await Ri(t);return cs(n,e)}async function Ri(t){let e=t.vault.getMarkdownFiles(),n=t.vault.getFiles().filter(i=>ut(i)==="canvas"),s=[...e,...n].filter(i=>!zi(i.path)),r=[];for(let i of s)try{let a=await t.vault.cachedRead(i);ut(i)==="canvas"?r.push(Bi(i,a)):r.push(Di(i,a,t.metadataCache.getFileCache(i)))}catch(a){console.warn("[Life Assistant] Failed to read searchable file",i.path,a)}return r}function Di(t,e,n){let s={...n?.frontmatter??{}},r=Hi(s.aliases),i=Fi(n,s);return r.length>0&&(s.aliases=r),i.length>0&&(s.tags=i),{path:t.path,name:t.name,ext:ut(t),content:e,mtime:t.stat.mtime,ctime:t.stat.ctime,tags:i,aliases:r,properties:s,sections:Ni(e,n),blocks:Oi(e,n),tasks:Ui(e,n)}}function Bi(t,e){let n=$i(e);return{path:t.path,name:t.name,ext:ut(t),content:n.content,mtime:t.stat.mtime,ctime:t.stat.ctime,tags:[],aliases:[],properties:{type:"canvas"},sections:n.blocks,blocks:n.blocks,tasks:[]}}function $i(t){try{let n=(JSON.parse(t).nodes??[]).map(s=>{let r=String(s.type??"");return r==="text"?String(s.text??"").trim():r==="file"?String(s.file??"").trim():r==="link"?String(s.url??"").trim():r==="group"?String(s.label??"").trim():""}).filter(Boolean).map(s=>({text:s}));return{content:n.map(s=>s.text).join(`

`),blocks:n}}catch{return{content:t,blocks:t.split(/\n\s*\n/g).map(e=>e.trim()).filter(Boolean).map(e=>({text:e}))}}}function Ni(t,e){let n=e?.headings??[];if(!n.length)return[{text:t,line:1}];let s=t.split(/\r?\n/);return n.map((r,i)=>{let a=r.position.start.line,c=n[i+1],o=c?c.position.start.line:s.length;return{text:s.slice(a,o).join(`
`),line:a+1}})}function Oi(t,e){let n=e?.sections??[],s=t.split(/\r?\n/);return n.length?n.filter(r=>r.type!=="yaml").map(r=>{let i=r.position.start.line,a=r.position.end.line+1;return{text:s.slice(i,a).join(`
`),line:i+1}}).filter(r=>r.text.trim().length>0):t.split(/\n\s*\n/g).map(r=>r.trim()).filter(Boolean).map(r=>({text:r}))}function Ui(t,e){let n=e?.listItems??[],s=t.split(/\r?\n/);return n.filter(r=>r.task!==void 0).map(r=>{let i=r.position.start.line;return{text:s[i]??"",line:i+1,status:r.task===" "?"todo":"done"}})}function Fi(t,e){let n=new Set;for(let s of t?.tags??[])s.tag&&n.add(s.tag);for(let s of Ki(e.tags))n.add(s.startsWith("#")?s:`#${s}`);return Array.from(n).sort()}function Hi(t){return Array.isArray(t)?t.map(e=>String(e).trim()).filter(Boolean):typeof t=="string"&&t.trim()?[t.trim()]:[]}function Ki(t){return Array.isArray(t)?t.map(e=>String(e).trim()).filter(Boolean):typeof t=="string"&&t.trim()?t.split(/[,\s]+/).map(e=>e.trim()).filter(Boolean):[]}function ut(t){return t.extension||t.path.split(".").pop()?.toLowerCase()||""}function zi(t){return t.split("/").some(e=>Ii.has(e))}var pt=class{constructor(e,n){this.plugin=e;this.getBackendUrl=n;this.ws=null;this.reconnectTimer=null;this.stopped=!0}start(){this.stopped=!1,this.connect()}stop(){this.stopped=!0,this.reconnectTimer!==null&&(window.clearTimeout(this.reconnectTimer),this.reconnectTimer=null),this.ws&&(this.ws.close(),this.ws=null)}connect(){if(this.stopped||this.ws)return;let e=this.getBackendUrl().trim();if(!e){this.scheduleReconnect();return}let n=e.replace(/^http/i,"ws").replace(/\/$/,""),s=new WebSocket(`${n}/client-tools/obsidian`);this.ws=s,s.onmessage=r=>{this.handleMessage(r.data)},s.onclose=()=>{this.ws===s&&(this.ws=null),this.scheduleReconnect()},s.onerror=()=>{s.close()}}scheduleReconnect(){this.stopped||this.reconnectTimer!==null||(this.reconnectTimer=window.setTimeout(()=>{this.reconnectTimer=null,this.connect()},3e3))}async handleMessage(e){let n;try{n=JSON.parse(e)}catch{return}if(!(n.type!=="client_tool_request"||!n.request_id))try{let s;if(n.tool==="obsidian_search")s=await ms(this.plugin.app,Vi(n.input));else if(n.tool==="life_assistant_settings")s=await is(this.plugin,as(n.input));else throw new Error(`Unknown client tool: ${n.tool}`);this.send({type:"client_tool_result",request_id:n.request_id,result:s})}catch(s){let r=s instanceof Error?s.message:String(s);this.send({type:"client_tool_error",request_id:n.request_id,error:r})}}send(e){!this.ws||this.ws.readyState!==WebSocket.OPEN||this.ws.send(JSON.stringify(e))}};function Vi(t){if(!t||typeof t!="object")return{query:""};let e=t;return{query:String(e.query??""),max_results:typeof e.max_results=="number"?e.max_results:void 0,context_chars:typeof e.context_chars=="number"?e.context_chars:void 0,sort:e.sort==="mtime_desc"||e.sort==="mtime_asc"||e.sort==="path"?e.sort:"score"}}var Ht=require("node:path");function Kt(t){return typeof t=="object"&&t!==null}function ee(t,e=""){return typeof t=="string"?t.trim():e}function ji(t){return Ge(t)}function hs(t){if(typeof t=="boolean")return t;if(typeof t=="string"){let e=t.trim().toLowerCase();if(["1","true","yes","on"].includes(e))return!0;if(["0","false","no","off",""].includes(e))return!1}return typeof t=="number"?t!==0:!1}function qi(t){if(!Kt(t))return null;let e=ee(t.id),n=ee(t.name),s=ee(t.model);return!e||!n||!s?null:{id:e,name:n,provider:ji(t.provider),model:s,baseUrl:ee(t.baseUrl),apiKey:ee(t.apiKey),supportsVision:hs(t.supportsVision),thinkingMode:ee(t.thinkingMode),thinkingEffort:ee(t.thinkingEffort),thinkingBudgetTokens:ee(t.thinkingBudgetTokens,"1024"),reasoningSplit:hs(t.reasoningSplit)}}function Wi(t,e){let n=ee(t.backendEnvPath,e.backendEnvPath);if(n)return(0,Ht.resolve)(n);let s=ee(t.backendPath);return s?(0,Ht.resolve)(s,".env"):""}function fs(t){return Kt(t)?!ee(t.backendEnvPath)&&!!ee(t.backendPath):!1}function zt(t,e){let n=Kt(e)?e:{},s=Wi(n,t);return{...t,backendUrl:ee(n.backendUrl,t.backendUrl),backendEnvPath:s,backendMcpConfigPath:ee(n.backendMcpConfigPath,t.backendMcpConfigPath),runtimeManifestUrl:ee(n.runtimeManifestUrl,t.runtimeManifestUrl),backendPath:"",llmProfiles:Array.isArray(n.llmProfiles)?n.llmProfiles.map(r=>qi(r)).filter(r=>r!==null):t.llmProfiles.map(r=>({...r})),activeProfileId:ee(n.activeProfileId,t.activeProfileId)}}var B=require("obsidian");var re=require("node:fs"),oe=require("node:path");var vs="LIFE_ASSISTANT_ADMIN_ENABLED",bs="LIFE_ASSISTANT_ADMIN_TOKEN";function He(t){let e=Se(t),n=t.backendMcpConfigPath?.trim();if(n){let r=(0,oe.resolve)(n),i=e.ok&&e.envPath?(0,oe.join)((0,oe.dirname)(e.envPath),"server","data","mcp_servers.example.json"):(0,oe.join)((0,oe.dirname)(r),"mcp_servers.example.json");return{ok:!0,configPath:r,examplePath:i,derivedFromBackendEnvPath:!1,message:""}}if(!e.ok||!e.envPath)return{ok:!1,derivedFromBackendEnvPath:!1,message:"\u8BF7\u5148\u914D\u7F6E\u201C\u540E\u7AEF .env \u8DEF\u5F84\u201D\uFF0C\u518D\u7F16\u8F91 MCP \u914D\u7F6E\u6587\u4EF6\u3002"};let s=(0,oe.dirname)(e.envPath);return{ok:!0,configPath:(0,oe.join)(s,"server","data","mcp_servers.json"),examplePath:(0,oe.join)(s,"server","data","mcp_servers.example.json"),derivedFromBackendEnvPath:!0,message:"\u5F53\u524D\u8DEF\u5F84\u7531\u201C\u540E\u7AEF .env \u8DEF\u5F84\u201D\u81EA\u52A8\u63A8\u5BFC\u3002"}}function Vt(t){let e;try{e=JSON.parse(t)}catch(r){return{ok:!1,message:`JSON \u683C\u5F0F\u65E0\u6548\uFF1A${r instanceof Error?r.message:String(r)}`,serverNames:[]}}if(!gt(e))return{ok:!1,message:"MCP \u914D\u7F6E\u5FC5\u987B\u662F\u4E00\u4E2A JSON \u5BF9\u8C61\u3002",serverNames:[]};let n=e.mcpServers;if(!gt(n))return{ok:!1,message:"`mcpServers` \u5FC5\u987B\u662F\u4E00\u4E2A\u5BF9\u8C61\u3002",serverNames:[]};let s=Object.keys(n);for(let r of s){let i=n[r];if(!gt(i))return{ok:!1,message:`MCP \u670D\u52A1\u201C${r}\u201D\u5FC5\u987B\u662F\u4E00\u4E2A\u5BF9\u8C61\u3002`,serverNames:[]};let a=typeof i.transport=="string"&&i.transport.trim()?i.transport.trim():"stdio";if(a!=="stdio"&&a!=="sse")return{ok:!1,message:`MCP \u670D\u52A1\u201C${r}\u201D\u4F7F\u7528\u4E86\u4E0D\u652F\u6301\u7684 transport\uFF1A\u201C${a}\u201D\u3002`,serverNames:[]};if(a==="stdio"&&(typeof i.command!="string"||!i.command.trim()))return{ok:!1,message:`MCP \u670D\u52A1\u201C${r}\u201D\u9700\u8981\u586B\u5199\u975E\u7A7A\u7684 "command"\u3002`,serverNames:[]};if(a==="sse"&&(typeof i.url!="string"||!i.url.trim()))return{ok:!1,message:`MCP \u670D\u52A1\u201C${r}\u201D\u9700\u8981\u586B\u5199\u975E\u7A7A\u7684 "url"\u3002`,serverNames:[]};if(i.args!==void 0&&(!Array.isArray(i.args)||i.args.some(c=>typeof c!="string")))return{ok:!1,message:`MCP \u670D\u52A1\u201C${r}\u201D\u7684 "args" \u6570\u7EC4\u683C\u5F0F\u4E0D\u6B63\u786E\u3002`,serverNames:[]};if(i.env!==void 0&&!gt(i.env))return{ok:!1,message:`MCP \u670D\u52A1\u201C${r}\u201D\u7684 "env" \u5BF9\u8C61\u683C\u5F0F\u4E0D\u6B63\u786E\u3002`,serverNames:[]}}return{ok:!0,message:s.length>0?`\u914D\u7F6E\u6709\u6548\uFF0C\u5F53\u524D\u5171\u5B9A\u4E49 ${s.length} \u4E2A MCP \u670D\u52A1\uFF1A${s.join("\u3001")}\u3002`:"\u914D\u7F6E\u6709\u6548\uFF0C\u4F46\u5F53\u524D\u8FD8\u6CA1\u6709\u5B9A\u4E49\u4EFB\u4F55 MCP \u670D\u52A1\u3002",serverNames:s}}function ks(t){let e=He(t);if(!e.ok||!e.configPath)return{ok:!1,message:e.message,exists:!1};if(!(0,re.existsSync)(e.configPath))return{ok:!0,configPath:e.configPath,examplePath:e.examplePath,text:"",exists:!1,message:`MCP \u914D\u7F6E\u6587\u4EF6\u5C1A\u4E0D\u5B58\u5728\uFF1A${e.configPath}`};try{return{ok:!0,configPath:e.configPath,examplePath:e.examplePath,text:(0,re.readFileSync)(e.configPath,"utf8"),exists:!0,message:`\u5DF2\u4ECE ${e.configPath} \u8F7D\u5165 MCP \u914D\u7F6E\u3002`}}catch(n){let s=n instanceof Error?n.message:String(n);return{ok:!1,configPath:e.configPath,examplePath:e.examplePath,exists:!0,message:`\u8BFB\u53D6 MCP \u914D\u7F6E\u5931\u8D25\uFF1A${s}`}}}function xs(t){let e=He(t);if(!e.ok||!e.configPath||!e.examplePath)return{ok:!1,message:e.message};if(!(0,re.existsSync)(e.examplePath))return{ok:!1,configPath:e.configPath,examplePath:e.examplePath,message:`\u7F3A\u5C11 MCP \u793A\u4F8B\u914D\u7F6E\u6587\u4EF6\uFF1A${e.examplePath}`};if((0,re.existsSync)(e.configPath))return{ok:!1,configPath:e.configPath,examplePath:e.examplePath,message:`MCP \u914D\u7F6E\u6587\u4EF6\u5DF2\u5B58\u5728\uFF1A${e.configPath}`};try{return(0,re.mkdirSync)((0,oe.dirname)(e.configPath),{recursive:!0}),(0,re.copyFileSync)(e.examplePath,e.configPath),{ok:!0,configPath:e.configPath,examplePath:e.examplePath,text:(0,re.readFileSync)(e.configPath,"utf8"),exists:!0,message:`\u5DF2\u6839\u636E\u793A\u4F8B\u6587\u4EF6\u521B\u5EFA MCP \u914D\u7F6E\uFF1A${e.configPath}`}}catch(n){let s=n instanceof Error?n.message:String(n);return{ok:!1,configPath:e.configPath,examplePath:e.examplePath,message:`\u521B\u5EFA MCP \u914D\u7F6E\u5931\u8D25\uFF1A${s}`}}}function jt(t,e){let n=He(t);if(!n.ok||!n.configPath)return{ok:!1,message:n.message};let s=Vt(e);if(!s.ok)return{ok:!1,configPath:n.configPath,examplePath:n.examplePath,text:e,message:s.message};try{return(0,re.mkdirSync)((0,oe.dirname)(n.configPath),{recursive:!0}),(0,re.writeFileSync)(n.configPath,e,"utf8"),{ok:!0,configPath:n.configPath,examplePath:n.examplePath,text:e,exists:!0,message:`\u5DF2\u5C06 MCP \u914D\u7F6E\u4FDD\u5B58\u5230 ${n.configPath}\u3002`}}catch(r){let i=r instanceof Error?r.message:String(r);return{ok:!1,configPath:n.configPath,examplePath:n.examplePath,text:e,message:`\u4FDD\u5B58 MCP \u914D\u7F6E\u5931\u8D25\uFF1A${i}`}}}async function Ps(t,e){let n=Es(t);if(!n.ok||!n.token)return{ok:!1,message:n.message};let s=await e.reloadConfig(n.token);return Gi(s)}async function ys(t,e){let n=Es(t);if(!n.ok||!n.token)return{ok:!1,httpStatus:null,message:n.message};let s=await e.getMcpStatus(n.token);return!s.ok||!s.data?{ok:!1,httpStatus:s.status,message:ws(s,"\u83B7\u53D6 MCP \u8FD0\u884C\u72B6\u6001")}:{ok:!0,status:s.data,httpStatus:s.status,message:s.data.connected_servers.length>0?`\u5F53\u524D\u5DF2\u8FDE\u63A5\u7684 MCP \u670D\u52A1\uFF1A${s.data.connected_servers.join("\u3001")}`:"\u5F53\u524D\u6CA1\u6709\u5DF2\u8FDE\u63A5\u7684 MCP \u670D\u52A1\u3002"}}function Ss(t){let e=[`\u914D\u7F6E\u6587\u4EF6\uFF1A${t.config_path}`,`\u793A\u4F8B\u6587\u4EF6\uFF1A${t.example_config_path}`,`\u914D\u7F6E\u662F\u5426\u5B58\u5728\uFF1A${t.config_exists?"\u662F":"\u5426"}`,`\u5DF2\u8FDE\u63A5\u670D\u52A1\uFF1A${t.connected_servers.length>0?t.connected_servers.join("\u3001"):"\u65E0"}`],n=Object.entries(t.tools_by_server);if(n.length===0)e.push("\u670D\u52A1\u5DE5\u5177\u8BE6\u60C5\uFF1A\u65E0");else{e.push("\u670D\u52A1\u5DE5\u5177\u8BE6\u60C5\uFF1A");for(let[s,r]of n)e.push(`- ${s}\uFF1A${r.join("\u3001")}`)}return e.push(`\u6700\u8FD1\u4E00\u6B21\u91CD\u8F7D\uFF1A${t.last_reload_ok===void 0||t.last_reload_ok===null?"\u5C1A\u672A\u6267\u884C":t.last_reload_ok?"\u6210\u529F":"\u5931\u8D25"}`),t.last_reload_at&&e.push(`\u91CD\u8F7D\u65F6\u95F4\uFF1A${t.last_reload_at}`),t.last_reload_error&&e.push(`\u9519\u8BEF\u4FE1\u606F\uFF1A${t.last_reload_error}`),e.join(`
`)}function Es(t){let e=Se(t);if(!e.ok||!e.envPath)return{ok:!1,message:"\u8BF7\u5148\u914D\u7F6E\u201C\u540E\u7AEF .env \u8DEF\u5F84\u201D\uFF0C\u518D\u67E5\u770B MCP \u8FD0\u884C\u72B6\u6001\u6216\u6267\u884C\u91CD\u8F7D\u3002"};let n=ue(e.envPath,vs);if(!Ue(n))return{ok:!1,envPath:e.envPath,message:`${e.envPath} \u4E2D\u672A\u5F00\u542F\u540E\u7AEF\u70ED\u91CD\u8F7D\u3002\u8BF7\u8BBE\u7F6E ${vs}=true \u540E\u518D\u67E5\u770B MCP \u72B6\u6001\u6216\u6267\u884C\u91CD\u8F7D\u3002`};let s=ue(e.envPath,bs)?.trim();return s?{ok:!0,token:s,envPath:e.envPath,message:""}:{ok:!1,envPath:e.envPath,message:`${e.envPath} \u4E2D\u7F3A\u5C11 ${bs}\u3002\u56E0\u6B64\u65E0\u6CD5\u67E5\u8BE2 MCP \u72B6\u6001\u6216\u6267\u884C\u540E\u7AEF\u91CD\u8F7D\u3002`}}function Gi(t){return t.ok?{ok:!0,reloadStatus:t.status,message:"\u5DF2\u4FDD\u5B58 MCP \u914D\u7F6E\uFF0C\u5E76\u5B8C\u6210\u540E\u7AEF\u70ED\u91CD\u8F7D\u3002"}:{ok:!1,reloadStatus:t.status,message:ws(t,"\u540E\u7AEF\u91CD\u8F7D")}}function ws(t,e){return t.status===null?`${e}\u5931\u8D25\uFF1A\u5F53\u524D\u540E\u7AEF\u4E0D\u53EF\u8BBF\u95EE\u3002`:t.detail?`${e}\u5931\u8D25\uFF08HTTP ${t.status}\uFF09\uFF1A${t.detail}`:`${e}\u5931\u8D25\uFF08HTTP ${t.status}\uFF09\u3002`}function gt(t){return!!t&&typeof t=="object"&&!Array.isArray(t)}function qt(t){let e=Pt(t.provider,t.model);e&&(typeof e.supportsVision=="boolean"&&(t.supportsVision=e.supportsVision),e.supportsThinking===!1&&(t.thinkingMode=""))}function Yi(t){let e=ae(t.provider),n=Pt(t.provider,t.model),s={...e.capabilities};return n&&typeof n.supportsVision=="boolean"&&(s.vision=s.vision&&n.supportsVision),n&&typeof n.supportsThinking=="boolean"&&(s.thinking=s.thinking&&n.supportsThinking),{activePreset:e,capabilities:s,modelPreset:n}}var Ke={backendUrl:"http://127.0.0.1:8000",backendEnvPath:"",backendMcpConfigPath:"",runtimeManifestUrl:"",backendPath:"",llmProfiles:[],activeProfileId:""};function Wt(t,e,n=!1){let s=t.createEl("details");s.open=n,s.style.marginBottom="10px";let r=s.createEl("summary",{text:e});r.style.cursor="pointer",r.style.fontWeight="600",r.style.marginBottom="8px";let i=s.createDiv();return i.style.marginTop="10px",i}function Ji(t){return t.last_reload_ok===void 0||t.last_reload_ok===null?"\u5C1A\u672A\u6267\u884C":t.last_reload_ok?"\u6210\u529F":"\u5931\u8D25"}function Xi(t){let e=Object.values(t.tools_by_server).reduce((r,i)=>r+i.length,0),n=t.connected_servers.length>0?t.connected_servers.join("\u3001"):"\u65E0",s=[`\u8FDE\u63A5\u72B6\u6001\uFF1A${t.connected_servers.length>0?`\u5DF2\u8FDE\u63A5 ${t.connected_servers.length} \u4E2A\u670D\u52A1`:"\u5F53\u524D\u6CA1\u6709\u5DF2\u8FDE\u63A5\u670D\u52A1"}`,`\u670D\u52A1\u5217\u8868\uFF1A${n}`,`\u5DE5\u5177\u603B\u6570\uFF1A${e}`,`\u6700\u8FD1\u91CD\u8F7D\uFF1A${Ji(t)}${t.last_reload_at?` \xB7 ${t.last_reload_at}`:""}`];return t.last_reload_error&&s.push(`\u9519\u8BEF\u4FE1\u606F\uFF1A${t.last_reload_error}`),s.join(`
`)}var mt=class extends B.PluginSettingTab{constructor(n,s){super(n,s);this.plugin=s}display(){let{containerEl:n}=this;n.empty(),n.createEl("h2",{text:"Life Assistant \u8BBE\u7F6E"}),this.renderRuntimeSection(n),this.renderMcpSection(n),this.renderLlmSection(n)}renderRuntimeSection(n){n.createEl("h3",{text:"\u540E\u7AEF\u8FD0\u884C\u65F6"});let s=this.plugin.runtimeManager;if(!s){n.createDiv().setText("\u540E\u7AEF\u8FD0\u884C\u65F6\u7BA1\u7406\u5668\u4E0D\u53EF\u7528\u3002");return}let r=this.plugin.settings.runtimeManifestUrl,i=n.createEl("pre");Object.assign(i.style,{backgroundColor:"var(--background-secondary)",border:"1px solid var(--background-modifier-border)",borderRadius:"6px",padding:"10px 12px",whiteSpace:"pre-wrap",fontSize:"12px",lineHeight:"1.5"});let a=0,c=async()=>{let o=++a,l=s.getStatus(),x=k=>{i.setText([`\u6A21\u5F0F\uFF1A${l.mode==="dev"?"\u5F00\u53D1\u6A21\u5F0F":"\u751F\u4EA7\u6A21\u5F0F"}`,`\u8FD0\u884C\u65F6\u5DF2\u5B89\u88C5\uFF1A${l.installed?"\u662F":"\u5426"}`,`\u540E\u7AEF\u8FDB\u7A0B\uFF1A${l.running?"\u8FD0\u884C\u4E2D":"\u672A\u8FD0\u884C"}`,`\u8FDE\u63A5\u72B6\u6001\uFF1A${k}`,`\u540E\u7AEF\u5730\u5740\uFF1A${l.backendUrl}`,`PID: ${l.pid??"-"}`,`Prompt config: ${l.promptsDir}`,`Persona config: ${l.personasDir}`,`.env \u6587\u4EF6\uFF1A${l.envPath}`,`MCP \u914D\u7F6E\uFF1A${l.mcpConfigPath}`,`\u6570\u636E\u76EE\u5F55\uFF1A${l.dataDir}`,`\u65E5\u5FD7\u76EE\u5F55\uFF1A${l.logsDir}`,`\u72B6\u6001\uFF1A${l.detail}`].join(`
`))};x("\u6B63\u5728\u68C0\u67E5...");let P=new V(l.backendUrl);try{let k=await P.health();o===a&&x(k?"\u53EF\u8BBF\u95EE\uFF08/health \u6B63\u5E38\uFF09":"\u4E0D\u53EF\u8BBF\u95EE")}catch(k){if(o===a){let A=k instanceof Error?k.message:String(k);x(`\u4E0D\u53EF\u8BBF\u95EE\uFF1A${A}`)}}};new B.Setting(n).setName("\u8FD0\u884C\u65F6\u6E05\u5355 URL").setDesc("\u751F\u4EA7\u6A21\u5F0F\u7528\u4E8E\u4E0B\u8F7D\u540E\u7AEF\u8FD0\u884C\u65F6\u3002\u5F00\u53D1\u6A21\u5F0F\u4F1A\u4F18\u5148\u4F7F\u7528 .dev-runtime.json\u3002").addText(o=>{o.setPlaceholder("https://example.com/life-assistant/runtime-manifest.json").setValue(r).onChange(l=>{r=l.trim()}),o.inputEl.style.width="420px"}).addButton(o=>{o.setButtonText("\u4FDD\u5B58"),o.onClick(async()=>{this.plugin.settings.runtimeManifestUrl=r,await this.plugin.saveSettings(),new B.Notice("\u8FD0\u884C\u65F6\u6E05\u5355 URL \u5DF2\u4FDD\u5B58\u3002")})}),new B.Setting(n).setName("\u5B89\u88C5\u540E\u7AEF\u8FD0\u884C\u65F6").setDesc("\u4E0B\u8F7D\u5E76\u6821\u9A8C\u5F53\u524D\u5E73\u53F0\u5BF9\u5E94\u7684\u540E\u7AEF\u8FD0\u884C\u65F6\u3002").addButton(o=>{o.setButtonText("\u5B89\u88C5"),o.onClick(async()=>{o.setDisabled(!0);try{this.plugin.settings.runtimeManifestUrl=r,await this.plugin.saveSettings(),await s.installRuntime(r),new B.Notice("\u540E\u7AEF\u8FD0\u884C\u65F6\u5DF2\u5B89\u88C5\u3002")}catch(l){let x=l instanceof Error?l.message:String(l);new B.Notice(`\u8FD0\u884C\u65F6\u5B89\u88C5\u5931\u8D25\uFF1A${x}`)}finally{o.setDisabled(!1),await c()}})}),new B.Setting(n).setName("\u540E\u7AEF\u8FDB\u7A0B").setDesc("\u63A7\u5236\u7531\u5F53\u524D\u63D2\u4EF6\u7BA1\u7406\u7684\u672C\u5730\u540E\u7AEF\u8FDB\u7A0B\u3002").addButton(o=>{o.setButtonText("\u542F\u52A8"),o.onClick(async()=>{o.setDisabled(!0);try{await s.start(),await this.plugin.saveSettings()}catch(l){let x=l instanceof Error?l.message:String(l);new B.Notice(`\u540E\u7AEF\u542F\u52A8\u5931\u8D25\uFF1A${x}`)}finally{o.setDisabled(!1),await c()}})}).addButton(o=>{o.setButtonText("\u91CD\u542F"),o.onClick(async()=>{o.setDisabled(!0);try{await s.restart(),await this.plugin.saveSettings()}catch(l){let x=l instanceof Error?l.message:String(l);new B.Notice(`\u540E\u7AEF\u91CD\u542F\u5931\u8D25\uFF1A${x}`)}finally{o.setDisabled(!1),await c()}})}).addButton(o=>{o.setButtonText("\u505C\u6B62"),o.onClick(async()=>{o.setDisabled(!0);try{await s.stop()}catch(l){let x=l instanceof Error?l.message:String(l);new B.Notice(`\u540E\u7AEF\u505C\u6B62\u5931\u8D25\uFF1A${x}`)}finally{o.setDisabled(!1),await c()}})}).addButton(o=>{o.setButtonText("\u5237\u65B0"),o.onClick(()=>{c()})}),c()}renderMcpSection(n){n.createEl("h3",{text:"MCP \u670D\u52A1"});let s=this.plugin.settings.backendMcpConfigPath,r=()=>this.plugin.settings.backendUrl||Ke.backendUrl,i=()=>({...this.plugin.settings,backendMcpConfigPath:s}),a=n.createDiv({cls:"mcp-config-hint"});Object.assign(a.style,{fontSize:"12px",color:"var(--text-muted)",marginBottom:"10px",lineHeight:"1.5",whiteSpace:"pre-wrap",wordBreak:"break-word"});let c=n.createDiv({cls:"mcp-runtime-summary"});Object.assign(c.style,{backgroundColor:"var(--background-secondary)",border:"1px solid var(--background-modifier-border)",borderRadius:"8px",padding:"12px 14px",marginBottom:"10px",fontSize:"12px",lineHeight:"1.6",whiteSpace:"pre-wrap",color:"var(--text-normal)"}),c.setText("\u6B63\u5728\u8BFB\u53D6 MCP \u8FD0\u884C\u72B6\u6001...");let o=n.createDiv({cls:"mcp-status-bar"});o.style.fontSize="12px",o.style.color="var(--text-muted)",o.style.marginBottom="10px",o.style.minHeight="18px";let x=Wt(n,"\u67E5\u770B\u670D\u52A1\u4E0E\u5DE5\u5177\u8BE6\u60C5").createEl("pre",{cls:"mcp-runtime-status"});Object.assign(x.style,{backgroundColor:"var(--background-secondary)",border:"1px solid var(--background-modifier-border)",borderRadius:"6px",padding:"10px 12px",marginBottom:"0",fontSize:"12px",fontFamily:"var(--font-monospace)",whiteSpace:"pre-wrap",wordBreak:"break-word",lineHeight:"1.5",color:"var(--text-normal)"}),x.setText("\u6B63\u5728\u8BFB\u53D6 MCP \u8FD0\u884C\u72B6\u6001...");let P=()=>{let g=He(i());if(!g.ok||!g.configPath){a.setText(g.message);return}let y=g.derivedFromBackendEnvPath?"\u81EA\u52A8\u4ECE\u63D2\u4EF6\u914D\u7F6E\u76EE\u5F55\u63A8\u5BFC":"\u624B\u52A8\u8986\u76D6\u8DEF\u5F84",R=g.examplePath?`
\u6A21\u677F\u6587\u4EF6\uFF1A${g.examplePath}`:"";a.setText(`\u5F53\u524D MCP \u914D\u7F6E\u6587\u4EF6\uFF1A${g.configPath}
\u8DEF\u5F84\u6765\u6E90\uFF1A${y}${R}`)},k=async()=>{this.plugin.settings.backendMcpConfigPath=s,await this.plugin.saveSettings()},A=async()=>{let g="\u6B63\u5728\u8BFB\u53D6 MCP \u8FD0\u884C\u72B6\u6001...";c.setText(g),x.setText(g);try{let y=new V(r()),R=await ys(i(),y);R.ok&&R.status?(c.setText(Xi(R.status)),x.setText(Ss(R.status))):(c.setText(R.message),x.setText(R.message))}catch(y){let O=`\u8BFB\u53D6 MCP \u8FD0\u884C\u72B6\u6001\u5931\u8D25\uFF1A${y instanceof Error?y.message:String(y)}`;c.setText(O),x.setText(O)}};new B.Setting(n).setName("\u5237\u65B0\u8FD0\u884C\u72B6\u6001").setDesc("\u91CD\u65B0\u8BFB\u53D6\u540E\u7AEF\u5F53\u524D\u5DF2\u8FDE\u63A5\u7684 MCP \u670D\u52A1\u548C\u5DE5\u5177\u3002").addButton(g=>{g.setButtonText("\u5237\u65B0"),g.onClick(()=>{A()})});let d=Wt(n,"\u9AD8\u7EA7\u8DEF\u5F84\u8986\u76D6",!!s);new B.Setting(d).setName("MCP \u914D\u7F6E\u6587\u4EF6\u8DEF\u5F84").setDesc("\u4E00\u822C\u4E0D\u9700\u8981\u8BBE\u7F6E\u3002\u4EC5\u5728 mcp_servers.json \u4E0D\u5728\u9ED8\u8BA4\u7684 server/data/ \u4F4D\u7F6E\u65F6\u624B\u52A8\u586B\u5199\u3002").addText(g=>{g.setPlaceholder("D:\\path\\to\\LifeAssistantAgent\\server\\data\\mcp_servers.json").setValue(s).onChange(y=>{s=y.trim(),P()}),g.inputEl.style.width="320px"});let I=Wt(n,"\u7F16\u8F91\u539F\u59CB MCP JSON"),C=I.createEl("textarea",{cls:"mcp-config-editor"});Object.assign(C.style,{width:"100%",minHeight:"280px",boxSizing:"border-box",padding:"10px 12px",marginBottom:"10px",borderRadius:"6px",border:"1px solid var(--background-modifier-border)",backgroundColor:"var(--background-primary)",color:"var(--text-normal)",fontFamily:"var(--font-monospace)",fontSize:"12px",lineHeight:"1.5",resize:"vertical"}),C.placeholder=`{
  "mcpServers": {}
}
`;let v=()=>{let g=ks(i());g.ok&&(C.value=g.text??""),o.setText(g.message),P()};new B.Setting(I).setName("\u4ECE\u6587\u4EF6\u8F7D\u5165").setDesc("\u628A\u5F53\u524D\u914D\u7F6E\u6587\u4EF6\u91CD\u65B0\u8F7D\u5165\u5230\u7F16\u8F91\u5668\u3002").addButton(g=>{g.setButtonText("\u8F7D\u5165"),g.onClick(()=>{v()})}),new B.Setting(I).setName("\u4ECE\u6A21\u677F\u521B\u5EFA").setDesc("\u5F53\u771F\u5B9E\u914D\u7F6E\u6587\u4EF6\u4E0D\u5B58\u5728\u65F6\uFF0C\u6839\u636E mcp_servers.example.json \u521B\u5EFA\u3002").addButton(g=>{g.setButtonText("\u521B\u5EFA"),g.onClick(async()=>{await k();let y=xs(this.plugin.settings);y.ok?(C.value=y.text??"",o.setText(y.message),new B.Notice("\u5DF2\u6839\u636E\u6A21\u677F\u521B\u5EFA MCP \u914D\u7F6E\u6587\u4EF6\u3002"),await A()):(o.setText(y.message),new B.Notice(`\u521B\u5EFA\u5931\u8D25\uFF1A${y.message}`)),P()})}),new B.Setting(I).setName("\u672C\u5730\u6821\u9A8C").setDesc("\u53EA\u6821\u9A8C JSON \u8BED\u6CD5\u548C MCP \u914D\u7F6E\u7ED3\u6784\uFF0C\u4E0D\u4F1A\u5199\u5165\u540E\u7AEF\u3002").addButton(g=>{g.setButtonText("\u6821\u9A8C"),g.onClick(()=>{let y=Vt(C.value);o.setText(y.message),y.ok?new B.Notice("MCP \u914D\u7F6E\u6821\u9A8C\u901A\u8FC7\u3002"):new B.Notice(`\u6821\u9A8C\u5931\u8D25\uFF1A${y.message}`)})}),new B.Setting(I).setName("\u4FDD\u5B58\u914D\u7F6E").setDesc("\u628A\u7F16\u8F91\u5668\u5185\u5BB9\u5199\u5165 mcp_servers.json\u3002").addButton(g=>{g.setButtonText("\u4FDD\u5B58"),g.onClick(async()=>{await k();let y=jt(this.plugin.settings,C.value);o.setText(y.message),y.ok?new B.Notice("MCP \u914D\u7F6E\u5DF2\u4FDD\u5B58\u3002"):new B.Notice(`\u4FDD\u5B58\u5931\u8D25\uFF1A${y.message}`),P()})}).addButton(g=>{g.setButtonText("\u4FDD\u5B58\u5E76\u91CD\u8F7D"),g.setCta(),g.onClick(async()=>{await k();let y=jt(this.plugin.settings,C.value);if(!y.ok){o.setText(y.message),new B.Notice(`\u4FDD\u5B58\u5931\u8D25\uFF1A${y.message}`),P();return}o.setText(`${y.message} \u6B63\u5728\u91CD\u8F7D\u540E\u7AEF...`);let R=new V(r()),O=await Ps(this.plugin.settings,R);o.setText(O.message),O.ok?new B.Notice("MCP \u914D\u7F6E\u5DF2\u4FDD\u5B58\uFF0C\u5E76\u5B8C\u6210\u540E\u7AEF\u91CD\u8F7D\u3002"):new B.Notice(`\u91CD\u8F7D\u5931\u8D25\uFF1A${O.message}`),await A(),P()})}),P(),v(),A()}renderLlmSection(n){n.createEl("h3",{text:"LLM \u914D\u7F6E"});let s=Se(this.plugin.settings),r=n.createDiv({cls:"llm-config-hint"});r.style.fontSize="12px",r.style.color="var(--text-muted)",r.style.marginBottom="10px",r.setText(s.ok&&s.envPath?`\u5F53\u524D\u751F\u6548\u914D\u7F6E\u6587\u4EF6\uFF1A${s.envPath}`:s.message);let i=n.createDiv({cls:"llm-status-bar"});i.style.fontSize="12px",i.style.color="var(--text-muted)",i.style.marginBottom="10px",i.style.minHeight="18px";let a=n.createDiv({cls:"llm-profile-list"});a.style.marginBottom="4px";let c=()=>this.plugin.settings.backendUrl||Ke.backendUrl,o=async()=>{i.setText("\u6B63\u5728\u4ECE\u540E\u7AEF\u8BFB\u53D6 LLM \u914D\u7F6E...");try{let d=await this.plugin.syncLlmProfilesFromBackend({migrateLocalProfiles:!0});i.setText(d.message),d.ok&&(A(),l())}catch(d){let I=d instanceof Error?d.message:String(d);i.setText(`\u8BFB\u53D6\u540E\u7AEF LLM \u914D\u7F6E\u5931\u8D25\uFF1A${I}`)}},l=()=>{let d=this.plugin.settings.llmProfiles.find(I=>I.id===this.plugin.settings.activeProfileId);d?i.setText(`\u5F53\u524D\u542F\u7528\uFF1A${d.name}\uFF08${d.provider} / ${d.model}\uFF09`):this.plugin.settings.llmProfiles.length>0?i.setText("\u5F53\u524D\u8FD8\u6CA1\u6709\u9009\u4E2D\u7684\u914D\u7F6E\u3002"):i.setText("\u5F53\u524D\u8FD8\u6CA1\u6709\u521B\u5EFA\u4EFB\u4F55 LLM \u914D\u7F6E\u3002")},x=async d=>{i.setText(`\u6B63\u5728\u5E94\u7528 ${d.name} ...`);let I=new V(c());try{let C=await Ee(this.plugin.settings,d,I,!0);return i.setText(C.message),C.ok?(await this.plugin.saveSettings(),A(),new B.Notice(`\u5DF2\u5207\u6362\u5230 ${d.name}\u3002`),!0):(A(),new B.Notice(`\u5207\u6362\u5931\u8D25\uFF1A${C.message}`),!1)}catch(C){let v=C instanceof Error?C.message:String(C);return i.setText(`\u5207\u6362\u5931\u8D25\uFF1A${v}`),A(),new B.Notice(`\u5207\u6362\u5931\u8D25\uFF1A${v}`),!1}},P=async d=>{let I=d.id===this.plugin.settings.activeProfileId;i.setText(`\u6B63\u5728\u4FDD\u5B58 ${d.name} \u5230\u540E\u7AEF...`);let C=new V(c());try{let v=await Ee(this.plugin.settings,d,C,I);i.setText(v.message),v.ok?(await this.plugin.saveSettings(),A(),l(),new B.Notice(`\u5DF2\u4FDD\u5B58 ${d.name}\u3002`)):new B.Notice(`\u4FDD\u5B58\u5931\u8D25\uFF1A${v.message}`)}catch(v){let g=v instanceof Error?v.message:String(v);i.setText(`\u4FDD\u5B58\u5931\u8D25\uFF1A${g}`),new B.Notice(`\u4FDD\u5B58\u5931\u8D25\uFF1A${g}`)}},k=async()=>{let d=this.plugin.settings.llmProfiles.find(R=>R.id===this.plugin.settings.activeProfileId),I=Se(this.plugin.settings);if(!I.ok||!I.envPath){i.setText(I.message);return}let C=ue(I.envPath,"LIFE_ASSISTANT_ADMIN_TOKEN")?.trim();if(!C){i.setText(`\u65E0\u6CD5\u6D4B\u8BD5\u5F53\u524D Profile\uFF1A${I.envPath} \u7F3A\u5C11 LIFE_ASSISTANT_ADMIN_TOKEN\u3002`);return}let v=d?`${d.name}\uFF08${d.provider} / ${d.model}\uFF09`:"\u540E\u7AEF\u5F53\u524D\u5DF2\u751F\u6548\u914D\u7F6E";i.setText(`\u6B63\u5728\u6D4B\u8BD5\u5F53\u524D Profile\uFF1A${v}...`);let y=await new V(c()).testCurrentProfile(C);if(!y.ok||!y.data){let R=y.status===null?"\u540E\u7AEF\u5F53\u524D\u4E0D\u53EF\u8BBF\u95EE\u3002":y.detail||`HTTP ${y.status}`;i.setText(`\u6D4B\u8BD5\u5931\u8D25\uFF1A${R}`),new B.Notice(`\u6D4B\u8BD5\u5931\u8D25\uFF1A${R}`);return}i.setText(y.data.message),new B.Notice(y.data.ok?y.data.message:`\u6D4B\u8BD5\u672A\u901A\u8FC7\uFF1A${y.data.message}`)},A=()=>{if(a.empty(),this.plugin.settings.llmProfiles.length===0){let d=a.createDiv();d.setText("\u8FD8\u6CA1\u6709\u914D\u7F6E\u3002\u70B9\u51FB\u201C\u6DFB\u52A0\u914D\u7F6E\u201D\u521B\u5EFA\u4E00\u4E2A\u65B0\u7684 LLM \u914D\u7F6E\u3002"),d.style.color="var(--text-muted)",d.style.fontStyle="italic",d.style.padding="8px 0";return}this.plugin.settings.llmProfiles.forEach((d,I)=>{qt(d);let C=d.id===this.plugin.settings.activeProfileId,v=a.createDiv({cls:"llm-profile-card"});Object.assign(v.style,{border:`1px solid ${C?"var(--interactive-accent)":"var(--background-modifier-border)"}`,borderRadius:"8px",padding:"12px 16px",marginBottom:"10px",backgroundColor:C?"var(--background-secondary-alt)":"var(--background-secondary)",transition:"border-color 0.15s, background-color 0.15s"});let g=v.createDiv();Object.assign(g.style,{display:"flex",alignItems:"center",gap:"8px",marginBottom:"10px",flexWrap:"wrap"});let y=g.createSpan();y.style.fontSize="16px",y.style.cursor="pointer",y.title=C?"\u8FD9\u4E2A\u914D\u7F6E\u5F53\u524D\u5DF2\u542F\u7528\u3002":"\u70B9\u51FB\u542F\u7528\u8FD9\u4E2A\u914D\u7F6E\uFF0C\u5E76\u70ED\u91CD\u8F7D\u540E\u7AEF\u3002",y.setText(C?"\u25CF":"\u25CB"),y.addEventListener("click",async()=>{await x(d)});let R=g.createEl("strong"),O=()=>d.name||`\u914D\u7F6E ${I+1}`;R.setText(O()),R.style.flex="1",R.style.fontSize="14px";let q=Object.fromEntries(We.map(h=>[h,ae(h).badge])),F=g.createSpan();Object.assign(F.style,{fontSize:"11px",padding:"2px 8px",borderRadius:"12px",backgroundColor:q[d.provider],color:"#fff",fontWeight:"600",letterSpacing:"0.03em"}),(()=>{let h=String(d.provider||"");F.setText(h.toUpperCase()||"UNKNOWN"),F.style.backgroundColor=q[h]??"var(--text-muted)"})();let E=g.createEl("button");E.setText("\u4FDD\u5B58"),E.title=C?"\u4FDD\u5B58\u8FD9\u4E2A\u914D\u7F6E\uFF0C\u5E76\u7ACB\u5373\u5E94\u7528\u5230\u540E\u7AEF\u3002":"\u628A\u8FD9\u4E2A\u914D\u7F6E\u4FDD\u5B58\u5230\u540E\u7AEF\u3002",E.addEventListener("click",()=>{P(d)});let u=g.createEl("button");u.setText("\u5220\u9664"),u.title="\u5220\u9664\u8FD9\u4E2A\u914D\u7F6E\u3002",u.addEventListener("click",async()=>{i.setText(`\u6B63\u5728\u4ECE\u540E\u7AEF\u5220\u9664 ${d.name}...`);let h=new V(c()),f=await et(this.plugin.settings,d.id,h);if(i.setText(f.message),!f.ok){new B.Notice(`\u5220\u9664\u5931\u8D25\uFF1A${f.message}`);return}await this.plugin.saveSettings(),A(),l(),new B.Notice(`\u5DF2\u5220\u9664 ${d.name}\u3002`)});{let{activePreset:h,capabilities:f}=Yi(d),p=D=>{Object.assign(D.style,{display:"grid",gridTemplateColumns:"80px 1fr",alignItems:"center",gap:"8px",marginBottom:"6px"})},S=D=>{Object.assign(D.style,{fontSize:"12px",color:"var(--text-muted)",textAlign:"right"})},T=D=>{Object.assign(D.style,{width:"100%",boxSizing:"border-box",fontSize:"13px",padding:"4px 8px",borderRadius:"4px",border:"1px solid var(--background-modifier-border)",backgroundColor:"var(--background-primary)",color:"var(--text-normal)"})},_=(D,Y,ce,X,Te,Ce="text")=>{let Me=D.createDiv();p(Me);let be=Me.createEl("label");be.setText(Y),S(be);let ke=Me.createEl("input");return ke.type=Ce,ke.placeholder=X,ke.value=ce,T(ke),ke.addEventListener("input",async()=>{await Te(ke.value),l()}),ke},U=(D,Y,ce,X)=>{let Te=D.createDiv();p(Te);let Ce=Te.createEl("label");Ce.setText(Y),S(Ce);let be=Te.createDiv().createEl("input");be.type="checkbox",be.checked=ce,be.addEventListener("change",async()=>{await X(be.checked),l()})};_(v,"Name",d.name,"Daily driver",async D=>{d.name=D,await this.plugin.saveSettings(),R.setText(O())});let W=v.createDiv();p(W);let te=W.createEl("label");te.setText("Provider"),S(te);let G=W.createEl("select");T(G),We.forEach(D=>{let Y=G.createEl("option");Y.value=D,Y.setText(ae(D).label)}),G.value=d.provider,G.addEventListener("change",async()=>{d.provider=G.value;let D=ae(d.provider),Y=gn(d.provider);d.model=Y||d.model,d.baseUrl=D.defaultBaseUrl,qt(d),D.capabilities.thinking||(d.thinkingMode=""),D.capabilities.thinkingBudget||(d.thinkingBudgetTokens="1024"),D.capabilities.reasoningEffort||(d.thinkingEffort=""),D.capabilities.reasoningSplit||(d.reasoningSplit=!1),await this.plugin.saveSettings(),A(),l()});let le=v.createEl("datalist");le.id=`llm-models-${d.id}`,h.models.forEach(D=>{let Y=le.createEl("option");Y.value=D.id,Y.label=D.label});let ve=_(v,"Model",d.model,"Select or type a model id",async D=>{d.model=D.trim(),qt(d),await this.plugin.saveSettings()});if(ve.setAttribute("list",le.id),ve.addEventListener("change",()=>{A(),l()}),f.baseUrl&&_(v,"Base URL",d.baseUrl,h.defaultBaseUrl,async D=>{d.baseUrl=D.trim(),await this.plugin.saveSettings()}),f.apiKey&&_(v,"API Key",d.apiKey,h.apiKeyEnv||"LLM_API_KEY",async D=>{d.apiKey=D.trim(),await this.plugin.saveSettings()},"password"),f.vision||f.thinking||f.thinkingBudget||f.reasoningEffort||f.reasoningSplit){let D=v.createEl("details");D.style.marginTop="8px";let Y=D.createEl("summary");Y.setText("Advanced"),Y.style.cursor="pointer",Y.style.fontSize="12px",Y.style.color="var(--text-muted)";let ce=D.createDiv();ce.style.marginTop="8px",f.vision&&U(ce,"Vision",!!d.supportsVision,async X=>{d.supportsVision=X,await this.plugin.saveSettings()}),f.thinking&&U(ce,"Thinking",d.thinkingMode.trim().toLowerCase()==="enabled",async X=>{d.thinkingMode=X?"enabled":"",await this.plugin.saveSettings()}),f.thinkingBudget&&_(ce,"Budget",d.thinkingBudgetTokens,"1024",async X=>{d.thinkingBudgetTokens=X.trim(),await this.plugin.saveSettings()}),f.reasoningEffort&&_(ce,"Effort",d.thinkingEffort,pn(d.provider),async X=>{d.thinkingEffort=X.trim(),await this.plugin.saveSettings()}),f.reasoningSplit&&U(ce,"Split",!!d.reasoningSplit,async X=>{d.reasoningSplit=X,await this.plugin.saveSettings()})}}})};A(),l(),o(),new B.Setting(n).setName("\u5237\u65B0\u540E\u7AEF Profile").setDesc("\u91CD\u65B0\u4ECE\u540E\u7AEF\u8BFB\u53D6\u5F53\u524D LLM Profile \u5217\u8868\u3002").addButton(d=>{d.setButtonText("\u5237\u65B0"),d.onClick(()=>{o()})}),new B.Setting(n).setName("\u6D4B\u8BD5\u5F53\u524D Profile").setDesc("\u6821\u9A8C\u540E\u7AEF\u5F53\u524D\u5DF2\u751F\u6548\u7684 provider\u3001model\u3001key\uFF0C\u5E76\u5728 DeepSeek / MiniMax \u4E0A\u505A\u4E00\u6B21\u4F4E token \u771F\u5B9E\u63A2\u6D4B\u3002").addButton(d=>{d.setButtonText("\u6D4B\u8BD5"),d.onClick(()=>{k()})}),new B.Setting(n).setName("\u6DFB\u52A0\u914D\u7F6E").setDesc("\u65B0\u589E\u4E00\u4E2A LLM \u914D\u7F6E\u9884\u8BBE\u3002").addButton(d=>{d.setButtonText("\u6DFB\u52A0"),d.onClick(async()=>{let I={id:Math.random().toString(36).substring(2,10),name:"\u65B0\u914D\u7F6E",provider:"anthropic",model:"claude-sonnet-4-20250514",baseUrl:"",apiKey:"",supportsVision:!1,thinkingMode:"",thinkingEffort:"",thinkingBudgetTokens:"1024",reasoningSplit:!1},C=this.plugin.settings.llmProfiles.length===0;i.setText(`\u6B63\u5728\u521B\u5EFA ${I.name}...`);let v=new V(c()),g=await Ee(this.plugin.settings,I,v,C);if(i.setText(g.message),!g.ok){new B.Notice(`\u6DFB\u52A0\u5931\u8D25\uFF1A${g.message}`);return}await this.plugin.saveSettings(),A(),l()})})}};var ht=class extends ze.Plugin{constructor(){super(...arguments);this.settings=zt(Ke,null);this.runtimeManager=null;this.clientToolBridge=null;this.unloaded=!1}async onload(){this.unloaded=!1,await this.loadSettings(),this.runtimeManager=new ot(this.app,this.settings),this.clientToolBridge=new pt(this,()=>this.settings.backendUrl),this.clientToolBridge.start(),this.registerView(Be,n=>new at(n,this)),this.addSettingTab(new mt(this.app,this)),this.addRibbonIcon("bot","Life Assistant",()=>{this.activateView()}),this.addCommand({id:"open-chat",name:"Open Life Assistant Chat",callback:()=>this.activateView()}),this.startRuntimeInBackground()}async onunload(){this.unloaded=!0,this.app.workspace.detachLeavesOfType(Be),this.clientToolBridge&&(this.clientToolBridge.stop(),this.clientToolBridge=null),this.runtimeManager&&(await this.runtimeManager.stop(),this.runtimeManager=null)}startRuntimeInBackground(){let n=this.runtimeManager;n&&(async()=>{try{if(await n.ensureRuntimeLayout(),this.unloaded||this.runtimeManager!==n)return;let s=await n.start();if(this.unloaded||this.runtimeManager!==n)return;await this.syncLlmProfilesFromBackend({migrateLocalProfiles:!0}),await this.saveSettings(),!s.running&&s.mode==="production"&&new ze.Notice("Life Assistant backend runtime is not installed. Open settings to install it.")}catch(s){if(!this.unloaded){console.error("[Life Assistant] Failed to start backend runtime:",s);let r=s instanceof Error?s.message:String(s);new ze.Notice(`Life Assistant backend startup failed: ${r}`)}}})()}async loadSettings(){let n=await this.loadData();this.settings=zt(Ke,n),fs(n)&&await this.saveSettings()}async saveSettings(){await this.saveData(this.settings),Xt()}restartClientToolBridge(){this.clientToolBridge&&(this.clientToolBridge.stop(),this.clientToolBridge.start())}getCurrentVaultPath(){return(this.app.vault.adapter.basePath??"").trim()}async ensureBackendVaultPathSynced(n){try{let s=await bn(this.settings,this.getCurrentVaultPath(),n??new V(this.settings.backendUrl));return{ok:s.ok,changed:!!s.changed,message:s.message}}catch(s){let r=s instanceof Error?s.message:String(s);return console.error("[Life Assistant] Failed to sync backend vault path:",s),{ok:!1,changed:!1,message:"Failed to sync the current vault path with the backend .env. Check the plugin's backend .env path setting. "+r}}}async applyLlmProfile(){let n=this.settings.llmProfiles.find(s=>s.id===this.settings.activeProfileId)??this.settings.llmProfiles[0];if(!n)return{ok:!1,message:"No LLM profile is configured."};await this.saveSettings();try{let s=new V(this.settings.backendUrl),r=await De(this.settings,n.id,s);return r.ok&&await this.saveSettings(),{ok:r.ok,message:r.message}}catch(s){let r=s instanceof Error?s.message:String(s);return console.error(s),{ok:!1,message:`Failed to apply the active LLM profile: ${r}`}}}async syncLlmProfilesFromBackend(n={}){let s=new V(this.settings.backendUrl),r=this.settings.llmProfiles.map(c=>({...c})),i=this.settings.activeProfileId,a=await Qe(this.settings,s);if(!a.ok)return{ok:!1,message:a.message};if(n.migrateLocalProfiles&&a.profiles?.length===0&&r.length>0){for(let c of r){let o=c.id===i||!i&&c.id===r[0].id,l=await Ee(this.settings,c,s,o);if(!l.ok)return{ok:!1,message:l.message}}return await this.saveSettings(),{ok:!0,message:"Migrated local LLM profiles to backend."}}return await this.saveSettings(),{ok:!0,message:a.message}}async activateView(){let{workspace:n}=this.app,s=n.getLeavesOfType(Be)[0];if(!s){let r=n.getRightLeaf(!1);r&&(s=r,await s.setViewState({type:Be,active:!0}))}s&&n.revealLeaf(s)}};

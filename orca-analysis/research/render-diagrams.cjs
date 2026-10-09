const fs=require('fs');
const sharp=require('/Users/bytedance/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/sharp');
const base=__dirname+'/../assets/';
const esc=s=>s.replaceAll('&','&amp;').replaceAll('<','&lt;');
function start(w,h,title,subtitle){return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#425b72"/></marker></defs><rect width="100%" height="100%" fill="#f8fafc"/><style>text{font-family:PingFang SC,Noto Sans CJK SC,Arial,sans-serif;fill:#183044} .title{font-size:32px;font-weight:700}.sub{font-size:20px;fill:#516a80}.label{font-size:23px;font-weight:600}.body{font-size:19px}.small{font-size:18px}</style><text x="45" y="55" class="title">${title}</text><text x="45" y="92" class="sub">${subtitle}</text>`;}
function box(x,y,w,h,title,lines=[],fill='#fff'){return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="12" fill="${fill}" stroke="#a6b8c7" stroke-width="2"/><text x="${x+20}" y="${y+34}" class="label">${esc(title)}</text>${lines.map((l,i)=>`<text x="${x+20}" y="${y+66+i*29}" class="body">${esc(l)}</text>`).join('')}`;}
function arrow(path,label,x,y,dash=false){return `<path d="${path}" fill="none" stroke="#425b72" stroke-width="2.5" ${dash?'stroke-dasharray="8 6"':''} marker-end="url(#arrow)"/>${label?`<text x="${x}" y="${y}" class="small">${esc(label)}</text>`:''}`;}
async function save(name,s){s+='</svg>';fs.writeFileSync(base+name+'.svg',s);await sharp(Buffer.from(s)).png().toFile(base+name+'.png');}
(async()=>{
let s=start(1440,1040,'Orca：控制入口与执行归属','本文按职责归纳；外框表示归属，实线表示调用，虚线表示事件或状态流');
s+=box(40,130,420,155,'客户端',['桌面 Renderer / Web / Mobile','显示终端、聊天与工作区','保存呈现偏好，不判定远端进程死亡'],'#e9f1fa');
s+=box(40,350,420,185,'目标 Orca Runtime',['CLI 经 RPC；桌面也有 IPC 入口','创建工作区、选择执行主机','管理会话、状态和编排接口'],'#e9f1fa');
s+=arrow('M 250 285 V 348','请求 / 订阅',265,325);
s+=`<rect x="550" y="125" width="850" height="685" rx="18" fill="#edf6f1" stroke="#709b85" stroke-width="2"/><text x="580" y="165" class="label">执行状态与持有者：本图与目标 Runtime 同属一个主机</text>`;
s+=box(585,205,365,155,'PTY 执行路径',['Daemon → TerminalHost → Session','Shell / CLI Agent','活进程 + 终端模拟器']);
s+=box(1000,205,365,155,'结构化会话路径',['StructuredAgentSessionHost','投递循环 → Provider Adapter','会话与 Provider 子进程分离']);
s+=arrow('M 460 395 H 515 V 280 H 582','选择路径',464,378);
s+=arrow('M 515 380 H 980 V 280 H 997','',0,0);
s+=box(585,435,365,140,'终端快照与历史',['ANSI、模式、尺寸、输出位置','保存画面不等于保存进程']);
s+=box(1000,435,365,140,'结构化 Journal',['SQLite WAL + FULL','先提交消息记录，再向 Provider 投递']);
s+=arrow('M 768 360 V 432','快照 / 输出记录',785,402);
s+=arrow('M 1182 360 V 432','先写记录',1196,402);
s+=box(650,650,645,115,'Hook Server / 状态存储',['结构化会话有完整作用域；PTY 证据仍经 legacy adapter']);
s+=arrow('M 585 320 H 567 V 705 H 647','',0,0,true);
s+=arrow('M 1365 320 H 1380 V 705 H 1298','',0,0,true);
s+=arrow('M 650 745 H 490 V 470 H 463','状态发布',496,731,true);
s+=box(40,855,1360,130,'直接 SSH 是另一种归属关系',['客户端 Runtime → SSH relay → 远端 PTY；远端 orca shim 的控制请求仍回到客户端。','与上图的远端独立 Runtime 区分；cloud/ 手机中继也不是 src/relay 的 SSH 执行代理。'],'#fff3df');
await save('architecture',s);
s=start(1440,1060,'结构化消息：接收、投递和结果是三个时刻','说明性示例；响应与后台投递可交错，图示一种顺序，省略鉴权与非核心字段');
const xs=[135,470,855,1260];const names=['客户端','Session Host','SQLite Journal','Provider Adapter'];
xs.forEach((x,i)=>{s+=box(x-120,125,240,65,names[i],[],'#e9f1fa');s+=`<path d="M ${x} 190 V 980" stroke="#acbcc9" stroke-width="2" stroke-dasharray="6 7"/>`;});
s+=arrow('M 135 235 H 468','send：sessionId + clientOperationId + body',150,219);
s+=`<text x="490" y="273" class="body">按会话串行；核对指纹、操作账本与 fence</text>`;
s+=arrow('M 470 330 H 852','appendSubmission',492,314);
s+=`<rect x="735" y="350" width="245" height="69" rx="8" fill="#dbefdf"/><text x="750" y="378" class="body">COMMIT：queued</text><text x="750" y="403" class="small">消息已记录，尚未投递</text>`;
s+=arrow('M 470 452 H 138','返回接收结果 + cursor / fence',155,435,true);
s+=`<text x="490" y="494" class="body">接收后异步 wakeDelivery；启动或复用 Provider 子进程</text>`;
s+=arrow('M 470 555 H 852','先写 dispatch=pending 并提交',485,538);
s+=arrow('M 470 625 H 1257','handOverSubmission → adapter.dispatch',580,608);
s+=arrow('M 1260 694 H 473','accepted / rejected / unknown（异常）',584,677,true);
s+=arrow('M 470 765 H 852','记录投递状态',515,748);
s+=arrow('M 1260 837 H 473','后续消息、工具和轮次事件',585,820,true);
s+=arrow('M 470 885 H 852','追加 journal 后向订阅者发布',494,870);
s+=arrow('M 470 943 H 138','增量事件 / 状态',184,928,true);
s+=`<text x="45" y="1020" class="sub">同一消息 ID 重试只重放记录；unknown 不证明未送达，因此不会自动再次投递。</text>`;
await save('send-sequence',s);
})();

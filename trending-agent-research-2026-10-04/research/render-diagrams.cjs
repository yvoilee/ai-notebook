const fs=require('node:fs');
const path=require('node:path');
const sharp=require('/Users/bytedance/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/sharp');
const root=path.resolve('trending-agent-research-2026-10-04/assets');
const specs=[
 ['ponytail','Ponytail · 规则注入与模式状态','宿主 hook 调用；文件状态不等于模型执行保证',[
  ['SessionStart','宿主触发'],['activate.js','读取默认模式'],['instructions.js','筛选并输出规则'],['UserPromptSubmit','解析模式命令'],['mode-tracker.js','临时 / 默认切换'],['运行状态文件','项目与共享回退']
 ],[[0,1,'调用'],[1,2,'生成上下文'],[3,4,'调用'],[4,5,'写入'],[5,1,'后续读取','dash']], '规则由宿主模型解释；同项目多会话可能覆盖模式状态。'],
 ['marketingskills','Marketing Skills · 背景文件连接不同任务','技能是指令；CLI 才执行外部请求',[
  ['产品背景技能','收集并确认事实'],['product-marketing.md','持久共享背景'],['CRO 等任务技能','读取背景与方法'],['宿主 Agent','选择并调用工具'],['plausible.js','构造分析查询'],['Plausible API','返回数据']
 ],[[0,1,'写入'],[1,2,'提供上下文'],[2,3,'指导'],[3,4,'调用'],[4,5,'HTTP']], '建议质量和实验效果需另行验证；背景文件没有多写者事务。'],
 ['agent-skills','Agent Skills · 任务指令与可选缓存','上方为宿主遵循的流程；下方是额外启用的 hook',[
  ['build 命令','读取规格与任务'],['宿主 Agent','测试 → 实现 → 验证'],['Git 提交','逐项保存结果'],['WebFetch 完成','可选 post hook'],['本地缓存','内容 + ETag'],['下次 pre hook','HEAD 304 才复用']
 ],[[0,1,'指导'],[1,2,'执行后提交'],[3,4,'写入'],[4,5,'读取 / 验证']], '插件声明未自动接入这条缓存 hook；流程要求并非独立调度器强制保证。'],
 ['Agent-Reach','Agent Reach · 诊断路径与数据路径','doctor 检查接入状态；内容访问通常直接使用上游工具',[
  ['doctor / get_status','诊断入口'],['Channel 检查','候选后端顺序'],['状态报告','ok / warn / error'],['宿主 Agent','依据安装技能'],['上游 CLI / MCP','执行实际访问'],['外部内容平台','返回内容或错误']
 ],[[0,1,'调用'],[1,2,'聚合'],[3,4,'直接调用'],[4,5,'访问']], '配置文件原子替换；诊断为可用不等于每个真实请求成功。'],
 ['text-to-cad','text-to-cad · 源码、构建与发布','构建期间源码可能变化；发布前重新判断',[
  ['模型 Python 源码','@step 与依赖'],['stale gate','源码 / 依赖 / 输出 hash'],['generation runner','实际源码编译与几何生成'],['候选导出结果','尚未成为当前发布'],['publish decision','重新比较磁盘状态'],['当前导出文件','发布或保留已有版本']
 ],[[0,1,'输入'],[1,2,'需要构建'],[2,3,'产生'],[3,4,'提交判断'],[4,5,'条件发布']], '检查与替换不是一个源码编辑事务；可能发布标记为 stale 的结果。'],
 ['OpenMontage','OpenMontage · 阶段合同与 checkpoint','Agent 执行产物生产；checkpoint 校验并记录阶段状态',[
  ['pipeline YAML','阶段 / 产物 / 审批要求'],['宿主 Agent 与工具','生成阶段产物'],['write_checkpoint','提交状态与路径'],['前置与产物校验','含需要的人类审批标记'],['临时 JSON → replace','当前 checkpoint 落盘'],['恢复读取','按阶段顺序找下一步']
 ],[[0,1,'指导'],[1,2,'调用'],[2,3,'校验'],[3,4,'通过后写入'],[4,5,'读取']], '审批布尔值不是身份认证；历史备份与 decision log 不属于同一事务。'],
 ['impeccable','Impeccable · 整库检查与写前 gate','共享检测能力，但退出与拒绝语义不同',[
  ['CLI detect','选择文件 / URL 范围'],['Rust 检测器','规则与配置'],['扫描报告','问题与运行错误分开'],['宿主写前 hook','拟写入操作'],['重建拟写入内容','运行相关检查'],['JSON 决策','允许 / 拒绝；含降级规则']
 ],[[0,1,'调用'],[1,2,'输出'],[3,4,'解析'],[4,5,'决定']], 'gate 的 fail-open 与重复拒绝放行意味着它不是不可绕过的安全边界。'],
 ['gstack','gstack · 两种浏览器生命周期','Aside 优先路径与持久 browse daemon 路径分开',[
  ['宿主 Agent','选择可用浏览器'],['Aside script','本次脚本会话'],['步骤 sentinel','显式证明步骤完成'],['browse CLI','发现 PID / port / token'],['Bun daemon','持久 Playwright tabs'],['snapshot refs','每个 tab 内的定位映射']
 ],[[0,1,'可用时'],[1,2,'返回证据'],[0,3,'回退路径'],[3,4,'鉴权请求'],[4,5,'生成']], 'Aside 脚本结束与 daemon tab 保留不同；旧 ref 可能失效，批量操作不原子。'],
 ['e2e','e2e · 后续断言确认动作缓存','图中流程为首次录制；后续运行可尝试轨迹回放',[
  ['agent.act','验证输入与预算'],['executor + 引擎','观察 / 执行动作'],['staged trace','内存候选轨迹'],['后续验证步骤','确定性断言或 Agent 判断'],['attempt 结算','lastVerifiedStepIndex'],['缓存 store','确认才写入 / 保留']
 ],[[0,1,'缓存未命中'],[1,2,'步骤成功'],[2,3,'继续测试'],[3,4,'记录验证边界'],[4,5,'确认后持久化']], '中断不 flush；模型不可达不直接归咎于轨迹；回放本身不替代后续断言。'],
 ['claude-mem','claude-mem · 入口、生成与召回','三个存储边界：磁盘 spool / 内存 buffer / SQLite 结果',[
  ['工具 hook','过滤并规范化'],['磁盘 spool','原子事件文件'],['内存 message buffer','交接 marker ≠ 结果提交'],['observer','异步模型归约'],['SQLite observation','事务成功后 confirm'],['上下文构建','查询 / 时间线 / 预算']
 ],[[0,1,'写入'],[1,2,'ingest 接受'],[2,3,'领取批次'],[3,4,'解析后存储'],[4,5,'后续会话读取']], '内存队列不耐进程重启；provider 与外部同步不在 SQLite 结果事务内。'],
 ['t3code','T3 Code · 持久意图先于外部执行','虚线框：事件、投影、receipt、outbox 同一数据库事务',[
  ['RPC 命令','commandId / threadId'],['Orchestrator','状态决策与去重'],['EventSink 事务','event + projection\nreceipt + outbox'],['订阅客户端','提交后按序发布'],['EffectWorker','claim / 执行 / 重试'],['Provider / Git','外部副作用']
 ],[[0,1,'调用'],[1,2,'提交计划'],[2,3,'commit 后发布'],[2,4,'持久工作'],[4,5,'调用']], 'ack 只确认意图提交；provider turn 结束和 checkpoint 完成分别记录。'],
 ['orca','Orca · 工作区路由与会话交付','上方分配运行目录；下方是结构化消息路径',[
  ['创建工作区请求','repo / startup 配置'],['execution host 路由','本地 / SSH / folder'],['工作区与终端','目录归属与启动'],['结构化 send','operation 身份 / queue'],['SQLite journal','先持久 submission'],['delivery + adapter','交付 provider 并记录状态']
 ],[[0,1,'解析'],[1,2,'创建或注册'],[3,4,'接纳'],[4,5,'commit 后交付']], 'folder 注册不自动隔离文件；unknown 不足以触发沿原 ID 自动重送。']
];
const esc=s=>s.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const xy=i=>[65+(i%3)*440,180+Math.floor(i/3)*275];
(async()=>{for(const [slug,title,subtitle,nodes,edges,note] of specs){
 let body=`<svg xmlns="http://www.w3.org/2000/svg" width="1460" height="800" viewBox="0 0 1460 800"><defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M0 0L10 5L0 10" fill="#41718b"/></marker></defs><rect width="1460" height="800" fill="#f5f7fa"/><g font-family="PingFang SC, Noto Sans CJK SC, sans-serif"><text x="65" y="65" font-size="32" font-weight="600" fill="#172c40">${esc(title)}</text><text x="65" y="112" font-size="21" fill="#4d6170">${esc(subtitle)}</text>`;
 for(const [a,b,label,style] of edges){let [x,y]=xy(a),[u,v]=xy(b);let d,lx,ly;
  if(y===v){d=`M${x+340} ${y+70}H${u-12}`;lx=x+349;ly=y+48;}
  else if(x===u){d=`M${x+170} ${y+140}V${v-12}`;lx=x+185;ly=(y+140+v)/2;}
  else if(a===2&&b===3){d=`M${x+170} ${y+140}V${y+205}H${u+170}V${v-12}`;lx=510;ly=y+193;}
  else if(a===5&&b===1){d=`M${x+340} ${y+70}H1405V155H${u+170}V${v-12}`;lx=1130;ly=150;}
  else {d=`M${x+170} ${y+140}V${y+205}H${u+170}V${v-12}`;lx=(x+u)/2+180;ly=y+193;}
  body+=`<path d="${d}" fill="none" stroke="#41718b" stroke-width="2.5" ${style?'stroke-dasharray="7 5"':''} marker-end="url(#a)"/><text x="${lx}" y="${ly}" font-size="17" fill="#35576b">${esc(label)}</text>`;
 }
 nodes.forEach(([name,desc],i)=>{const[x,y]=xy(i);body+=`<rect x="${x}" y="${y}" width="340" height="140" rx="14" fill="${i===4?'#e8f2ed':'white'}" stroke="#adbdc9" stroke-width="2" ${slug==='t3code'&&i===2?'stroke-dasharray="7 5"':''}/><text x="${x+22}" y="${y+45}" font-size="24" font-weight="600" fill="#173d55">${esc(name)}</text>`;desc.split('\n').forEach((s,j)=>body+=`<text x="${x+22}" y="${y+83+j*26}" font-size="20" fill="#4d6170">${esc(s)}</text>`);});
 body+=`<line x1="65" y1="690" x2="1395" y2="690" stroke="#ccd6df"/><text x="65" y="730" font-size="21" fill="#3c5465">${esc(note)}</text><text x="65" y="770" font-size="17" fill="#6c7e8c">固定源码分析 · 实线箭头表示标注的调用或数据传递；图不表示真实时间比例。</text></g></svg>`;
 fs.writeFileSync(path.join(root,slug+'.svg'),body);await sharp(Buffer.from(body)).png().toFile(path.join(root,slug+'.png'));
 }console.log(`Rendered ${specs.length} SVG and PNG diagrams`);})();

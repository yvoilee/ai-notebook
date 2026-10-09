import fs from 'node:fs';
import path from 'node:path';
const root=path.resolve('trending-agent-research-2026-10-04');
const manifest=JSON.parse(fs.readFileSync(path.join(root,'research/manifest.json')));
for(const m of manifest){
 const draft=path.join(root,'research/drafts',m.slug+'.md');if(!fs.existsSync(draft))continue;
 let body=fs.readFileSync(draft,'utf8');
 const first=body.indexOf('\n');
 const header=`\n\n> 版本依据：仓库 [${m.repo}](https://github.com/${m.repo})；默认分支 \`${m.branch}\`；完整 commit \`${m.commit}\`。源码读取日期：2026-10-05（Asia/Shanghai）。榜单快照：2026-10-04 23:56。${m.slug==='orca'?'Orca 为用户额外指定项目，不在本次榜单中。':''}\n\n本文面向有工程经验的开发者。实现事实以这一源码快照为准；“本文归纳”是分析判断，“说明性示例”未实际执行。许可证以仓库 [LICENSE](https://github.com/${m.repo}/blob/${m.commit}/LICENSE) 为依据。没有提供额外参考文档。\n`;
 body=body.slice(0,first)+header+body.slice(first);
 body=body.replace(/\]\(src:([^)]*)\)/g,`](${`https://github.com/${m.repo}/blob/${m.commit}/`}$1)`);
 fs.writeFileSync(path.join(root,m.slug+'.md'),body);
}

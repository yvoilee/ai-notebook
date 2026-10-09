import fs from 'node:fs';
import path from 'node:path';
const root=path.resolve('trending-agent-research-2026-10-04');
const manifest=JSON.parse(fs.readFileSync(path.join(root,'research/manifest.json')));
const docs=fs.readdirSync(root).filter(f=>f.endsWith('.md')&&f!=='IMPLEMENTATION_PLAN.md');
const report={checkedAt:new Date().toISOString(),documents:[],errors:[]};
for(const name of docs){
 const text=fs.readFileSync(path.join(root,name),'utf8');
 const entry={name,characters:text.length,sourceReferences:0,images:0,punctuation:[],suspectPhrases:[],headings:[]};
 let inCode=false;
 for(const [i,line] of text.split('\n').entries()){
  if(/^\s*```/.test(line)){inCode=!inCode;continue;}
  if(inCode)continue;
  if(/^#+ /.test(line))entry.headings.push(line);
  const clean=line.replace(/`[^`]*`/g,'').replace(/!?\[([^\]]*)\]\([^)]*\)/g,'$1').replace(/https?:\/\/\S+/g,'');
  if(/[\u4e00-\u9fff][,;:]|[\u4e00-\u9fff]\.[^0-9]/.test(clean))entry.punctuation.push({line:i+1,text:clean});
  if(/值得深思|值得关注|值得玩味|不禁让人|引人深思|发人深省|令人深思|不禁要问|不是.{1,30}而是/.test(clean))entry.suspectPhrases.push({line:i+1,text:clean});
 }
 if(inCode)report.errors.push(`${name}: unclosed fenced block`);
 for(const m of text.matchAll(/(!?)\[([^\]]*)\]\(([^)]+)\)/g)){
  let link=m[3];if(link.startsWith('<'))link=link.slice(1,-1);
  if(m[1])entry.images++;
  if(link.startsWith('https://github.com/')&&link.includes('/blob/')){
   entry.sourceReferences++;
   const x=link.match(/^https:\/\/github.com\/([^/]+\/[^/]+)\/blob\/([^/]+)\/(.*?)(?:#L(\d+)(?:-L(\d+))?)?$/);
   if(!x){report.errors.push(`${name}: malformed source ${link}`);continue;}
   const src=manifest.find(v=>v.repo.toLowerCase()===x[1].toLowerCase());
   if(!src){report.errors.push(`${name}: untracked repo ${link}`);continue;}
   if(x[2]!==src.commit)report.errors.push(`${name}: wrong commit ${link}`);
   const file=path.join(root,'research',src.slug,'source',decodeURIComponent(x[3]));
   if(!fs.existsSync(file)){report.errors.push(`${name}: missing source ${link}`);continue;}
   if(x[4]){const lines=fs.readFileSync(file,'utf8').split('\n').length;if(Number(x[4])>lines||Number(x[5]||x[4])>lines||Number(x[5]||x[4])<Number(x[4]))report.errors.push(`${name}: bad lines ${link}`);}
  }else if(!/^[a-z]+:|^#/.test(link)){
   const local=path.resolve(root,decodeURIComponent(link.split('#')[0]));
   if(!fs.existsSync(local))report.errors.push(`${name}: missing local link ${link}`);
  }
 }
 report.documents.push(entry);
}
fs.writeFileSync(path.join(root,'research/codex-check.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify(report,null,2));

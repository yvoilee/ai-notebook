const fs=require('fs'), path=require('path');
const file=path.resolve('orca-analysis/Orca_源码深度解读.md');const s=fs.readFileSync(file,'utf8');const base='/private/tmp/orca-source-20260928';
const links=[...s.matchAll(/https:\/\/github\.com\/stablyai\/orca\/blob\/([a-f0-9]{40})\/([^\s)]+)\)/g)];let errors=[];
for(const [,sha,target]of links){const [p,anchor]=target.split('#');if(sha!=='3dd7d294559309cc95b0143f6cece7404b2245c1')errors.push('wrong commit');if(!fs.existsSync(path.join(base,p))){errors.push('missing '+p);continue;}const n=fs.readFileSync(path.join(base,p),'utf8').trimEnd().split('\n').length;if(anchor){const m=/^L(\d+)(?:-L(\d+))?$/.exec(anchor);if(!m||+m[1]>n||+(m[2]||m[1])>n)errors.push(`${p} ${anchor} > ${n}`);}}
for(const [,target]of s.matchAll(/!\[[^\]]*\]\(([^)]+)\)/g))if(!fs.existsSync(path.resolve(path.dirname(file),target)))errors.push('missing image '+target);
let clean=s.replace(/```[\s\S]*?```/g,'').replace(/`[^`]+`/g,'').replace(/https?:\/\/[^\s)]+/g,'').replace(/\]\([^)]*\)/g,']');
const patterns={halfwidth:/[\u4e00-\u9fff][,;:]|[\u4e00-\u9fff],[^0-9]|[\u4e00-\u9fff]\.[^0-9]/g,meta:/(值得深思|值得关注|值得玩味|不禁让人|引人深思|发人深省)/g,contrast:/(不是[^，。；\n]{1,30}[，,](而)?是|这不是|不在[^，。\n]{1,15}[，,]?而(在|是)|你以为|看似[^，。\n]{1,30}实则|真正[^，。\n]{1,20}的是)/g,dashes:/——/g};
const scan=Object.fromEntries(Object.entries(patterns).map(([k,r])=>[k,[...clean.matchAll(r)].map(x=>x[0])]));
const headings=s.split('\n').filter(l=>/^#{1,6} /.test(l));const duplicates=headings.filter((x,i)=>headings.indexOf(x)!==i);
const result={sourceLinks:links.length,uniqueSourceFiles:new Set(links.map(x=>x[2].split('#')[0])).size,images:2,fences:(s.match(/^```/gm)||[]).length,headings:headings.length,duplicates,errors,scan};console.log(JSON.stringify(result,null,2));fs.writeFileSync('orca-analysis/research/document-check.json',JSON.stringify(result,null,2));if(errors.length||duplicates.length)process.exitCode=1;

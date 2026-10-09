import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
const root=path.resolve('trending-agent-research-2026-10-04/research');
const repos=['tester-army/e2e','pbakaus/impeccable','coreyhaines31/marketingskills','DietrichGebert/ponytail','earthtojake/text-to-cad','Panniantong/Agent-Reach','calesthio/OpenMontage','pingdotgg/t3code','addyosmani/agent-skills','thedotmack/claude-mem','garrytan/gstack','stablyai/orca'];
function curl(url,dest){execFileSync('curl',['-L','--fail','--silent','--show-error','--connect-timeout','15','--max-time','120',url,'-o',dest],{stdio:'pipe'});}
const manifest=[];
for(const repo of repos){
 const slug=repo.split('/')[1];const dir=path.join(root,slug);fs.mkdirSync(dir,{recursive:true});
 try{
 curl(`https://api.github.com/repos/${repo}`,path.join(dir,'metadata.json'));
 const meta=JSON.parse(fs.readFileSync(path.join(dir,'metadata.json')));
 curl(`https://api.github.com/repos/${repo}/commits/${encodeURIComponent(meta.default_branch)}`,path.join(dir,'commit.json'));
 const commit=JSON.parse(fs.readFileSync(path.join(dir,'commit.json'))).sha;
 curl(`https://codeload.github.com/${repo}/tar.gz/${commit}`,path.join(dir,'source.tar.gz'));
 fs.mkdirSync(path.join(dir,'source'),{recursive:true});
 execFileSync('tar',['-xzf',path.join(dir,'source.tar.gz'),'-C',path.join(dir,'source'),'--strip-components=1']);
 manifest.push({repo,slug,branch:meta.default_branch,commit,readAt:new Date().toISOString(),license:meta.license?.spdx_id,description:meta.description});
 console.log(`${repo} ${commit} downloaded`);
 }catch(e){manifest.push({repo,slug,error:String(e.message)});console.log(`${repo} FAILED ${e.message}`);}
 fs.writeFileSync(path.join(root,'manifest.json'),JSON.stringify(manifest,null,2));
}

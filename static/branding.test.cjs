const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
test('documentation and server descriptions use Unhideme branding',()=>{
 const read=file=>fs.readFileSync(path.join(__dirname,'..',file),'utf8');
 assert.match(read('README.md'),/^# Unhideme\n/);
 assert.ok(!read('backend/app.py').includes('Threadtrace'));
});
test('Unhideme branding replaces the old headline and removes requested promotional copy',()=>{
 const html=fs.readFileSync(path.join(__dirname,'index.html'),'utf8');
 assert.match(html,/<title>unhideme<\/title>/);
 assert.match(html,/<h1>Unhideme<\/h1>/);
 assert.match(html,/aria-label="unhideme home"/);
 for(const text of ['THREADTRACE','Threadtrace','Your words.','Somewhere','out <em>there.</em>','A username is a starting point.','Find the public Reddit posts that search engines still remember.','LESS SCROLLING. MORE FINDING.','Search the index. Separate your posts from passing mentions. Take the trail with you.','LEAVE NO THREAD UNFOLLOWED.'])assert.ok(!html.includes(text),`Removed: ${text}`);
});

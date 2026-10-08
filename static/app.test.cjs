const {test}=require('node:test');
const assert=require('node:assert/strict');
const app=require('./app.js');
const imp=require('./import.js');
const fs=require('node:fs');
const textOf=node=>[node.textContent,...node.children.map(textOf)].join(' ');
test('date sorting is stable, defaults to relevance and places unknown dates last',()=>{
 const rows=[{id:'unknown'},{id:'new',created_utc:200},{id:'old',created_utc:100},{id:'invalid',created_utc:'no'}];
 assert.equal(typeof app.sortResults,'function');
 assert.deepEqual(app.sortResults(rows,'newest').map(r=>r.id),['new','old','unknown','invalid']);
 assert.deepEqual(app.sortResults(rows,'oldest').map(r=>r.id),['old','new','unknown','invalid']);
 assert.deepEqual(app.sortResults(rows,'relevance'),rows);
});
test('coverage reports zero separately from unavailable and renders readable provider details',async()=>{
 const doc=documentFixture();app.mount(doc,async()=>({ok:true,json:async()=>({username:'abc',results:[],sources:[{name:'archive',status:'error',count:0,message:'Connection refused'},{name:'search',status:'ok',count:0,message:''},{name:'other',status:'partial',count:2,message:'Rate limited'}]})}));
 doc.ids.username.value='abc';await doc.ids['search-form'].listeners.submit({preventDefault(){}});
 assert.match(textOf(doc.ids.coverage),/archive.*Unavailable.*Connection refused/);
 assert.match(textOf(doc.ids.coverage),/search.*0 traces/);
 assert.match(textOf(doc.ids.coverage),/other.*Partial.*Rate limited/);
 assert.match(doc.ids['empty-copy'].textContent,/unavailable/i);
});
test('local import stays client-only, requires confirmation and matching search username, clears on search',async()=>{
 const doc=documentFixture();let calls=0;app.mount(doc,async()=>{calls++;return {ok:true,json:async()=>({username:'abc',results:[],warnings:[],sources:[]})};});
 doc.ids.username.value='abc';doc.ids['import-file'].files=[{name:'posts.csv',size:30,text:async()=> 'id,subreddit,title\nt3_abc123,Test,Imported'}];
 await doc.ids['import-button'].listeners.click();assert.match(doc.ids['import-message'].textContent,/confirm/i);assert.equal(calls,0);
 doc.ids['import-confirm'].checked=true;await doc.ids['import-button'].listeners.click();
 assert.equal(calls,0);assert.equal(doc.ids.results.children.length,1);assert.match(textOf(doc.ids.results),/not independently verified/);
 doc.ids.username.value='xyz';await doc.ids['import-button'].listeners.click();assert.match(doc.ids['import-message'].textContent,/username/i);
 await doc.ids['search-form'].listeners.submit({preventDefault(){}});assert.equal(calls,1);assert.equal(doc.ids.results.children.length,0);assert.match(doc.ids['import-message'].textContent,/cleared/i);
});
test('markup exposes CSV-only privacy control, sorting and coverage with mobile-safe styles',()=>{
 const html=fs.readFileSync(__dirname+'/index.html','utf8'),css=fs.readFileSync(__dirname+'/style.css','utf8');
 assert.match(html,/accept="\.csv"/);assert.match(html,/Processed in your browser\. File is not uploaded\./);
 assert.match(html,/id="sort"/);assert.match(html,/id="coverage"/);assert.match(html,/import\.js.*app\.js/s);
 assert.match(css,/\.coverage-strip/);assert.match(css,/prefers-reduced-motion/);
});
test('only permits credential-free HTTPS Reddit links',()=>{
 assert.equal(app.safeRedditURL('https://www.reddit.com/r/test/comments/abc/title/'),'https://www.reddit.com/r/test/comments/abc/title/');
 for(const url of ['javascript:alert(1)','http://reddit.com','https://reddit.com.evil.org','https://evil.org','https://user@reddit.com','/relative']) assert.equal(app.safeRedditURL(url),null);
});
test('filters classifications, subreddit and text together without mutating results',()=>{
 const rows=[{title:'First archive',subreddit:'r/Test',classification:'authored',snippet:'hello'}, {title:'Second',subreddit:'r/Other',classification:'mention',snippet:'archive'}, {title:'Third',subreddit:'r/Test',classification:'uncertain'}];
 assert.equal(app.filterResults(rows,{classification:'all',subreddit:'all',text:''}).length,3);
 assert.deepEqual(app.filterResults(rows,{classification:'authored',subreddit:'r/Test',text:'ARCHIVE'}),[rows[0]]);
 assert.equal(app.filterResults(rows,{classification:'all',subreddit:'r/Test',text:'absent'}).length,0);
 assert.equal(rows.length,3);
});
test('search client encodes username, forwards cancellation and reports API errors',async()=>{
 const signal=new AbortController().signal;
 const payload={username:'abc',results:[],warnings:[]};
 let seen;
 assert.deepEqual(await app.search('abc',signal,async(url,options)=>{seen={url,options}; return {ok:true,json:async()=>payload};}),payload);
 assert.equal(seen.url,'/api/search?username=abc'); assert.equal(seen.options.signal,signal);
 await assert.rejects(app.search('abc',signal,async()=>({ok:false,json:async()=>({error:'Provider unavailable'})})),/Provider unavailable/);
 await assert.rejects(app.search('abc',signal,async()=>({ok:true,json:async()=>({})})),/invalid response/i);
 await assert.rejects(app.search('u/abc',signal,async()=>{throw Error('should not fetch');}),/bare Reddit username/);
});
test('export retains provenance and only selected results',()=>{
 const data={username:'abc',results:[{id:'1'},{id:'2'}],warnings:['Limited index'],provider:'test',cached:false,searched_at:'2026-01-01'};
 const exported=JSON.parse(app.exportJSON(data,[data.results[0]]));
 assert.deepEqual(exported.results,[{id:'1'}]);assert.deepEqual(exported.warnings,data.warnings);assert.equal(exported.provider,'test');
});
class Element {
 constructor(){this.children=[];this.dataset={};this.style={setProperty(){}};this.value='';this.hidden=false;this.disabled=false;this.textContent='';this.listeners={};this.attrs={};this.classList={toggle(){},add(){}};}
 addEventListener(name,fn){this.listeners[name]=fn;} setAttribute(k,v){this.attrs[k]=v;}
 append(...nodes){this.children.push(...nodes);} replaceChildren(...nodes){this.children=nodes;}
 focus(){} click(){} remove(){} 
}
function documentFixture(){
 const ids=Object.fromEntries(['username','import-file','import-confirm','import-message','coverage','sort'].map(id=>[id,new Element()])); const tabs=['all','authored','mention','uncertain'].map(value=>Object.assign(new Element(),{dataset:{classification:value}}));
 const counts=['all','authored','mention','uncertain'].map(value=>Object.assign(new Element(),{dataset:{count:value}}));
 return {ids,tabs,createElement:()=>new Element(),body:new Element(),getElementById(id){return ids[id] ||= new Element();},querySelectorAll(selector){return selector==='[data-classification]'?tabs:counts;}};
}
test('UI stays idle until submit, renders real response safely, and filters counts',async()=>{
 const doc=documentFixture();let calls=0;
 app.mount(doc,async(url)=>{if(url==='/api/health')return {ok:true,json:async()=>({ok:true,provider:'test'})};calls++;return {ok:true,json:async()=>({username:'abc',results:[{id:'1',title:'<script>danger</script>',url:'javascript:alert(1)',classification:'authored',subreddit:'r/Test',snippet:'body',evidence:'by abc',source:'test'}],warnings:[],provider:'test'})};});
 assert.equal(calls,0);doc.getElementById('username').value='abc';
 await doc.ids['search-form'].listeners.submit({preventDefault(){}});
 assert.equal(calls,1);assert.equal(doc.ids.results.children.length,1);assert.equal(doc.ids.count.textContent,'1 of 1 traces');
 assert.equal(doc.ids.export.disabled,false);
 doc.tabs[2].listeners.click();assert.equal(doc.ids.results.children.length,0);assert.equal(doc.ids.count.textContent,'0 of 1 traces');
 assert.equal(doc.ids['empty-title'].textContent,'No traces match these filters.');
});
test('UI cancels a pending request and clears loading state',async()=>{
 const doc=documentFixture(); let signal;
 app.mount(doc,async(url,options)=>{if(url==='/api/health')return {ok:true,json:async()=>({ok:true})};signal=options.signal;return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(Object.assign(new Error('aborted'),{name:'AbortError'}))));});
 doc.getElementById('username').value='abc';const pending=doc.ids['search-form'].listeners.submit({preventDefault(){}});
 assert.equal(doc.ids.loading.hidden,false);doc.ids.cancel.listeners.click();await pending;
 assert.equal(signal.aborted,true);assert.equal(doc.ids.loading.hidden,true);assert.equal(doc.ids['search-button'].disabled,false);assert.equal(doc.ids['empty-title'].textContent,'Search stopped.');
});
test('browser script mounts the search form without an automatic search',()=>{
 const vm=require('node:vm');const fs=require('node:fs');const doc=documentFixture();
 vm.runInNewContext(fs.readFileSync(require.resolve('./app.js'),'utf8'),{window:{},document:doc,fetch:()=>{throw Error('No automatic fetch');},URL});
 assert.equal(typeof doc.getElementById('search-form').listeners.submit,'function');
});
test('validates a bare username without repairing invalid input',()=>{
 assert.equal(app.validateUsername('Tutyfruiity'), '');
 assert.equal(app.validateUsername('user_name-42'), '');
 for(const value of ['', 'ab', 'u/example','has space','abc<script>','a'.repeat(21)]) assert.ok(app.validateUsername(value),value);
});

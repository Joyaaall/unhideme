const {test}=require('node:test');
const assert=require('node:assert/strict');
let media;try{media=require('./media.js');}catch{media={};}
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.events={};this.hidden=false;this.open=false;this.style={};}
 append(...items){this.children.push(...items);} appendChild(x){this.children.push(x);return x;}
 setAttribute(k,v){this[k]=v;} addEventListener(k,v){this.events[k]=v;}
 remove(){this.removed=true;} showModal(){this.open=true;} close(){this.open=false;this.events.close?.();}
 focus(){this.focused=true;} click(){this.events.click?.({target:this});}
}
function doc(){return {body:new Element('body'),createElement:tag=>new Element(tag)};}
function find(root,tag){return [root,...root.children.flatMap(x=>find(x,tag))].filter(x=>x.tag===tag);}
test('media allows only credential-free HTTPS Reddit image hosts and caps galleries',()=>{
 assert.equal(typeof media.safeImageURL,'function');
 assert.equal(media.safeImageURL('https://i.redd.it/a.png'),'https://i.redd.it/a.png');
 for(const url of ['http://i.redd.it/a.png','https://user@i.redd.it/a.png','https://i.redd.it:8443/a.png','https://i.redd.it.evil.com/a.png','https://evil.com/a.png','https://i.redd.it/a.svg','javascript:x'])assert.equal(media.safeImageURL(url),null);
 assert.equal(media.cleanImages(Array.from({length:50},(_,i)=>({url:`https://i.redd.it/a${i}.png`}))).length,20);
});
test('image preview lazy loads, opens a keyboard gallery, and handles broken images',()=>{
 assert.equal(typeof media.render,'function');
 const d=doc(), row={title:'Actual post',images:[{url:'https://i.redd.it/a.png'},{url:'https://i.redd.it/b.png'}]};
 const view=media.render(d,row);const img=find(view,'img')[0];
 assert.equal(img.loading,'lazy');assert.equal(img.referrerPolicy,'no-referrer');
 const button=find(view,'button')[0];button.click();
 const dialog=find(d.body,'dialog')[0];assert.ok(dialog.open);
 assert.equal(find(dialog,'img')[0].src,'https://i.redd.it/a.png');
 dialog.events.keydown({key:'ArrowRight',preventDefault(){}});
 assert.equal(find(dialog,'img')[0].src,'https://i.redd.it/b.png');
 find(dialog,'img')[0].events.error();assert.ok(find(dialog,'p').some(p=>!p.hidden&&p.textContent?.includes('unavailable')));
 find(dialog,'button')[0].click();assert.ok(dialog.removed);
 img.events.error();assert.ok(img.hidden);assert.ok(find(view,'p').some(p=>!p.hidden&&p.textContent?.includes('unavailable')));
});
test('sensitive media makes no image request until explicitly revealed',()=>{
 assert.equal(typeof media.render,'function');
 const d=doc();const view=media.render(d,{over_18:true,spoiler:true,images:[{url:'https://i.redd.it/a.png'}]});
 assert.equal(find(view,'img').length,0);
 find(view,'button')[0].click();assert.equal(find(view,'img').length,1);
 assert.equal(media.render(d,{images:[{url:'https://evil.com/a.png'}]}),null);
});

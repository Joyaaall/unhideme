(function(root){
'use strict';
function safeImageURL(value){
 if(typeof value!=='string'||value.length>4096)return null;
 try{const url=new URL(value);return url.protocol==='https:'&&!url.username&&!url.password&&!url.port&&['i.redd.it','preview.redd.it','external-preview.redd.it'].includes(url.hostname)&&/\.(png|jpe?g|webp|gif|avif)$/i.test(url.pathname)?url.href:null;}catch{return null;}
}
function cleanImages(value){
 if(!Array.isArray(value))return [];
 const seen=new Set(),output=[];
 for(const item of value.slice(0,40)){if(!item||typeof item!=='object')continue;const url=safeImageURL(item.url);if(url&&!seen.has(url)){seen.add(url);output.push({url,preview_url:safeImageURL(item.preview_url)||url,caption:String(item.caption||'').slice(0,500)});}if(output.length===20)break;}
 return output;
}
function render(doc,row){
 const images=cleanImages(row.images);if(!images.length)return null;
 const make=(tag,text,cls)=>{const el=doc.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;};
 const wrap=make('section',undefined,'post-media');wrap.setAttribute('aria-label','Post images');
 function loadImage(img,url,fallback){
  img.referrerPolicy='no-referrer';img.decoding='async';
  img.addEventListener('load',()=>{img.hidden=false;fallback.hidden=true;});
  img.addEventListener('error',()=>{img.hidden=true;fallback.hidden=false;});
  img.src=url;
 }
 function openViewer(start,trigger){
  let position=start;
  const dialog=make('dialog',undefined,'image-viewer');dialog.setAttribute('aria-label','Post image viewer');
  const close=make('button','Close ×','viewer-close');close.type='button';
  const figure=make('figure'),img=make('img'),caption=make('figcaption'),fallback=make('p','Image unavailable. It may have been removed or blocked by Reddit.','media-fallback');fallback.hidden=true;
  const controls=make('div',undefined,'viewer-controls'),previous=make('button','← Previous'),counter=make('span'),next=make('button','Next →');
  previous.type=next.type='button';controls.append(previous,counter,next);figure.append(img,caption);dialog.append(close,figure,fallback,controls);
  function update(){const item=images[position];img.alt=`${row.title||'Reddit post'} — image ${position+1} of ${images.length}`;img.hidden=false;fallback.hidden=true;loadSource(item.url);caption.textContent=item.caption;counter.textContent=`${position+1} / ${images.length}`;previous.disabled=next.disabled=images.length<2;}
  function loadSource(url){img.src=url;}
  img.referrerPolicy='no-referrer';img.decoding='async';img.addEventListener('error',()=>{img.hidden=true;fallback.hidden=false;});img.addEventListener('load',()=>{img.hidden=false;fallback.hidden=true;});
  const move=delta=>{position=(position+delta+images.length)%images.length;update();};
  previous.addEventListener('click',()=>move(-1));next.addEventListener('click',()=>move(1));
  close.addEventListener('click',()=>dialog.close());dialog.addEventListener('close',()=>{dialog.remove();trigger.focus();});
  dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});
  dialog.addEventListener('keydown',event=>{if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();move(event.key==='ArrowRight'?1:-1);}});
  doc.body.append(dialog);update();dialog.showModal();close.focus();
 }
 function reveal(){
  const button=make('button',undefined,'media-preview');button.type='button';button.setAttribute('aria-label',`Enlarge post image${images.length>1?' gallery':''}`);
  const img=make('img');img.alt=`Image from ${row.title||'Reddit post'}`;img.loading='lazy';
  const label=make('span',images.length>1?`${images.length} images · View gallery ↗`:'Enlarge image ↗','media-label');
  const fallback=make('p','Image unavailable. Open the post to check the original.','media-fallback');fallback.hidden=true;
  loadImage(img,images[0].preview_url,fallback);button.append(img,label);button.addEventListener('click',()=>openViewer(0,button));wrap.append(button,fallback);
  if(images.length>1){const thumbs=make('div',undefined,'gallery-thumbs');images.forEach((item,index)=>{const thumb=make('button',String(index+1));thumb.type='button';thumb.setAttribute('aria-label',`View image ${index+1} of ${images.length}`);thumb.addEventListener('click',()=>openViewer(index,thumb));thumbs.append(thumb);});wrap.append(thumbs);}
 }
 if(row.over_18||row.spoiler){const warning=make('p',`${row.over_18?'NSFW':''}${row.over_18&&row.spoiler?' · ':''}${row.spoiler?'Spoiler':''} — image hidden.`,'media-warning');const show=make('button','Reveal image'+(images.length>1?'s':''),'reveal-media');show.type='button';show.addEventListener('click',()=>{show.hidden=true;warning.hidden=true;reveal();});wrap.append(warning,show);}else reveal();
 return wrap;
}
const api={safeImageURL,cleanImages,render};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.UnhidemeMedia=api;
})(typeof window!=='undefined'?window:globalThis);

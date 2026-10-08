(function(root){
'use strict';
const MAX_BYTES=5*1024*1024, MAX_ROWS=20000;
function parseCSV(text){
 const rows=[]; let row=[],field='',quoted=false,closed=false;
 text=String(text).replace(/^\uFEFF/,'');
 const finish=()=>{row.push(field);field='';closed=false; if(row.some(value=>value!==''))rows.push(row);row=[];if(rows.length>MAX_ROWS+1)throw Error('CSV exceeds the 20,000-row limit.');};
 for(let i=0;i<text.length;i++){
  const c=text[i];
  if(quoted){if(c==='"'){if(text[i+1]==='"'){field+='"';i++;}else{quoted=false;closed=true;}}else field+=c;continue;}
  if(c==='"'){if(field||closed)throw Error('Invalid CSV quote.');quoted=true;}
  else if(c===','){row.push(field);field='';closed=false;}
  else if(c==='\r'||c==='\n'){if(c==='\r'&&text[i+1]==='\n')i++;finish();}
  else {if(closed)throw Error('Unexpected text after a closing CSV quote.');field+=c;}
 }
 if(quoted)throw Error('Unclosed CSV quote.');
 if(field||row.length||closed)finish();
 return rows;
}
function dateUTC(value){
 if(value===undefined||value===null||String(value).trim()==='')return null;
 let text=String(value).trim();
 if(/^\d+(\.\d+)?$/.test(text)){const n=Number(text),seconds=n>1e12?n/1000:n;return Number.isFinite(seconds)&&seconds>=0&&seconds<=253402300799?seconds:null;}
 text=text.replace(/\s+UTC$/i,'Z').replace(/^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})/,'$1T$2');
 if(/^\d{4}-\d{2}-\d{2}$/.test(text))text+='T00:00:00Z';
 else if(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(text))text+='Z';
 if(!/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:?\d{2})$/i.test(text))return null;
 const n=Date.parse(text);return Number.isFinite(n)?n/1000:null;
}
function validateFile(file){if(!file||! /\.csv$/i.test(file.name))throw Error('Choose a .csv file only. ZIP files are not processed.');if(file.size>MAX_BYTES)throw Error('CSV exceeds the 5 MB limit.');}
function importPosts(text,username,confirmed){
 if(!confirmed)throw Error('Please confirm this is your export for the entered username.');
 if(!/^[A-Za-z0-9_-]{3,20}$/.test(username))throw Error('Enter a valid bare Reddit username.');
 if(new TextEncoder().encode(text).length>MAX_BYTES)throw Error('CSV exceeds the 5 MB limit.');
 const rows=parseCSV(text);if(rows.length<2)throw Error('No valid posts found in this CSV.');
 const headers=rows.shift().map(h=>h.trim().toLowerCase());
 if(new Set(headers).size!==headers.length)throw Error('Duplicate CSV headers make this export ambiguous.');
 const get=(row,...names)=>{for(const name of names){const i=headers.indexOf(name);if(i>=0&&row[i]?.trim())return row[i].trim();}return '';};
 const results=[];let skipped=0;
 for(const row of rows){
  if(row.length!==headers.length){skipped++;continue;}
  const author=get(row,'username','author','user');if(author&&author.toLowerCase()!==username.toLowerCase())throw Error('Export username does not match the entered username.');
  let id=get(row,'post_id','id','name'),sub=get(row,'subreddit').replace(/^r\//,'');const permalink=get(row,'permalink','link');let url;
  if(permalink){
   try{const u=new URL(permalink,'https://www.reddit.com');const match=u.pathname.match(/^\/r\/([A-Za-z0-9_]{1,21})\/comments\/([a-z0-9]+)(?:\/[^/]+)?\/?$/i);
    if(u.protocol!=='https:'||u.username||u.password||u.port||!(u.hostname==='reddit.com'||u.hostname.endsWith('.reddit.com'))||!match)throw Error();
    if(id&&id.replace(/^t3_/,'').toLowerCase()!==match[2].toLowerCase())throw Error();
    if(sub&&sub.toLowerCase()!==match[1].toLowerCase())throw Error();
    id=match[2].toLowerCase();sub=match[1];url='https://www.reddit.com'+u.pathname;
   }catch{skipped++;continue;}
  }else{if(!/^t3_[a-z0-9]+$/i.test(id)||! /^[A-Za-z0-9_]{1,21}$/.test(sub)){skipped++;continue;}id=id.slice(3).toLowerCase();url=`https://www.reddit.com/r/${sub}/comments/${id}/`;}
  const created=dateUTC(get(row,'created_utc','date','timestamp'));
  results.push({id,title:get(row,'title')||'Untitled imported post',url,subreddit:sub,snippet:get(row,'body','selftext'),classification:'authored',evidence:'User-supplied account export; not independently verified.',source:'local-import',sources:['local-import'],evidence_strength:'account-export',...(created===null?{}:{created_utc:created})});
 }
 if(!results.length)throw Error('No valid Reddit posts found. Supply a Reddit post permalink or a t3_ ID and subreddit; outbound URLs and comments are not accepted.');
 const warnings=['Local import is self-supplied account data; association with u/'+username+' is confirmed by you, not independently verified.'];
 if(skipped)warnings.push(`${skipped} invalid or ambiguous rows skipped (only Reddit posts are accepted).`);
 return {results:mergeResults([],results),warnings};
}
function mergeResults(existing,imports){
 const output=existing.map(row=>({...row}));const positions=new Map(output.map((row,i)=>[String(row.id).replace(/^t3_/,'').toLowerCase(),i]));
 for(const row of imports){const id=String(row.id).replace(/^t3_/,'').toLowerCase();if(positions.has(id)){const current=output[positions.get(id)];current.sources=[...new Set([...(current.sources||[current.source]).filter(Boolean),...(row.sources||[row.source]).filter(Boolean)])];current.import_provenance={...row};if(current.created_utc==null&&row.created_utc!=null)current.created_utc=row.created_utc;}else{positions.set(id,output.length);output.push({...row});}}
 return output;
}
const api={parseCSV,dateUTC,validateFile,importPosts,mergeResults,MAX_BYTES,MAX_ROWS};
if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.ThreadtraceImport=api;
})(typeof window!=='undefined'?window:globalThis);

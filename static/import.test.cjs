const {test}=require('node:test');
const assert=require('node:assert/strict');
let imp; try { imp=require('./import.js'); } catch { imp={}; }
test('CSV handles BOM, CRLF, quoted commas, escaped quotes and multiline fields',()=>{
 assert.equal(typeof imp.parseCSV,'function');
 assert.deepEqual(imp.parseCSV('\ufeffid,title,body\r\na,"Hello, ""world""","line1\r\nline2"\r\n'),[['id','title','body'],['a','Hello, "world"','line1\r\nline2']]);
 assert.throws(()=>imp.parseCSV('id,title\na,"broken'),/quote/i);
});
test('post import validates safe post links, UTC dates and self-supplied provenance',()=>{
 assert.equal(typeof imp.importPosts,'function');
 const result=imp.importPosts('name,permalink,date,subreddit,title,url,selftext\r\nt3_abc123,/r/Test/comments/abc123/title/,2024-01-02 03:04:05 UTC,Test,Hello,https://evil.org,Body\r\nt3_def456,,2024-01-03T00:00:00,Test,Other,https://evil.org,', 'example',true);
 assert.equal(result.results.length,2);
 assert.equal(result.results[0].created_utc,1704164645);
 assert.equal(result.results[0].subreddit,'Test');
 assert.equal(result.results[1].url,'https://www.reddit.com/r/Test/comments/def456/');
 assert.equal(result.results[0].evidence_strength,'account-export');
 assert.deepEqual(result.results[0].sources,['local-import']);
 assert.match(result.results[0].evidence,/not independently verified/);
 assert.match(result.warnings.join(' '),/self-supplied/i);
});
test('import requires confirmed username and refuses comment/nonreddit links and bad files',()=>{
 assert.throws(()=>imp.importPosts('id,subreddit\nt3_abc,Test','example',false),/confirm/i);
 assert.throws(()=>imp.importPosts('id,subreddit\nt3_abc,Test','u/example',true),/username/i);
 for(const csv of ['id,permalink,subreddit\nt3_abc,https://evil.org/r/Test/comments/abc/,Test','id,permalink,subreddit\nt3_abc,/r/Test/comments/abc/title/def/,Test','id,subreddit\nt1_abc,Test','id,subreddit,username\nt3_abc,Test,someone_else']) assert.throws(()=>imp.importPosts(csv,'example',true),/valid|match|post/i);
 assert.throws(()=>imp.validateFile({name:'posts.zip',size:1}),/\.csv/i);
 assert.throws(()=>imp.validateFile({name:'posts.csv',size:5*1024*1024+1}),/5 MB/i);
 assert.throws(()=>imp.parseCSV('id\n'+Array(20002).fill('abc').join('\n')),/20,000/);
});
test('UTC timestamps and unknown dates are explicit, CSV row widths cannot shift identity',()=>{
 assert.equal(imp.dateUTC('2024-01-03T00:00:00'),imp.dateUTC('2024-01-03T00:00:00Z'));
 for(const value of ['',null,undefined,'January 3, 2024','nonsense','999999999999999999999999'])assert.equal(imp.dateUTC(value),null);
 assert.throws(()=>imp.importPosts('id,subreddit,title\nt3_abc,Test,Hello,unexpected','example',true),/valid/i);
});
test('merging deduplicates normalized post IDs while preserving archive and import provenance',()=>{
 assert.equal(typeof imp.mergeResults,'function');
 const a={id:'t3_abc',source:'archive',sources:['archive'],evidence:'archive evidence'};
 const b={id:'abc',source:'local-import',sources:['local-import'],evidence:'self-supplied',evidence_strength:'account-export'};
 const merged=imp.mergeResults([a],[b]);
 assert.equal(merged.length,1);assert.deepEqual(merged[0].sources,['archive','local-import']);
 assert.equal(merged[0].evidence,'archive evidence');assert.equal(merged[0].import_provenance.evidence,'self-supplied');
 assert.equal(a.import_provenance,undefined);
});

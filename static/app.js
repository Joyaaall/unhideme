(function (root) {
'use strict';
const imports = typeof module !== 'undefined' && module.exports ? require('./import.js') : root.ThreadtraceImport;
const media = typeof module !== 'undefined' && module.exports ? require('./media.js') : root.UnhidemeMedia;
function sortResults(results, mode) {
 const rows = [...results]; if (!['newest','oldest'].includes(mode)) return rows;
 return rows.sort((a,b) => {const x=imports.dateUTC(a.created_utc),y=imports.dateUTC(b.created_utc); return x===null ? (y===null?0:1) : y===null ? -1 : mode==='newest'?y-x:x-y;});
}
function validateUsername(value) {
 return /^[A-Za-z0-9_-]{3,20}$/.test(value) ? '' : 'Use a bare Reddit username: 3–20 letters, numbers, underscores or hyphens. No u/ prefix.';
}
function safeRedditURL(value) {
 try {
  const url = new URL(value);
  return url.protocol === 'https:' && !url.username && !url.password && !url.port && (url.hostname === 'reddit.com' || url.hostname.endsWith('.reddit.com')) ? url.href : null;
 } catch { return null; }
}
function filterResults(results, filters) {
 const needle = (filters.text || '').trim().toLowerCase();
 return results.filter(row => (filters.classification === 'all' || row.classification === filters.classification) && (filters.subreddit === 'all' || row.subreddit === filters.subreddit) && [row.title, row.snippet, row.subreddit, row.evidence].filter(Boolean).join(' ').toLowerCase().includes(needle));
}
async function search(username, signal, fetcher = fetch) {
 const error = validateUsername(username);
 if (error) throw new Error(error);
 const response = await fetcher('/api/search?username=' + encodeURIComponent(username), {signal, headers:{Accept:'application/json'}});
 let data;
 try { data = await response.json(); } catch { throw new Error('The server returned an unreadable response. Please try again.'); }
 if (!response.ok) throw new Error(data.error || 'Search is unavailable. Please try again.');
 if (!data || !Array.isArray(data.results)) throw new Error('The server returned an invalid response. Please try again.');
 return data;
}
function exportJSON(data, results) { return JSON.stringify({...data, results}, null, 2); }
function mount(doc, fetcher = fetch) {
 const $ = id => doc.getElementById(id);
 const make = (tag, text, className) => { const node = doc.createElement(tag); if (text !== undefined) node.textContent = String(text); if (className) node.className = className; return node; };
 const state = {data:null, visible:[], classification:'all', controller:null, generation:0, importing:false};
 const tabs = [...doc.querySelectorAll('[data-classification]')];
 function empty(kicker, title, copy, error = false) {
  $('empty').hidden = false; $('empty-kicker').textContent = kicker; $('empty-title').textContent = title; $('empty-copy').textContent = copy; $('empty').classList.toggle('error-state', error);
 }
 function busy(value) {
  $('loading').hidden = !value; $('search-button').disabled = value; $('username').disabled = value;
  $('filters').disabled = value || !state.data; $('export').disabled = value || !state.visible.length;
  $('import-button').disabled = value || state.importing; $('import-file').disabled = value || state.importing; $('import-confirm').disabled = value || state.importing;
  $('result-region').setAttribute('aria-busy', String(value));
 }
 function resetFilters() {
  state.classification = 'all'; $('subreddit').value = 'all'; $('text-filter').value = ''; $('sort').value = 'relevance';
  tabs.forEach(tab => tab.setAttribute('aria-pressed', String(tab.dataset.classification === 'all')));
 }
 function render() {
  if (!state.data) return;
  state.visible = sortResults(filterResults(state.data.results, {classification:state.classification, subreddit:$('subreddit').value, text:$('text-filter').value}), $('sort').value);
  renderCoverage();
  $('results').replaceChildren(); $('empty').hidden = state.visible.length > 0;
  $('count').textContent = `${state.visible.length} of ${state.data.results.length} traces`;
  $('status').textContent = $('count').textContent;
  $('export').disabled = !state.visible.length;
  doc.querySelectorAll('[data-count]').forEach(node => { node.textContent = String(node.dataset.count === 'all' ? state.data.results.length : state.data.results.filter(row => row.classification === node.dataset.count).length); });
  if (!state.visible.length) {
   if (state.data.results.length) empty('REFINE THE TRAIL', 'No traces match these filters.', 'Try another keyword, choose a different classification, or reset the filters.');
   else if ((state.data.sources || []).some(source => source.status !== 'ok')) empty('COVERAGE IS INCOMPLETE', 'No traces returned by available sources.', 'Some sources were unavailable or only partially searched. Review the coverage details above. No results is not evidence of no posts.');
   else empty('NOTHING IN THE INDEX', 'No indexed traces found.', 'Search indexes are incomplete. No results does not mean this account has no posts. Check the username or try again later.');
  }
  state.visible.forEach((row, index) => {
   const article = make('article', undefined, 'result-row'); article.style.setProperty('--delay', `${Math.min(index, 8) * 35}ms`);
   const meta = make('div', undefined, 'row-meta');
   meta.append(make('span', String(index + 1).padStart(2, '0'), 'row-number'), make('span', row.subreddit || 'Subreddit unknown'), make('span', row.classification || 'uncertain', 'classification ' + (['authored','mention','uncertain'].includes(row.classification) ? row.classification : 'uncertain')));
   const timestamp = imports ? imports.dateUTC(row.created_utc) : null;
   meta.append(make('span', timestamp === null ? 'Date unknown' : new Date(timestamp*1000).toISOString().slice(0,10) + ' UTC', 'row-date'));
   const heading = make('h3'); const url = safeRedditURL(row.url);
   if (url) { const link = make('a', undefined, 'result-title'); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.append(make('span', row.title || 'Untitled Reddit result'), make('span', '↗', 'arrow')); heading.append(link); }
   else heading.textContent = row.title || 'Untitled Reddit result';
   article.append(meta, heading, make('p', row.snippet || 'No preview was supplied by the search index.', 'snippet'));
   if (media && row.images?.length) { const preview = media.render(doc, row); if (preview) article.append(preview); }
   const detail = make('details'); const summary = make('summary', 'Inspect evidence'); summary.append(make('span', '+')); const body = make('div');
   const evidence = typeof row.evidence === 'object' ? JSON.stringify(row.evidence) : row.evidence;
   body.append(make('p', evidence || 'No additional author evidence was supplied.'), make('p', 'Sources: ' + ((row.sources && row.sources.length ? row.sources : [row.source || state.data.provider || 'Search index']).join(', '))));
   if (row.import_provenance) body.append(make('p', row.import_provenance.evidence));
   if (row.evidence_strength) body.append(make('p', 'Evidence strength: '+row.evidence_strength));
   if (row.classification === 'authored' && row.evidence_strength !== 'account-export') body.append(make('p', 'Index or archive author evidence. Not verified directly by Reddit.'));
   if (!url) body.append(make('p', 'Link unavailable: this result did not provide a safe HTTPS Reddit URL.', 'unsafe-link'));
   detail.append(summary, body); article.append(detail); $('results').append(article);
  });
 }
 $('search-form').addEventListener('submit', async event => {
  event.preventDefault(); if (state.controller || state.importing) return;
  const username = $('username').value; const error = validateUsername(username);
  $('validation').textContent = error; $('validation').hidden = !error; $('username').setAttribute('aria-invalid', String(Boolean(error)));
  if (error) { $('username').focus(); return; }
  const controller = new AbortController(); state.controller = controller; const generation = ++state.generation;
  state.data = null; state.visible = []; $('import-file').value = ''; $('import-confirm').checked = false; $('import-message').textContent = 'New search: local imports cleared. Re-import after this search if needed.'; $('coverage').replaceChildren(); $('coverage').hidden = true; resetFilters(); $('results').replaceChildren(); $('warnings').replaceChildren(); $('warnings').hidden = true; $('provenance').hidden = true; $('empty').hidden = true;
  $('count').textContent = 'Searching for u/' + username; $('status').textContent = 'Search started. This can take up to 90 seconds.';
  doc.querySelectorAll('[data-count]').forEach(node => { node.textContent = '—'; });
  busy(true); let timedOut = false;
  const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 105000);
  try {
   const data = await search(username, controller.signal, fetcher);
   if (generation !== state.generation || controller.signal.aborted) return;
   state.data = {...data,username:data.username || username};
   $('subreddit').replaceChildren(); const all = make('option', 'All subreddits'); all.value = 'all'; $('subreddit').append(all);
   [...new Set(data.results.map(row => row.subreddit).filter(Boolean))].sort().forEach(name => { const option = make('option', name); option.value = name; $('subreddit').append(option); }); $('subreddit').value = 'all';
   const warnings = Array.isArray(data.warnings) ? data.warnings : [];
   warnings.forEach(warning => $('warnings').append(make('p', warning))); $('warnings').hidden = !warnings.length;
   const date = new Date(data.searched_at); const searched = Number.isNaN(date.getTime()) ? 'Time not supplied' : date.toLocaleString();
   $('provenance').textContent = `${data.provider || 'Search index'} / ${data.cached ? 'Cached search' : 'Fresh search'} / ${searched}`; $('provenance').hidden = false;
   render();
  } catch (error) {
   if (generation !== state.generation) return;
   if (controller.signal.aborted) empty('THE DESK IS STILL HERE', timedOut ? 'The search took too long.' : 'Search stopped.', timedOut ? 'The provider did not finish in time. Please try again.' : 'Nothing has been added to your index. Start a new search whenever you’re ready.');
   else empty('A BREAK IN THE TRAIL', 'Couldn’t complete this search.', error.message || 'Check your connection and try again.', true);
   $('count').textContent = 'No search results'; $('status').textContent = $('empty-title').textContent + ' ' + $('empty-copy').textContent;
  } finally { clearTimeout(timeout); if (generation === state.generation) { state.controller = null; busy(false); } }
 });
 function renderCoverage() {
  const sources = Array.isArray(state.data.sources) ? state.data.sources : [];
  $('coverage').replaceChildren(); $('coverage').hidden = !sources.length;
  sources.forEach(source => {
   const item=make('div',undefined,'coverage-source '+(source.status==='ok'?'ok':source.status==='partial'?'partial':'error'));
   const label=source.status==='ok'?`${source.count ?? 0} traces`:source.status==='partial'?`Partial · ${source.count ?? 0} traces`:'Unavailable';
   item.append(make('strong',source.name || 'Unnamed source'),make('span',label));
   if(source.message)item.append(make('p',typeof source.message==='object'?JSON.stringify(source.message):source.message));
   $('coverage').append(item);
  });
 }
 function refreshOptions() {
  const previous=$('subreddit').value; $('subreddit').replaceChildren(); const all=make('option','All subreddits');all.value='all';$('subreddit').append(all);
  [...new Set(state.data.results.map(row=>row.subreddit).filter(Boolean))].sort().forEach(name=>{const option=make('option',name);option.value=name;$('subreddit').append(option);});
  $('subreddit').value=state.data.results.some(row=>row.subreddit===previous)?previous:'all';
  $('warnings').replaceChildren(); (state.data.warnings || []).forEach(warning=>$('warnings').append(make('p',warning)));$('warnings').hidden=!(state.data.warnings || []).length;
 }
 $('import-button').addEventListener('click',async()=>{
  if(state.controller || state.importing)return;
  const username=$('username').value, generation=state.generation;
  try {
   if(validateUsername(username))throw Error(validateUsername(username));
   if(!$('import-confirm').checked)throw Error('Please confirm this is your export for the entered username.');
   if(state.data && state.data.username.toLowerCase()!==username.toLowerCase())throw Error('The entered username differs from the current results. Start a new search before importing for another username.');
   const file=$('import-file').files?.[0]; imports.validateFile(file);
   state.importing=true;busy(true); const text=await file.text();
   if(generation!==state.generation || $('username').value!==username || !$('import-confirm').checked)throw Error('Username or confirmation changed while reading. Please confirm and import again.');
   const imported=imports.importPosts(text,username,true);
   const data=state.data || {username,results:[],warnings:[],sources:[],provider:'Local account export',cached:false,searched_at:null};
   state.data={...data,results:imports.mergeResults(data.results,imported.results),warnings:[...new Set([...(data.warnings||[]),...imported.warnings])],sources:[...(data.sources || []).filter(source=>source.name!=='local-import'),{name:'local-import',status:'ok',count:imports.mergeResults(data.results,imported.results).filter(row=>row.sources?.includes('local-import')).length,message:'Self-supplied; not independently verified.'}]};
   refreshOptions();render();$('import-message').textContent=`Imported ${imported.results.length} posts for u/${username}. Deduplicated by post ID. File remains in memory only.`;
   $('provenance').textContent='u/'+username+' / '+(state.data.provider || 'Search index')+' / Includes self-supplied local import';$('provenance').hidden=false;
   $('import-file').value=''; $('status').textContent=$('import-message').textContent;
  } catch(error) {$('import-message').textContent=error.message || 'Could not read this CSV.';}
  finally {state.importing=false;busy(Boolean(state.controller));}
 });
 $('cancel').addEventListener('click', () => { if (state.controller) state.controller.abort(); });
 tabs.forEach(tab => tab.addEventListener('click', () => { state.classification = tab.dataset.classification; tabs.forEach(other => other.setAttribute('aria-pressed', String(other === tab))); render(); }));
 $('sort').addEventListener('change', render); $('subreddit').addEventListener('change', render); $('text-filter').addEventListener('input', render);
 $('reset-filters').addEventListener('click', () => { resetFilters(); render(); });
 $('export').addEventListener('click', () => {
  if (!state.data || !state.visible.length) return;
  const blob = new Blob([exportJSON(state.data, state.visible)], {type:'application/json'}); const url = URL.createObjectURL(blob); const link = make('a');
  link.href = url; link.download = 'unhideme-' + $('username').value.replace(/[^A-Za-z0-9_-]/g, '') + '.json'; doc.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  $('status').textContent = 'Exported ' + state.visible.length + ' filtered results as JSON.';
 });
}
const api = {sortResults, validateUsername, safeRedditURL, filterResults, search, exportJSON, mount};
if (typeof module !== 'undefined' && module.exports) module.exports = api;
else { root.Threadtrace = api; mount(document); }
})(typeof window !== 'undefined' ? window : globalThis);

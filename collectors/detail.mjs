// Run through ego-browser's documented Node runtime; never exports browser cookies.
import fs from 'node:fs/promises';
import path from 'node:path';

function number(value) {
  const text=String(value??'').replaceAll(',','').trim();
  if(/^\d+$/.test(text))return Number(text);
  // Rounded display numbers must not be represented as exact counts.
  throw new Error('Missing or rounded engagement count: '+text);
}

export async function collect({page,targets,outputDirectory,keyword='美国信用卡'}) {
  if(!path.isAbsolute(outputDirectory))throw Error('Use an absolute output directory.');
  await fs.mkdir(path.join(outputDirectory,'posts'),{recursive:true});
  await fs.mkdir(path.join(outputDirectory,'images'),{recursive:true});
  for(const target of targets){
    if(!/^https:\/\/www\.xiaohongshu\.com\//.test(target.url)||!/^[a-f0-9]{24}$/.test(target.id))throw Error('Invalid observed target.');
    try{await page.goto(target.url)}catch(error){if(!String(error).includes('navigation committed'))throw error;}
    await page.waitForFunction(id=>{
      const note=window.__INITIAL_STATE__?.note?.noteDetailMap?.[id]?.note;
      return note?.title&&document.querySelector('#detail-title')?.textContent.trim()===note.title.trim();
    },target.id,{timeout:12000});
    const raw=await page.evaluate(id=>{
      const note=window.__INITIAL_STATE__.note.noteDetailMap[id].note;
      const gallery=[...new Set(Array.from(document.querySelectorAll('.note-slider-img img')).map(n=>n.src))];
      return {id,title:document.querySelector('#detail-title').innerText,body:document.querySelector('#detail-desc')?.innerText||note.desc,author:note.user?.nickname||document.querySelector('.author-container .username')?.textContent,author_id:note.user?.userId||'',published_at_ms:note.time,last_updated_at_ms:note.lastUpdateTime,date:document.querySelector('.note-content .date')?.innerText,likes:document.querySelector('.interact-container .like-wrapper .count')?.innerText,saves:document.querySelector('.interact-container .collect-wrapper .count')?.innerText,comments:document.querySelector('.interact-container .chat-wrapper .count')?.innerText,images:gallery,type:note.type==='video'?'video':'image',capturedAt:new Date().toISOString()};
    },target.id);
    if(!Number.isFinite(raw.published_at_ms))throw Error('Publication timestamp not supplied by the detail page.');
    if(raw.author_id==='6211936c00000000100056ae'||raw.author==='北美撸卡MaxWorth'){console.log({excluded:target.id});continue;}
    raw.likes=number(raw.likes);raw.saves=number(raw.saves);raw.comments=number(raw.comments);
    raw.url=target.url;raw.keywords=[keyword];raw.publication_basis='detail-page';
    raw.published_date=new Date(raw.published_at_ms).toLocaleDateString('en-CA',{timeZone:'America/Los_Angeles'});
    raw.files=[];
    const urls=[target.img||raw.images[0],...raw.images].filter(Boolean);
    for(const [index,url] of urls.entries()){
      const response=await fetch(url,{signal:AbortSignal.timeout(15000)});
      if(!response.ok)throw Error('Image download failed: '+response.status);
      const name='images/'+raw.id+'-'+(index===0?'cover':index)+'.webp';
      await fs.writeFile(path.join(outputDirectory,name),new Uint8Array(await response.arrayBuffer()));raw.files.push(name);
    }
    await fs.writeFile(path.join(outputDirectory,'posts',raw.id+'.json'),JSON.stringify(raw,null,2));
    console.log({id:raw.id,title:raw.title,author:raw.author,published_date:raw.published_date,likes:raw.likes,saves:raw.saves,comments:raw.comments,images:raw.files.length,body:raw.body.slice(0,1300)});
  }
}

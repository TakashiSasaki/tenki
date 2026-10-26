import {mkdir, copyFile, rm} from 'node:fs/promises';
await rm('dist', {recursive:true,force:true});
await mkdir('dist');
for (const file of ['index.html','app.js','core.js','style.css']) await copyFile(`static/${file}`,`dist/${file}`);
console.log('Static artifact: dist/ (4 files, no runtime server)');

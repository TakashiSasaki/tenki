import {mkdir, cp, rm} from 'node:fs/promises';
await rm('dist', {recursive:true,force:true});
await mkdir('dist');
await cp('static', 'dist', {recursive:true});
console.log('Static artifact: dist/ (static files, no runtime server)');

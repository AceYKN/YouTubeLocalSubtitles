import { build } from 'vite';
import { cp, mkdir } from 'node:fs/promises';
import path from 'node:path';

for (const name of ['main', 'content', 'background', 'offscreen', 'options', 'capture-worklet']) {
  await build({
    configFile: false,
    build: {
      outDir: 'dist', emptyOutDir: name === 'main', sourcemap: false,
      lib: { entry: path.resolve(`extension/src/${name}.ts`), name: `YTLocal_${name.replaceAll('-', '_')}`, formats: ['iife'], fileName: () => `${name}.js` },
    },
  });
}
await mkdir('dist', { recursive: true });
for (const file of ['manifest.json', 'offscreen.html', 'options.html']) {
  await cp(`extension/${file}`, `dist/${file}`);
}

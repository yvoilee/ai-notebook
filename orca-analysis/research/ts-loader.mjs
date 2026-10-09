import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
export async function resolve(specifier, context, nextResolve) {
  if (specifier.startsWith('.') && context.parentURL?.startsWith('file:')) {
    const u = new URL(specifier, context.parentURL);
    if (!/\.[a-z]+$/i.test(u.pathname) && existsSync(fileURLToPath(u)+'.ts')) return {url:u.href+'.ts',shortCircuit:true};
  }
  return nextResolve(specifier, context);
}

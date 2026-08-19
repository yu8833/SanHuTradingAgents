// 统计模板中实际用到的 Element Plus 图标，生成 main.ts 图标白名单。
// 用法：docker run --rm -v $PWD/frontend:/app -w /app node:22-alpine node scripts/extract-icons.mjs
import { readFileSync, readdirSync, statSync } from 'fs'
import { join, resolve, extname } from 'path'
import * as icons from '@element-plus/icons-vue'

const iconNames = new Set(Object.keys(icons))
const srcDir = resolve('src')

function walk(d, out = []) {
  for (const e of readdirSync(d)) {
    const p = join(d, e)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (extname(p) === '.vue') out.push(p)
  }
  return out
}

const files = walk(srcDir)
const used = new Set()

for (const f of files) {
  const src = readFileSync(f, 'utf8')
  // <el-icon><XxxIcon /></el-icon> 或 <XxxIcon .../> 的 PascalCase 标签
  const reTag = /<(?:el-icon\s*\/?>\s*)?([A-Z][A-Za-z0-9]*)(?=[\s/>])/g
  let m
  while ((m = reTag.exec(src))) if (iconNames.has(m[1])) used.add(m[1])
  // 字符串字面量引用（component :is 动态图标）
  const reStr = /['"]((?:[A-Z][A-Za-z0-9]*Icon|[A-Z][A-Za-z0-9]*))['"]/g
  let s
  while ((s = reStr.exec(src))) if (iconNames.has(s[1])) used.add(s[1])
}

const list = [...used].sort()
console.log('total icons:', iconNames.size)
console.log('used icons:', list.length)
console.log(JSON.stringify(list, null, 2))

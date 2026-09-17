/**
 * 构建后静态资源 gzip 预压缩（零依赖，Node 内置 zlib）。
 * 逐个文本类产物生成 .gz 文件，配合 nginx `gzip_static on` 直接下发预压缩文件，
 * 免去每个浏览器首访时的服务端实时压缩（echarts≈1MB / element-plus≈500KB 收益明显）。
 */
const fs = require('fs')
const path = require('path')
const zlib = require('zlib')

const DIST = path.resolve(__dirname, '../dist')
// 参与 gzip 的扩展名（与 nginx gzip_types 对齐）
const EXT = new Set(['.js', '.css', '.json', '.svg', '.html', '.txt'])
const MIN_SIZE = 100 // 小于该字节数不值得压缩

let generated = 0
let skipped = 0

function walk(dir) {
  for (const name of fs.readdirSync(dir)) {
    const fp = path.join(dir, name)
    const stat = fs.statSync(fp)
    if (stat.isDirectory()) {
      walk(fp)
      continue
    }
    if (!EXT.has(path.extname(fp)) || fp.endsWith('.gz')) {
      continue
    }
    if (stat.size < MIN_SIZE) {
      skipped++
      continue
    }
    const content = fs.readFileSync(fp)
    const gz = zlib.gzipSync(content, { level: 9 })
    // 压缩后不减小则不产出（避免无意义文件）
    if (gz.length >= content.length) {
      skipped++
      continue
    }
    fs.writeFileSync(fp + '.gz', gz)
    generated++
  }
}

walk(DIST)
console.log(`[compress-dist] 生成 ${generated} 个 .gz 文件（跳过 ${skipped}）`)
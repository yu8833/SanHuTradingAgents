<template>
  <div class="vibe-overview">
    <!-- 页面标题 -->
    <div class="page-header">
      <div class="title-block">
        <h1 class="page-title">
          <el-icon class="title-icon"><DataAnalysis /></el-icon>
          {{ today }} · 大盘看板
        </h1>
        <p class="page-subtitle">大盘指数 / 全球市场 / 市场情绪一屏看全</p>
      </div>
      <el-button type="primary" plain :icon="Refresh" :loading="loading" @click="loadAll">
        刷新
      </el-button>
    </div>

    <!-- 大盘指数 -->
    <section class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><DataLine /></el-icon> 大盘指数</span>
        <span v-if="loading" class="block-hint">
          <el-icon class="is-loading"><Loading /></el-icon> 加载中
        </span>
      </div>
      <div class="grid grid-4">
        <el-card
          v-for="item in indices"
          :key="item.name"
          shadow="never"
          class="idx-card"
        >
          <div class="idx-name">{{ item.name }}</div>
          <div class="idx-price">{{ formatPrice(item.price) }}</div>
          <div class="idx-change" :class="colorClass(item.change_pct)">
            <span class="pct">{{ sign(item.change_pct) }}{{ formatPct(item.change_pct) }}%</span>
            <span class="amt">{{ sign(item.change_amt) }}{{ formatPrice(item.change_amt) }}</span>
          </div>
        </el-card>
        <el-card v-if="!indices.length && !loading" shadow="never" class="idx-card empty-card">
          <el-empty :image-size="48" description="暂无指数数据" />
        </el-card>
      </div>
    </section>

    <!-- 全球市场 -->
    <section class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><DataLine /></el-icon> 全球市场</span>
      </div>
      <div class="grid grid-5">
        <el-card
          v-for="item in globalIndices"
          :key="item.key"
          shadow="never"
          class="idx-card"
        >
          <div class="idx-name">
            {{ item.name }}<span class="region">{{ item.region }}</span>
          </div>
          <div class="idx-price">{{ item.price == null ? '—' : formatPrice(item.price) }}</div>
          <div class="idx-change" :class="colorClass(item.change_pct)">
            {{ item.change_pct == null ? '—' : sign(item.change_pct) + formatPct(item.change_pct) + '%' }}
          </div>
        </el-card>
        <el-card v-if="!globalIndices.length && !loading" shadow="never" class="idx-card empty-card">
          <el-empty :image-size="48" description="暂无全球指数" />
        </el-card>
      </div>
    </section>

    <!-- 关注股票 -->
    <section class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><Star /></el-icon> 关注股票</span>
        <div class="watch-input-wrap">
          <el-input
            v-model="watchInput"
            placeholder="输入6位代码，回车添加"
            maxlength="6"
            style="width: 200px"
            size="small"
            @keyup.enter="addWatch"
          />
          <el-button size="small" type="primary" @click="addWatch">添加</el-button>
        </div>
      </div>
      <div v-loading="watchLoading" class="grid grid-watch">
        <el-card
          v-for="q in watchQuotes"
          :key="q.code"
          shadow="never"
          class="watch-card"
        >
          <div class="watch-head">
            <span class="watch-name">{{ q.name || q.code }}</span>
            <el-icon class="watch-del" @click="removeWatch(q.code)"><Close /></el-icon>
          </div>
          <div class="watch-price">{{ q.price == null ? '—' : q.price.toFixed(2) }}</div>
          <div class="watch-change" :class="colorClass(q.change_pct)">
            {{ q.change_pct == null ? '—' : sign(q.change_pct) + formatPct(q.change_pct) + '%' }}
          </div>
        </el-card>
        <div v-if="watchlist.length === 0" class="watch-placeholder">
          添加关注的股票，实时跟踪行情
        </div>
      </div>
    </section>

    <!-- AI 当日复盘 -->
    <section class="block">
      <el-card shadow="never" class="review-card">
        <template #header>
          <div class="card-head">
            <span class="block-title"><el-icon><MagicStick /></el-icon> AI 当日复盘</span>
            <div class="head-actions">
              <el-button
                v-if="!reviewing && !reviewText"
                type="primary"
                :icon="MagicStick"
                @click="runReview"
              >
                让 AI 复盘今天
              </el-button>
              <el-button v-if="reviewing" type="info" loading disabled>
                AI 复盘中…
              </el-button>
              <el-button
                v-if="reviewText && !reviewing"
                type="success"
                :icon="EditPen"
                @click="saveReview"
              >
                存入沉淀
              </el-button>
            </div>
          </div>
        </template>
        <div class="review-body">
          <div v-if="!reviewText && !reviewing" class="placeholder">
            点击「让 AI 复盘今天」，AI 会结合今日大盘、情绪与板块资金，输出一段简明当日复盘。
          </div>
          <div v-if="reviewText" class="review-text">
            {{ reviewText }}<span v-if="reviewing" class="cursor">▍</span>
          </div>
        </div>
      </el-card>
    </section>

    <!-- 市场情绪 -->
    <section class="block">
      <div class="block-head">
        <span class="block-title"><el-icon><Odometer /></el-icon> 市场情绪</span>
        <span v-if="sentiment?.date" class="block-hint">数据日期：{{ sentiment.date }}</span>
      </div>
      <div class="sentiment-wrap">
        <div class="mood-row">
          <el-card shadow="never" class="mood-card">
            <div class="mood-label">大盘宽度</div>
            <div class="mood-value" :class="breadthClass">{{ sentiment?.breadth || '—' }}</div>
            <div class="mood-tags">
              <span
                v-for="l in ['冰点','偏弱','中性','偏强','普涨']"
                :key="l"
                class="tag"
                :class="{ active: sentiment?.breadth === l }"
              >{{ l }}</span>
            </div>
          </el-card>
          <el-card shadow="never" class="mood-card">
            <div class="mood-label">题材投机</div>
            <div class="mood-value" :class="specClass">{{ sentiment?.speculation || '—' }}</div>
            <div class="mood-tags">
              <span
                v-for="l in ['冰点','普通','活跃','亢奋']"
                :key="l"
                class="tag"
                :class="{ active: sentiment?.speculation === l }"
              >{{ l }}</span>
            </div>
          </el-card>
        </div>
        <div class="stat-grid">
          <div class="stat-cell">
            <div class="stat-num up">{{ sentiment?.up ?? '—' }}</div>
            <div class="stat-name">上涨家数</div>
          </div>
          <div class="stat-cell">
            <div class="stat-num down">{{ sentiment?.down ?? '—' }}</div>
            <div class="stat-name">下跌家数</div>
          </div>
          <div class="stat-cell">
            <div class="stat-num flat">{{ sentiment?.flat ?? '—' }}</div>
            <div class="stat-name">平盘</div>
          </div>
          <div class="stat-cell">
            <div class="stat-num up">{{ sentiment?.zt ?? '—' }}</div>
            <div class="stat-name">涨停</div>
          </div>
          <div class="stat-cell">
            <div class="stat-num up">{{ sentiment?.zt_real ?? '—' }}</div>
            <div class="stat-name">真实涨停</div>
          </div>
          <div class="stat-cell">
            <div class="stat-num down">{{ sentiment?.dt ?? '—' }}</div>
            <div class="stat-name">跌停</div>
          </div>
          <div class="stat-cell">
            <div class="stat-num down">{{ sentiment?.dt_real ?? '—' }}</div>
            <div class="stat-name">真实跌停</div>
          </div>
          <div class="stat-cell">
            <div class="stat-num flat">{{ sentiment?.active || '—' }}</div>
            <div class="stat-name">活跃度</div>
          </div>
        </div>
      </div>
    </section>

    <!-- 免责声明 -->
    <p class="disclaimer">以上数据来自公开源，仅供参考，不构成投资建议</p>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  DataAnalysis,
  DataLine,
  Refresh,
  MagicStick,
  Loading,
  Odometer,
  EditPen,
  Star,
  Close,
} from '@element-plus/icons-vue'
import {
  vibeApi,
  type IndexQuote,
  type GlobalIndex,
  type MarketSentiment,
  type SectorFlow,
  type StockQuote,
} from '@/api/vibe'

const loading = ref(false)
const indices = ref<IndexQuote[]>([])
const globalIndices = ref<GlobalIndex[]>([])
const sentiment = ref<MarketSentiment | null>(null)
const sectors = ref<SectorFlow[]>([])

const reviewing = ref(false)
const reviewText = ref('')

// 关注股票
const watchlist = ref<string[]>([])
const watchQuotes = ref<StockQuote[]>([])
const watchInput = ref('')
const watchLoading = ref(false)

const today = computed(() => {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
})

const formatPrice = (v: number | null | undefined) =>
  v == null ? '—' : v.toFixed(2)
const formatPct = (v: number | null | undefined) =>
  v == null ? '—' : Math.abs(v).toFixed(2)
const sign = (v: number | null | undefined) =>
  v == null ? '' : v > 0 ? '+' : v < 0 ? '-' : ''
const colorClass = (v: number | null | undefined) => {
  if (v == null) return 'flat'
  if (v > 0) return 'up'
  if (v < 0) return 'down'
  return 'flat'
}

const breadthClass = computed(() => {
  const b = sentiment.value?.breadth || ''
  if (['普涨', '偏强'].includes(b)) return 'up'
  if (['冰点', '偏弱'].includes(b)) return 'down'
  return 'flat'
})
const specClass = computed(() => {
  const s = sentiment.value?.speculation || ''
  if (['亢奋', '活跃'].includes(s)) return 'up'
  if (['冰点'].includes(s)) return 'down'
  return 'flat'
})

const loadAll = async () => {
  loading.value = true
  try {
    const [idx, g, ov] = await Promise.all([
      vibeApi.getIndices(),
      vibeApi.getGlobalIndices(),
      vibeApi.getMarketOverview(),
    ])
    indices.value = idx.data || []
    globalIndices.value = g.data || []
    sentiment.value = ov.data?.sentiment || null
    sectors.value = ov.data?.sectors || []
  } catch (e: any) {
    ElMessage.error(e?.message || '数据加载失败')
  } finally {
    loading.value = false
  }
}

const buildContext = () => {
  const parts: string[] = []
  if (indices.value.length) {
    parts.push(
      '大盘指数: ' +
        indices.value
          .map(
            i =>
              `${i.name} ${i.price.toFixed(2)}(${sign(i.change_pct)}${formatPct(i.change_pct)}%)`
          )
          .join(', ')
    )
  }
  if (sentiment.value) {
    const s = sentiment.value
    parts.push(
      `市场情绪: 上涨${s.up}家 下跌${s.down}家 平盘${s.flat}家 涨停${s.zt}家(真实${s.zt_real}) 跌停${s.dt}家(真实${s.dt_real}) 大盘宽度:${s.breadth} 题材投机:${s.speculation} 活跃度:${s.active}`
    )
  }
  if (sectors.value.length) {
    const top = sectors.value
      .slice(0, 5)
      .map(
        x =>
          `${x.name}(${sign(x.pct)}${formatPct(x.pct)}%,净${(x.net / 1e8).toFixed(1)}亿)`
      )
      .join(', ')
    parts.push('板块资金Top: ' + top)
  }
  return parts.join('\n')
}

const runReview = async () => {
  reviewing.value = true
  reviewText.value = ''
  const messages = [
    {
      role: 'user',
      content:
        '请基于今日 A 股大盘、市场情绪与板块资金数据，做一段简明当日复盘（300字以内），指出市场风格、资金主攻方向与潜在风险点。不要给出任何个股买卖建议。',
    },
  ]
  try {
    await vibeApi.chatStream(
      messages,
      buildContext(),
      delta => {
        reviewText.value += delta
      },
      err => {
        ElMessage.error(err)
      }
    )
  } catch (e: any) {
    ElMessage.error(e?.message || 'AI 复盘失败')
  } finally {
    reviewing.value = false
  }
}

const saveReview = () => {
  if (!reviewText.value) return
  vibeApi.saveNote('复盘', `${today.value} AI 当日复盘`, reviewText.value)
  ElMessage.success('已存入研究沉淀')
}

// 关注股票
const loadWatchQuotes = async () => {
  if (watchlist.value.length === 0) {
    watchQuotes.value = []
    return
  }
  watchLoading.value = true
  try {
    const res = await vibeApi.getQuotes(watchlist.value)
    watchQuotes.value = res.data || []
  } catch (e: any) {
    console.error('加载关注股票失败:', e)
  } finally {
    watchLoading.value = false
  }
}

const addWatch = () => {
  const code = watchInput.value.trim()
  if (!/^\d{6}$/.test(code)) {
    ElMessage.warning('请输入6位数字代码')
    return
  }
  watchlist.value = vibeApi.addWatchlist(code)
  watchInput.value = ''
  loadWatchQuotes()
}

const removeWatch = (code: string) => {
  watchlist.value = vibeApi.removeWatchlist(code)
  loadWatchQuotes()
}

onMounted(() => {
  loadAll()
  watchlist.value = vibeApi.loadWatchlist()
  loadWatchQuotes()
})
</script>

<style scoped>
.vibe-overview {
  padding: 4px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
}

.page-title {
  font-size: 22px;
  font-weight: 600;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--el-text-color-primary);
}

.title-icon {
  color: var(--el-color-primary);
}

.page-subtitle {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.block {
  margin-bottom: 24px;
}

.block-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.block-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.block-title .el-icon {
  color: var(--el-color-primary);
}

.block-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.grid {
  display: grid;
  gap: 12px;
}

.grid-4 {
  grid-template-columns: repeat(4, 1fr);
}

.grid-5 {
  grid-template-columns: repeat(5, 1fr);
}

.idx-card {
  border-radius: 8px;
}

.idx-card :deep(.el-card__body) {
  padding: 16px;
}

.idx-name {
  font-size: 13px;
  color: var(--el-text-color-regular);
  display: flex;
  align-items: center;
  gap: 6px;
}

.idx-name .region {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}

.idx-price {
  font-family: 'JetBrains Mono', monospace;
  font-size: 26px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin: 8px 0 4px;
  letter-spacing: -0.5px;
}

.idx-change {
  font-family: 'JetBrains Mono', monospace;
  font-size: 14px;
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.idx-change .amt {
  font-size: 12px;
  opacity: 0.8;
}

.empty-card :deep(.el-empty) {
  padding: 12px 0;
  margin: 0;
}

.review-card {
  border-radius: 8px;
}

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.head-actions {
  display: flex;
  gap: 8px;
}

.review-body {
  min-height: 120px;
}

.placeholder {
  color: var(--el-text-color-secondary);
  font-size: 14px;
  line-height: 1.8;
}

.review-text {
  white-space: pre-wrap;
  font-size: 14px;
  line-height: 1.9;
  color: var(--el-text-color-primary);
}

.cursor {
  color: var(--el-color-primary);
  animation: blink 1s steps(2) infinite;
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  50.01%, 100% { opacity: 0; }
}

.sentiment-wrap {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.mood-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.mood-card {
  border-radius: 8px;
}

.mood-card :deep(.el-card__body) {
  padding: 18px 20px;
}

.mood-label {
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.mood-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 30px;
  font-weight: 700;
  margin: 6px 0 12px;
}

.mood-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.tag {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 10px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
}

.tag.active {
  background: var(--el-color-primary-light-8);
  color: var(--el-color-primary);
  font-weight: 600;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.stat-cell {
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 14px;
  text-align: center;
}

.stat-num {
  font-family: 'JetBrains Mono', monospace;
  font-size: 22px;
  font-weight: 600;
}

.stat-name {
  font-size: 12px;
  color: var(--el-text-color-regular);
  margin-top: 4px;
}

.up { color: #f56c6c; }
.down { color: #67c23a; }
.flat { color: #909399; }

.disclaimer {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  text-align: center;
}

@media (max-width: 1200px) {
  .grid-5 { grid-template-columns: repeat(3, 1fr); }
}

/* 关注股票 */
.watch-input-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}

.grid-watch {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.watch-card {
  width: 160px;
  border-radius: 8px;
  flex-shrink: 0;
}

.watch-card :deep(.el-card__body) {
  padding: 12px 14px;
}

.watch-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.watch-name {
  font-size: 13px;
  color: var(--el-text-color-regular);
  font-weight: 500;
}

.watch-del {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  cursor: pointer;
  transition: color 0.2s;
}

.watch-del:hover {
  color: var(--el-color-danger);
}

.watch-price {
  font-family: 'JetBrains Mono', monospace;
  font-size: 22px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin: 4px 0 2px;
}

.watch-change {
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
}

.watch-placeholder {
  color: var(--el-text-color-placeholder);
  font-size: 13px;
  padding: 16px 0;
  width: 100%;
}

@media (max-width: 768px) {
  .grid-4, .grid-5 { grid-template-columns: repeat(2, 1fr); }
  .mood-row { grid-template-columns: 1fr; }
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>

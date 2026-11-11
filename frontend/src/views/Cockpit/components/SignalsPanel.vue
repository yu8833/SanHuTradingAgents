<script setup lang="ts">
defineOptions({ name: 'CockpitSignalsPanel' })
import { computed } from 'vue'
import type { PoolItem, SignalsData } from '@/api/cockpit'

const props = defineProps<{ data: SignalsData | null; loading?: boolean }>()
const emit = defineEmits<{ (e: 'buy', item: PoolItem): void }>()

const triggered = computed(() => props.data?.triggered || [])
const near = computed(() => props.data?.near || [])

function fmt(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return v.toFixed(digits)
}
function fmtPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return `${v > 0 ? '+' : ''}${(v * 100).toFixed(1)}%`
}
function shortTime(v: string | null | undefined): string {
  if (!v) return ''
  const s = String(v)
  const m = s.match(/(\d{2}:\d{2})/)
  return m ? m[1] : s.slice(0, 16)
}

const emptyText = computed(() => {
  const d = props.data
  if (!d) return '暂无 B2 突破买点'
  const since = d.pool_since ? `观察池 ${d.pool_since} 建立，` : ''
  if (!d.last_check_at && !d.trading_session) {
    return `${since}尚未经历盘中检测 —— 下一交易日 09:30 起每 15 分钟按 B2 扫描，放量中阳站上 MA55/60 才会出现信号`
  }
  return '当前没有标的满足 B2 突破买点。没有信号就是最好的信号——不买，等确认'
})
</script>

<template>
  <div class="cs-wrap">
    <div class="cs-status">
      <span class="cs-dot" :class="{ 'is-live': data?.trading_session }" />
      <span>{{ data?.scan_note || '盘中检测未开启' }}</span>
      <span v-if="data?.last_check_at" class="cs-last">最近检查 {{ shortTime(data.last_check_at) }}</span>
      <span class="cs-watching">观察中 {{ data?.watching_count ?? 0 }} 只</span>
    </div>

    <div v-if="loading && !data" class="cs-skel"><el-skeleton :rows="3" animated /></div>

    <template v-else>
      <!-- 已触发：最重要，一张票一个卡 -->
      <div v-if="triggered.length" class="cs-triggered">
        <div v-for="t in triggered" :key="t.code" class="cs-card">
          <div class="cs-card-head">
            <div class="cs-card-name">
              <span class="cs-name">{{ t.name }}</span>
              <span class="cs-code">{{ t.code }}</span>
              <span class="cs-ind">{{ t.industry }}</span>
            </div>
            <span class="cs-badge">B2 已确认</span>
          </div>

          <div class="cs-card-body">
            <div class="cs-kv">
              <span class="cs-k">触发价</span>
              <span class="cs-v">{{ fmt(t.trigger_price) }}</span>
            </div>
            <div class="cs-kv">
              <span class="cs-k">现价</span>
              <span class="cs-v is-hot">{{ fmt(t.current_price ?? t.last_price ?? t.close) }}</span>
            </div>
            <div class="cs-kv">
              <span class="cs-k">
                确认量比
                <em class="cs-help" title="B2 突破买点：放量（量比 ≥ 1.5）+ 中阳 + 站上 MA55/MA60，与 Candidate 页同一真源">ⓘ</em>
              </span>
              <span class="cs-v">{{ fmt(t.b2_volume_ratio ?? t.trigger_vol_ratio) }}</span>
            </div>
            <div class="cs-kv">
              <span class="cs-k">确认时间</span>
              <span class="cs-v">{{ shortTime(t.triggered_at) || '—' }}</span>
            </div>
          </div>

          <div class="cs-card-foot">
            <span class="cs-advice">B2 突破买点 = 右侧确认。按纪律：确认一只买一只，不追高、不补仓</span>
            <el-button type="primary" size="small" @click="emit('buy', t)">标记买入</el-button>
          </div>
        </div>
      </div>

      <!-- 临近：即将触发，值得盯 -->
      <div v-if="near.length" class="cs-near">
        <div class="cs-sub-title">临近触发（还差一点，盯住）</div>
        <div class="cs-near-list">
          <div v-for="n in near" :key="n.code" class="cs-near-item" @click="emit('buy', n)">
            <span class="cs-near-name">{{ n.name }}</span>
            <span class="cs-near-code">{{ n.code }}</span>
            <span class="cs-near-dist">{{ fmtPct(n.distance_to_trigger) }}</span>
            <span class="cs-near-trigger">触发价 {{ fmt(n.trigger_price) }}</span>
          </div>
        </div>
      </div>

      <el-empty
        v-if="!triggered.length && !near.length"
        :description="emptyText"
        :image-size="56"
      />
    </template>
  </div>
</template>

<style scoped>
.cs-status {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 12px;
}
.cs-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--el-text-color-placeholder);
}
.cs-dot.is-live { background: #22c55e; box-shadow: 0 0 0 4px rgba(34, 197, 94, 0.15); }
.cs-last { color: var(--el-text-color-placeholder); }
.cs-watching { margin-left: auto; }
.cs-skel { padding: 6px 0; }

.cs-triggered {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.cs-card {
  border: 1px solid #86efac;
  border-radius: 12px;
  background: linear-gradient(135deg, #f0fdf4 0%, #fff 70%);
  padding: 14px;
}
.cs-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}
.cs-card-name { display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; }
.cs-name { font-size: 15px; font-weight: 700; }
.cs-code { font-size: 11px; color: var(--el-text-color-placeholder); }
.cs-ind {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-light);
  border-radius: 4px;
  padding: 1px 6px;
}
.cs-badge {
  font-size: 11px;
  font-weight: 700;
  color: #15803d;
  background: #dcfce7;
  border-radius: 20px;
  padding: 2px 9px;
  white-space: nowrap;
}
.cs-card-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 10px;
  margin-bottom: 10px;
}
.cs-kv { display: flex; justify-content: space-between; gap: 6px; font-size: 12px; }
.cs-k { color: var(--el-text-color-secondary); }
.cs-v { font-weight: 600; color: var(--el-text-color-primary); }
.cs-v.is-hot { color: #e11d48; }
.cs-help { font-style: normal; cursor: help; }
.cs-card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-top: 10px;
  border-top: 1px dashed #bbf7d0;
}
.cs-advice { font-size: 11px; color: var(--el-text-color-secondary); line-height: 1.5; }

.cs-sub-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
  margin-bottom: 8px;
}
.cs-near-list { display: flex; flex-wrap: wrap; gap: 8px; }
.cs-near-item {
  display: flex;
  align-items: baseline;
  gap: 7px;
  font-size: 12px;
  border: 1px solid #fde68a;
  background: #fffbeb;
  border-radius: 8px;
  padding: 6px 10px;
  cursor: pointer;
  transition: transform 0.15s;
}
.cs-near-item:hover { transform: translateY(-1px); }
.cs-near-name { font-weight: 600; }
.cs-near-code { color: var(--el-text-color-placeholder); font-size: 11px; }
.cs-near-dist { color: #b45309; font-weight: 700; }
.cs-near-trigger { color: var(--el-text-color-secondary); font-size: 11px; }
</style>

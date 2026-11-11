<script setup lang="ts">
defineOptions({ name: 'CockpitPoolTable' })
import { computed, ref } from 'vue'
import type { PoolData, PoolItem, PoolStatus } from '@/api/cockpit'

const props = defineProps<{ data: PoolData | null; loading?: boolean }>()
const emit = defineEmits<{ (e: 'buy', item: PoolItem): void; (e: 'rescan'): void }>()

const statusFilter = ref<'all' | PoolStatus>('all')
const industryFilter = ref('')

const STATUS_META: Record<string, { text: string; type: 'success' | 'warning' | 'info' | 'danger' }> = {
  watching: { text: '观察中', type: 'info' },
  near: { text: '临近触发', type: 'warning' },
  triggered: { text: 'B2 已确认', type: 'success' },
  expired: { text: '已出池', type: 'danger' }
}

const items = computed(() => props.data?.items || [])

const industries = computed(() => {
  const set = new Set<string>()
  items.value.forEach(i => i.industry && set.add(i.industry))
  return Array.from(set).sort()
})

const filtered = computed(() =>
  items.value.filter(i => {
    if (statusFilter.value !== 'all' && i.status !== statusFilter.value) return false
    if (industryFilter.value && i.industry !== industryFilter.value) return false
    return true
  })
)

const counts = computed(() => {
  const c: Record<string, number> = { all: items.value.length, watching: 0, near: 0, triggered: 0 }
  items.value.forEach(i => { if (c[i.status] != null) c[i.status] += 1 })
  return c
})

function priceOf(i: PoolItem): number {
  return i.current_price ?? i.close
}
function fmt(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return v.toFixed(digits)
}
function fmtPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return `${v > 0 ? '+' : ''}${(v * 100).toFixed(1)}%`
}
function distCls(v: number | null | undefined): string {
  if (v == null) return ''
  if (v >= -0.02) return 'is-near'
  if (v >= -0.08) return 'is-close'
  return ''
}
function amountYi(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return `${(v / 1e8).toFixed(1)} 亿`
}
function canBuy(i: PoolItem): boolean {
  return i.status === 'triggered' || i.status === 'near'
}
</script>

<template>
  <div class="cp-wrap">
    <div class="cp-toolbar">
      <div class="cp-filters">
        <el-radio-group v-model="statusFilter" size="small">
          <el-radio-button value="all">全部 {{ counts.all }}</el-radio-button>
          <el-radio-button value="triggered">B2 已确认 {{ counts.triggered }}</el-radio-button>
          <el-radio-button value="near">临近 {{ counts.near }}</el-radio-button>
          <el-radio-button value="watching">观察中 {{ counts.watching }}</el-radio-button>
        </el-radio-group>

        <el-select
          v-model="industryFilter"
          size="small"
          placeholder="全部行业"
          clearable
          class="cp-industry"
        >
          <el-option v-for="ind in industries" :key="ind" :label="ind" :value="ind" />
        </el-select>
      </div>

      <div class="cp-actions">
        <span v-if="data" class="cp-param" :title="`参数版本 ${data.params_version}`">
          {{ data.params_note }}
        </span>
        <el-button size="small" :loading="loading" @click="emit('rescan')">重扫观察池</el-button>
      </div>
    </div>

    <div v-if="loading && !data" class="cp-skel"><el-skeleton :rows="6" animated /></div>

    <el-table
      v-else-if="filtered.length"
      :data="filtered"
      size="small"
      class="cp-table"
      :show-overflow-tooltip="true"
    >
      <el-table-column label="标的" min-width="140" fixed>
        <template #default="{ row }">
          <div class="cp-name-cell">
            <span class="cp-name">{{ row.name }}</span>
            <span class="cp-code">{{ row.code }}</span>
          </div>
          <span class="cp-industry-tag">{{ row.industry || '—' }}</span>
        </template>
      </el-table-column>

      <el-table-column label="现价" width="86" align="right">
        <template #default="{ row }">
          <span class="cp-price">{{ fmt(priceOf(row)) }}</span>
        </template>
      </el-table-column>

      <el-table-column width="108" align="right">
        <template #header>
          <span class="cp-th" title="盘中高点口径：近 20 日高点与前段（60日窗口前40日）高点取更紧者">触发价 ⓘ</span>
        </template>
        <template #default="{ row }">
          <span class="cp-trigger">{{ fmt(row.trigger_price) }}</span>
        </template>
      </el-table-column>

      <el-table-column width="104" align="right">
        <template #header>
          <span class="cp-th" title="(现价 ÷ 触发价 - 1)。0% 即到达触发价，负数表示还有多少空间">距触发 ⓘ</span>
        </template>
        <template #default="{ row }">
          <span class="cp-dist" :class="distCls(row.distance_to_trigger)">
            {{ fmtPct(row.distance_to_trigger) }}
          </span>
        </template>
      </el-table-column>

      <el-table-column width="92" align="center">
        <template #header>
          <span class="cp-th" title="距最近一次创新低的交易日数，衡量横盘时间">横盘 ⓘ</span>
        </template>
        <template #default="{ row }">
          <span class="cp-muted">{{ row.sideways_days }} 日</span>
        </template>
      </el-table-column>

      <el-table-column width="96" align="center">
        <template #header>
          <span class="cp-th" title="当前 20 日年化波动率在自身近 250 日中的分位。越低说明越平静（蓄势）">波动分位 ⓘ</span>
        </template>
        <template #default="{ row }">
          <span :class="['cp-strong', row.volatility_pctile <= 0.4 ? 'is-good' : '']">
            {{ (row.volatility_pctile * 100).toFixed(0) }}%
          </span>
        </template>
      </el-table-column>

      <el-table-column width="96" align="center">
        <template #header>
          <span class="cp-th" title="近 15 日平均振幅 ÷ 近 60 日平均振幅，≤0.9 表示振幅收缩">振幅收敛 ⓘ</span>
        </template>
        <template #default="{ row }">
          <span class="cp-muted">{{ fmt(row.converge_ratio) }}</span>
        </template>
      </el-table-column>

      <el-table-column label="日均额" width="86" align="right">
        <template #default="{ row }">
          <span class="cp-muted">{{ amountYi(row.avg_amount_20d) }}</span>
        </template>
      </el-table-column>

      <el-table-column label="状态" width="88" align="center">
        <template #default="{ row }">
          <el-tag size="small" :type="STATUS_META[row.status]?.type || 'info'" effect="plain">
            {{ STATUS_META[row.status]?.text || row.status }}
          </el-tag>
        </template>
      </el-table-column>

      <el-table-column label="操作" width="88" align="center" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="canBuy(row)"
            size="small"
            type="primary"
            link
            @click="emit('buy', row)"
          >
            标记买入
          </el-button>
          <span v-else class="cp-muted">等待</span>
        </template>
      </el-table-column>
    </el-table>

    <el-empty
      v-else
      :description="items.length ? '当前筛选无结果' : '观察池为空：没有同时满足 B1 左侧买点与积累区四条件的标的（熊市/普涨行情下都可能为空，属正常）'"
      :image-size="60"
    />

    <div v-if="data" class="cp-foot">
      <span>入池条件：{{ data.params.no_new_low }} · 波动分位 &lt; {{ data.params.vol_pctile_max }} · {{ data.params.converge }} · {{ data.params.min_avg_amount }} · {{ data.params.exclude }}</span>
      <span class="cp-foot-right">
        <span v-if="data.quote_as_of">现价 {{ data.quote_as_of }} 收盘</span>
        <span v-if="data.scanned_at">形态扫描 {{ data.scanned_at }}</span>
      </span>
    </div>
  </div>
</template>

<style scoped>
.cp-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.cp-filters { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.cp-industry { width: 130px; }
.cp-actions { display: flex; gap: 10px; align-items: center; }
.cp-param {
  font-size: 11px;
  color: #b45309;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 4px;
  padding: 2px 7px;
  cursor: help;
}
.cp-skel { padding: 6px 0; }
.cp-name-cell { display: flex; align-items: baseline; gap: 6px; }
.cp-name { font-weight: 600; font-size: 13px; }
.cp-code { font-size: 11px; color: var(--el-text-color-placeholder); }
.cp-industry-tag { font-size: 11px; color: var(--el-text-color-secondary); }
.cp-price { font-weight: 600; }
.cp-trigger { font-weight: 600; color: #b45309; }
.cp-dist { font-weight: 700; color: var(--el-text-color-secondary); }
.cp-dist.is-close { color: #f59e0b; }
.cp-dist.is-near { color: #e11d48; }
.cp-muted { font-size: 12px; color: var(--el-text-color-secondary); }
.cp-strong { font-size: 12px; font-weight: 600; }
.cp-strong.is-good { color: #16a34a; }
.cp-th { cursor: help; border-bottom: 1px dashed var(--el-border-color); }
.cp-foot-right { display: inline-flex; gap: 12px; }
.cp-foot {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 10px;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}
</style>

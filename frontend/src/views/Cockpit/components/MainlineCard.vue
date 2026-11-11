<script setup lang="ts">
defineOptions({ name: 'CockpitMainlineCard' })
import { computed } from 'vue'
import type { MainlineData } from '@/api/cockpit'

const props = defineProps<{ data: MainlineData | null; loading?: boolean }>()

const rows = computed(() => props.data?.mainlines || [])

function fmtYi(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const yi = v / 1e8
  const sign = yi > 0 ? '+' : ''
  return `${sign}${yi.toFixed(1)} 亿`
}
function fmtPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return `${v > 0 ? '+' : ''}${v.toFixed(2)}%`
}
function netCls(v: number | null | undefined): string {
  if (v == null) return ''
  return v > 0 ? 'is-up' : v < 0 ? 'is-down' : ''
}
function pctCls(v: number | null | undefined): string {
  if (v == null) return ''
  return v > 0 ? 'is-up' : v < 0 ? 'is-down' : ''
}
function shortTime(v: string | null | undefined): string {
  if (!v) return ''
  const s = String(v)
  const m = s.match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}:\d{2})/)
  if (m) return `${m[2]}-${m[3]} ${m[4]}`
  return s.slice(0, 16)
}
</script>

<template>
  <div class="cm-wrap">
    <div v-if="loading && !data" class="cm-skel"><el-skeleton :rows="4" animated /></div>

    <template v-else-if="rows.length">
      <el-table :data="rows" size="small" class="cm-table" :show-overflow-tooltip="true">
        <el-table-column label="方向（行业）" min-width="130">
          <template #default="{ row, $index }">
            <span class="cm-rank" :class="{ 'is-top': $index < 3 }">{{ $index + 1 }}</span>
            <span class="cm-name">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="3日涨幅" width="92" align="right">
          <template #default="{ row }">
            <span :class="pctCls(row.pct_3d)">{{ fmtPct(row.pct_3d) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="3日净流入" width="108" align="right">
          <template #default="{ row }">
            <span :class="netCls(row.net_3d)">{{ fmtYi(row.net_3d) }}</span>
          </template>
        </el-table-column>
        <el-table-column width="150" align="center">
          <template #header>
            <span class="cm-th-help" title="口径：3/5/10/20 日累计净额「连续为正」的最长前缀，是周期净流入为正的代理，非逐日连续">
              资金持续性 ⓘ
            </span>
          </template>
          <template #default="{ row }">
            <span class="cm-streak">{{ row.streak }} 日+</span>
          </template>
        </el-table-column>
        <el-table-column label="池内" width="80" align="center">
          <template #default="{ row }">
            <span :class="['cm-pool', { 'is-zero': !row.pool_count }]">{{ row.pool_count }} 只</span>
          </template>
        </el-table-column>
      </el-table>

      <div class="cm-foot">
        <span class="cm-src">
          来源：{{ data?.source || '同花顺 90 行业' }}
          <template v-if="data?.updated_at"> · 抓取 {{ shortTime(data.updated_at) }}</template>
          <span
            v-if="data?.as_of"
            class="cm-asof"
            :title="`日线实收日 ${data.as_of}。当日日线数据约 19:30 同步，同步后此处自动前移`"
          >
            · 日线 {{ data.as_of }}
          </span>
        </span>
        <span class="cm-tip">主线的作用：只在这些方向里挑观察池标的，方向不对的票不碰</span>
      </div>
    </template>

    <el-empty v-else description="暂无持续净流入的方向（资金全线流出时这是正常结果）" :image-size="60" />
  </div>
</template>

<style scoped>
.cm-skel { padding: 8px 0; }
.cm-table { background: transparent; }
.cm-rank {
  display: inline-block;
  width: 18px;
  height: 18px;
  line-height: 18px;
  text-align: center;
  border-radius: 4px;
  font-size: 11px;
  margin-right: 8px;
  background: var(--el-fill-color);
  color: var(--el-text-color-secondary);
}
.cm-rank.is-top { background: #fef3c7; color: #b45309; font-weight: 700; }
.cm-name { font-weight: 600; }
.cm-streak { font-size: 12px; color: #16a34a; font-weight: 600; }
.cm-pool { font-size: 12px; color: var(--el-text-color-primary); }
.cm-pool.is-zero { color: var(--el-text-color-placeholder); }
.cm-th-help { cursor: help; border-bottom: 1px dashed var(--el-border-color); }
.is-up { color: #e11d48; }
.is-down { color: #16a34a; }
.cm-foot {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 10px;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}
.cm-tip { color: var(--el-text-color-secondary); }
.cm-asof { cursor: help; border-bottom: 1px dashed var(--el-border-color); }
</style>

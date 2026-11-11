<script setup lang="ts">
defineOptions({ name: 'CockpitPositionsPanel' })
import { computed } from 'vue'
import type { PositionsData, PositionItem } from '@/api/cockpit'

const props = defineProps<{ data: PositionsData | null; loading?: boolean }>()
const emit = defineEmits<{ (e: 'close', item: PositionItem): void }>()

const items = computed(() => props.data?.items || [])

const STATE_META: Record<string, { text: string; cls: string }> = {
  exit: { text: '离场', cls: 'is-exit' },
  warn: { text: '预警', cls: 'is-warn' },
  normal: { text: '持有', cls: 'is-normal' },
  closed: { text: '已了结', cls: 'is-closed' }
}

const summary = computed(() => {
  const list = items.value
  return {
    total: list.length,
    exit: list.filter(i => i.state === 'exit').length,
    warn: list.filter(i => i.state === 'warn').length
  }
})

function fmt(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return v.toFixed(digits)
}
function pnlText(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return `${v > 0 ? '+' : ''}${(v * 100).toFixed(2)}%`
}
function pnlCls(v: number | null | undefined): string {
  if (v == null) return ''
  return v > 0 ? 'is-up' : v < 0 ? 'is-down' : ''
}
</script>

<template>
  <div class="cp2-wrap">
    <div v-if="data" class="cp2-status">
      <span>持仓 {{ summary.total }} 只</span>
      <span v-if="summary.exit" class="cp2-badge is-exit">离场 {{ summary.exit }}</span>
      <span v-if="summary.warn" class="cp2-badge is-warn">预警 {{ summary.warn }}</span>
      <span class="cp2-time">
        {{ data.is_intraday ? '盘中实时判定' : '收盘判定' }} · 评估于 {{ data.evaluated_at.slice(11, 16) }}
      </span>
    </div>

    <div v-if="loading && !data" class="cp2-skel"><el-skeleton :rows="3" animated /></div>

    <el-table v-else-if="items.length" :data="items" size="small" class="cp2-table" :show-overflow-tooltip="true">
      <el-table-column label="标的" min-width="130">
        <template #default="{ row }">
          <span class="cp2-name">{{ row.name }}</span>
          <span class="cp2-code">{{ row.code }}</span>
        </template>
      </el-table-column>

      <el-table-column label="成本" width="80" align="right">
        <template #default="{ row }"><span class="cp2-num">{{ fmt(row.buy_price) }}</span></template>
      </el-table-column>

      <el-table-column label="现价" width="80" align="right">
        <template #default="{ row }"><span class="cp2-num">{{ fmt(row.current_price) }}</span></template>
      </el-table-column>

      <el-table-column label="浮盈" width="88" align="right">
        <template #default="{ row }">
          <span :class="['cp2-pnl', pnlCls(row.pnl_pct)]">{{ pnlText(row.pnl_pct) }}</span>
        </template>
      </el-table-column>

      <el-table-column label="持有" width="72" align="center">
        <template #default="{ row }"><span class="cp2-muted">{{ row.holding_days }} 天</span></template>
      </el-table-column>

      <el-table-column width="76" align="center">
        <template #header>
          <span class="cp2-th" title="成本 × (1 - 8%)，触及即离场">止损线 ⓘ</span>
        </template>
        <template #default="{ row }">
          <span class="cp2-muted">{{ fmt(row.stop_loss_line) }}</span>
        </template>
      </el-table-column>

      <el-table-column width="76" align="center">
        <template #header>
          <span class="cp2-th" title="MA5 移动止盈：收盘跌破即离场（盘中跌破只预警）">MA5 ⓘ</span>
        </template>
        <template #default="{ row }">
          <span class="cp2-muted">{{ fmt(row.trailing_line) }}</span>
        </template>
      </el-table-column>

      <el-table-column label="纪律" width="82" align="center">
        <template #default="{ row }">
          <span class="cp2-state" :class="STATE_META[row.state]?.cls">
            {{ STATE_META[row.state]?.text || row.state }}
          </span>
          <span v-if="row.t1_locked" class="cp2-t1" title="T+1：当日买入不可卖出，次日执行">T+1</span>
        </template>
      </el-table-column>

      <el-table-column label="原因（为什么该走/该盯）" min-width="220">
        <template #default="{ row }">
          <div v-if="row.reasons?.length" class="cp2-reasons">
            <span v-for="(r, idx) in row.reasons" :key="idx" class="cp2-reason">{{ r }}</span>
          </div>
          <span v-else class="cp2-muted">按纪律持有</span>
        </template>
      </el-table-column>

      <el-table-column label="操作" width="80" align="center" fixed="right">
        <template #default="{ row }">
          <el-button
            size="small"
            :type="row.state === 'exit' ? 'danger' : 'primary'"
            link
            @click="emit('close', row)"
          >
            {{ row.state === 'exit' ? '立即了结' : '了结' }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty
      v-else
      description="还没有纪律持仓。从上方「B2 突破买点」标记买入后，这里会自动跟踪离场条件"
      :image-size="60"
    />

    <div class="cp2-foot">
      统一离场：假突破（跌破触发价 2%）→ 止损（计划价与 -8% 取更紧）→ S1/S2/S3 卖点 → 收盘跌破 MA5 → 止盈 15% / MA20 → 时间止损（30 天）
    </div>
  </div>
</template>

<style scoped>
.cp2-status {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 10px;
}
.cp2-badge { border-radius: 20px; padding: 1px 9px; font-weight: 600; }
.cp2-badge.is-exit { background: #fee2e2; color: #b91c1c; }
.cp2-badge.is-warn { background: #fef3c7; color: #b45309; }
.cp2-time { margin-left: auto; font-size: 11px; color: var(--el-text-color-placeholder); }
.cp2-skel { padding: 6px 0; }
.cp2-name { font-weight: 600; font-size: 13px; }
.cp2-code { font-size: 11px; color: var(--el-text-color-placeholder); margin-left: 6px; }
.cp2-num { font-weight: 600; }
.cp2-pnl { font-weight: 700; }
.is-up { color: #e11d48; }
.is-down { color: #16a34a; }
.cp2-muted { font-size: 12px; color: var(--el-text-color-secondary); }
.cp2-th { cursor: help; border-bottom: 1px dashed var(--el-border-color); }
.cp2-state {
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  border-radius: 4px;
  padding: 1px 6px;
}
.cp2-state.is-exit { background: #fee2e2; color: #b91c1c; }
.cp2-state.is-warn { background: #fef3c7; color: #b45309; }
.cp2-state.is-normal { background: #dcfce7; color: #15803d; }
.cp2-state.is-closed { background: var(--el-fill-color); color: var(--el-text-color-secondary); }
.cp2-t1 {
  display: inline-block;
  margin-left: 4px;
  font-size: 10px;
  color: #b45309;
  border: 1px solid #fcd34d;
  border-radius: 3px;
  padding: 0 3px;
  cursor: help;
}
.cp2-reasons { display: flex; flex-direction: column; gap: 2px; }
.cp2-reason { font-size: 11px; color: var(--el-text-color-secondary); line-height: 1.5; }
.cp2-foot {
  margin-top: 10px;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}
</style>

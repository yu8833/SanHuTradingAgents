<template>
  <div class="vibe-fundflow">
    <!-- 页面标题 -->
    <div class="page-header">
      <div class="title-block">
        <h1 class="page-title">
          <el-icon class="title-icon"><DataAnalysis /></el-icon>
          资金流向
        </h1>
        <p class="page-subtitle">板块资金趋势榜与成交额排行</p>
      </div>
      <el-button type="primary" plain :icon="Refresh" :loading="loading" @click="loadAll">
        刷新
      </el-button>
    </div>

    <!-- 全市场成交额 TOP20 -->
    <section class="block">
      <div class="block-head">
        <span class="block-title">
          <el-icon><Lightning /></el-icon> 全市场成交额 TOP20
        </span>
        <span v-if="turnoverUpdated" class="block-hint">更新时间：{{ turnoverUpdated }}</span>
      </div>
      <el-card shadow="never" class="table-card">
        <el-table :data="turnoverStocks" v-loading="loading" stripe size="default">
          <el-table-column label="序号" type="index" width="70" align="center" />
          <el-table-column label="名称" min-width="170">
            <template #default="{ row }">
              <div class="stock-cell">
                <span class="stock-name">{{ row.name }}</span>
                <span class="stock-code">{{ row.code }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="现价" width="100" align="right">
            <template #default="{ row }">
              {{ row.price == null ? '—' : row.price.toFixed(2) }}
            </template>
          </el-table-column>
          <el-table-column label="涨跌%" width="100" align="right">
            <template #default="{ row }">
              <span :class="colorClass(row.pct)">
                {{ row.pct == null ? '—' : sign(row.pct) + Math.abs(row.pct).toFixed(2) + '%' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="成交额(亿)" width="120" align="right">
            <template #default="{ row }">{{ formatYi(row.amount) }}</template>
          </el-table-column>
          <el-table-column label="总市值(亿)" width="120" align="right">
            <template #default="{ row }">{{ formatYi(row.mcap) }}</template>
          </el-table-column>
          <el-table-column label="行业" min-width="110" prop="industry" />
        </el-table>
      </el-card>
    </section>

    <!-- 板块资金趋势榜 -->
    <section class="block">
      <div class="block-head">
        <span class="block-title">
          <el-icon><Histogram /></el-icon> 板块资金趋势榜 · Top15
        </span>
        <span class="block-hint">按今日净流入降序</span>
      </div>
      <el-card shadow="never" class="table-card">
        <el-table :data="topSectors" v-loading="loading" stripe size="default">
          <el-table-column label="行业" min-width="120" prop="name" />
          <el-table-column label="涨跌%" width="110" align="right">
            <template #default="{ row }">
              <span :class="colorClass(row.pct)">
                {{ sign(row.pct) }}{{ Math.abs(row.pct).toFixed(2) }}%
              </span>
            </template>
          </el-table-column>
          <el-table-column label="今日净流入(亿)" width="150" align="right">
            <template #default="{ row }">
              <span :class="colorClass(row.net)" class="net-cell">
                {{ sign(row.net) }}{{ Math.abs(row.net).toFixed(2) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="流入(亿)" width="110" align="right">
            <template #default="{ row }">{{ (row.inflow || 0).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column label="流出(亿)" width="110" align="right">
            <template #default="{ row }">{{ (row.outflow || 0).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column label="家数" width="90" align="right" prop="firms" />
        </el-table>
      </el-card>
    </section>

    <!-- 资金轮动 -->
    <section class="block">
      <div class="block-head">
        <span class="block-title">
          <el-icon><Sort /></el-icon> 资金轮动 · 流入 / 流出 Top6
        </span>
      </div>
      <div class="rotate-row">
        <el-card shadow="never" class="rotate-card">
          <template #header>
            <span class="rotate-head in">
              <el-icon><Top /></el-icon> 流入 Top6
            </span>
          </template>
          <div class="rotate-list">
            <div v-for="(s, i) in inflowTop" :key="s.name" class="rotate-item">
              <span class="rk">{{ i + 1 }}</span>
              <span class="nm">{{ s.name }}</span>
              <span class="pc" :class="colorClass(s.pct)">
                {{ sign(s.pct) }}{{ Math.abs(s.pct).toFixed(2) }}%
              </span>
              <span class="nt up">+{{ (s.net || 0).toFixed(2) }}亿</span>
            </div>
            <div v-if="!inflowTop.length" class="empty">暂无数据</div>
          </div>
        </el-card>

        <el-card shadow="never" class="rotate-card">
          <template #header>
            <span class="rotate-head out">
              <el-icon><Bottom /></el-icon> 流出 Top6
            </span>
          </template>
          <div class="rotate-list">
            <div v-for="(s, i) in outflowTop" :key="s.name" class="rotate-item">
              <span class="rk">{{ i + 1 }}</span>
              <span class="nm">{{ s.name }}</span>
              <span class="pc" :class="colorClass(s.pct)">
                {{ sign(s.pct) }}{{ Math.abs(s.pct).toFixed(2) }}%
              </span>
              <span class="nt down">{{ (s.net || 0).toFixed(2) }}亿</span>
            </div>
            <div v-if="!outflowTop.length" class="empty">暂无数据</div>
          </div>
        </el-card>
      </div>
    </section>

    <p class="disclaimer">以上数据来自公开源，仅供参考，不构成投资建议</p>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  DataAnalysis,
  Refresh,
  Lightning,
  Histogram,
  Sort,
  Top,
  Bottom,
} from '@element-plus/icons-vue'
import { vibeApi, type SectorFlow, type TurnoverStock } from '@/api/vibe'

const loading = ref(false)
const sectors = ref<SectorFlow[]>([])
const turnoverStocks = ref<TurnoverStock[]>([])
const turnoverUpdated = ref('')

const topSectors = computed(() =>
  [...sectors.value].sort((a, b) => b.net - a.net).slice(0, 15)
)
const inflowTop = computed(() =>
  [...sectors.value].sort((a, b) => b.net - a.net).slice(0, 6)
)
const outflowTop = computed(() =>
  [...sectors.value].sort((a, b) => a.net - b.net).slice(0, 6)
)

const formatYi = (v: number | null | undefined) =>
  v == null ? '—' : (v / 1e8).toFixed(2)
const sign = (v: number | null | undefined) =>
  v == null ? '' : v > 0 ? '+' : v < 0 ? '-' : ''
const colorClass = (v: number | null | undefined) => {
  if (v == null) return 'flat'
  if (v > 0) return 'up'
  if (v < 0) return 'down'
  return 'flat'
}

const loadAll = async () => {
  loading.value = true
  try {
    const [ov, tt] = await Promise.all([
      vibeApi.getMarketOverview(),
      vibeApi.getTurnoverTop(),
    ])
    sectors.value = ov.data?.sectors || []
    turnoverStocks.value = tt.data?.stocks || []
    turnoverUpdated.value = tt.data?.updated || ''
  } catch (e: any) {
    ElMessage.error(e?.message || '数据加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadAll()
})
</script>

<style scoped>
.vibe-fundflow {
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
}

.table-card {
  border-radius: 8px;
}

.stock-cell {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}

.stock-name {
  font-size: 14px;
  color: var(--el-text-color-primary);
  font-weight: 500;
}

.stock-code {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-family: 'JetBrains Mono', monospace;
}

.net-cell {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 600;
}

.rotate-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.rotate-card {
  border-radius: 8px;
}

.rotate-head {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
}

.rotate-head.in {
  color: #f56c6c;
}

.rotate-head.out {
  color: #67c23a;
}

.rotate-list {
  display: flex;
  flex-direction: column;
}

.rotate-item {
  display: grid;
  grid-template-columns: 28px 1fr auto auto;
  align-items: center;
  gap: 10px;
  padding: 10px 4px;
  border-bottom: 1px dashed var(--el-border-color-lighter);
}

.rotate-item:last-child {
  border-bottom: none;
}

.rk {
  width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--el-fill-color-light);
  border-radius: 50%;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-family: 'JetBrains Mono', monospace;
}

.nm {
  font-size: 14px;
  color: var(--el-text-color-primary);
}

.pc {
  font-size: 12px;
  font-family: 'JetBrains Mono', monospace;
  min-width: 64px;
  text-align: right;
}

.nt {
  font-size: 13px;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 600;
  min-width: 76px;
  text-align: right;
}

.empty {
  text-align: center;
  color: var(--el-text-color-placeholder);
  padding: 20px 0;
  font-size: 13px;
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

@media (max-width: 768px) {
  .rotate-row {
    grid-template-columns: 1fr;
  }
}
</style>

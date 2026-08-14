<template>
  <div class="candidate-page">
    <div class="page-header">
      <div>
        <h2>候选</h2>
        <p class="sub">资金为王 · 行业资金流筛选 → 个股资金流 → 择时进出</p>
      </div>
      <div class="header-actions">
        <el-tag v-if="screenAsOf" type="info" effect="plain">数据日 {{ screenAsOf }}</el-tag>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="candidate-tabs">
      <!-- Tab1 行业筛选（行业 ETF 主力净流入排名 + 行业 ΔG 景气融合） -->
      <el-tab-pane label="行业筛选" name="screening">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          class="tab-hint"
          title="资金为王：按行业主题 ETF 主力净流入分位排名（动量/量能仅展示不参与排序），同花顺行业资金流交叉核验方向。点击行业进入个股筛选。"
        />
        <div class="screening-toolbar">
          <el-button type="primary" :icon="Lightning" :loading="screenRefreshing" @click="loadScreening(true)">
            实时采集
          </el-button>
          <el-button :icon="Refresh" :loading="screenLoading" @click="loadScreening(false)">刷新快照</el-button>
          <span class="screening-hint">共 {{ screenCount }} 个行业 · 点行业进入个股筛选</span>
        </div>

        <!-- Top 卡片 -->
        <div v-if="screenRankings.length" class="top-grid">
          <div
            v-for="(item, i) in screenTop"
            :key="item.etf_code"
            class="top-card"
            :class="`rank-${i + 1}`"
            @click="goToStockScreening(item)"
          >
            <div class="card-head">
              <span class="rank-badge">{{ i + 1 }}</span>
              <span class="ind-name">{{ item.industry }}</span>
            </div>
            <div class="card-score">
              <span class="score-val" :class="(item.fund_net_inflow || 0) >= 0 ? 'up' : 'down'">
                {{ fmtYi(item.fund_net_inflow) }}亿
              </span>
              <span class="score-label">资金流分 {{ item.fund_flow_score }}</span>
            </div>
            <div class="card-etf">
              <span class="etf-name">{{ item.etf_name }}</span>
              <span class="etf-code">{{ item.etf_code }}</span>
            </div>
            <div class="card-metrics">
              <div class="metric">
                <span class="m-label">涨跌幅</span>
                <span class="m-val" :class="(item.pct_chg || 0) >= 0 ? 'up' : 'down'">{{ fmtSign(item.pct_chg) }}%</span>
              </div>
              <div class="metric">
                <span class="m-label">行业净流入</span>
                <span class="m-val" :class="(item.sector_net_inflow || 0) >= 0 ? 'up' : 'down'">
                  {{ fmtNum(item.sector_net_inflow) }}亿
                </span>
              </div>
            </div>
          </div>
        </div>
        <el-empty v-else-if="!screenLoading && !screenRefreshing" description="暂无行业资金流数据（点击「实时采集」获取，或等待盘中任务入库）" />

        <!-- 全排名表 -->
        <div class="section-title">行业资金流排名（{{ screenRankings.length }}）</div>
        <el-table
          :data="screenRankings"
          v-loading="screenLoading"
          stripe
          empty-text="暂无排名数据"
          class="rank-table"
          @row-click="goToStockScreening"
        >
          <el-table-column label="排名" width="70" align="center">
            <template #default="{ $index }">
              <span class="rank" :class="rankClass($index)">{{ $index + 1 }}</span>
            </template>
          </el-table-column>
          <el-table-column label="行业" min-width="150">
            <template #default="{ row }">
              <div class="ind-cell">
                <span class="ind-name">{{ row.industry }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="代表ETF" min-width="140">
            <template #default="{ row }">
              <span class="etf-name">{{ row.etf_name }}</span>
              <span class="muted etf-code">{{ row.etf_code }}</span>
            </template>
          </el-table-column>
          <el-table-column label="资金流分" width="90" align="center">
            <template #default="{ row }">
              <span class="score-num" :class="scoreTone(row.fund_flow_score)">{{ row.fund_flow_score }}</span>
            </template>
          </el-table-column>
          <el-table-column label="主力净流入" min-width="130" align="right">
            <template #default="{ row }">
              <span :class="(row.fund_net_inflow || 0) >= 0 ? 'up' : 'down'">{{ fmtYi(row.fund_net_inflow) }}亿</span>
              <span class="muted">({{ fmtSign(row.fund_net_inflow_pct) }}%)</span>
            </template>
          </el-table-column>
          <el-table-column label="涨跌幅" width="90" align="right">
            <template #default="{ row }">
              <span :class="(row.pct_chg || 0) >= 0 ? 'up' : 'down'">{{ fmtSign(row.pct_chg) }}%</span>
            </template>
          </el-table-column>
          <el-table-column label="行业净流入(亿)" min-width="120" align="right">
            <template #default="{ row }">
              <span :class="(row.sector_net_inflow || 0) >= 0 ? 'up' : 'down'">{{ fmtNum(row.sector_net_inflow) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="量比" width="80" align="right">
            <template #default="{ row }">{{ fmtNum(row.volume_ratio) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="110" align="center" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="primary" plain @click.stop="goToStockScreening(row)">个股筛选</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- Tab2 个股筛选（行业成分股多因子打分 + ΔG 象限 + 择时预览） -->
      <el-tab-pane label="个股筛选" name="stock-screening">
        <div class="stocks-toolbar">
          <el-select
            v-model="selectedIndustry"
            filterable
            clearable
            placeholder="选择行业（来自行业筛选）"
            class="industry-select"
            @change="loadCandidates"
          >
            <el-option
              v-for="ind in screenRankings"
              :key="ind.industry"
              :label="ind.industry"
              :value="ind.industry"
            />
          </el-select>
          <el-button :icon="Refresh" :loading="stockLoading" @click="loadCandidates">计算候选</el-button>
          <el-radio-group v-model="signalFilter" class="signal-filter" size="small">
            <el-radio-button value="all">全部 {{ signalStats.all }}</el-radio-button>
            <el-radio-button value="B1">左侧买点 {{ signalStats.B1 }}</el-radio-button>
            <el-radio-button value="B2">突破买点 {{ signalStats.B2 }}</el-radio-button>
            <el-radio-button value="B3">回踩买点 {{ signalStats.B3 }}</el-radio-button>
          </el-radio-group>
          <span class="stocks-hint">{{ selectedIndustry ? `行业 ${selectedIndustry} · top ${limit}` : `前10行业 · 每行业top3 · 共${signalStats.all}只` }} · 显示 {{ filteredCandidates.length }} 只</span>
        </div>

        <el-table
          :data="filteredCandidates"
          v-loading="stockLoading"
          stripe
          empty-text="请选择行业后计算候选个股"
          class="candidate-table"
        >
          <el-table-column prop="code" label="代码" width="90" />
          <el-table-column prop="name" label="名称" min-width="100">
            <template #default="{ row }">
              <router-link :to="`/stocks/${row.code}`" class="stock-link">{{ row.name }}</router-link>
            </template>
          </el-table-column>
          <el-table-column label="行业" min-width="90">
            <template #default="{ row }">
              <span class="muted">{{ row.industry || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="质量分" width="150">
            <template #default="{ row }">
              <div class="qscore">
                <el-progress
                  :percentage="Number(row.quality_score || 0)"
                  :stroke-width="7"
                  :color="scoreColor(row.quality_score)"
                  :show-text="false"
                />
                <span class="score-num">{{ row.quality_score }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="涨跌幅" width="90" align="right">
            <template #default="{ row }">
              <span :class="(row.pct_chg || 0) >= 0 ? 'up' : 'down'">{{ fmtPct(row.pct_chg) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="ΔG 象限" width="120">
            <template #default="{ row }">
              <el-tag v-if="row.dg_quadrant" size="small" :type="dgTagType(row.dg_quadrant)">
                {{ row.dg_quadrant }}
              </el-tag>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="择时信号" width="120">
            <template #default="{ row }">
              <el-tag v-if="row.signal_type" size="small" :type="signalTagType(row.signal_type)">
                {{ row.signal_label || row.signal_type }}
              </el-tag>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="辅助分" width="130">
            <template #default="{ row }">
              <el-tooltip :content="auxTooltip(row)" placement="top" :disabled="!row.auxiliary">
                <div class="aux-cell">
                  <el-progress
                    :percentage="Number(row.aux_score || 0)"
                    :stroke-width="7"
                    :color="auxColor(row.aux_score)"
                    :show-text="false"
                  />
                  <span class="score-num">{{ row.aux_score }}</span>
                </div>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="预警" min-width="150">
            <template #default="{ row }">
              <template v-if="row.aux_warnings && row.aux_warnings.length">
                <el-tooltip :content="row.aux_warnings.join('；')" placement="top" :disabled="row.aux_warnings.length <= 2">
                  <div class="warn-cell">
                    <el-tag v-for="w in row.aux_warnings.slice(0, 2)" :key="w" size="small" type="warning" effect="light" class="warn-tag">
                      {{ w }}
                    </el-tag>
                    <el-tag v-if="row.aux_warnings.length > 2" size="small" type="info" effect="plain" class="warn-tag">
                      +{{ row.aux_warnings.length - 2 }}
                    </el-tag>
                  </div>
                </el-tooltip>
              </template>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="20日动量" width="100" align="right">
            <template #default="{ row }">
              <span :class="(row.momentum_20d || 0) >= 0 ? 'up' : 'down'">{{ fmtPct(row.momentum_20d) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="ROE" width="80" align="right">
            <template #default="{ row }">{{ fmtNum(row.roe) }}%</template>
          </el-table-column>
          <el-table-column label="营收YOY" width="90" align="right">
            <template #default="{ row }">{{ fmtPct(row.revenue_yoy) }}</template>
          </el-table-column>
          <el-table-column label="PE(TTM)" width="90" align="right">
            <template #default="{ row }">{{ fmtNum(row.pe_ttm) }}</template>
          </el-table-column>
          <el-table-column label="市值(亿)" width="100" align="right">
            <template #default="{ row }">{{ fmtNum(row.total_mv) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="110" fixed="right" align="center">
            <template #default="{ row }">
              <el-button size="small" type="success" plain @click="addFavorite(row)">+ 自选</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Lightning } from '@element-plus/icons-vue'
import {
  candidateApi,
  type CandidateStock,
  type IndustryScreeningItem
} from '@/api/candidate'

// 外层 Tab：行业筛选 / 个股筛选
const activeTab = ref('screening')
const stockLoading = ref(false)

// Tab1 行业筛选（行业 ETF 主力净流入资金流排名 + 行业 ΔG 景气）
const screenLoading = ref(false)
const screenRefreshing = ref(false)
const screenTop = ref<IndustryScreeningItem[]>([])
const screenRankings = ref<IndustryScreeningItem[]>([])
const screenAsOf = ref('')
const screenCount = ref(0)

// Tab2 个股筛选
const selectedIndustry = ref('')
const candidates = ref<CandidateStock[]>([])
const limit = 30
// 择时信号筛选：all(全部B) / B1 / B2 / B3
const signalFilter = ref<'all' | 'B1' | 'B2' | 'B3'>('all')

/** 按择时信号筛选后的候选个股（后端已只返回 B1/B2/B3 信号） */
const filteredCandidates = computed(() => {
  const f = signalFilter.value
  if (f === 'all') return candidates.value
  return candidates.value.filter((r) => r.signal_type === f)
})

/** 择时信号统计：{all, B1, B2, B3} */
const signalStats = computed(() => {
  const s = { all: candidates.value.length, B1: 0, B2: 0, B3: 0 }
  for (const r of candidates.value) {
    if (r.signal_type === 'B1') s.B1++
    else if (r.signal_type === 'B2') s.B2++
    else if (r.signal_type === 'B3') s.B3++
  }
  return s
})

function rankClass(i: number) {
  if (i === 0) return 'rank-gold'
  if (i === 1) return 'rank-silver'
  if (i === 2) return 'rank-bronze'
  return 'rank-normal'
}

function scoreColor(v: number | null | undefined) {
  const s = Number(v || 0)
  if (s >= 70) return '#f56c6c'
  if (s >= 50) return '#e6a23c'
  return '#409eff'
}

function scoreTone(v: number | null | undefined) {
  const s = Number(v || 0)
  if (s >= 70) return 'tone-strong'
  if (s >= 50) return 'tone-mid'
  return 'tone-weak'
}

function fmtPct(v: number | null | undefined) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '-'
  return `${Number(v) >= 0 ? '+' : ''}${(Number(v) * 100).toFixed(1)}%`
}

function fmtNum(v: number | null | undefined) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '-'
  return Number(v).toFixed(2)
}

/** 元 -> 亿 */
function fmtYi(v: number | null | undefined) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '-'
  return (Number(v) / 1e8).toFixed(2)
}

/** 带符号数值（输入为百分数数值，如 1.23 代表 1.23%，模板后续拼 %） */
function fmtSign(v: number | null | undefined) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '-'
  return `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(2)}`
}

function dgTagType(q: string) {
  if (q.includes('双击')) return 'success'
  if (q.includes('反转')) return 'info'
  if (q.includes('见顶')) return 'warning'
  if (q.includes('双杀')) return 'danger'
  return 'info'
}

function signalTagType(s: string) {
  if (s.startsWith('B')) return 'danger'
  if (s.startsWith('S')) return 'success'
  return 'info'
}

function auxColor(v: number | null | undefined) {
  const s = Number(v || 0)
  if (s >= 70) return '#67c23a'
  if (s >= 55) return '#409eff'
  return '#909399'
}

function auxTooltip(row: CandidateStock) {
  const aux = row.auxiliary || {}
  const parts = Object.values(aux)
    .filter((s: any) => s && s.label)
    .map((s: any) => `${s.label}：${s.detail || ''}`)
  return parts.length ? parts.join('\n') : '暂无辅助信号'
}

/** 行业筛选：读取行业 ETF 主力净流入排名（refresh=true 强制实时采集） */
async function loadScreening(refresh = false) {
  if (refresh) {
    screenRefreshing.value = true
  } else {
    screenLoading.value = true
  }
  try {
    const res = await candidateApi.industryScreening(10, refresh)
    const data = res.data
    screenTop.value = data?.top || []
    screenRankings.value = data?.rankings || []
    screenAsOf.value = data?.as_of || ''
    screenCount.value = data?.industry_count ?? screenRankings.value.length
    // 资金流排名就绪后，若未选行业则加载跨行业默认视图（前10行业每行业top3）
    if (!selectedIndustry.value) {
      loadCandidates()
    }
  } catch (e) {
    ElMessage.error('加载行业资金流失败')
  } finally {
    screenLoading.value = false
    screenRefreshing.value = false
  }
}

/** 从行业筛选进入个股筛选：选中行业并计算候选个股 */
function goToStockScreening(item: IndustryScreeningItem) {
  selectedIndustry.value = item.industry
  activeTab.value = 'stock-screening'
  loadCandidates()
}

async function loadCandidates() {
  stockLoading.value = true
  try {
    if (selectedIndustry.value) {
      // 选择了行业：只展示该行业有 B1/B2/B3 信号的前 limit(30) 只
      const res = await candidateApi.stocks(selectedIndustry.value, limit)
      candidates.value = res.data?.items || []
    } else {
      // 未选行业：默认展示前 10 个行业每行业前 3 只 B 信号个股（共约 30 只）
      const topInds = screenRankings.value.slice(0, 10).map((r) => r.industry).filter(Boolean)
      const res = await candidateApi.stocksOverview(10, 3, topInds)
      candidates.value = res.data?.items || []
    }
  } catch (e) {
    ElMessage.error('计算候选个股失败')
  } finally {
    stockLoading.value = false
  }
}

async function addFavorite(row: CandidateStock) {
  try {
    await candidateApi.addFavorite(row.code, row.name)
    ElMessage.success(`已将 ${row.name} 加入自选`)
  } catch (e) {
    ElMessage.error('加入自选失败')
  }
}

onMounted(() => {
  // 资金流排名就绪后会级联加载个股筛选的跨行业默认视图
  loadScreening(false)
})
</script>

<style scoped>
.candidate-page {
  padding: 24px;
  max-width: 1280px;
  margin: 0 auto;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 16px;
}
.page-header h2 {
  margin: 0;
  font-size: 22px;
}
.page-header .sub {
  margin: 4px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
.tab-hint {
  margin-bottom: 12px;
}
.screening-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.screening-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin: 16px 0 8px;
}
.top-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
  margin-bottom: 8px;
}
.top-card {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  padding: 12px 14px;
  cursor: pointer;
  transition: box-shadow .2s, transform .2s;
}
.top-card:hover {
  box-shadow: var(--el-box-shadow-light);
  transform: translateY(-2px);
}
.top-card.rank-1 { border-top: 3px solid #f7ba2a; }
.top-card.rank-2 { border-top: 3px solid #a0a4a8; }
.top-card.rank-3 { border-top: 3px solid #cd7f32; }
.card-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}
.rank-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #f0f2f5;
  color: #909399;
  font-size: 12px;
  font-weight: 600;
}
.top-card.rank-1 .rank-badge { background: #f7ba2a; color: #fff; }
.top-card.rank-2 .rank-badge { background: #a0a4a8; color: #fff; }
.top-card.rank-3 .rank-badge { background: #cd7f32; color: #fff; }
.card-score {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.score-val {
  font-weight: 700;
  font-size: 18px;
}
.score-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.card-etf {
  display: flex;
  justify-content: space-between;
  margin: 6px 0;
  font-size: 12px;
}
.etf-name {
  color: var(--el-text-color-primary);
  font-weight: 500;
}
.etf-code {
  color: var(--el-text-color-secondary);
}
.card-metrics {
  display: flex;
  gap: 16px;
  border-top: 1px dashed var(--el-border-color-lighter);
  padding-top: 6px;
}
.metric {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.m-label { display: block; }
.m-val { font-weight: 600; }
.ind-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}
.ind-name {
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.dg-empty {
  font-size: 12px;
}
/* 行业卡片 & 表格：四象限分布 */
.card-dg-dist {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  margin: 4px 0 6px;
}
.dg-dist-item {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.dg-dist-item b {
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.dg-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.dot-success { background: #67c23a; }
.dot-warning { background: #e6a23c; }
.dot-danger { background: #f56c6c; }
.dot-info { background: #909399; }
.ind-line {
  display: flex;
  align-items: center;
  gap: 6px;
}
.ind-dg-dist {
  display: block;
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.signal-filter {
  flex-shrink: 0;
}
.qscore, .aux-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}
.qscore .el-progress, .aux-cell .el-progress {
  flex: 1;
}
.score-num {
  min-width: 36px;
  text-align: right;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.tone-strong { color: #f56c6c; }
.tone-mid { color: #e6a23c; }
.tone-weak { color: #409eff; }
.rank {
  display: inline-block;
  width: 24px;
  height: 24px;
  line-height: 24px;
  border-radius: 50%;
  font-size: 13px;
  font-weight: 600;
  text-align: center;
}
.rank-gold { background: #f7ba2a; color: #fff; }
.rank-silver { background: #a0a4a8; color: #fff; }
.rank-bronze { background: #cd7f32; color: #fff; }
.rank-normal { background: #f0f2f5; color: #909399; }
.up { color: #f56c6c; }
.down { color: #67c23a; }
.muted { color: var(--el-text-color-secondary); }
.stocks-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.industry-select {
  width: 260px;
}
.stocks-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.stock-link {
  color: var(--el-color-primary);
  text-decoration: none;
  font-weight: 500;
}
.stock-link:hover {
  text-decoration: underline;
}
.sector-dg-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  margin-bottom: 12px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
}
.sector-dg-banner.dg-success { background: rgba(103, 194, 58, .08); border-color: rgba(103, 194, 58, .3); }
.sector-dg-banner.dg-warning { background: rgba(230, 162, 60, .08); border-color: rgba(230, 162, 60, .3); }
.sector-dg-banner.dg-danger { background: rgba(245, 108, 108, .08); border-color: rgba(245, 108, 108, .3); }
.sector-dg-banner.dg-info { background: rgba(144, 147, 153, .08); border-color: rgba(144, 147, 153, .3); }
.sector-dg-banner .dg-label {
  font-weight: 600;
  font-size: 14px;
}
.sector-dg-banner .dg-metric {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.warn-tag {
  margin-right: 4px;
  margin-bottom: 2px;
}
.warn-cell {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
}
.rank-table {
  cursor: pointer;
}
</style>
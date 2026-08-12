<template>
  <div class="candidate-page">
    <div class="page-header">
      <div>
        <h2>候选池</h2>
        <p class="sub">「行业 → 个股 → 择时」流水线 · 强势行业轮动 + 行业成分股多因子打分</p>
      </div>
      <div class="header-actions">
        <el-tag v-if="asOf" type="info" effect="plain">数据日 {{ asOf }}</el-tag>
        <el-button :icon="Refresh" :loading="loading" @click="refreshIndustries">刷新</el-button>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="candidate-tabs">
      <!-- Tab1 强势行业 -->
      <el-tab-pane label="强势行业 / 概念" name="industries">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          class="tab-hint"
          title="行业强度分 = 成分股动量加权平均（5/10/20/60日动量，权重 20%/25%/30%/25%）为主，叠加上行比例（近20日动量>0的成分股占比）与量能（量比）合成，映射到 0-100，按分数降序取强势行业。点击行业进入候选个股打分。"
        />
        <el-table
          :data="industries"
          v-loading="loading"
          stripe
          empty-text="暂无行业数据（请先刷新）"
          class="industry-table"
          @row-click="goToStocks"
        >
          <el-table-column label="排名" width="70" align="center">
            <template #default="{ $index }">
              <span class="rank" :class="rankClass($index)">{{ $index + 1 }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="industry" label="行业 / 概念" min-width="160">
            <template #default="{ row }">
              <span class="industry-name">{{ row.industry }}</span>
            </template>
          </el-table-column>
          <el-table-column label="行业强度分" width="110">
            <template #default="{ row }">
              <span class="score-val" :class="scoreTone(row.sector_score)">{{ row.sector_score }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="member_count" label="成分股数" width="100" align="center" />
          <el-table-column label="行业ΔG景气" width="130">
            <template #default="{ row }">
              <el-tag v-if="row.sector_dg && row.sector_dg.quadrant_label" size="small" :type="dgTagType(row.sector_dg.quadrant_label)">
                {{ row.sector_dg.quadrant_label }}
              </el-tag>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="代表个股" min-width="220">
            <template #default="{ row }">
              <div class="top-members">
                <span v-for="m in row.top_members" :key="m.code" class="member-chip">
                  {{ m.name }}
                  <em :class="m.pct_chg >= 0 ? 'up' : 'down'">{{ fmtPct(m.pct_chg) }}</em>
                </span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="110" align="center" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="primary" plain @click.stop="goToStocks(row)">候选个股</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- Tab2 候选个股 -->
      <el-tab-pane label="候选个股" name="stocks">
        <div class="stocks-toolbar">
          <el-select
            v-model="selectedIndustry"
            filterable
            clearable
            placeholder="选择行业 / 概念"
            class="industry-select"
            @change="loadCandidates"
          >
            <el-option
              v-for="ind in industries"
              :key="ind.industry"
              :label="`${ind.industry}（${ind.member_count}）`"
              :value="ind.industry"
            />
          </el-select>
          <el-button :icon="Refresh" :loading="stockLoading" @click="loadCandidates">计算候选</el-button>
          <span class="stocks-hint">行业成分股多因子打分 · top {{ selectedIndustry ? limit : 0 }} · ΔG 过滤 + 三买三卖择时预览</span>
        </div>

        <div v-if="sectorDg && sectorDg.quadrant_label" class="sector-dg-banner" :class="`dg-${dgTagType(sectorDg.quadrant_label)}`">
          <el-tag size="small" :type="dgTagType(sectorDg.quadrant_label)" effect="dark">
            {{ selectedIndustry }} · 行业ΔG景气
          </el-tag>
          <span class="dg-label">{{ sectorDg.quadrant_label }}</span>
          <span class="dg-metric" v-if="sectorDg.avg_g != null">平均G {{ sectorDg.avg_g }}%</span>
          <span class="dg-metric" v-if="sectorDg.avg_dg != null">平均ΔG {{ sectorDg.avg_dg }}</span>
          <span class="dg-metric" v-if="sectorDg.data_count != null">数据 {{ sectorDg.data_count }}/{{ sectorDg.member_count }}</span>
        </div>

        <el-table
          :data="candidates"
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
              <span :class="row.pct_chg >= 0 ? 'up' : 'down'">{{ fmtPct(row.pct_chg) }}</span>
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
                      <el-tooltip
                        :content="auxTooltip(row)"
                        placement="top"
                        :disabled="!row.auxiliary"
                      >
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
                        <el-tooltip
                          :content="row.aux_warnings.join('；')"
                          placement="top"
                          :disabled="row.aux_warnings.length <= 2"
                        >
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
              <span :class="row.momentum_20d >= 0 ? 'up' : 'down'">{{ fmtPct(row.momentum_20d) }}</span>
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
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { candidateApi, type IndustryItem, type CandidateStock, type SectorDg } from '@/api/candidate'

const activeTab = ref('industries')
const loading = ref(false)
const stockLoading = ref(false)
const asOf = ref('')
const industries = ref<IndustryItem[]>([])
const selectedIndustry = ref('')
const candidates = ref<CandidateStock[]>([])
const sectorDg = ref<SectorDg | null>(null)
const limit = 30

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

async function refreshIndustries() {
  loading.value = true
  try {
    const res = await candidateApi.industries(100)
    industries.value = res.data?.industries || []
    asOf.value = res.data?.as_of || ''
  } catch (e) {
    ElMessage.error('加载强势行业失败')
  } finally {
    loading.value = false
  }
}

function goToStocks(row: IndustryItem) {
  selectedIndustry.value = row.industry
  activeTab.value = 'stocks'
  loadCandidates()
}

async function loadCandidates() {
  if (!selectedIndustry.value) {
    ElMessage.warning('请先选择行业')
    return
  }
  stockLoading.value = true
  sectorDg.value = null
  try {
    const res = await candidateApi.stocks(selectedIndustry.value, limit)
    candidates.value = res.data?.items || []
    sectorDg.value = res.data?.sector_dg || null
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
  refreshIndustries()
})
</script>

<style scoped>
.candidate-page {
  padding: 24px;
  max-width: 1200px;
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
.score-cell, .qscore {
  display: flex;
  align-items: center;
  gap: 8px;
}
.aux-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}
.aux-cell .el-progress {
  flex: 1;
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
.score-cell .el-progress, .qscore .el-progress {
  flex: 1;
}
.score-num {
  min-width: 36px;
  text-align: right;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.score-val {
  font-weight: 700;
  font-size: 15px;
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
.industry-name {
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.top-members {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.member-chip {
  background: var(--el-fill-color-light);
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 12px;
  color: var(--el-text-color-primary);
}
.member-chip em {
  font-style: normal;
  margin-left: 4px;
}
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
.muted {
  color: var(--el-text-color-placeholder);
}
</style>
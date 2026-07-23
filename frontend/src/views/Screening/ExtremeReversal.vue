<template>
  <div class="extreme-reversal">
    <!-- 页面标题 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><TrendCharts /></el-icon>
        极端情绪反转
      </h1>
      <p class="page-description">
        连续跌停后恐慌超跌、基本面未恶化时博弈超跌反弹的极端反转策略
      </p>
    </div>

    <!-- 策略原理卡片 -->
    <el-card class="strategy-intro" shadow="never">
      <template #header>
        <div class="card-header">
          <div style="display: flex; align-items: center; gap: 12px;">
            <el-icon><InfoFilled /></el-icon>
            <span class="panel-title">策略原理</span>
            <el-tag type="danger" size="small" effect="plain">超跌反弹/恐慌反转</el-tag>
          </div>
        </div>
      </template>
      <div class="strategy-detail">
        <p class="strategy-overview">
          <strong>核心逻辑：</strong>当股票因突发利空或市场恐慌出现<strong>连续跌停</strong>，价格短期内大幅下挫，
          但公司基本面并未发生实质性恶化时，恐慌盘出尽后往往出现技术性反弹。
          本策略在跌停打开、抛压衰竭的关键位置博弈超跌反弹。
        </p>
        <p class="strategy-overview" style="margin-top: 12px;">
          <strong>关键信号：</strong>连续跌停天数≥2、累计跌幅≥15%、PE/PB分位处于历史低位（&lt;30%）、
          量能萎缩显示抛压减弱、信号类型分为左侧潜伏与右侧确认两种。
        </p>
        <p class="strategy-overview" style="margin-top: 12px;">
          <strong>风险提示：</strong>极端反转属于逆向博弈，反弹幅度不确定，需严格设置止损（跌破买入价5%立即止损），
          不追高、不重仓、不留隔夜重仓，避免遇到基本面真实恶化的"假反转"。
        </p>
      </div>
    </el-card>

    <!-- 参数配置 -->
    <el-card class="params-panel" shadow="never" style="margin-top: 16px;">
      <template #header>
        <div class="card-header">
          <div style="display: flex; align-items: center; gap: 12px;">
            <el-icon><Search /></el-icon>
            <span class="panel-title">参数配置</span>
          </div>
        </div>
      </template>

      <el-form :model="params" label-position="top" size="default" class="params-form">
        <el-row :gutter="32">
          <el-col :span="8">
            <el-form-item label="最低评分(100分制)">
              <el-slider v-model="params.min_score" :min="0" :max="100" :step="5" show-stops />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="返回数量限制">
              <el-input-number v-model="params.limit" :min="10" :max="200" :step="10" style="width: 100%;" />
            </el-form-item>
          </el-col>
        </el-row>

        <div class="form-actions">
          <el-button type="primary" :loading="loading" @click="doScan" size="large">
            <el-icon><Search /></el-icon>
            开始扫描
          </el-button>
          <el-button :loading="loading" @click="resetParams" size="large">
            <el-icon><Refresh /></el-icon>
            重置参数
          </el-button>
        </div>
      </el-form>
    </el-card>

    <!-- Tab切换 -->
    <el-tabs v-model="activeTab" style="margin-top: 16px;">
      <!-- 扫描结果Tab -->
      <el-tab-pane label="扫描结果" name="scan">
        <el-card class="result-panel" shadow="never">
          <template #header>
            <div class="card-header">
              <div style="display: flex; align-items: center; gap: 12px;">
                <el-icon><List /></el-icon>
                <span class="panel-title">扫描结果</span>
                <el-tag v-if="results.length > 0" type="success" size="small" effect="plain">
                  找到 {{ results.length }} 只符合条件的股票
                </el-tag>
                <el-tag v-if="tookMs" type="info" size="small" effect="plain">
                  耗时 {{ (tookMs / 1000).toFixed(1) }}s
                </el-tag>
              </div>
            </div>
          </template>

          <div v-if="!loading && results.length === 0 && !hasSearched" class="empty-state">
            <el-empty description="调整参数后点击开始扫描">
              <el-button type="primary" @click="doScan">立即扫描</el-button>
            </el-empty>
          </div>

          <el-table
            v-if="results.length > 0"
            :data="results"
            v-loading="loading"
            element-loading-text="扫描中..."
            stripe
            :height="tableHeight"
            row-key="code"
            style="width: 100%"
          >
            <el-table-column prop="code" label="代码" width="90" fixed="left">
              <template #default="{ row }">
                <router-link :to="`/stocks/${row.code}`" class="stock-code">{{ row.code }}</router-link>
              </template>
            </el-table-column>
            <el-table-column prop="name" label="名称" width="110" fixed="left">
              <template #default="{ row }">
                <router-link :to="`/stocks/${row.code}`" class="stock-name">{{ row.name }}</router-link>
              </template>
            </el-table-column>
            <el-table-column prop="industry" label="行业" width="110" />
            <el-table-column prop="close" label="现价" width="90" sortable>
              <template #default="{ row }">
                <span class="price">{{ formatNum(row.close) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="pct_chg" label="涨跌幅" width="100" sortable>
              <template #default="{ row }">
                <span :class="['pct', (row.pct_chg ?? 0) >= 0 ? 'up' : 'down']">
                  {{ (row.pct_chg ?? 0) >= 0 ? '+' : '' }}{{ (row.pct_chg ?? 0).toFixed(2) }}%
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="consecutive_limit_down_days" label="连续跌停天数" width="120" sortable>
              <template #default="{ row }">{{ row.consecutive_limit_down_days ?? '-' }}天</template>
            </el-table-column>
            <el-table-column prop="cumulative_drop" label="累计跌幅" width="110" sortable>
              <template #default="{ row }">
                <span class="pct down">-{{ formatNum(row.cumulative_drop) }}%</span>
              </template>
            </el-table-column>
            <el-table-column prop="pe_percentile" label="PE分位" width="100" sortable>
              <template #default="{ row }">{{ formatNum(row.pe_percentile) }}%</template>
            </el-table-column>
            <el-table-column prop="pb_percentile" label="PB分位" width="100" sortable>
              <template #default="{ row }">{{ formatNum(row.pb_percentile) }}%</template>
            </el-table-column>
            <el-table-column prop="signal_type" label="信号类型" width="110">
              <template #default="{ row }">
                <el-tag :type="getSignalTypeTag(row.signal_type)" size="small">
                  {{ row.signal_type || '-' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="score" label="综合评分" width="120" sortable fixed="right">
              <template #default="{ row }">
                <el-progress :percentage="row.score" :color="getScoreColor(row.score)" :stroke-width="12" />
              </template>
            </el-table-column>
            <el-table-column label="风险" width="100" fixed="right">
              <template #default="{ row }">
                <el-tag v-if="row.risk_info" :type="getRiskTagType(row.risk_info.risk_level)" size="small">
                  {{ getRiskLabel(row.risk_info) }}
                </el-tag>
                <span v-else style="color:#909399;font-size:11px;">未扫描</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="140" fixed="right">
              <template #default="{ row }">
                <router-link :to="{ path: '/analysis/single', query: { stock: row.code } }" class="table-link">分析</router-link>
                <el-button type="success" link @click="addToFavorites(row)">自选</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- 回测分析Tab -->
      <el-tab-pane label="回测分析" name="backtest">
        <el-card shadow="never" style="margin-bottom: 16px;">
          <template #header>
            <div class="card-header">
              <div style="display: flex; align-items: center; gap: 12px;">
                <el-icon><DataLine /></el-icon>
                <span class="panel-title">回测参数配置</span>
              </div>
            </div>
          </template>

          <el-form :model="backtestParams" label-position="top" size="default" class="params-form">
            <el-row :gutter="32">
              <el-col :span="6">
                <el-form-item label="开始日期">
                  <el-date-picker v-model="backtestParams.start_date" type="date" format="YYYY-MM-DD" value-format="YYYY-MM-DD" placeholder="选择开始日期" style="width: 100%;" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="结束日期">
                  <el-date-picker v-model="backtestParams.end_date" type="date" format="YYYY-MM-DD" value-format="YYYY-MM-DD" placeholder="选择结束日期" style="width: 100%;" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="最大持有天数">
                  <el-input-number v-model="backtestParams.hold_days" :min="1" :max="60" :step="1" style="width: 100%;" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="每次选前N只">
                  <el-input-number v-model="backtestParams.top_n" :min="1" :max="50" :step="1" style="width: 100%;" />
                </el-form-item>
              </el-col>
            </el-row>

            <div class="form-actions">
              <el-button type="success" :loading="backtestLoading" @click="doBacktest" size="large">
                <el-icon><DataLine /></el-icon>
                开始回测
              </el-button>
              <el-button :loading="backtestLoading" @click="resetBacktestParams" size="large">
                <el-icon><Refresh /></el-icon>
                重置参数
              </el-button>
            </div>
          </el-form>
        </el-card>

        <el-card v-if="!backtestResult && !backtestLoading" shadow="never">
          <el-empty description="配置回测参数后点击开始回测，回测可能耗时2-5分钟">
            <el-button type="success" @click="doBacktest">立即回测</el-button>
          </el-empty>
        </el-card>

        <el-card v-if="backtestLoading" shadow="never" v-loading="backtestLoading" element-loading-text="正在回测，请耐心等待（可能需要2-5分钟）...">
          <div style="height: 200px;"></div>
        </el-card>

        <div v-if="backtestResult">
          <!-- 核心指标 -->
          <el-row :gutter="16">
            <el-col :span="6"><el-card shadow="never" class="metric-card"><div class="metric-label">总交易次数</div><div class="metric-value">{{ backtestResult.total_trades }}</div></el-card></el-col>
            <el-col :span="6"><el-card shadow="never" class="metric-card"><div class="metric-label">胜率</div><div class="metric-value" :class="backtestResult.win_rate >= 50 ? 'up' : 'down'">{{ backtestResult.win_rate.toFixed(2) }}%</div></el-card></el-col>
            <el-col :span="6"><el-card shadow="never" class="metric-card"><div class="metric-label">平均收益</div><div class="metric-value" :class="backtestResult.avg_return >= 0 ? 'up' : 'down'">{{ backtestResult.avg_return >= 0 ? '+' : '' }}{{ backtestResult.avg_return.toFixed(2) }}%</div></el-card></el-col>
            <el-col :span="6"><el-card shadow="never" class="metric-card"><div class="metric-label">最大回撤</div><div class="metric-value down">{{ backtestResult.max_drawdown.toFixed(2) }}%</div></el-card></el-col>
          </el-row>
          <el-row :gutter="16" style="margin-top: 16px;">
            <el-col :span="6"><el-card shadow="never" class="metric-card"><div class="metric-label">总收益</div><div class="metric-value" :class="backtestResult.total_return >= 0 ? 'up' : 'down'">{{ backtestResult.total_return >= 0 ? '+' : '' }}{{ backtestResult.total_return.toFixed(2) }}%</div></el-card></el-col>
            <el-col :span="6"><el-card shadow="never" class="metric-card"><div class="metric-label">盈亏比</div><div class="metric-value" :class="backtestResult.profit_loss_ratio >= 1 ? 'up' : 'down'">{{ backtestResult.profit_loss_ratio.toFixed(2) }}</div></el-card></el-col>
            <el-col :span="6"><el-card shadow="never" class="metric-card"><div class="metric-label">夏普比率</div><div class="metric-value" :class="backtestResult.sharpe_ratio >= 1 ? 'up' : 'down'">{{ backtestResult.sharpe_ratio.toFixed(2) }}</div></el-card></el-col>
            <el-col :span="6"><el-card shadow="never" class="metric-card"><div class="metric-label">年化收益</div><div class="metric-value" :class="backtestResult.annualized_return >= 0 ? 'up' : 'down'">{{ backtestResult.annualized_return >= 0 ? '+' : '' }}{{ backtestResult.annualized_return.toFixed(2) }}%</div></el-card></el-col>
          </el-row>

          <!-- 卖出原因统计 -->
          <el-card shadow="never" style="margin-top: 16px;">
            <template #header><div class="card-header"><span>卖出原因统计</span></div></template>
            <el-table :data="sellReasonStatsList" stripe style="width: 100%">
              <el-table-column prop="sell_reason" label="卖出原因" width="180" />
              <el-table-column prop="count" label="交易次数" width="120" />
              <el-table-column prop="win_rate" label="胜率" width="120">
                <template #default="{ row }">
                  <span :class="['pct', row.win_rate >= 50 ? 'up' : 'down']">{{ row.win_rate.toFixed(2) }}%</span>
                </template>
              </el-table-column>
              <el-table-column prop="avg_return" label="平均收益">
                <template #default="{ row }">
                  <span :class="['pct', row.avg_return >= 0 ? 'up' : 'down']">{{ row.avg_return >= 0 ? '+' : '' }}{{ row.avg_return.toFixed(2) }}%</span>
                </template>
              </el-table-column>
            </el-table>
          </el-card>

          <!-- 盈利最多交易 -->
          <el-card shadow="never" style="margin-top: 16px;">
            <template #header><div class="card-header"><span>盈利最多交易</span></div></template>
            <el-table :data="backtestResult.top_trades" stripe style="width: 100%">
              <el-table-column prop="code" label="代码" width="90" />
              <el-table-column prop="name" label="名称" width="100" />
              <el-table-column prop="buy_date" label="买入日期" width="110" />
              <el-table-column prop="sell_date" label="卖出日期" width="110" />
              <el-table-column prop="buy_price" label="买入价" width="90">
                <template #default="{ row }">{{ formatNum(row.buy_price) }}</template>
              </el-table-column>
              <el-table-column prop="sell_price" label="卖出价" width="90">
                <template #default="{ row }">{{ formatNum(row.sell_price) }}</template>
              </el-table-column>
              <el-table-column prop="return_pct" label="收益率" width="110" sortable>
                <template #default="{ row }">
                  <span :class="['pct', row.return_pct >= 0 ? 'up' : 'down']">{{ row.return_pct >= 0 ? '+' : '' }}{{ row.return_pct.toFixed(2) }}%</span>
                </template>
              </el-table-column>
              <el-table-column prop="sell_reason" label="卖出原因" width="120" />
            </el-table>
          </el-card>

          <!-- 亏损最多交易 -->
          <el-card shadow="never" style="margin-top: 16px;">
            <template #header><div class="card-header"><span>亏损最多交易</span></div></template>
            <el-table :data="backtestResult.worst_trades" stripe style="width: 100%">
              <el-table-column prop="code" label="代码" width="90" />
              <el-table-column prop="name" label="名称" width="100" />
              <el-table-column prop="buy_date" label="买入日期" width="110" />
              <el-table-column prop="sell_date" label="卖出日期" width="110" />
              <el-table-column prop="buy_price" label="买入价" width="90">
                <template #default="{ row }">{{ formatNum(row.buy_price) }}</template>
              </el-table-column>
              <el-table-column prop="sell_price" label="卖出价" width="90">
                <template #default="{ row }">{{ formatNum(row.sell_price) }}</template>
              </el-table-column>
              <el-table-column prop="return_pct" label="收益率" width="110" sortable>
                <template #default="{ row }">
                  <span :class="['pct', row.return_pct >= 0 ? 'up' : 'down']">{{ row.return_pct >= 0 ? '+' : '' }}{{ row.return_pct.toFixed(2) }}%</span>
                </template>
              </el-table-column>
              <el-table-column prop="sell_reason" label="卖出原因" width="120" />
            </el-table>
          </el-card>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { TrendCharts, InfoFilled, Refresh, Search, List, DataLine } from '@element-plus/icons-vue'
import { screeningApi, type RetailScanReq, type RetailBacktestReq, type RetailScanResp, type RetailBacktestResp } from '@/api/screening'
import { favoritesApi } from '@/api/favorites'

const activeTab = ref<'scan' | 'backtest'>('scan')

const loading = ref(false)
const results = ref<RetailScanResp['items']>([])
const tookMs = ref(0)
const hasSearched = ref(false)

const defaultParams = { min_score: 40, limit: 50 }
const params = reactive<RetailScanReq>({ ...defaultParams })

const resetParams = () => {
  Object.assign(params, defaultParams)
  ElMessage.info('参数已重置')
}

const doScan = async () => {
  loading.value = true
  hasSearched.value = true
  results.value = []
  tookMs.value = 0
  try {
    const resp = await screeningApi.scanExtremeReversal(params)
    results.value = resp.items
    tookMs.value = resp.took_ms || 0
    if (resp.items.length > 0) {
      ElMessage.success(`找到 ${resp.items.length} 只符合条件的股票`)
    } else {
      ElMessage.warning('未找到符合条件的股票，请调整参数后重试')
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '扫描失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

// 回测
const backtestLoading = ref(false)
const backtestResult = ref<RetailBacktestResp | null>(null)

const defaultBacktestParams = {
  start_date: '',
  end_date: '',
  hold_days: 10,
  top_n: 10,
  min_score: 40,
  limit: 50
}
const backtestParams = reactive<RetailBacktestReq>({ ...defaultBacktestParams })

const resetBacktestParams = () => {
  Object.assign(backtestParams, defaultBacktestParams)
  ElMessage.info('回测参数已重置')
}

const sellReasonStatsList = computed(() => {
  if (!backtestResult.value?.sell_reason_stats) return []
  return Object.entries(backtestResult.value.sell_reason_stats).map(([sell_reason, v]) => ({
    sell_reason,
    count: v.count,
    win_rate: v.win_rate,
    avg_return: v.avg_return
  }))
})

const doBacktest = async () => {
  if (!backtestParams.start_date || !backtestParams.end_date) {
    ElMessage.warning('请选择回测开始和结束日期')
    return
  }
  backtestLoading.value = true
  backtestResult.value = null
  activeTab.value = 'backtest'
  try {
    const payload: RetailBacktestReq = {
      ...backtestParams,
      min_score: params.min_score,
      limit: params.limit
    }
    const resp = await screeningApi.backtestExtremeReversal(payload)
    backtestResult.value = resp
    if (resp.total_trades > 0) {
      ElMessage.success(`回测完成，共 ${resp.total_trades} 笔交易，胜率 ${resp.win_rate.toFixed(2)}%`)
    } else {
      ElMessage.warning('回测完成，但未产生交易，请调整参数或日期范围')
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '回测失败，请稍后重试')
  } finally {
    backtestLoading.value = false
  }
}

const addToFavorites = async (row: any) => {
  try {
    await favoritesApi.add({ stock_code: row.code, stock_name: row.name || '', market: 'A股' })
    ElMessage.success(`已添加 ${row.name}(${row.code}) 到自选`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '添加自选失败')
  }
}

const getSignalTypeTag = (type?: string) => {
  if (!type) return ''
  if (type.includes('右侧') || type.includes('确认')) return 'success'
  if (type.includes('左侧') || type.includes('潜伏')) return 'warning'
  if (type.includes('观察')) return 'info'
  return ''
}

const getScoreColor = (score: number) => {
  if (score >= 80) return '#67C23A'
  if (score >= 60) return '#E6A23C'
  if (score >= 40) return '#F56C6C'
  return '#909399'
}

const getRiskTagType = (level: string) => {
  if (level === 'high') return 'danger'
  if (level === 'medium') return 'warning'
  return 'success'
}

const getRiskLabel = (riskInfo: any) => {
  if (!riskInfo || riskInfo.risk_count === 0) return '安全'
  const names = riskInfo.risks.map((r: any) => r.risk_name.replace('风险', ''))
  return names.join('/')
}

const formatNum = (n: any) => (typeof n === 'number' ? n.toFixed(2) : '-')

const windowHeight = ref(window.innerHeight)
function handleResize() { windowHeight.value = window.innerHeight }
const tableHeight = computed(() => Math.max(400, windowHeight.value - 420))

onMounted(() => { window.addEventListener('resize', handleResize) })
onUnmounted(() => { window.removeEventListener('resize', handleResize) })
</script>

<style lang="scss" scoped>
.extreme-reversal { padding: 16px; }

.page-header {
  margin-bottom: 20px;
  .page-title {
    font-size: 24px; font-weight: 600; margin: 0 0 8px 0;
    display: flex; align-items: center; gap: 10px;
    color: var(--el-text-color-primary);
  }
  .page-description { margin: 0; color: var(--el-text-color-secondary); font-size: 14px; }
}

.panel-title { font-size: 15px; font-weight: 600; color: var(--el-text-color-primary); }

.card-header {
  display: flex; justify-content: space-between; align-items: center; width: 100%;
}

.strategy-detail .strategy-overview {
  font-size: 14px; color: var(--el-text-color-regular); line-height: 1.7; margin-bottom: 0;
}

.params-form {
  :deep(.el-form-item) { margin-bottom: 18px; }
  :deep(.el-form-item__label) { font-weight: 500; color: var(--el-text-color-regular); }
}

.form-actions {
  display: flex; justify-content: center; gap: 16px;
  margin-top: 8px; padding-top: 16px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.result-panel {
  .empty-state { padding: 40px 0; }
  .stock-code, .stock-name {
    cursor: pointer; color: var(--el-color-primary);
    text-decoration: none; font-size: 13px;
    &:hover { text-decoration: underline; }
  }
  .price { font-family: 'Monaco', 'Consolas', monospace; font-weight: 500; }
  .pct {
    font-family: 'Monaco', 'Consolas', monospace; font-weight: 500;
    &.up { color: var(--el-color-danger); }
    &.down { color: var(--el-color-success); }
  }
}

.table-link {
  color: var(--el-color-primary); text-decoration: none;
  cursor: pointer; margin-right: 8px; font-size: 13px;
  &:hover { color: var(--el-color-primary-light-3); text-decoration: underline; }
}

.metric-card {
  text-align: center; border-radius: 8px;
  :deep(.el-card__body) { padding: 16px 12px; }
  .metric-label { font-size: 13px; color: var(--el-text-color-secondary); margin-bottom: 10px; }
  .metric-value {
    font-size: 24px; font-weight: 700;
    font-family: 'Monaco', 'Consolas', monospace;
    color: var(--el-text-color-primary); line-height: 1.2;
    &.up { color: var(--el-color-danger); }
    &.down { color: var(--el-color-success); }
  }
}
</style>

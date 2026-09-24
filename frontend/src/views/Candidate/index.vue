<template>
  <div class="candidate-page app-page">
    <!-- 顶部横幅：三层确认主线 -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><TrendCharts /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">股票筛选</h2>
          <p class="page-hero-sub">三层确认：赛道（行业/概念趋势）→ 标的（个股趋势）→ 时机（三买三卖）</p>
        </div>
      </div>
      <div class="page-hero-meta">
        <span v-if="screenAsOf" class="page-hero-tag">
          <el-icon :size="14"><Calendar /></el-icon> 数据日 {{ screenAsOf }}
        </span>
        <el-button :icon="Refresh" :loading="refreshingAll" @click="refreshAll">刷新</el-button>
      </div>
    </div>

    <!-- ① 市场温度：大盘冷暖决定进攻节奏（来自个股趋势 · 全市场 30 日帧） -->
    <section class="flow-block">
      <div class="flow-head">
        <span class="flow-step">①</span>
        <div class="flow-title">
          市场温度
          <span class="flow-sub">个股趋势 · 全市场帧（{{ trendAsOf || '—' }}）</span>
        </div>
        <span class="flow-hint">先看大盘冷暖，再定进攻方向</span>
      </div>
      <div class="kpi-row">
        <div class="kpi-cell">
          <div class="kpi-label">个股总数</div>
          <div class="kpi-value accent">{{ widthTotal ?? '—' }}</div>
          <div class="kpi-sub">全市场 A 股（有成交额）</div>
        </div>
        <div class="kpi-cell">
          <div class="kpi-label">上涨 / 下跌</div>
          <div class="kpi-value">
            <span class="up">{{ widthUp ?? '—' }}</span><span class="kpi-sep">/</span><span class="down">{{ widthDown ?? '—' }}</span>
          </div>
          <div class="kpi-sub">当前帧涨跌家数</div>
        </div>
        <div class="kpi-cell">
          <div class="kpi-label">平均涨幅</div>
          <div class="kpi-value accent" :class="clsByVal(widthAvg, '')">{{ fmtPct(widthAvg) }}</div>
          <div class="kpi-sub">当前帧全市场均值</div>
        </div>
        <div class="kpi-cell">
          <div class="kpi-label">上涨占比</div>
          <div class="kpi-value accent" :class="clsByVal(widthUpRatio, '')">{{ widthUpRatio == null ? '—' : fmtNum(widthUpRatio, 1) + '%' }}</div>
          <div class="kpi-sub">赚钱效应 · 强弱分水岭 50%</div>
        </div>
      </div>
    </section>

    <!-- ② 标的精选：个股趋势帧确认 + 三买三卖时机（默认各行业三买 TOP） -->
    <section ref="stockSection" class="flow-block">
      <div class="flow-head">
        <span class="flow-step">②</span>
        <div class="flow-title">
          标的精选
          <span class="flow-sub">个股趋势列（主力净流入/5日/连板）附于候选 · 趋势数据日 {{ trendAsOf || '—' }}</span>
        </div>
        <div class="flow-actions">
          <el-select
            v-model="selectedIndustry"
            filterable
            clearable
            placeholder="全部行业（各行业三买 TOP）"
            class="industry-select"
            @change="loadCandidates"
          >
            <el-option v-for="ind in industryOptions" :key="ind" :label="ind" :value="ind" />
          </el-select>
          <el-button :icon="Refresh" :loading="stockLoading" @click="loadCandidates">计算候选</el-button>
          <el-radio-group v-model="signalFilter" class="signal-filter" size="small">
            <el-radio-button value="buy">三买 {{ signalStats.buy }}</el-radio-button>
            <el-radio-button value="all">全部 {{ signalStats.all }}</el-radio-button>
            <el-radio-button value="B1">左侧买点 {{ signalStats.B1 }}</el-radio-button>
            <el-radio-button value="B2">突破买点 {{ signalStats.B2 }}</el-radio-button>
            <el-radio-button value="B3">回踩买点 {{ signalStats.B3 }}</el-radio-button>
            <el-radio-button value="S1">加速卖点 {{ signalStats.S1 }}</el-radio-button>
            <el-radio-button value="S2">跌破卖点 {{ signalStats.S2 }}</el-radio-button>
            <el-radio-button value="S3">清仓卖出 {{ signalStats.S3 }}</el-radio-button>
          </el-radio-group>
        </div>
      </div>

      <div class="split-grid scatter-split">
        <!-- 质量轴 -->
        <div class="panel">
          <div class="panel-title">动量 × ROE（质量轴 · 气泡大小=市值，颜色=当日涨跌）</div>
          <div v-if="scatterData.length > 1">
            <v-chart class="chart chart--scatter" :option="scatterOption" autoresize />
          </div>
          <el-empty v-else :image-size="48" description="暂无候选个股" />
          <div class="panel-tip">右上角 = 高动量 + 高 ROE 的质量优等生</div>
        </div>
        <!-- 趋势确认轴 -->
        <div class="panel">
          <div class="panel-title">涨跌 × 主力净流入（趋势确认轴 · 点击圆点看个股详情）</div>
          <div v-if="candidateTrendCount > 0">
            <v-chart class="chart chart--scatter" :option="candidateTrendOption" autoresize @click="onTrendChartClick" />
          </div>
          <el-empty v-else :image-size="48" description="候选暂无趋势帧数据（外部行情域受限）" />
          <div class="board-tips">
            <span v-for="(t, i) in BOARD_TIPS" :key="'c' + i" class="bt-item">
              <i class="bt-dot" :class="'dot-' + i" />{{ t }}
            </span>
          </div>
        </div>
      </div>

      <div class="stocks-hint">{{ stocksHint }} · {{ signalFilter === 'buy' ? '仅三买' : signalFilter === 'all' ? '三买三卖' : signalFilter }} · 显示 {{ filteredCandidates.length }} 只</div>
      <div class="table-scroll">
        <el-table
          :data="filteredCandidates"
          v-loading="stockLoading"
          stripe
          :empty-text="selectedIndustry ? '该行业当前无三买信号，可切「全部」查看三买三卖' : '市场当前无三买买入信号（可切换行业，或稍后再看）'"
          class="candidate-table app-table app-table--trades"
        >
          <el-table-column prop="code" label="代码" width="90">
            <template #default="{ row }">
              <router-link target="_blank" rel="noopener" :to="`/stocks/${row.code}`" class="stock-code">{{ row.code }}</router-link>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" min-width="100">
            <template #default="{ row }">
              <router-link target="_blank" rel="noopener" :to="`/stocks/${row.code}`" class="stock-name">{{ row.name }}</router-link>
            </template>
          </el-table-column>
          <el-table-column label="行业" min-width="90">
            <template #default="{ row }">
              <span class="muted">{{ row.industry || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="涨跌幅" prop="pct_chg" width="90" align="right" sortable :sort-method="(a, b) => (a.pct_chg||0) - (b.pct_chg||0)">
            <template #default="{ row }">
              <span :class="(row.pct_chg || 0) >= 0 ? 'up' : 'down'">{{ fmtPctF(row.pct_chg) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="趋势象限" width="110">
            <template #default="{ row }">
              <span v-if="trendTagOf(row.code)" class="trend-tag" :class="trendTagOf(row.code)!.cls">
                <i class="tt-dot" />{{ trendTagOf(row.code)!.label }}
              </span>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="主力净流入(亿)" width="120" align="right" sortable :sort-method="(a, b) => (mainFlowOf(a.code)||0) - (mainFlowOf(b.code)||0)">
            <template #default="{ row }">
              <span v-if="mainFlowOf(row.code) != null" :class="(mainFlowOf(row.code) || 0) >= 0 ? 'up' : 'down'">{{ fmtSign(mainFlowOf(row.code), 1) }}</span>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="5日涨跌" width="95" align="right" sortable :sort-method="(a, b) => (d5Of(a.code)||0) - (d5Of(b.code)||0)">
            <template #default="{ row }">
              <span v-if="d5Of(row.code) != null" :class="(d5Of(row.code) || 0) >= 0 ? 'up' : 'down'">{{ fmtPct(d5Of(row.code), 1) }}</span>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="连板" width="70" align="center">
            <template #default="{ row }">
              <span v-if="boardOf(row.code) != null" :class="boardOf(row.code)! > 0 ? 'up' : 'muted'">{{ boardOf(row.code)! > 0 ? boardOf(row.code) + ' 板' : '未涨停' }}</span>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="ΔG 象限" width="110">
            <template #default="{ row }">
              <el-tag v-if="row.dg_quadrant" size="small" :type="dgTagType(row.dg_quadrant)">{{ row.dg_quadrant }}</el-tag>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="择时信号" width="110">
            <template #default="{ row }">
              <el-tag v-if="row.signal_type" size="small" :type="signalTagType(row.signal_type)">{{ row.signal_label || row.signal_type }}</el-tag>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="预警" min-width="130">
            <template #default="{ row }">
              <template v-if="row.aux_warnings && row.aux_warnings.length">
                <el-tooltip :content="row.aux_warnings.join('；')" placement="top">
                  <div class="warn-cell">
                    <el-tag v-for="w in row.aux_warnings.slice(0, 1)" :key="w" size="small" type="warning" effect="light" class="warn-tag">{{ w }}</el-tag>
                    <el-tag v-if="row.aux_warnings.length > 1" size="small" type="info" effect="plain" class="warn-tag">+{{ row.aux_warnings.length - 1 }}</el-tag>
                  </div>
                </el-tooltip>
              </template>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="20日动量" prop="momentum_20d" width="100" align="right" sortable :sort-method="(a, b) => (a.momentum_20d||0) - (b.momentum_20d||0)">
            <template #default="{ row }">
              <span :class="(row.momentum_20d || 0) >= 0 ? 'up' : 'down'">{{ fmtPctF(row.momentum_20d) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="ROE" prop="roe" width="80" align="right" sortable :sort-method="(a, b) => (a.roe||0) - (b.roe||0)">
            <template #default="{ row }">{{ fmtNum(row.roe) }}%</template>
          </el-table-column>
          <el-table-column label="操作" width="170" fixed="right" align="center">
            <template #default="{ row }">
              <el-button size="small" type="success" plain @click="addFavorite(row)">+ 自选</el-button>
              <el-button size="small" type="primary" plain :loading="aiRow?.code === row.code && aiLoading" :icon="Cpu" @click="doAiAnalyze(row)">AI 分析</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </section>

    <!-- ③ 赛道双确认：行业资金流排序 × 行业/概念趋势象限 -->
    <section class="flow-block">
      <div class="flow-head">
        <span class="flow-step">③</span>
        <div class="flow-title">
          赛道双确认
          <span class="flow-sub">资金流决定排序，趋势象限决定强弱 —— 双维交叉定进攻方向</span>
        </div>
        <div class="flow-actions">
          <el-radio-group v-model="boardScope" size="small" class="board-switch">
            <el-radio-button value="industry">行业趋势</el-radio-button>
            <el-radio-button value="concept">概念趋势</el-radio-button>
          </el-radio-group>
          <el-button size="small" type="primary" :icon="Lightning" :loading="screenRefreshing" @click="loadScreening(true)">实时采集</el-button>
          <el-button size="small" :icon="Refresh" :loading="screenLoading" @click="loadScreening(false)">刷新快照</el-button>
        </div>
      </div>

      <div class="split-grid board-split">
        <!-- 左：行业资金流 -->
        <div class="panel">
          <div class="panel-title">行业主力资金净流入 TOP10（亿元 · 红流入绿流出）</div>
          <div v-if="industryFlowData.length > 0">
            <v-chart class="chart chart--industry" :option="industryFlowOption" autoresize @click="onIndustryChartClick" />
          </div>
          <el-empty v-else-if="!screenLoading && !screenRefreshing" :image-size="48" description="暂无行业资金流数据（点击「实时采集」获取）" />
          <div class="panel-tip">点击柱形或下方列表进入该行业的个股筛选</div>
        </div>

        <!-- 右：行业/概念趋势象限 -->
        <div class="panel">
          <div class="panel-title">{{ boardScope === 'industry' ? '行业' : '概念' }}趋势 · 涨跌 × 主力资金（四象限强弱定位）</div>
          <div v-if="boardReady" class="board-chart">
            <v-chart class="chart chart--board" :option="boardOption" autoresize @click="onBoardChartClick" />
          </div>
          <el-empty v-else :image-size="48" description="趋势象限数据暂不可用（外部行情域受限）" />
          <div class="board-tips">
            <span v-for="(t, i) in BOARD_TIPS" :key="i" class="bt-item">
              <i class="bt-dot" :class="'dot-' + i" />{{ t }}
            </span>
          </div>
          <div v-if="strongBoards.length" class="strong-board">
            <div class="strong-label">强势 {{ boardScope === 'industry' ? '行业' : '概念' }} TOP{{ strongBoards.length }}（点击跳详情）</div>
            <div class="strong-chips">
              <button
                v-for="b in strongBoards"
                :key="b.code"
                class="strong-chip"
                @click="openBoard(b.link)"
              >
                <span class="sc-name">{{ b.name }}</span>
                <span class="sc-pct" :class="(b.pct || 0) >= 0 ? 'up' : 'down'">{{ fmtPct(b.pct, 1) }}</span>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 全行业资金流排名表 -->
      <div class="section-title">行业资金流排名（{{ screenRankings.length }} · 点行进入个股筛选）</div>
      <div class="table-scroll">
        <el-table
          :data="screenRankings"
          v-loading="screenLoading"
          stripe
          empty-text="暂无排名数据"
          class="rank-table app-table app-table--ranking"
          @row-click="goToStockScreening"
        >
          <el-table-column label="排名" width="70" align="center">
            <template #default="{ $index }">
              <span class="rank" :class="rankClass($index)">{{ $index + 1 }}</span>
            </template>
          </el-table-column>
          <el-table-column label="行业" min-width="150">
            <template #default="{ row }">
              <span class="ind-name">{{ row.industry }}</span>
            </template>
          </el-table-column>
          <el-table-column label="代表ETF" min-width="140">
            <template #default="{ row }">
              <span class="etf-name">{{ row.etf_name }}</span>
              <span class="muted etf-code">{{ row.etf_code }}</span>
            </template>
          </el-table-column>
          <el-table-column label="主力净占比" prop="fund_net_inflow_pct" min-width="130" align="right" sortable :sort-method="(a, b) => (a.fund_net_inflow_pct||0) - (b.fund_net_inflow_pct||0)">
            <template #default="{ row }">
              <span :class="(row.fund_net_inflow_pct || 0) >= 0 ? 'up' : 'down'">{{ fmtSign(row.fund_net_inflow_pct) }}%</span>
              <span class="muted">({{ fmtYi(row.fund_net_inflow) }}亿)</span>
            </template>
          </el-table-column>
          <el-table-column label="涨跌幅" prop="pct_chg" width="90" align="right" sortable :sort-method="(a, b) => (a.pct_chg||0) - (b.pct_chg||0)">
            <template #default="{ row }">
              <span :class="(row.pct_chg || 0) >= 0 ? 'up' : 'down'">{{ fmtSign(row.pct_chg) }}%</span>
            </template>
          </el-table-column>
          <el-table-column label="行业净流入(亿)" prop="sector_net_inflow" min-width="120" align="right" sortable :sort-method="(a, b) => (a.sector_net_inflow||0) - (b.sector_net_inflow||0)">
            <template #default="{ row }">
              <span :class="(row.sector_net_inflow || 0) >= 0 ? 'up' : 'down'">{{ fmtNum(row.sector_net_inflow) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="110" align="center" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="primary" plain @click.stop="goToStockScreening(row)">个股筛选</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </section>

    <!-- AI 分析结果弹窗（复用个股趋势的单股 AI 操作结论） -->
    <el-dialog v-model="aiDialog" :title="aiDialogTitle" width="640px" class="ai-dialog" :close-on-click-modal="false">
      <div v-if="aiLoading" class="ai-body ai-loading">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>正在基于四维信号（趋势象限/择时/ΔG/预警）+ 个股趋势帧解读一致性…</span>
      </div>
      <el-alert v-else-if="aiError" :title="aiError" type="error" show-icon :closable="false" class="ai-body" />
      <el-empty v-else-if="aiResult && !aiResult.found" :description="aiResult.message || '未找到该股数据'" />
      <template v-else-if="aiResult">
        <div class="ai-body">
          <div class="ai-head">
            <div class="ai-head-tags">
              <el-tag :color="aiActionColor" effect="dark" size="large">{{ aiResult.action_label }}</el-tag>
              <el-tag :type="aiResult.engine === 'llm' ? 'primary' : 'info'" size="small" effect="plain">
                {{ aiResult.engine === 'llm' ? 'LLM 深度分析' : '规则引擎兜底' }}
              </el-tag>
            </div>
            <div class="ai-score">
              <el-progress :percentage="aiScorePct" :color="aiActionColor" :stroke-width="10" />
              <span class="ai-score-txt">综合评分 {{ aiResult.score }} 分</span>
            </div>
          </div>

          <!-- 维度一致性（融合改造核心：四维共振/背离解读） -->
          <div v-if="aiResult.consistency" class="ai-block consistency-block">
            <div class="ai-block-title">
              维度一致性
              <span class="consistency-tag" :class="'cs-' + aiResult.consistency">{{ aiResult.consistency_label }}</span>
              <span class="consistency-engine">{{ aiResult.engine === 'llm' ? 'LLM 解读' : '规则判定' }}</span>
            </div>
            <p v-if="aiResult.consistency_summary" class="ai-summary cs-summary">{{ aiResult.consistency_summary }}</p>
            <div v-if="aiResult.dimensions?.length" class="cs-grid">
              <div
                v-for="(d, i) in aiResult.dimensions"
                :key="i"
                class="cs-cell"
                :class="d.support > 0 ? 'cs-up' : (d.support < 0 ? 'cs-down' : 'cs-flat')"
              >
                <div class="cs-head">
                  <span class="cs-name">{{ d.name }}</span>
                  <span class="cs-flag">{{ d.support > 0 ? '偏多' : (d.support < 0 ? '偏空' : '中性') }}</span>
                </div>
                <div class="cs-value">{{ d.value || '—' }}</div>
                <div class="cs-view">{{ d.view }}</div>
              </div>
            </div>
            <div v-if="aiResult.conflicts?.length" class="cs-conflicts">
              <div v-for="(c, i) in aiResult.conflicts" :key="'cf' + i" class="cs-conflict">{{ c }}</div>
            </div>
          </div>

          <p class="ai-summary">{{ aiResult.summary }}</p>
          <div v-if="aiResult.reasons?.length" class="ai-block">
            <div class="ai-block-title">判断要点</div>
            <ul class="ai-list"><li v-for="(r, i) in aiResult.reasons" :key="'r' + i">{{ r }}</li></ul>
          </div>
          <div v-if="aiResult.risks?.length" class="ai-block">
            <div class="ai-block-title">风险提示</div>
            <ul class="ai-list ai-risk"><li v-for="(r, i) in aiResult.risks" :key="'k' + i">{{ r }}</li></ul>
          </div>
          <div class="ai-block">
            <div class="ai-block-title">今日数据（个股趋势帧 · {{ aiResult.as_of }}）</div>
            <div class="ai-table">
              <div v-for="cell in aiTodayCells" :key="cell.label" class="ai-cell">
                <span class="ai-cell-label">{{ cell.label }}</span>
                <b :class="cell.cls">{{ cell.text }}</b>
              </div>
            </div>
          </div>
          <div v-if="aiResult.data?.recent_trend?.length" class="ai-block">
            <div class="ai-block-title">近期走势（最近 {{ aiResult.data.recent_trend.length }} 个交易日）</div>
            <div class="ai-trend">
              <span v-for="t in aiResult.data.recent_trend" :key="t.date" class="ai-trend-item" :class="(t.pct ?? 0) >= 0 ? 'up' : 'down'">
                {{ t.date.slice(5) }} {{ fmtPct(t.pct) }}
              </span>
            </div>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Lightning, TrendCharts, Calendar, Cpu, Loading } from '@element-plus/icons-vue'
import {
  candidateApi,
  type CandidateStock,
  type IndustryScreeningItem
} from '@/api/candidate'
import { vibeApi, SQ } from '@/api/vibe'
import { makeQuadrantOption, type QuadrantCfg } from '@/utils/quadrant'
import {
  fmtNum,
  fmtYi,
  fmtYiSigned,
  fmtPct,
  fmtPctFromFraction,
  fmtSigned as fmtSign,
  clsByVal
} from '@/utils/format'
/** 候选股/动量等"小数"口径（0.0123 → +1.23%）；趋势帧与市场温度为"百分数"口径（0.62 → +0.62%）用 fmtPct */
const fmtPctF = fmtPctFromFraction
import { use as echartsUse } from 'echarts/core'
import { BarChart, ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent, MarkAreaComponent, MarkLineComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'

defineOptions({ name: 'CandidateScreening' })

echartsUse([BarChart, ScatterChart, GridComponent, TooltipComponent, DataZoomComponent, MarkAreaComponent, MarkLineComponent, CanvasRenderer])

/* ---------------- ① 市场温度：全市场个股趋势帧（slim） ---------------- */
const trendLoading = ref(false)
const trendSlim = ref<{ total?: number; as_of?: string; breadth?: { up?: number; down?: number; avg_pct?: number | null }; frame?: Record<string, number[]> } | null>(null)
const trendAsOf = computed(() => trendSlim.value?.as_of || '')
const widthTotal = computed(() => trendSlim.value?.total ?? null)
const trendBreadth = computed(() => trendSlim.value?.breadth || {})
const widthUp = computed(() => trendBreadth.value.up ?? null)
const widthDown = computed(() => trendBreadth.value.down ?? null)
const widthAvg = computed(() => trendBreadth.value.avg_pct ?? null)
const widthUpRatio = computed(() => {
  const up = widthUp.value
  const down = widthDown.value
  if (up == null || down == null || up + down === 0) return null
  return (up / (up + down)) * 100
})

// 个股趋势帧（最新交易日 8 元组），以纯数字代码为键便于候选股 join
const trendByCode = computed(() => {
  const frame = trendSlim.value?.frame || {}
  const out: Record<string, number[]> = {}
  for (const [code, v] of Object.entries(frame)) out[norm(code)] = v
  return out
})
function norm(c: string): string {
  return String(c).replace(/\D/g, '')
}

/* ---------------- ② 赛道双确认：行业资金流 + 行业/概念趋势象限 ---------------- */
const screenLoading = ref(false)
const screenRefreshing = ref(false)
const screenRankings = ref<IndustryScreeningItem[]>([])
const screenAsOf = ref('')
const refreshingAll = ref(false)

// 行业/概念趋势象限（板块快照）
const boardScope = ref<'industry' | 'concept'>('industry')
const boardLoading = ref(false)
const boardData = ref<{ as_of?: string; total?: number; meta?: Record<string, { name: string; industry: string; link?: string }>; frame?: Record<string, number[]> } | null>(null)

const BOARD_TIPS: [string, string, string, string] = ['流入+上涨 · 强势共振', '流出+上涨 · 缩量上行', '流入+下跌 · 低位承接', '流出+下跌 · 弱势杀跌']
const BOARD_CARD: QuadrantCfg = {
  id: 'money_pct', title: '涨跌 × 主力资金',
  xKey: SQ.P, yKey: SQ.MAIN, xName: '涨跌幅', xUnit: '%', yName: '主力净流入', yUnit: '亿',
  quadrants: ['强势共振', '缩量上行', '低位承接', '弱势杀跌'],
  tips: BOARD_TIPS,
  emptyHint: '当前快照主力资金数据暂不可用',
}

const boardReady = computed(() => {
  const f = boardData.value?.frame || {}
  return Object.keys(f).length > 0
})
const boardOption = computed(() => {
  const meta = (boardData.value?.meta || {}) as Record<string, { name: string; industry: string }>
  const frame = boardData.value?.frame || {}
  if (!Object.keys(frame).length) return {} as any
  return makeQuadrantOption(meta, frame, BOARD_CARD, new Set<string>())
})
// 强势板块 TOP8（按当日涨幅倒序）
const strongBoards = computed(() => {
  const f = boardData.value?.frame || {}
  const meta = boardData.value?.meta || {}
  const arr = Object.entries(f)
    .map(([code, v]) => ({ code, name: meta[code]?.name || code, pct: v?.[SQ.P], link: meta[code]?.link || '' }))
    .filter((x) => x.pct != null)
    .sort((a, b) => (b.pct as number) - (a.pct as number))
  return arr.slice(0, 8)
})

// 行业资金流柱状图（TOP10）
const industryFlowData = computed(() =>
  screenRankings.value
    .filter((r) => r.fund_net_inflow != null)
    .sort((a, b) => (b.fund_net_inflow || 0) - (a.fund_net_inflow || 0))
    .slice(0, 10)
)
const industryFlowOption = computed(() => {
  const items = industryFlowData.value
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        const p = params[0]
        const r = items[p?.dataIndex]
        if (!p || !r) return ''
        const v = Number(r.fund_net_inflow || 0)
        return `${r.industry}<br/>主力净流入：${fmtYi(v)}亿<br/>净占比：${fmtSign(r.fund_net_inflow_pct)}%`
      },
    },
    grid: { left: 8, right: 70, top: 8, bottom: 6, containLabel: true },
    xAxis: { type: 'value', axisLabel: { formatter: (v: number) => fmtYiSigned(v) }, splitLine: { lineStyle: { type: 'dashed', color: '#ebeef5' } } },
    yAxis: { type: 'category', inverse: true, axisLabel: { fontSize: 11 }, data: items.map((r) => r.industry) },
    series: [{
      name: '主力净流入(亿)',
      type: 'bar',
      barWidth: 12,
      data: items.map((r) => ({
        value: Math.round(Number(r.fund_net_inflow || 0) * 100) / 100,
        itemStyle: { color: (r.fund_net_inflow || 0) >= 0 ? '#f56c6c' : '#67c23a', borderRadius: 3 },
      })),
      label: { show: true, position: 'right', fontSize: 10, formatter: (p: any) => `${fmtYiSigned(p.value)}亿` },
    }],
  }
})

/* ---------------- ③ 标的精选：候选 + 个股趋势帧 + 双散点 ---------------- */
// 默认未选行业：直接展示「各行业 top5」的三买买入候选 TOP（每行业质量前10窗）
const selectedIndustry = ref('')
const candidates = ref<CandidateStock[]>([])
const limit = 30
const stockSection = ref<HTMLElement | null>(null)
const signalFilter = ref<'all' | 'buy' | 'B1' | 'B2' | 'B3' | 'S1' | 'S2' | 'S3'>('buy')
const stockLoading = ref(false)

// 行业下拉选项：资金流排名 + 兜底默认行业（若排名中不包含「计算机」）
const industryOptions = computed(() => {
  const names = screenRankings.value.map((r) => r.industry).filter(Boolean)
  if (selectedIndustry.value && !names.includes(selectedIndustry.value)) {
    return [...names, selectedIndustry.value]
  }
  return names
})
const stocksHint = computed(() =>
  selectedIndustry.value
    ? `行业 ${selectedIndustry.value} · top 30`
    : '全市场各行业 · 每行业 top 5 · 全为三买信号'
)

// 信号过滤：buy=仅三买（B1/B2/B3）/ all=全部 / 具体信号
const filteredCandidates = computed(() => {
  const f = signalFilter.value
  if (f === 'all') return candidates.value
  if (f === 'buy') return candidates.value.filter((r) => (r.signal_type || '').startsWith('B'))
  return candidates.value.filter((r) => r.signal_type === f)
})
const signalStats = computed(() => {
  const s: Record<string, number> = { all: candidates.value.length, buy: 0, B1: 0, B2: 0, B3: 0, S1: 0, S2: 0, S3: 0 }
  for (const r of candidates.value) {
    if (r.signal_type && s[r.signal_type] !== undefined) s[r.signal_type]++
    if (r.signal_type && r.signal_type.startsWith('B')) s.buy++
  }
  return s
})

// —— 个股趋势帧 join：候选股 → 趋势列 / 趋势确认散点 / 趋势象限标签 ——
const mainFlowOf = (code: string) => {
  const v = trendByCode.value[norm(code)]
  return v ? v[SQ.MAIN] : null
}
const d5Of = (code: string) => {
  const v = trendByCode.value[norm(code)]
  return v ? v[SQ.D5] : null
}
const boardOf = (code: string) => {
  const v = trendByCode.value[norm(code)]
  return v ? (v[SQ.BOARD] || 0) : null
}
function trendTagOf(code: string) {
  const v = trendByCode.value[norm(code)]
  if (!v) return null
  const p = v[SQ.P]
  const m = v[SQ.MAIN]
  if (p == null || m == null) return null
  if (m >= 0 && p >= 0) return { label: '强势共振', cls: 'tq-red' }
  if (m < 0 && p >= 0) return { label: '缩量上行', cls: 'tq-yellow' }
  if (m >= 0 && p < 0) return { label: '低位承接', cls: 'tq-blue' }
  return { label: '弱势杀跌', cls: 'tq-green' }
}

// 候选股子帧 + 子 meta（趋势确认散点用）
const candidateTrendFrame = computed(() => {
  const out: Record<string, number[]> = {}
  for (const r of filteredCandidates.value) {
    const v = trendByCode.value[norm(r.code)]
    if (v) out[r.code] = v
  }
  return out
})
const candidateTrendMeta = computed(() => {
  const out: Record<string, { name: string; industry: string }> = {}
  for (const r of filteredCandidates.value) {
    if (trendByCode.value[norm(r.code)]) out[r.code] = { name: r.name || r.code, industry: r.industry || '' }
  }
  return out
})
const candidateTrendCount = computed(() => Object.keys(candidateTrendFrame.value).length)
const candidateTrendOption = computed(() => {
  if (!candidateTrendCount.value) return {} as any
  return makeQuadrantOption(candidateTrendMeta.value, candidateTrendFrame.value, BOARD_CARD, new Set<string>())
})

// —— 动量 × ROE 散点 ——
const scatterData = computed(() =>
  filteredCandidates.value
    .filter((r) => r.momentum_20d != null && r.roe != null)
    .map((r) => ({
      name: r.name || r.code,
      code: r.code,
      momentum: Number(r.momentum_20d),
      roe: Number(r.roe),
      mv: Number(r.total_mv || 0),
      pct: Number(r.pct_chg || 0),
    }))
)
const scatterOption = computed(() => {
  const pts = scatterData.value
  return {
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => {
        const d = p?.data
        if (!d) return ''
        const v = d.value || []
        return `${d.name}（${d.code}）<br/>动量：${fmtPctF(v[0])}<br/>ROE：${fmtNum(v[1])}%<br/>市值：${fmtNum(v[2])}亿<br/>涨跌幅：${fmtPctF(v[3])}`
      },
    },
    grid: { left: 56, right: 24, top: 24, bottom: 40 },
    xAxis: {
      type: 'value',
      name: '20日动量(%)',
      nameLocation: 'middle',
      nameGap: 24,
      axisLabel: { formatter: (v: number) => fmtPctF(v), fontSize: 10 },
      splitLine: { lineStyle: { type: 'dashed', color: '#ebeef5' } },
    },
    yAxis: {
      type: 'value',
      name: 'ROE(%)',
      axisLabel: { fontSize: 10 },
      splitLine: { lineStyle: { type: 'dashed', color: '#ebeef5' } },
    },
    series: [{
      type: 'scatter',
      symbolSize: (d: any) => Math.max(8, Math.min(42, Math.sqrt(d[2] || 1) * 1.2)),
      itemStyle: { opacity: 0.75 },
      data: pts.map((p) => ({
        name: p.name,
        code: p.code,
        value: [p.momentum, p.roe, p.mv, p.pct],
        itemStyle: { color: p.pct >= 0 ? '#f56c6c' : '#67c23a' },
      })),
      markLine: {
        symbol: 'none',
        lineStyle: { type: 'dashed', color: '#909399' },
        label: { show: false },
        data: [{ xAxis: 0 }],
      },
    }],
  }
})

/* ---------------- AI 分析（复用个股趋势单股 AI 操作结论） ---------------- */
const aiDialog = ref(false)
const aiLoading = ref(false)
const aiError = ref('')
const aiResult = ref<any>(null)
const aiRow = ref<CandidateStock | null>(null)
const AI_ACTION_COLOR: Record<string, string> = {
  strong_buy: '#f56c6c',
  buy: '#e6a23c',
  hold: '#409eff',
  wait: '#909399',
  reduce: '#67c23a',
  avoid: '#13a8a8',
}
const aiActionColor = computed(() => AI_ACTION_COLOR[aiResult.value?.action as string] || '#909399')
const aiDialogTitle = computed(() => {
  const r = aiResult.value
  return r ? `AI 分析 · ${r.name}（${r.code}）` : 'AI 分析'
})
const aiScorePct = computed(() => {
  const s = Number(aiResult.value?.score ?? 0)
  return Math.max(0, Math.min(100, Math.round((s + 100) / 2)))
})
function fmtN(v: any, unit = '', sign = false): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  const s = sign && n > 0 ? '+' : ''
  const num = Number.isInteger(n) ? String(n) : n.toFixed(2)
  return `${s}${num}${unit}`
}
const AI_TODAY_DEF = [
  { key: 'pct', label: '涨跌幅', unit: '%', sign: true },
  { key: 'amt', label: '成交额', unit: '亿' },
  { key: 'turn', label: '换手率', unit: '%' },
  { key: 'pe', label: '市盈率' },
  { key: 'mv', label: '总市值', unit: '亿' },
  { key: 'main', label: '主力净流入', unit: '亿', sign: true },
  { key: 'board', label: '连板', render: (v: any) => (v == null ? '—' : v === 0 ? '未涨停' : `${v} 板`) },
  { key: 'd5', label: '5日涨跌', unit: '%', sign: true },
]
const aiTodayCells = computed(() => {
  const today = aiResult.value?.data?.today ?? {}
  return AI_TODAY_DEF.map((d) => {
    const raw = today[d.key]
    let text: string
    let cls = ''
    if (d.render) {
      text = d.render(raw)
      cls = (raw != null && raw > 0) ? 'up' : (raw != null && raw < 0 ? 'down' : '')
    } else {
      text = fmtN(raw, d.unit || '', !!d.sign)
      cls = (raw != null && raw > 0) ? 'up' : (raw != null && raw < 0 ? 'down' : '')
    }
    return { label: d.label, text, cls }
  })
})
async function doAiAnalyze(row: CandidateStock) {
  aiRow.value = row
  aiError.value = ''
  aiResult.value = null
  aiDialog.value = true
  aiLoading.value = true
  try {
    // 维度一致性分析：候选股四维信号（趋势象限/择时/ΔG/预警） + 个股趋势帧 → 共振/背离解读
    const res = await vibeApi.getStockQuadrantAiConsistency({
      code: row.code,
      name: row.name,
      industry: row.industry || '',
      signal_type: row.signal_type || '',
      signal_label: row.signal_label || '',
      dg_quadrant: row.dg_quadrant || '',
      aux_warnings: row.aux_warnings || [],
    })
    aiResult.value = (res as any)?.data ?? null
  } catch (e) {
    console.error('AI 分析请求失败', e)
    aiError.value = 'AI 分析请求失败，请稍后重试'
  } finally {
    aiLoading.value = false
  }
}

/* ---------------- 交互与数据加载 ---------------- */
function rankClass(i: number) {
  if (i === 0) return 'rank-gold'
  if (i === 1) return 'rank-silver'
  if (i === 2) return 'rank-bronze'
  return 'rank-normal'
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
function openBoard(link?: string) {
  if (link) window.open(link, '_blank', 'noopener')
}
function onIndustryChartClick(params: any) {
  const item = industryFlowData.value[params?.dataIndex]
  if (item) goToStockScreening(item)
}
function onBoardChartClick(e: any) {
  if (e?.componentType !== 'series') return
  const code = e?.data?.code ?? e?.data?.name
  if (!code || !boardData.value) return
  openBoard(boardData.value?.meta?.[code]?.link)
}
function onTrendChartClick(e: any) {
  if (e?.componentType !== 'series') return
  const code = e?.data?.code ?? e?.data?.name
  if (!code) return
  window.open(`/stocks/${code}`, '_blank', 'noopener')
}
function goToStockScreening(item: IndustryScreeningItem) {
  selectedIndustry.value = item.industry
  loadCandidates()
  nextTick(() => stockSection.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
}

async function loadScreening(refresh = false) {
  if (refresh) screenRefreshing.value = true
  else screenLoading.value = true
  try {
    const res = await candidateApi.industryScreening(10, refresh)
    const data = res.data
    screenRankings.value = data?.rankings || []
    screenAsOf.value = data?.as_of || ''
    // 始终按当前选中的行业（默认「计算机」）加载候选股
    await loadCandidates()
  } catch (e) {
    ElMessage.error('加载行业资金流失败')
  } finally {
    screenLoading.value = false
    screenRefreshing.value = false
  }
}

async function loadBoard() {
  boardLoading.value = true
  try {
    const res = await vibeApi.getBoardQuadrant(boardScope.value)
    boardData.value = (res as any)?.data ?? null
  } catch (e) {
    console.warn('加载板块趋势象限失败', e)
    boardData.value = null
  } finally {
    boardLoading.value = false
  }
}

async function loadTrendSlim() {
  trendLoading.value = true
  try {
    const res = await vibeApi.getStockQuadrantSlim()
    trendSlim.value = (res as any)?.data ?? null
  } catch (e) {
    console.warn('加载个股趋势帧失败', e)
    trendSlim.value = null
  } finally {
    trendLoading.value = false
  }
}

async function loadCandidates() {
  stockLoading.value = true
  try {
    if (selectedIndustry.value) {
      const res = await candidateApi.stocks(selectedIndustry.value, limit)
      candidates.value = res.data?.items || []
    } else {
      // 未选行业：后端按全量行业扫描各行业三买买入候选 TOP（每行业质量前10窗取top5，覆盖回调行业，避免漏单）
      const res = await candidateApi.stocksOverview(10, 5)
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

async function refreshAll() {
  refreshingAll.value = true
  try {
    await Promise.allSettled([loadScreening(true), loadBoard(), loadTrendSlim()])
  } finally {
    refreshingAll.value = false
  }
}

watch(boardScope, () => {
  boardData.value = null
  loadBoard()
})

// 首次进入：并行加载，完成后平滑滚动到②标的精选（默认各行业三买 TOP，打开即见候选）
let initialScrollDone = false
onMounted(async () => {
  await Promise.allSettled([loadScreening(false), loadBoard(), loadTrendSlim()])
  if (!initialScrollDone) {
    initialScrollDone = true
    nextTick(() => stockSection.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }
})
</script>

<style scoped lang="scss">
.candidate-page {
  /* 页面容器交给全局 .app-page */
}

/* —— 三段式主线 —— */
.flow-block {
  margin-bottom: 20px;
  padding: 18px 20px;
  background: var(--el-bg-color);
  border-radius: var(--app-radius-lg, 12px);
  border: 1px solid var(--el-border-color-light);
  box-shadow: var(--app-shadow, none);
}
.flow-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.flow-step {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 10px;
  background: linear-gradient(120deg, #1e3a5f, #2b6cb0);
  color: #fff;
  font-size: 15px;
  font-weight: 700;
  flex-shrink: 0;
}
.flow-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}
.flow-sub {
  font-size: 12px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
}
.flow-hint {
  margin-left: auto;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.flow-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
  flex-wrap: wrap;
}
.board-switch .el-radio-button__inner {
  padding: 4px 12px;
}
.industry-select {
  width: 240px;
}

/* —— KPI —— */
.kpi-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  .kpi-cell {
    padding: 12px 16px;
    border-radius: 8px;
    background: var(--el-fill-color-blank);
    border: 1px solid var(--el-border-color-lighter);
    .kpi-label { font-size: 12px; color: var(--el-text-color-secondary); }
    .kpi-value {
      margin: 6px 0;
      font-size: 22px;
      font-weight: 600;
      .kpi-sep { margin: 0 6px; color: var(--el-text-color-placeholder); font-weight: 400; }
    }
    .kpi-sub { font-size: 12px; color: var(--el-text-color-secondary); }
  }
}
.accent { color: var(--el-color-warning); }

/* —— 面板 —— */
.panel {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  background: var(--el-fill-color-blank);
  padding: 12px 14px;
}
.panel-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 8px;
}
.panel-tip {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.split-grid {
  display: grid;
  gap: 16px;
  margin-bottom: 16px;
}
.board-split {
  grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr);
  .board-chart { min-height: 220px; }
}
.scatter-split {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  margin-top: 16px;
}
.chart--industry { height: 260px; }
.chart--board { height: 340px; }
.chart--scatter { height: 300px; }

/* —— 板块象限图例 —— */
.board-tips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  padding: 8px 10px;
  margin-top: 10px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
  .bt-item {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--el-text-color-secondary);
    white-space: nowrap;
  }
  .bt-dot {
    width: 10px;
    height: 10px;
    border-radius: 3px;
    display: inline-block;
  }
  .dot-0 { background: #fbe0e0; }
  .dot-1 { background: #fdf3d1; }
  .dot-2 { background: #e3f0fd; }
  .dot-3 { background: #e8f7e2; }
}

/* —— 强势板块 chips —— */
.strong-board { margin-top: 10px; }
.strong-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
}
.strong-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.strong-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--el-border-color-light);
  background: var(--el-fill-color-blank);
  cursor: pointer;
  transition: box-shadow .15s, transform .15s;
  &:hover {
    box-shadow: var(--app-shadow-light, 0 2px 8px rgba(30,58,95,.12));
    transform: translateY(-1px);
  }
  .sc-name { font-size: 12px; font-weight: 500; color: var(--el-text-color-primary); }
  .sc-pct { font-size: 12px; font-weight: 600; }
}

/* —— 表格区 —— */
.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin: 4px 0 10px;
}
.stocks-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin: 12px 0 8px;
}
.rank-table, .candidate-table {
  border-radius: 10px;
  overflow: hidden;
  box-shadow: var(--el-box-shadow-light);
  border: 1px solid var(--el-border-color-light);
}
.signal-filter { flex-wrap: wrap; }
.muted { color: var(--el-text-color-secondary); }
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
.rank-table { cursor: pointer; }

/* —— 个股趋势象限标签 —— */
.trend-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
  .tt-dot { width: 8px; height: 8px; border-radius: 3px; display: inline-block; }
}
.tq-red { background: #fbe0e0; color: #c0392b; .tt-dot { background: #e57373; } }
.tq-yellow { background: #fdf3d1; color: #b7791f; .tt-dot { background: #ecc94b; } }
.tq-blue { background: #e3f0fd; color: #2b6cb0; .tt-dot { background: #63b3ed; } }
.tq-green { background: #e8f7e2; color: #2f855a; .tt-dot { background: #68d391; } }

.warn-tag { margin-right: 4px; white-space: nowrap; flex-shrink: 0; }
.warn-cell {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  overflow: hidden;
}
.table-scroll {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}
.table-scroll::-webkit-scrollbar { height: 6px; }
.table-scroll::-webkit-scrollbar-thumb { background: var(--el-border-color); border-radius: 3px; }

/* —— AI 弹窗 —— */
.ai-dialog {
  .ai-body { padding: 4px 2px; }
  .ai-loading {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    min-height: 120px;
    color: var(--el-text-color-secondary);
    font-size: 13px;
  }
  .ai-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 12px;
    .ai-head-tags { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
    .ai-score {
      flex: 1;
      .el-progress { margin-bottom: 4px; }
      .ai-score-txt { font-size: 12px; color: var(--el-text-color-secondary); }
    }
  }
  .ai-summary {
    margin: 0 0 12px;
    padding: 10px 12px;
    border-radius: 8px;
    background: var(--el-fill-color-light);
    font-size: 13px;
    line-height: 1.7;
    color: var(--el-text-color-primary);
  }
  .ai-block {
    margin-top: 12px;
    .ai-block-title { font-size: 13px; font-weight: 600; margin-bottom: 6px; }
    .ai-list {
      margin: 0;
      padding-left: 18px;
      font-size: 12.5px;
      line-height: 1.9;
      color: var(--el-text-color-regular);
      &.ai-risk { color: #d4380d; }
    }
  }

  // —— 维度一致性（融合改造核心）——
  .consistency-block {
    padding: 12px 14px;
    border-radius: 10px;
    background: var(--el-fill-color-light);
    border: 1px solid var(--el-border-color-lighter);

    .ai-block-title {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .consistency-tag {
      padding: 1px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 600;
      &.cs-align { background: rgba(103, 194, 58, .14); color: #2f855a; border: 1px solid rgba(103, 194, 58, .35); }
      &.cs-partial { background: rgba(230, 162, 60, .14); color: #b7791f; border: 1px solid rgba(230, 162, 60, .35); }
      &.cs-diverg { background: rgba(245, 108, 108, .14); color: #c0392b; border: 1px solid rgba(245, 108, 108, .35); }
      &.cs-neutral { background: rgba(144, 147, 153, .14); color: #606266; border: 1px solid rgba(144, 147, 153, .35); }
    }
    .consistency-engine {
      margin-left: auto;
      font-size: 11px;
      font-weight: 400;
      color: var(--el-text-color-secondary);
    }
    .cs-summary {
      margin-top: 10px;
      margin-bottom: 10px;
    }
    .cs-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 8px;
    }
    .cs-cell {
      padding: 8px 10px;
      border-radius: 8px;
      background: var(--el-fill-color-blank);
      border-left: 3px solid var(--el-border-color);
      .cs-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 4px;
        .cs-name { font-size: 12px; font-weight: 600; color: var(--el-text-color-primary); }
        .cs-flag { font-size: 11px; font-weight: 600; }
      }
      .cs-value { font-size: 13.5px; font-weight: 700; margin-bottom: 3px; }
      .cs-view { font-size: 11.5px; line-height: 1.6; color: var(--el-text-color-secondary); }
      &.cs-up { border-left-color: #f56c6c; .cs-flag { color: #f56c6c; } .cs-value { color: #c0392b; } }
      &.cs-down { border-left-color: #67c23a; .cs-flag { color: #67c23a; } .cs-value { color: #2f855a; } }
      &.cs-flat { border-left-color: #909399; .cs-flag { color: #909399; } }
    }
    .cs-conflicts {
      margin-top: 10px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      .cs-conflict {
        font-size: 12.5px;
        line-height: 1.7;
        color: #b7791f;
        background: rgba(230, 162, 60, .10);
        border: 1px dashed rgba(230, 162, 60, .45);
        border-radius: 8px;
        padding: 6px 10px;
        &::first-letter { font-weight: 700; }
      }
    }
  }
  .ai-table {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
    .ai-cell {
      padding: 8px 10px;
      border-radius: 8px;
      background: var(--el-fill-color-blank);
      border: 1px solid var(--el-border-color-lighter);
      display: flex;
      flex-direction: column;
      gap: 4px;
      .ai-cell-label { font-size: 11px; color: var(--el-text-color-secondary); }
      b {
        font-family: 'SFMono-Regular', ui-monospace, Menlo, monospace;
        font-size: 14px;
        color: var(--el-text-color-primary);
        &.up { color: #f56c6c; }
        &.down { color: #67c23a; }
      }
    }
  }
  .ai-trend {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    .ai-trend-item {
      font-size: 11.5px;
      padding: 3px 8px;
      border-radius: 6px;
      background: var(--el-fill-color-light);
      font-family: 'SFMono-Regular', ui-monospace, Menlo, monospace;
      &.up { color: #f56c6c; }
      &.down { color: #67c23a; }
    }
  }
}

/* —— 响应式 —— */
@media (max-width: 1100px) {
  .board-split, .scatter-split { grid-template-columns: 1fr !important; }
  .kpi-row { grid-template-columns: repeat(2, 1fr); }
  .flow-hint { display: none; }
  .flow-actions { margin-left: 0; }
}
@media (max-width: 768px) {
  .flow-block { padding: 14px; }
  .flow-head { gap: 8px; }
  .industry-select { width: 100%; }
  .signal-filter { width: 100%; gap: 6px; }
  .signal-filter .el-radio-button__inner { padding: 6px 10px; font-size: 12px; }
  .kpi-row { grid-template-columns: repeat(2, 1fr); gap: 8px; }
  .kpi-cell .kpi-value { font-size: 18px; }
  .rank-table, .candidate-table { font-size: 13px; }
  .table-scroll { margin: 0 -14px; padding: 0 14px; }
}
</style>
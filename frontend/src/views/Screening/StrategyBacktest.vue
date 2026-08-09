<template>
  <div class="strategy-backtest">
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><Histogram /></el-icon>
        回测工作台
      </h1>
      <p class="page-description">{{ activeMode.hint }}</p>
      <div class="header-actions">
        <el-radio-group v-model="activeTab" size="small">
          <el-radio-button v-for="m in MODES" :key="m.key" :value="m.key">
            {{ m.title }}
          </el-radio-button>
          <el-radio-button key="compare" :value="'compare'">
            结果对比
          </el-radio-button>
        </el-radio-group>
      </div>
    </div>

    <!-- 回测进行中：进度 + 预计剩余时间（无论停留在哪个标签页都展示） -->
    <el-card v-if="runningKind" class="progress-panel" shadow="never">
      <template #header>
        <span class="panel-title">
          <el-icon class="is-loading" style="margin-right: 6px"><Loading /></el-icon>
          回测进行中
        </span>
      </template>
      <el-progress :percentage="progressInfo.percent" :stroke-width="14"
                   :status="progressInfo.percent >= 100 ? 'success' : undefined" />
      <div class="progress-meta">
        <span class="progress-msg">{{ progressInfo.message }}</span>
        <span v-if="progressInfo.etaSec > 0" class="progress-eta">预计还需 {{ formatEta(progressInfo.etaSec) }}</span>
        <span v-else class="progress-eta">正在计算，请稍候…</span>
        <span class="progress-elapsed">已运行 {{ formatEta(progressInfo.elapsedSec) }}</span>
      </div>
    </el-card>

    <!-- 策略回测 -->
    <template v-if="activeTab === 'strategy'">
      <el-card class="form-panel" shadow="never">
        <template #header><span class="panel-title">策略回测参数</span></template>
        <el-form :inline="true" label-width="110px" class="bt-form">
          <el-form-item label="策略">
            <el-select v-model="btForm.strategy_id" placeholder="选择策略" style="width: 200px">
              <el-option v-for="s in strategies" :key="s.id" :label="s.name" :value="s.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="区间">
            <el-date-picker v-model="btRange" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始" end-placeholder="结束" style="width: 260px" />
          </el-form-item>
          <el-form-item label="初始资金">
            <el-input-number v-model="btForm.initial_capital" :min="10000" :step="100000" style="width: 160px" />
          </el-form-item>
          <el-form-item label="最大持仓">
            <el-input-number v-model="btForm.max_positions" :min="1" :max="50" style="width: 120px" />
          </el-form-item>
          <el-form-item label="仓位方式">
            <el-select v-model="btForm.position_sizing" style="width: 140px">
              <el-option label="等权" value="equal" />
              <el-option label="评分加权" value="score_weight" />
            </el-select>
          </el-form-item>
          <el-form-item label="费率">
            <el-input-number v-model="btForm.fees_pct" :min="0" :max="0.01" :step="0.0001" :precision="4" style="width: 120px" />
          </el-form-item>
          <el-form-item label="滑点(bp)">
            <el-input-number v-model="btForm.slippage_bps" :min="0" :max="100" style="width: 120px" />
          </el-form-item>
          <el-form-item label="止损%">
            <el-input-number v-model="btForm.stop_loss_pct" :min="0" :max="0.5" :step="0.01" :precision="2" style="width: 120px" />
          </el-form-item>
          <el-form-item label="止盈%">
            <el-input-number v-model="btForm.take_profit_pct" :min="0" :max="1" :step="0.01" :precision="2" style="width: 120px" />
          </el-form-item>
          <el-form-item label="最大持有(天)">
            <el-input-number v-model="btForm.max_hold_days" :min="0" :max="365" style="width: 120px" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="strategyLoading" @click="runStrategyBacktest">
              <el-icon><Search /></el-icon>
              开始回测
            </el-button>
          </el-form-item>
        </el-form>
      </el-card>

      <template v-if="strategyResult">
        <el-alert v-if="!strategyResult.success" :title="strategyResult.error || '回测失败'" type="error" show-icon :closable="false" />
        <template v-else>
          <!-- 结果概览：策略名 / 区间 / 参数 -->
          <el-card class="result-header" shadow="never">
            <div class="result-header-inner">
              <div class="result-title">
                <span class="result-strategy-name">{{ strategyResult.strategy_info?.name || '策略回测' }}</span>
                <el-tag size="small" type="success" effect="light" class="result-tag">回测完成</el-tag>
              </div>
              <div class="result-meta">
                <div class="meta-item">
                  <span class="meta-label">回测区间</span>
                  <span class="meta-value">{{ strategyResult.config?.start }} ~ {{ strategyResult.config?.end }}</span>
                </div>
                <div class="meta-item">
                  <span class="meta-label">初始资金</span>
                  <span class="meta-value">¥{{ formatMoney(strategyResult.config?.initial_capital) }}</span>
                </div>
                <div class="meta-item">
                  <span class="meta-label">最大持仓</span>
                  <span class="meta-value">{{ strategyResult.config?.max_positions }} 只</span>
                </div>
                <div class="meta-item">
                  <span class="meta-label">仓位方式</span>
                  <span class="meta-value">{{ positionSizingLabel(strategyResult.config?.position_sizing) }}</span>
                </div>
                <div class="meta-item">
                  <span class="meta-label">费率 / 滑点</span>
                  <span class="meta-value">{{ (strategyResult.config?.fees_pct * 100).toFixed(2) }}% / {{ strategyResult.config?.slippage_bps }}bp</span>
                </div>
                <div class="meta-item">
                  <span class="meta-label">回测耗时</span>
                  <span class="meta-value">{{ formatEta((strategyResult.elapsed_ms ?? 0) / 1000) }}</span>
                </div>
              </div>
            </div>
          </el-card>

          <el-card class="stats-panel" shadow="never">
            <template #header>
              <span class="panel-title">
                <el-icon style="margin-right: 6px"><DataAnalysis /></el-icon>
                绩效指标
              </span>
            </template>
            <StatCards :stats="strategyResult.stats" />
          </el-card>
          <el-card class="chart-panel" shadow="never">
            <template #header><span class="panel-title">净值曲线（起始=1，相对收益）</span></template>
            <v-chart class="chart" :option="equityOption" autoresize />
          </el-card>
          <el-card class="chart-panel" shadow="never">
            <template #header><span class="panel-title">交易明细 ({{ strategyResult.trades?.length }})</span></template>
            <el-table :data="strategyResult.trades" size="small" stripe border max-height="480"
                      :default-sort="{ prop: 'entry_date', order: 'ascending' }" class="trade-table">
              <el-table-column prop="symbol" label="代码" width="90">
                <template #default="{ row }">
                  <router-link :to="`/stocks/${row.symbol}`" class="stock-code">{{ row.symbol }}</router-link>
                </template>
              </el-table-column>
              <el-table-column prop="name" label="名称" min-width="110">
                <template #default="{ row }">
                  <router-link :to="`/stocks/${row.symbol}`" class="stock-name">{{ row.name }}</router-link>
                </template>
              </el-table-column>
              <el-table-column prop="entry_date" label="买入日期" min-width="110" sortable />
              <el-table-column prop="exit_date" label="卖出日期" min-width="110" sortable />
              <el-table-column prop="entry_price" label="买入价" width="95" align="right" sortable />
              <el-table-column prop="exit_price" label="卖出价" width="95" align="right" sortable />
              <el-table-column prop="pnl_pct" label="收益率" width="95" align="right" sortable>
                <template #default="{ row }">
                  <span :class="row.pnl_pct >= 0 ? 'text-red' : 'text-green'">{{ (row.pnl_pct * 100).toFixed(2) }}%</span>
                </template>
              </el-table-column>
              <el-table-column prop="duration" label="持有(天)" width="90" align="right" sortable />
              <el-table-column prop="exit_reason" label="卖出原因" min-width="110">
                <template #default="{ row }">
                  <el-tag size="small" effect="plain" :type="exitReasonType(row.exit_reason)">{{ exitReasonLabel(row.exit_reason) }}</el-tag>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </template>
      </template>
    </template>

    <!-- 因子回测 -->
    <template v-else-if="activeTab === 'factor'">
      <el-card class="form-panel" shadow="never">
        <template #header><span class="panel-title">因子回测参数</span></template>
        <el-form :inline="true" label-width="110px" class="bt-form">
          <el-form-item label="因子">
            <el-select v-model="factorForm.factor_name" placeholder="选择因子" style="width: 200px">
              <el-option v-for="f in FACTOR_OPTIONS" :key="f.value" :label="f.label" :value="f.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="区间">
            <el-date-picker v-model="factorRange" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始" end-placeholder="结束" style="width: 260px" />
          </el-form-item>
          <el-form-item label="分组数">
            <el-input-number v-model="factorForm.n_groups" :min="2" :max="10" style="width: 120px" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="factorLoading" @click="runFactorBacktest">
              <el-icon><Search /></el-icon>
              开始回测
            </el-button>
          </el-form-item>
        </el-form>
      </el-card>

      <template v-if="factorResult">
        <el-alert v-if="!factorResult.success" :title="factorResult.error || '回测失败'" type="error" show-icon :closable="false" />
        <template v-else>
          <el-row :gutter="12" class="stat-row">
            <el-col :span="4"><el-statistic title="IC均值" :value="factorResult.stats?.ic_mean" :precision="4" /></el-col>
            <el-col :span="4"><el-statistic title="IC标准差" :value="factorResult.stats?.ic_std" :precision="4" /></el-col>
            <el-col :span="4"><el-statistic title="IC_IR" :value="factorResult.stats?.ic_ir" :precision="4" /></el-col>
            <el-col :span="4"><el-statistic title="IC正值占比" :value="factorResult.stats?.ic_positive_ratio" :precision="4" /></el-col>
            <el-col :span="4"><el-statistic title="多空收益" :value="factorResult.long_short?.avg_return" :precision="4" /></el-col>
            <el-col :span="4"><el-statistic title="样本天数" :value="factorResult.stats?.n_days" /></el-col>
          </el-row>
          <el-card class="chart-panel" shadow="never">
            <template #header><span class="panel-title">IC 序列</span></template>
            <v-chart class="chart" :option="icOption" autoresize />
          </el-card>
          <el-card class="chart-panel" shadow="never">
            <template #header><span class="panel-title">分组收益</span></template>
            <el-table :data="factorResult.group_returns" size="small" stripe border>
              <el-table-column prop="group" label="分组" width="120" />
              <el-table-column prop="avg_return" label="平均收益" align="right">
                <template #default="{ row }"><span :class="row.avg_return >= 0 ? 'text-red' : 'text-green'">{{ (row.avg_return * 100).toFixed(2) }}%</span></template>
              </el-table-column>
              <el-table-column prop="cum_return" label="累计收益" align="right">
                <template #default="{ row }"><span :class="row.cum_return >= 0 ? 'text-red' : 'text-green'">{{ (row.cum_return * 100).toFixed(2) }}%</span></template>
              </el-table-column>
              <el-table-column prop="n_days" label="样本天数" align="right" />
            </el-table>
          </el-card>
        </template>
      </template>
    </template>

    <!-- 参数优化 -->
    <template v-else-if="activeTab === 'optimizer'">
      <el-card class="form-panel" shadow="never">
        <template #header><span class="panel-title">参数优化</span></template>
        <el-form :inline="true" label-width="110px" class="bt-form">
          <el-form-item label="策略">
            <el-select v-model="optForm.strategy_id" placeholder="选择策略" style="width: 200px">
              <el-option v-for="s in strategies" :key="s.id" :label="s.name" :value="s.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="区间">
            <el-date-picker v-model="optRange" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始" end-placeholder="结束" style="width: 260px" />
          </el-form-item>
          <el-form-item label="目标函数">
            <el-select v-model="optForm.objective" style="width: 160px">
              <el-option label="总收益" value="total_return" />
              <el-option label="夏普比率" value="sharpe" />
              <el-option label="最大回撤" value="max_drawdown" />
              <el-option label="胜率" value="win_rate" />
            </el-select>
          </el-form-item>
          <el-form-item label="参数网格">
            <el-input v-model="optForm.paramGridText" type="textarea" :rows="3" placeholder='{"vol_ratio_min": [1.0, 1.2, 1.5], "use_volume_filter": [true, false]}' style="width: 420px" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="optLoading" @click="runOptimizer">
              <el-icon><Search /></el-icon>
              开始优化
            </el-button>
          </el-form-item>
        </el-form>
      </el-card>

      <template v-if="optResult">
        <el-alert v-if="!optResult.success" :title="optResult.error || '优化失败'" type="error" show-icon :closable="false" />
        <template v-else>
          <el-card class="chart-panel" shadow="never">
            <template #header><span class="panel-title">参数组合结果 ({{ optResult.n_trials }})</span></template>
            <el-table :data="optResult.results" size="small" stripe border>
              <el-table-column type="index" label="#" width="50" />
              <el-table-column label="参数" min-width="220">
                <template #default="{ row }">
                  <el-tag v-for="(v, k) in row.params" :key="k" size="small" class="param-tag">{{ k }}={{ v }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="value" label="目标值" align="right" width="120">
                <template #default="{ row }"><span class="text-red">{{ Number(row.value).toFixed(4) }}</span></template>
              </el-table-column>
              <el-table-column prop="stats.total_return" label="总收益" align="right" width="100">
                <template #default="{ row }">{{ (row.stats?.total_return * 100).toFixed(2) }}%</template>
              </el-table-column>
              <el-table-column prop="stats.sharpe" label="夏普" align="right" width="90" />
              <el-table-column prop="stats.max_drawdown" label="最大回撤" align="right" width="100">
                <template #default="{ row }">{{ (row.stats?.max_drawdown * 100).toFixed(2) }}%</template>
              </el-table-column>
              <el-table-column prop="stats.win_rate" label="胜率" align="right" width="90">
                <template #default="{ row }">{{ (row.stats?.win_rate * 100).toFixed(1) }}%</template>
              </el-table-column>
              <el-table-column prop="stats.n_trades" label="交易数" align="right" width="90" />
            </el-table>
          </el-card>
        </template>
      </template>
    </template>

    <!-- 步进优化 -->
    <template v-else-if="activeTab === 'walkforward'">
      <el-card class="form-panel" shadow="never">
        <template #header><span class="panel-title">步进优化</span></template>
        <el-form :inline="true" label-width="110px" class="bt-form">
          <el-form-item label="策略">
            <el-select v-model="wfForm.strategy_id" placeholder="选择策略" style="width: 200px">
              <el-option v-for="s in strategies" :key="s.id" :label="s.name" :value="s.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="区间">
            <el-date-picker v-model="wfRange" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始" end-placeholder="结束" style="width: 260px" />
          </el-form-item>
          <el-form-item label="训练天数">
            <el-input-number v-model="wfForm.train_days" :min="30" :max="500" style="width: 120px" />
          </el-form-item>
          <el-form-item label="测试天数">
            <el-input-number v-model="wfForm.test_days" :min="10" :max="200" style="width: 120px" />
          </el-form-item>
          <el-form-item label="参数网格">
            <el-input v-model="wfForm.paramGridText" type="textarea" :rows="2" placeholder='{"vol_ratio_min": [1.0, 1.2, 1.5]}' style="width: 380px" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="wfLoading" @click="runWalkForward">
              <el-icon><Search /></el-icon>
              开始优化
            </el-button>
          </el-form-item>
        </el-form>
      </el-card>

      <template v-if="wfResult">
        <el-alert v-if="!wfResult.success" :title="wfResult.error || '步进优化失败'" type="error" show-icon :closable="false" />
        <template v-else>
          <el-card class="chart-panel" shadow="never">
            <template #header>
              <span class="panel-title">各折样本外表现 · 平均测试收益</span>
              <el-tag size="small" type="success" style="margin-left: 8px">{{ (wfResult.avg_test_return * 100).toFixed(2) }}%</el-tag>
            </template>
            <el-table :data="wfResult.folds" size="small" stripe border>
              <el-table-column type="index" label="#" width="50" />
              <el-table-column label="训练区间" width="190">
                <template #default="{ row }">{{ row.train.start }} ~ {{ row.train.end }}</template>
              </el-table-column>
              <el-table-column label="测试区间" width="190">
                <template #default="{ row }">{{ row.test.start }} ~ {{ row.test.end }}</template>
              </el-table-column>
              <el-table-column label="最优参数" min-width="200">
                <template #default="{ row }">
                  <el-tag v-for="(v, k) in row.best_params" :key="k" size="small" class="param-tag">{{ k }}={{ v }}</el-tag>
                  <span v-if="!row.best_params || Object.keys(row.best_params).length === 0" class="text-muted">-</span>
                </template>
              </el-table-column>
              <el-table-column label="测试收益" align="right" width="110">
                <template #default="{ row }">
                  <span :class="row.stats?.total_return >= 0 ? 'text-red' : 'text-green'">{{ (row.stats?.total_return * 100).toFixed(2) }}%</span>
                </template>
              </el-table-column>
              <el-table-column prop="stats.sharpe" label="夏普" align="right" width="90" />
              <el-table-column prop="stats.max_drawdown" label="最大回撤" align="right" width="100">
                <template #default="{ row }">{{ (row.stats?.max_drawdown * 100).toFixed(2) }}%</template>
              </el-table-column>
              <el-table-column prop="stats.n_trades" label="交易数" align="right" width="90" />
            </el-table>
          </el-card>
        </template>
      </template>
    </template>

    <!-- 结果对比 -->
    <template v-else-if="activeTab === 'compare'">
      <template v-if="compareResults.length === 0">
        <el-empty description="暂无回测结果。先在「策略回测」中运行至少一个策略，结果会自动收录到这里对比。" />
      </template>
      <template v-else>
        <el-card class="compare-panel" shadow="never">
          <template #header>
            <span class="panel-title">
              <el-icon style="margin-right: 6px"><Histogram /></el-icon>
              策略回测结果对比（{{ compareResults.length }} 个策略）
            </span>
          </template>
          <el-table :data="compareResults" size="small" stripe border class="compare-table">
            <el-table-column prop="strategy_name" label="策略名称" min-width="150">
              <template #default="{ row }">
                <span class="compare-strategy">{{ row.strategy_name }}</span>
              </template>
            </el-table-column>
            <el-table-column label="回测区间" min-width="180">
              <template #default="{ row }">{{ row.range }}</template>
            </el-table-column>
            <el-table-column prop="stats.total_return" label="总收益" align="right" sortable width="105">
              <template #default="{ row }">
                <span :class="row.stats.total_return >= 0 ? 'text-red' : 'text-green'">{{ (row.stats.total_return * 100).toFixed(2) }}%</span>
              </template>
            </el-table-column>
            <el-table-column prop="stats.annual_return" label="年化收益" align="right" sortable width="105">
              <template #default="{ row }">
                <span :class="row.stats.annual_return >= 0 ? 'text-red' : 'text-green'">{{ (row.stats.annual_return * 100).toFixed(2) }}%</span>
              </template>
            </el-table-column>
            <el-table-column prop="stats.max_drawdown" label="最大回撤" align="right" sortable width="105">
              <template #default="{ row }">
                <span class="text-green">{{ (row.stats.max_drawdown * 100).toFixed(2) }}%</span>
              </template>
            </el-table-column>
            <el-table-column prop="stats.sharpe" label="夏普" align="right" sortable width="90">
              <template #default="{ row }">{{ (row.stats.sharpe ?? 0).toFixed(2) }}</template>
            </el-table-column>
            <el-table-column prop="stats.win_rate" label="胜率" align="right" sortable width="90">
              <template #default="{ row }">{{ (row.stats.win_rate * 100).toFixed(1) }}%</template>
            </el-table-column>
            <el-table-column prop="stats.profit_factor" label="盈亏比" align="right" sortable width="90">
              <template #default="{ row }">{{ row.stats.profit_factor != null ? row.stats.profit_factor.toFixed(2) : '-' }}</template>
            </el-table-column>
            <el-table-column prop="stats.n_trades" label="交易次数" align="right" sortable width="90" />
            <el-table-column prop="savedAtText" label="更新于" min-width="150" sortable />
            <el-table-column label="操作" width="90" fixed="right">
              <template #default="{ row }">
                <el-button type="text" size="small" @click="removeFromCompare(row.strategy_id)">移除</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div class="compare-charts">
            <div class="chart-card">
              <div class="chart-title">总收益率对比</div>
              <v-chart class="chart" :option="returnBarOption" autoresize />
            </div>
            <div class="chart-card">
              <div class="chart-title">净值曲线对比（起始=1）</div>
              <v-chart class="chart" :option="equityOverlayOption" autoresize />
            </div>
          </div>
        </el-card>
      </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch, h, defineComponent, type PropType } from 'vue'
import { ElMessage } from 'element-plus'
import { Histogram, Search, Loading, DataAnalysis } from '@element-plus/icons-vue'
import { use as echartsUse } from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import { strategyApi, FACTOR_OPTIONS, type StrategyMeta, type BacktestResult, type BacktestStats, type CompareResultItem, type FactorBacktestResult, type OptimizeResult, type WalkForwardResult } from '@/api/strategy'

echartsUse([LineChart, BarChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent, CanvasRenderer])

defineOptions({ name: 'StrategyBacktest' })

// 回测统计卡片（标准组合式组件：setup() 返回渲染函数，避免裸函数被当作文本渲染）
const StatCards = defineComponent({
  name: 'StatCards',
  props: {
    stats: { type: Object as PropType<BacktestStats>, default: () => ({}) },
  },
  setup(props) {
    const s = props.stats || {}
    const pct = (v: number) => (v != null ? `${(v * 100).toFixed(2)}%` : '-')
    // 平均盈利/平均亏损/最佳/最差 为单笔盈亏金额（元），非收益率，不能用 pct 放大成百分比
    const money = (v: number) => (v != null ? `¥${Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}` : '-')
    const cards = computed(() => [
      { label: '总收益', value: pct(s.total_return), color: (s.total_return ?? 0) >= 0 ? 'var(--el-color-danger)' : 'var(--el-color-success)' },
      { label: '年化收益', value: pct(s.annual_return), color: (s.annual_return ?? 0) >= 0 ? 'var(--el-color-danger)' : 'var(--el-color-success)' },
      { label: '最大回撤', value: pct(s.max_drawdown), color: 'var(--el-color-warning)' },
      { label: '夏普比率', value: s.sharpe != null ? s.sharpe.toFixed(2) : '-', color: 'var(--el-color-primary)' },
      { label: '胜率', value: pct(s.win_rate), color: 'var(--el-color-primary)' },
      { label: '盈亏比', value: s.profit_factor != null ? s.profit_factor.toFixed(2) : '-', color: 'var(--el-color-primary)' },
      { label: '交易次数', value: String(s.n_trades ?? 0), color: 'var(--el-color-primary)' },
      { label: '平均盈利', value: money(s.avg_win), color: 'var(--el-color-danger)' },
      { label: '平均亏损', value: money(s.avg_loss), color: 'var(--el-color-success)' },
      { label: '最佳', value: money(s.best), color: 'var(--el-color-danger)' },
      { label: '最差', value: money(s.worst), color: 'var(--el-color-success)' },
    ])
    return () =>
      h('div', { class: 'stat-cards' }, cards.value.map((c) =>
        h('div', { class: 'stat-card', key: c.label }, [
          h('div', { class: 'stat-label' }, c.label),
          h('div', { class: 'stat-value', style: { color: c.color } }, c.value),
        ])
      ))
  },
})

const MODES = [
  { key: 'strategy', title: '策略回测', hint: '验证完整选股和交易规则，看净值曲线、回撤、胜率和交易明细。' },
  { key: 'factor', title: '因子回测', hint: '验证单个因子是否有预测能力，看 IC / IR 和分层收益。' },
  { key: 'optimizer', title: '参数优化', hint: '网格搜索最优参数组合，按夏普/收益等目标排序。' },
  { key: 'walkforward', title: '步进优化', hint: '滚动窗口样本外验证，识别过拟合。' },
] as const

const COMPARE_HINT = '对比不同策略的回测结果，聚焦收益率等核心指标，快速判断哪个策略效果更好。每次策略回测完成后自动收录，再次回测会更新对应数据。'

type TabKey = 'strategy' | 'factor' | 'optimizer' | 'walkforward' | 'compare'
const activeTab = ref<TabKey>('strategy')
const activeMode = computed(() => {
  if (activeTab.value === 'compare') return { key: 'compare' as const, title: '结果对比' as const, hint: COMPARE_HINT }
  return MODES.find(m => m.key === activeTab.value)!
})
const strategies = ref<StrategyMeta[]>([])

// 策略回测表单
const btRange = ref<[string, string] | null>(null)
const btForm = ref({
  strategy_id: '',
  initial_capital: 1000000,
  max_positions: 10,
  position_sizing: 'equal',
  fees_pct: 0.0002,
  slippage_bps: 5,
  stop_loss_pct: null as number | null,
  take_profit_pct: null as number | null,
  max_hold_days: null as number | null,
})
const strategyLoading = ref(false)
const strategyResult = ref<BacktestResult | null>(null)

// 因子回测表单
const factorRange = ref<[string, string] | null>(null)
const factorForm = ref({ factor_name: 'momentum_20d', n_groups: 5 })
const factorLoading = ref(false)
const factorResult = ref<FactorBacktestResult | null>(null)

// 参数优化表单
const optRange = ref<[string, string] | null>(null)
const optForm = ref({ strategy_id: '', objective: 'total_return', paramGridText: '' })
const optLoading = ref(false)
const optResult = ref<OptimizeResult | null>(null)

// 步进优化表单
const wfRange = ref<[string, string] | null>(null)
const wfForm = ref({ strategy_id: '', train_days: 120, test_days: 30, paramGridText: '' })
const wfLoading = ref(false)
const wfResult = ref<WalkForwardResult | null>(null)

// ---------------------------------------------------------------------------
// 回测结果持久化：离开页面/刷新后再次进入仍能查看上次结果
// ---------------------------------------------------------------------------
const BT_STORAGE_TTL = 24 * 60 * 60 * 1000 // 结果保留 24 小时
// 缓存键带构建版本号：前端重新部署后版本号变化，旧回测结果缓存自动失效，不再展示旧数据
const BT_STORAGE_PREFIX = `strategy_backtest_result_${__APP_BUILD_VERSION__}_`

interface StoredResult {
  savedAt: number
  data: unknown
}

function saveResult(key: string, value: unknown | null) {
  try {
    if (value == null) {
      localStorage.removeItem(BT_STORAGE_PREFIX + key)
      return
    }
    const payload: StoredResult = { savedAt: Date.now(), data: value }
    localStorage.setItem(BT_STORAGE_PREFIX + key, JSON.stringify(payload))
  } catch (e) {
    console.warn('[回测结果] 本地保存失败:', e)
  }
}

function isErrorResult(d: unknown): boolean {
  if (d && typeof d === 'object') {
    const o = d as Record<string, unknown>
    if (o.success === false) return true
    if (typeof o.error === 'string' && o.error) return true
  }
  return false
}

function loadResult<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(BT_STORAGE_PREFIX + key)
    if (!raw) return null
    const parsed = JSON.parse(raw) as StoredResult
    if (!parsed?.data || Date.now() - parsed.savedAt > BT_STORAGE_TTL) {
      localStorage.removeItem(BT_STORAGE_PREFIX + key)
      return null
    }
    // 丢弃历史失败的错误结果，避免刷新后仍展示旧错误
    if (isErrorResult(parsed.data)) {
      localStorage.removeItem(BT_STORAGE_PREFIX + key)
      return null
    }
    return parsed.data as T
  } catch (e) {
    console.warn('[回测结果] 本地读取失败:', e)
    return null
  }
}

// 监听四个结果，变更时自动持久化
watch(strategyResult, v => {
  saveResult('strategy', v)
  // 回测结果已由后端落库到 MongoDB；此处刷新「结果对比」列表，使新结果/更新及时反映
  loadStrategyResults()
})
watch(factorResult, v => saveResult('factor', v))
watch(optResult, v => saveResult('optimizer', v))
watch(wfResult, v => saveResult('walkforward', v))

// ---------------------------------------------------------------------------
// 结果对比：从 MongoDB 读取跨策略回测结果，横向对比核心指标
// ---------------------------------------------------------------------------
interface CompareItem {
  strategy_id: string
  strategy_name: string
  range: string
  savedAt: number
  savedAtText: string
  stats: BacktestStats
  equity_curve: Array<{ date: string; value: number }>
}

const compareResults = ref<CompareItem[]>([])

async function loadStrategyResults() {
  try {
    const res: any = await strategyApi.backtestResults()
    const raw = (res as any)?.data ?? res
    const list: CompareResultItem[] = Array.isArray(raw) ? raw : []
    const items: CompareItem[] = []
    for (const r of list) {
      if (!r.strategy_id || !r.stats) continue
      items.push({
        strategy_id: r.strategy_id,
        strategy_name: r.strategy_name || r.strategy_id,
        range: `${r.config?.start ?? '-'} ~ ${r.config?.end ?? '-'}`,
        savedAt: r.saved_at,
        savedAtText: new Date(r.saved_at * 1000).toLocaleString('zh-CN', { hour12: false }),
        stats: r.stats,
        equity_curve: r.equity_curve ?? [],
      })
    }
    // 后端已按 saved_at 倒序返回，这里再兜底排序
    items.sort((a, b) => b.savedAt - a.savedAt)
    compareResults.value = items
  } catch (e) {
    console.warn('[结果对比] 加载失败:', e)
    compareResults.value = []
  }
}

async function removeFromCompare(strategyId: string) {
  try {
    await strategyApi.deleteBacktestResult(strategyId)
  } catch (e) {
    console.warn('[结果对比] 删除失败:', e)
  }
  compareResults.value = compareResults.value.filter(item => item.strategy_id !== strategyId)
}

const RETURN_COLORS = ['#409eff', '#fa541c', '#52c41a', '#faad14', '#722ed1', '#eb2f96', '#13c2c2', '#f5222d']

const returnBarOption = computed(() => ({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  legend: { show: false },
  grid: { left: 60, right: 20, top: 30, bottom: 40 },
  xAxis: { type: 'category', data: compareResults.value.map(item => item.strategy_name), axisLabel: { interval: 0, rotate: 20 } },
  yAxis: { type: 'value', name: '总收益率(%)' },
  series: [{
    name: '总收益率',
    type: 'bar',
    barMaxWidth: 48,
    data: compareResults.value.map((item, i) => ({
      value: Number((item.stats.total_return * 100).toFixed(2)),
      itemStyle: { color: item.stats.total_return >= 0 ? RETURN_COLORS[i % RETURN_COLORS.length] : '#999' },
    })),
    label: { show: true, position: 'top', formatter: (p: any) => `${p.value}%` },
  }],
}))

const equityOverlayOption = computed(() => {
  const items = compareResults.value
  const dates = items[0]?.equity_curve.map(p => p.date) ?? []
  const series = items.map((item, index) => {
    const curve = item.equity_curve
    const initial = curve[0]?.value ?? 1
    return {
      name: item.strategy_name,
      type: 'line',
      showSymbol: false,
      data: curve.map(p => [p.date, initial > 0 ? p.value / initial : p.value]),
      lineStyle: { width: 2 },
      itemStyle: { color: RETURN_COLORS[index % RETURN_COLORS.length] },
    }
  })
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: items.map(item => item.strategy_name), top: 0 },
    grid: { left: 60, right: 20, top: 40, bottom: 40 },
    xAxis: { type: 'category', data: dates },
    yAxis: { type: 'value', scale: true, name: '净值(起始=1)' },
    series,
  }
})

// ---------------------------------------------------------------------------
// 异步回测任务：离开页面/刷新后仍可恢复进度，完成后自动展示结果
// ---------------------------------------------------------------------------
type TaskKind = 'strategy' | 'factor' | 'optimizer' | 'walkforward'

const BT_ACTIVE_KEY = 'strategy_backtest_active_task' // 记录当前进行中的任务

const runningKind = ref<TaskKind | null>(null)
const progressInfo = ref({ percent: 0, message: '', etaSec: 0, elapsedSec: 0 })
let pollTimer: ReturnType<typeof setInterval> | null = null

function saveActiveTask(kind: TaskKind, taskId: string | null) {
  try {
    if (taskId == null) {
      localStorage.removeItem(BT_ACTIVE_KEY)
      return
    }
    localStorage.setItem(BT_ACTIVE_KEY, JSON.stringify({ kind, task_id: taskId }))
  } catch (e) {
    console.warn('[回测任务] 本地保存失败:', e)
  }
}

function loadActiveTask(): { kind: TaskKind; task_id: string } | null {
  try {
    const raw = localStorage.getItem(BT_ACTIVE_KEY)
    if (!raw) return null
    const p = JSON.parse(raw)
    return p?.task_id ? { kind: p.kind, task_id: p.task_id } : null
  } catch {
    return null
  }
}

function clearActiveTask() {
  try {
    localStorage.removeItem(BT_ACTIVE_KEY)
  } catch { /* ignore */ }
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function formatEta(sec: number): string {
  if (!sec || sec < 0 || !isFinite(sec)) return ''
  if (sec < 60) return `${Math.max(1, Math.round(sec))} 秒`
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return s > 0 ? `${m} 分 ${s} 秒` : `${m} 分钟`
}

const resultSetters: Record<TaskKind, (r: any) => void> = {
  strategy: (r) => { strategyResult.value = r; saveResult('strategy', r) },
  factor: (r) => { factorResult.value = r; saveResult('factor', r) },
  optimizer: (r) => { optResult.value = r; saveResult('optimizer', r) },
  walkforward: (r) => { wfResult.value = r; saveResult('walkforward', r) },
}

const loadingSetters: Record<TaskKind, (v: boolean) => void> = {
  strategy: (v) => { strategyLoading.value = v },
  factor: (v) => { factorLoading.value = v },
  optimizer: (v) => { optLoading.value = v },
  walkforward: (v) => { wfLoading.value = v },
}

function pollTask(taskId: string, kind: TaskKind) {
  stopPolling()
  pollTimer = setInterval(async () => {
    try {
      const res = await strategyApi.getTask(taskId)
      const data = (res as any)?.data ?? res
      const status = data.status
      if (status === 'running') {
        const p = data.progress ?? 0
        const elapsed = (data.elapsed_ms ?? 0) / 1000
        // 进度低于 5% 时不显示预计时间：
        // 早期阶段（数据加载/技术指标计算）进度上报值小但耗时占比高，
        // 用 (elapsed/p)*(1-p) 外推会得到离谱的 ETA（如 99 分钟），误导用户。
        // 进度 >= 5% 后再显示，此时估算才有意义。
        const etaSec = p >= 0.05 && p < 1 ? (elapsed / p) * (1 - p) : 0
        progressInfo.value = {
          percent: Math.max(1, Math.round(p * 100)),
          message: data.message || '回测进行中…',
          elapsedSec: elapsed,
          etaSec,
        }
      } else if (status === 'success') {
        stopPolling()
        loadingSetters[kind](false)
        runningKind.value = null
        clearActiveTask()
        resultSetters[kind](data.result)
        ElMessage.success('回测已完成')
      } else if (status === 'failure') {
        stopPolling()
        loadingSetters[kind](false)
        runningKind.value = null
        clearActiveTask()
        ElMessage.error(data.error || '回测失败')
      }
    } catch (e) {
      // 瞬时网络错误忽略，下个周期重试
    }
  }, 2000)
}

function startTask(kind: TaskKind, taskId: string) {
  saveActiveTask(kind, taskId)
  runningKind.value = kind
  loadingSetters[kind](true)
  progressInfo.value = { percent: 0, message: '任务已提交，等待执行…', etaSec: 0, elapsedSec: 0 }
  pollTask(taskId, kind)
}

const parseParamGrid = (text: string): Record<string, any> => {
  if (!text.trim()) return {}
  try {
    const obj = JSON.parse(text)
    return obj && typeof obj === 'object' ? obj : {}
  } catch {
    ElMessage.error('参数网格 JSON 格式错误')
    throw new Error('JSON parse error')
  }
}

const loadStrategies = async () => {
  try {
    const res = await strategyApi.list()
    const list = (res as any)?.data ?? res
    strategies.value = Array.isArray(list) ? list : []
    if (strategies.value.length > 0) {
      const first = strategies.value[0].id
      btForm.value.strategy_id = first
      optForm.value.strategy_id = first
      wfForm.value.strategy_id = first
    }
  } catch {
    ElMessage.error('加载策略列表失败')
  }
}

const runStrategyBacktest = async () => {
  if (!btForm.value.strategy_id) return ElMessage.warning('请选择策略')
  if (!btRange.value?.[0]) return ElMessage.warning('请选择回测区间')
  try {
    const res = await strategyApi.startBacktest({
      strategy_id: btForm.value.strategy_id,
      start: btRange.value[0],
      end: btRange.value[1],
      params: {},
      entry_fill: 'open_t+1',
      exit_fill: 'open_t+1',
      fees_pct: btForm.value.fees_pct,
      slippage_bps: btForm.value.slippage_bps,
      max_positions: btForm.value.max_positions,
      max_exposure_pct: 1.0,
      initial_capital: btForm.value.initial_capital,
      position_sizing: btForm.value.position_sizing,
      stop_loss_pct: btForm.value.stop_loss_pct,
      take_profit_pct: btForm.value.take_profit_pct,
      max_hold_days: btForm.value.max_hold_days,
      holding_days: 5,
    })
    const data = (res as any)?.data ?? res
    if (!data?.task_id) return ElMessage.error('提交回测任务失败')
    startTask('strategy', data.task_id)
  } catch (e) {
    ElMessage.error('提交策略回测失败')
  }
}

const runFactorBacktest = async () => {
  if (!factorRange.value?.[0]) return ElMessage.warning('请选择回测区间')
  try {
    const res = await strategyApi.startFactorBacktest({
      factor_name: factorForm.value.factor_name,
      start: factorRange.value[0],
      end: factorRange.value[1],
      n_groups: factorForm.value.n_groups,
      rebalance: 'monthly',
    })
    const data = (res as any)?.data ?? res
    if (!data?.task_id) return ElMessage.error('提交因子回测任务失败')
    startTask('factor', data.task_id)
  } catch (e) {
    ElMessage.error('提交因子回测失败')
  }
}

const runOptimizer = async () => {
  if (!optForm.value.strategy_id) return ElMessage.warning('请选择策略')
  if (!optRange.value?.[0]) return ElMessage.warning('请选择回测区间')
  let paramGrid: Record<string, any>
  try { paramGrid = parseParamGrid(optForm.value.paramGridText) } catch { return }
  try {
    const res = await strategyApi.startOptimize({
      strategy_id: optForm.value.strategy_id,
      start: optRange.value[0],
      end: optRange.value[1],
      objective: optForm.value.objective,
      param_grid: Object.keys(paramGrid).length ? paramGrid : undefined,
      entry_fill: 'open_t+1',
      exit_fill: 'open_t+1',
      fees_pct: 0.0002,
      slippage_bps: 5,
      max_positions: 10,
      initial_capital: 1000000,
      position_sizing: 'equal',
    })
    const data = (res as any)?.data ?? res
    if (!data?.task_id) return ElMessage.error('提交参数优化任务失败')
    startTask('optimizer', data.task_id)
  } catch (e) {
    ElMessage.error('提交参数优化失败')
  }
}

const runWalkForward = async () => {
  if (!wfForm.value.strategy_id) return ElMessage.warning('请选择策略')
  if (!wfRange.value?.[0]) return ElMessage.warning('请选择回测区间')
  let paramGrid: Record<string, any>
  try { paramGrid = parseParamGrid(wfForm.value.paramGridText) } catch { return }
  try {
    const res = await strategyApi.startWalkforward({
      strategy_id: wfForm.value.strategy_id,
      start: wfRange.value[0],
      end: wfRange.value[1],
      train_days: wfForm.value.train_days,
      test_days: wfForm.value.test_days,
      param_grid: Object.keys(paramGrid).length ? paramGrid : undefined,
      entry_fill: 'open_t+1',
      exit_fill: 'open_t+1',
      fees_pct: 0.0002,
      slippage_bps: 5,
      max_positions: 10,
      initial_capital: 1000000,
      position_sizing: 'equal',
    })
    const data = (res as any)?.data ?? res
    if (!data?.task_id) return ElMessage.error('提交步进优化任务失败')
    startTask('walkforward', data.task_id)
  } catch (e) {
    ElMessage.error('提交步进优化失败')
  }
}

// 结果概览辅助函数
const formatMoney = (v: number | null | undefined) =>
  v != null ? Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 0 }) : '-'

const positionSizingLabel = (v: string | null | undefined) =>
  v === 'score_weight' ? '评分加权' : v === 'equal' ? '等权' : v || '-'

// 交易明细金额列（保留 2 位小数）
const toMoney = (v: number | null | undefined) =>
  v != null ? Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '-'

// 卖出原因展示：英文标识 → 中文 + 标签颜色
const exitReasonType = (r: string | undefined) => {
  switch (r) {
    case 'signal': return 'danger'
    case 'stop_loss': return 'warning'
    case 'take_profit': return 'success'
    case 'max_hold': return 'info'
    case 'end': return 'info'
    default: return 'primary'
  }
}
const exitReasonLabel = (r: string | undefined) => {
  switch (r) {
    case 'signal': return '信号卖出'
    case 'stop_loss': return '止损'
    case 'take_profit': return '止盈'
    case 'max_hold': return '超期'
    case 'end': return '期末'
    default: return r || '-'
  }
}

const equityOption = computed(() => {
  const curve = strategyResult.value?.equity_curve ?? []
  const initial = strategyResult.value?.config?.initial_capital ?? 1
  const legend = ['策略净值']
  // 策略净值 / 基准均以起始=1 归一化，便于在同一坐标轴比较相对收益
  const series: any[] = [{
    name: '策略净值',
    type: 'line',
    showSymbol: false,
    data: curve.map(p => [p.date, initial > 0 ? p.value / initial : p.value]),
    lineStyle: { width: 2 },
    itemStyle: { color: '#409eff' },
  }]
  const bench = strategyResult.value?.benchmark_curve ?? []
  if (bench.length) {
    const base = bench[0]?.value ?? 1
    legend.push('上证指数')
    series.push({
      name: '上证指数',
      type: 'line',
      showSymbol: false,
      data: bench.map(p => [p.date, base > 0 ? p.value / base : p.value]),
      lineStyle: { width: 1.5, type: 'dashed' },
      itemStyle: { color: '#67c23a' },
    })
  }
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: legend },
    grid: { left: 60, right: 20, top: 40, bottom: 40 },
    xAxis: { type: 'category', data: curve.map(p => p.date) },
    yAxis: { type: 'value', scale: true, name: '净值(起始=1)' },
    series,
  }
})

const icOption = computed(() => {
  const series = factorResult.value?.ic_series ?? []
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 60, right: 20, top: 20, bottom: 40 },
    xAxis: { type: 'category', data: series.map(p => p.date) },
    yAxis: { type: 'value', scale: true },
    series: [{
      name: 'IC',
      type: 'line',
      showSymbol: false,
      data: series.map(p => p.value),
      lineStyle: { width: 1.5 },
      itemStyle: { color: '#409eff' },
    }],
  }
})

onMounted(async () => {
  loadStrategies()
  // 加载「结果对比」收录数据
  loadStrategyResults()
  // 恢复上次保存的回测结果（离开页面/刷新后仍可查看）
  strategyResult.value = loadResult<BacktestResult>('strategy')
  factorResult.value = loadResult<FactorBacktestResult>('factor')
  optResult.value = loadResult<OptimizeResult>('optimizer')
  wfResult.value = loadResult<WalkForwardResult>('walkforward')

  // 恢复进行中的异步回测任务
  const active = loadActiveTask()
  if (active) {
    try {
      const res = await strategyApi.getTask(active.task_id)
      const data = (res as any)?.data ?? res
      if (data.status === 'running' && (data.kind === 'strategy' || data.kind === 'factor'
          || data.kind === 'optimizer' || data.kind === 'walkforward')) {
        startTask(active.kind, active.task_id)
      } else if (data.status === 'success') {
        resultSetters[active.kind]?.(data.result)
        clearActiveTask()
      } else {
        clearActiveTask()
      }
    } catch (e) {
      clearActiveTask()
    }
  }
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<style lang="scss" scoped>
.strategy-backtest {
  padding: 20px;
  max-width: 1600px;
  margin: 0 auto;

  .page-header {
    margin-bottom: 24px;
    padding-bottom: 16px;
    border-bottom: 2px solid var(--el-border-color-lighter);

    .page-title {
      display: flex;
      align-items: center;
      gap: 12px;
      font-size: 28px;
      font-weight: 700;
      color: var(--el-text-color-primary);
      margin: 0 0 8px 0;

      .el-icon { color: var(--el-color-primary); font-size: 28px; }
    }

    .page-description {
      color: var(--el-text-color-regular);
      margin: 0 0 16px 0;
      font-size: 14px;
    }
  }

  .form-panel {
    margin-bottom: 20px;
    border-radius: 12px;

    :deep(.el-card__header) {
      background: linear-gradient(135deg, var(--el-color-primary-light-9) 0%, var(--el-color-primary-light-8) 100%);
      padding: 14px 20px;
    }

    .panel-title { font-size: 15px; font-weight: 600; color: var(--el-text-color-primary); }

    .bt-form { padding: 16px; }
  }

  .result-header {
    margin-bottom: 20px;
    border-radius: 12px;
    border: 1px solid var(--el-border-color-lighter);
    background:
      linear-gradient(135deg, var(--el-color-primary-light-9) 0%, var(--el-bg-color) 55%);

    .result-header-inner { padding: 18px 20px; }

    .result-title {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 14px;

      .result-strategy-name {
        font-size: 20px;
        font-weight: 700;
        color: var(--el-text-color-primary);
      }
    }

    .result-meta {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: 12px 24px;

      .meta-item {
        display: flex;
        flex-direction: column;
        gap: 4px;

        .meta-label {
          font-size: 12px;
          color: var(--el-text-color-secondary);
        }

        .meta-value {
          font-size: 14px;
          font-weight: 600;
          color: var(--el-text-color-primary);
        }
      }
    }
  }

  .chart-panel,
  .stats-panel {
    margin-bottom: 20px;
    border-radius: 12px;

    :deep(.el-card__header) {
      background: linear-gradient(135deg, var(--el-color-info-light-9) 0%, var(--el-color-info-light-8) 100%);
      padding: 14px 20px;
    }

    .panel-title { font-size: 15px; font-weight: 600; color: var(--el-text-color-primary); }
  }

  .chart-panel {
    .chart { height: 320px; }
  }

  .stats-panel {
    :deep(.stat-cards) { margin-bottom: 0; }
  }

  .trade-table {
    border-radius: 8px;
    overflow: hidden;

    :deep(.el-table__header th) {
      background: var(--el-fill-color-light);
      color: var(--el-text-color-primary);
      font-weight: 600;
    }

    :deep(.el-table__row:hover) {
      background: var(--el-color-primary-light-9) !important;
    }
  }

  .stat-row {
    margin-bottom: 20px;

    :deep(.el-statistic__head) { font-size: 13px; }
  }

  .progress-panel {
    margin-bottom: 20px;
    border-radius: 12px;

    .progress-meta {
      display: flex;
      align-items: baseline;
      gap: 16px;
      margin-top: 12px;
      font-size: 13px;

      .progress-msg { color: var(--el-text-color-primary); }
      .progress-eta { color: var(--el-color-primary); font-weight: 600; }
      .progress-elapsed { color: var(--el-text-color-secondary); }
    }
  }

  .param-tag { margin-right: 6px; margin-bottom: 4px; }
  .text-red { color: var(--el-color-danger); font-weight: 600; }
  .text-green { color: var(--el-color-success); font-weight: 600; }
  .text-muted { color: var(--el-text-color-secondary); }

  .compare-panel {
    margin-bottom: 20px;
    border-radius: 12px;

    :deep(.el-card__header) {
      background: linear-gradient(135deg, var(--el-color-primary-light-9) 0%, var(--el-color-primary-light-8) 100%);
      padding: 14px 20px;
    }

    .panel-title { font-size: 15px; font-weight: 600; color: var(--el-text-color-primary); }

    .compare-table {
      .compare-strategy { font-weight: 600; color: var(--el-text-color-primary); }

      :deep(.el-table__header th) {
        background: var(--el-fill-color-light);
        color: var(--el-text-color-primary);
        font-weight: 600;
      }

      :deep(.el-table__row:hover) {
        background: var(--el-color-primary-light-9) !important;
      }
    }

    .compare-charts {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
      margin-top: 20px;

      @media (max-width: 1100px) {
        grid-template-columns: 1fr;
      }

      .chart-card {
        border: 1px solid var(--el-border-color-lighter);
        border-radius: 10px;
        padding: 14px;

        .chart-title {
          font-size: 14px;
          font-weight: 600;
          color: var(--el-text-color-primary);
          margin-bottom: 10px;
        }

        .chart { height: 340px; }
      }
    }
  }

  .stat-cards {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    gap: 14px;
    margin-bottom: 20px;

    .stat-card {
      background: var(--el-bg-color);
      border: 1px solid var(--el-border-color-lighter);
      padding: 16px;
      border-radius: 10px;
      transition: transform 0.15s ease, box-shadow 0.15s ease;

      &:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
      }

      .stat-label {
        font-size: 13px;
        color: var(--el-text-color-secondary);
        margin-bottom: 10px;
      }

      .stat-value {
        font-size: 20px;
        font-weight: 700;
        font-variant-numeric: tabular-nums;
      }
    }
  }
}

html.dark {
  .strategy-backtest {
    .form-panel,
    .chart-panel,
    .stats-panel {
      :deep(.el-card__header) {
        background: linear-gradient(135deg, var(--el-bg-color-overlay) 0%, var(--el-fill-color-darker) 100%);
      }
    }
  }
}
</style>
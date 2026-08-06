<template>
  <div class="retail-center">
    <!-- 页面标题 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><Aim /></el-icon>
        散户策略中心
      </h1>
      <p class="page-description">
        仓位管理 · 持仓监控 · 市场环境 · 策略说明 —— 散户交易四大核心能力一站式平台
      </p>
    </div>

    <!-- 标签页 -->
    <el-tabs v-model="activeTab" class="retail-tabs" type="border-card">
      <!-- ============ Tab 1: 策略说明 ============ -->
      <el-tab-pane label="策略说明" name="strategies">
        <div v-loading="strategyLoading" class="dashboard-container">
          <!-- 1. 市场环境概览卡片 -->
          <el-card shadow="never" class="dashboard-card market-overview-card">
            <template #header>
              <div class="card-header">
                <el-icon><TrendCharts /></el-icon>
                <span class="panel-title">市场环境概览</span>
                <span class="header-hint">实时掌握市场状态，辅助策略选择</span>
                <el-button type="success" size="small" :loading="autoRegimeLoading" @click="detectRegimeAuto" style="margin-left:auto;">
                  <el-icon><Aim /></el-icon> 一键检测市场环境
                </el-button>
              </div>
            </template>
            <el-row :gutter="16">
              <el-col :span="6">
                <div class="metric-card">
                  <div class="metric-label">趋势</div>
                  <div class="metric-value" v-if="regimeResult">
                    <el-tag :type="getTrendType(regimeResult.trend)" size="large" effect="dark">
                      {{ getTrendLabel(regimeResult.trend) }}
                    </el-tag>
                  </div>
                  <div class="metric-empty" v-else>点击右侧一键检测</div>
                </div>
              </el-col>
              <el-col :span="6">
                <div class="metric-card">
                  <div class="metric-label">波动率</div>
                  <div class="metric-value" v-if="regimeResult">
                    <el-tag :type="getVolType(regimeResult.volatility)" size="large" effect="dark">
                      {{ getVolLabel(regimeResult.volatility) }}
                    </el-tag>
                  </div>
                  <div class="metric-empty" v-else>点击右侧一键检测</div>
                </div>
              </el-col>
              <el-col :span="6">
                <div class="metric-card">
                  <div class="metric-label">市场宽度</div>
                  <div class="metric-value" v-if="regimeResult">
                    <el-tag :type="getBreadthType(regimeResult.breadth)" size="large" effect="dark">
                      {{ getBreadthLabel(regimeResult.breadth) }}
                    </el-tag>
                  </div>
                  <div class="metric-empty" v-else>点击右侧一键检测</div>
                </div>
              </el-col>
              <el-col :span="6">
                <div class="metric-card">
                  <div class="metric-label">情绪</div>
                  <div class="metric-value" v-if="regimeResult">
                    <el-tag :type="getSentimentType(regimeResult.sentiment)" size="large" effect="dark">
                      {{ getSentimentLabel(regimeResult.sentiment) }}
                    </el-tag>
                  </div>
                  <div class="metric-empty" v-else>点击右侧一键检测</div>
                </div>
              </el-col>
            </el-row>
            <div v-if="regimeResult" class="market-summary">
              <el-icon><InfoFilled /></el-icon>
              <span>{{ regimeResult.summary }}</span>
            </div>
          </el-card>

          <!-- 2. 策略快速入口 -->
          <el-card shadow="never" class="dashboard-card">
            <template #header>
              <div class="card-header">
                <el-icon><Aim /></el-icon>
                <span class="panel-title">策略快速入口</span>
                <span class="header-hint">六大精选策略，点击直达筛选页面</span>
              </div>
            </template>
            <el-row :gutter="16">
              <el-col :span="8" v-for="strategy in strategyQuickEntries" :key="strategy.key" style="margin-bottom: 16px;">
                <div class="strategy-quick-card" :style="{ borderTopColor: strategy.borderColor }">
                  <div class="strategy-quick-header">
                    <span class="strategy-quick-name">{{ strategy.name }}</span>
                    <el-tag :type="strategy.tagType" size="small" effect="plain">{{ strategy.marketTag }}</el-tag>
                  </div>
                  <div class="strategy-quick-desc">{{ strategy.description }}</div>
                  <el-button type="primary" size="small" @click="goToStrategy(strategy.route)" class="strategy-quick-btn">
                    立即查看 <el-icon><ArrowRight /></el-icon>
                  </el-button>
                </div>
              </el-col>
            </el-row>
          </el-card>

          <!-- 3. 策略表现统计 -->
          <el-card shadow="never" class="dashboard-card">
            <template #header>
              <div class="card-header">
                <el-icon><DataLine /></el-icon>
                <span class="panel-title">策略表现统计</span>
                <span class="header-hint">基于已平仓持仓的真实数据，交易满5次后自动反馈到仓位计算的胜率/盈亏比参数</span>
                <el-button size="small" :loading="perfLoading" @click="loadPerformance" style="margin-left:auto;">刷新统计</el-button>
              </div>
            </template>
            <div v-if="perfData">
              <el-descriptions :column="5" border size="small" style="margin-bottom: 12px;">
                <el-descriptions-item label="总交易次数">{{ perfData.overall.total_trades }}</el-descriptions-item>
                <el-descriptions-item label="总体胜率">
                  <span :style="{color: perfData.overall.win_rate >= 0.5 ? '#e6232a' : '#19a519', fontWeight:'bold'}">
                    {{ (perfData.overall.win_rate * 100).toFixed(1) }}%
                  </span>
                </el-descriptions-item>
                <el-descriptions-item label="盈亏比">{{ perfData.overall.profit_loss_ratio.toFixed(2) }}</el-descriptions-item>
                <el-descriptions-item label="平均盈利">{{ (perfData.overall.avg_win * 100).toFixed(2) }}%</el-descriptions-item>
                <el-descriptions-item label="平均亏损">{{ (perfData.overall.avg_loss * 100).toFixed(2) }}%</el-descriptions-item>
              </el-descriptions>

              <el-table :data="perfTableData" size="small" border>
                <el-table-column label="策略" width="140">
                  <template #default="{ row }">{{ getStrategyLabel(row.strategy) }}</template>
                </el-table-column>
                <el-table-column label="交易次数" prop="total_trades" width="100" sortable />
                <el-table-column label="胜率" width="100" sortable :sort-by="'win_rate'">
                  <template #default="{ row }">
                    <span :style="{color: row.win_rate >= 0.5 ? '#e6232a' : '#19a519', fontWeight:'bold'}">
                      {{ (row.win_rate * 100).toFixed(1) }}%
                    </span>
                  </template>
                </el-table-column>
                <el-table-column label="盈亏比" width="100" sortable :sort-by="'profit_loss_ratio'">
                  <template #default="{ row }">{{ row.profit_loss_ratio.toFixed(2) }}</template>
                </el-table-column>
                <el-table-column label="平均收益" width="120" sortable :sort-by="'avg_return'">
                  <template #default="{ row }">
                    <span :style="{color: row.avg_return >= 0 ? '#e6232a' : '#19a519'}">
                      {{ (row.avg_return * 100).toFixed(2) }}%
                    </span>
                  </template>
                </el-table-column>
                <el-table-column label="建议胜率参数" width="130">
                  <template #default="{ row }">
                    <el-tag size="small" :type="row.total_trades >= 5 ? 'success' : 'info'">
                      {{ (perfData.suggested_params[row.strategy].win_rate * 100).toFixed(0) }}%
                    </el-tag>
                    <span v-if="row.total_trades < 5" style="font-size:11px;color:#909399;margin-left:4px;">(默认)</span>
                  </template>
                </el-table-column>
                <el-table-column label="建议盈亏比参数" width="130">
                  <template #default="{ row }">
                    <el-tag size="small" :type="row.total_trades >= 5 ? 'success' : 'info'">
                      {{ perfData.suggested_params[row.strategy].profit_loss_ratio.toFixed(1) }}
                    </el-tag>
                    <span v-if="row.total_trades < 5" style="font-size:11px;color:#909399;margin-left:4px;">(默认)</span>
                  </template>
                </el-table-column>
              </el-table>
              <div style="margin-top:8px;font-size:12px;color:#909399;">
                注：交易次数不足5次的策略使用默认参数（胜率55%，盈亏比1.5），满5次后自动使用真实表现数据
              </div>
            </div>
            <el-empty v-else description="暂无已平仓持仓数据，平仓后将自动生成策略表现统计" />
          </el-card>

          <!-- 4. 策略详细说明（可折叠） -->
          <el-card shadow="never" class="dashboard-card">
            <template #header>
              <div class="card-header" style="cursor: pointer;" @click="strategyDetailVisible = !strategyDetailVisible">
                <el-icon><Aim /></el-icon>
                <span class="panel-title">策略详细说明</span>
                <span class="header-hint">点击展开/收起各策略的详细参数说明</span>
                <el-icon style="margin-left:auto; transition: transform 0.3s;" :style="{ transform: strategyDetailVisible ? 'rotate(180deg)' : 'rotate(0)' }">
                  <ArrowDown />
                </el-icon>
              </div>
            </template>
            <div v-show="strategyDetailVisible">
              <el-row :gutter="16">
                <el-col :span="12" v-for="(info, key) in strategyList" :key="key" style="margin-bottom: 16px;">
                  <el-card shadow="hover" class="strategy-card">
                    <template #header>
                      <div class="strategy-card-header">
                        <span class="strategy-name">{{ info.name }}</span>
                        <el-tag :type="getStrategyTagType(key)" size="small">{{ key }}</el-tag>
                      </div>
                    </template>
                    <div class="strategy-info-body">
                      <div class="info-row"><span class="info-label">散户优势：</span>{{ info.edge }}</div>
                      <div class="info-row"><span class="info-label">持有周期：</span>{{ info.hold_days }}</div>
                      <div class="info-row"><span class="info-label">盈利条件：</span>{{ info.win_condition }}</div>
                      <el-divider content-position="left" style="margin: 12px 0;">风控参数</el-divider>
                      <div class="risk-params" v-if="riskParams[key]">
                        <el-tag type="warning" size="small">单只≤{{ (riskParams[key].max_single_position * 100).toFixed(0) }}%</el-tag>
                        <el-tag type="warning" size="small">总仓≤{{ (riskParams[key].max_total_position * 100).toFixed(0) }}%</el-tag>
                        <el-tag type="danger" size="small">止损≤{{ (riskParams[key].max_single_loss * 100).toFixed(0) }}%</el-tag>
                      </div>
                    </div>
                  </el-card>
                </el-col>
              </el-row>
            </div>
          </el-card>
        </div>
      </el-tab-pane>

      <!-- ============ Tab 2: 仓位计算器 ============ -->
      <el-tab-pane label="仓位计算器" name="position">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <el-icon><Wallet /></el-icon>
              <span class="panel-title">仓位计算器</span>
              <span class="header-hint">输入账户信息和目标股票，获取建议买入股数和风控提示</span>
            </div>
          </template>

          <el-form :model="posForm" label-position="top" size="default">
            <el-row :gutter="24">
              <el-col :span="6">
                <el-form-item label="账户总资产（元）">
                  <el-input-number v-model="posForm.account_size" :min="1000" :step="10000" style="width:100%" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="目标股票代码">
                  <el-input v-model="posForm.symbol" placeholder="如 600519.SH" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="当前股价（元）">
                  <el-input-number v-model="posForm.price" :min="0.01" :step="0.1" :precision="2" style="width:100%" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="策略类型">
                  <el-select v-model="posForm.strategy" style="width:100%">
                    <el-option label="默认" value="default" />
                    <el-option label="极端情绪反转" value="extreme_reversal" />
                    <el-option label="困境反转" value="turnaround" />
                    <el-option label="小盘价值" value="small_cap_value" />
                    <el-option label="转债下修博弈" value="convertible_arbitrage" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="24">
              <el-col :span="6">
                <el-form-item label="行业">
                  <el-input v-model="posForm.industry" placeholder="如 白酒" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="主题">
                  <el-input v-model="posForm.theme" placeholder="如 消费" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="历史胜率">
                  <el-slider v-model="posForm.win_rate" :min="0" :max="1" :step="0.01" show-input :format-tooltip="v => (v*100).toFixed(0)+'%'" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="历史盈亏比">
                  <el-input-number v-model="posForm.profit_loss_ratio" :min="0.1" :step="0.1" :precision="1" style="width:100%" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="24">
              <el-col :span="6">
                <el-form-item label="当日成交额（元，可选）">
                  <el-input-number v-model="posForm.daily_volume_amount" :min="0" :step="1000000" style="width:100%" />
                </el-form-item>
              </el-col>
            </el-row>

            <!-- 当前持仓（简化） -->
            <el-divider content-position="left">当前持仓（用于风控计算，可留空）</el-divider>
            <el-table :data="posForm.holdings" size="small" border style="margin-bottom:12px;">
              <el-table-column label="代码" width="140">
                <template #default="{ row }"><el-input v-model="row.symbol" size="small" /></template>
              </el-table-column>
              <el-table-column label="行业" width="120">
                <template #default="{ row }"><el-input v-model="row.industry" size="small" /></template>
              </el-table-column>
              <el-table-column label="市值(元)" width="140">
                <template #default="{ row }"><el-input-number v-model="row.market_value" :min="0" size="small" style="width:100%" /></template>
              </el-table-column>
              <el-table-column label="仓位占比" width="120">
                <template #default="{ row }"><el-input-number v-model="row.position_ratio" :min="0" :max="1" :step="0.01" :precision="2" size="small" style="width:100%" /></template>
              </el-table-column>
              <el-table-column label="操作" width="80">
                <template #default="{ $index }"><el-button type="danger" size="small" link @click="posForm.holdings.splice($index,1)">删除</el-button></template>
              </el-table-column>
            </el-table>
            <el-button size="small" @click="posForm.holdings.push({ symbol:'', industry:'', market_value:0, position_ratio:0 })">+ 添加持仓</el-button>

            <div style="margin-top:16px; text-align:center;">
              <el-button type="primary" size="large" :loading="posLoading" @click="calcPosition">
                <el-icon><MagicStick /></el-icon> 计算仓位建议
              </el-button>
            </div>
          </el-form>

          <!-- 仓位建议结果 -->
          <div v-if="posAdvice" class="advice-result">
            <el-divider />
            <el-result
              :icon="posAdvice.blocked ? 'error' : 'success'"
              :title="posAdvice.blocked ? '买入被风控阻断' : `建议买入 ${posAdvice.suggested_shares} 股`"
              :sub-title="posAdvice.blocked ? posAdvice.block_reasons.join('；') : `建议金额 ${posAdvice.suggested_amount.toLocaleString()} 元，目标仓位 ${(posAdvice.target_position_ratio*100).toFixed(1)}%`"
            />
            <div v-if="!posAdvice.blocked" class="advice-details">
              <el-descriptions :column="2" border size="small">
                <el-descriptions-item label="建议股数">{{ posAdvice.suggested_shares }} 股</el-descriptions-item>
                <el-descriptions-item label="建议金额">{{ posAdvice.suggested_amount.toLocaleString() }} 元</el-descriptions-item>
                <el-descriptions-item label="目标仓位">{{ (posAdvice.target_position_ratio*100).toFixed(2) }}%</el-descriptions-item>
                <el-descriptions-item label="买入后总仓位">{{ (posAdvice.total_position_ratio_after*100).toFixed(2) }}%</el-descriptions-item>
              </el-descriptions>
            </div>
            <div v-if="posAdvice.warnings && posAdvice.warnings.length" class="advice-warnings">
              <el-alert v-for="(w, i) in posAdvice.warnings" :key="i" :title="w" type="warning" :closable="false" show-icon style="margin-bottom:6px;" />
            </div>
            <div v-if="posAdvice.block_reasons && posAdvice.block_reasons.length" class="advice-warnings">
              <el-alert v-for="(r, i) in posAdvice.block_reasons" :key="i" :title="r" type="error" :closable="false" show-icon style="margin-bottom:6px;" />
            </div>
          </div>
        </el-card>
      </el-tab-pane>

      <!-- ============ Tab 3: 持仓监控 ============ -->
      <el-tab-pane label="持仓监控" name="exits">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <el-icon><DataLine /></el-icon>
              <span class="panel-title">持仓退出信号监控</span>
              <span class="header-hint">可一键加载真实持仓（来自模拟交易），或手动添加检查止盈/止损/时间止损信号</span>
              <el-button size="small" type="primary" :loading="loadPositionsLoading" @click="loadRealPositions" style="margin-left:auto;">加载真实持仓</el-button>
            </div>
          </template>

          <el-table :data="exitHoldings" size="small" border style="margin-bottom:12px;">
            <el-table-column label="代码" width="130">
              <template #default="{ row }"><el-input v-model="row.symbol" size="small" :disabled="row._real" /></template>
            </el-table-column>
            <el-table-column label="策略" width="160">
              <template #default="{ row }">
                <el-select v-model="row.strategy" size="small" style="width:100%" :disabled="row._real">
                  <el-option label="默认" value="default" />
                  <el-option label="极端反转" value="extreme_reversal" />
                  <el-option label="困境反转" value="turnaround" />
                  <el-option label="小盘价值" value="small_cap_value" />
                  <el-option label="转债博弈" value="convertible_arbitrage" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="买入价" width="100">
              <template #default="{ row }"><el-input-number v-model="row.buy_price" :min="0" :step="0.1" :precision="2" size="small" style="width:100%" :disabled="row._real" /></template>
            </el-table-column>
            <el-table-column label="买入日期" width="140">
              <template #default="{ row }"><el-date-picker v-model="row.buy_date" type="date" value-format="YYYY-MM-DD" size="small" style="width:100%" :disabled="row._real" /></template>
            </el-table-column>
            <el-table-column label="当前价" width="100">
              <template #default="{ row }"><el-input-number v-model="row.current_price" :min="0" :step="0.1" :precision="2" size="small" style="width:100%" /></template>
            </el-table-column>
            <el-table-column label="当前MA(可选)" width="110">
              <template #default="{ row }"><el-input-number v-model="row.current_ma" :min="0" :step="0.1" :precision="2" size="small" style="width:100%" /></template>
            </el-table-column>
            <el-table-column label="逻辑证伪" width="80">
              <template #default="{ row }"><el-switch v-model="row.thesis_invalid" size="small" /></template>
            </el-table-column>
            <el-table-column label="操作" width="80">
              <template #default="{ $index }"><el-button type="danger" size="small" link @click="exitHoldings.splice($index,1)">删除</el-button></template>
            </el-table-column>
          </el-table>
          <el-button size="small" @click="addExitHolding">+ 手动添加持仓</el-button>

          <div style="margin-top:16px; text-align:center;">
            <el-button type="primary" size="large" :loading="exitLoading" @click="checkExits">
              <el-icon><Clock /></el-icon> 检查退出信号
            </el-button>
          </div>
        </el-card>

        <!-- 退出信号结果 -->
        <el-card v-if="exitResult" shadow="never" style="margin-top:16px;">
          <template #header>
            <div class="card-header">
              <el-icon><Warning /></el-icon>
              <span class="panel-title">退出信号结果</span>
              <el-badge :value="`${exitResult.exits_count} 个触发`" :type="exitResult.exits_count > 0 ? 'danger' : 'info'" />
            </div>
          </template>
          <el-table :data="exitResult.signals" size="small" border>
            <el-table-column label="代码" prop="symbol" width="120">
              <template #default="{ row }">
                <router-link :to="`/stocks/${row.symbol}`" class="stock-code">{{ row.symbol }}</router-link>
              </template>
            </el-table-column>
            <el-table-column label="是否退出" width="100">
              <template #default="{ row }">
                <el-tag :type="row.should_exit ? 'danger' : 'success'" size="small">{{ row.should_exit ? '需退出' : '继续持有' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="退出原因" width="120">
              <template #default="{ row }">
                <el-tag :type="getExitReasonType(row.reason)" size="small">{{ getExitReasonLabel(row.reason) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="当前盈亏" width="100">
              <template #default="{ row }">
                <span :style="{color: row.current_pnl_pct >= 0 ? '#e6232a' : '#19a519', fontWeight:'bold'}">
                  {{ (row.current_pnl_pct * 100).toFixed(2) }}%
                </span>
              </template>
            </el-table-column>
            <el-table-column label="持仓天数" prop="holding_days" width="90" />
            <el-table-column label="建议卖出比例" width="120">
              <template #default="{ row }">{{ (row.suggested_sell_ratio * 100).toFixed(0) }}%</template>
            </el-table-column>
            <el-table-column label="详情" prop="detail" min-width="200" />
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- ============ Tab 4: 市场环境 ============ -->
      <el-tab-pane label="市场环境" name="regime">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <el-icon><TrendCharts /></el-icon>
              <span class="panel-title">市场环境检测</span>
              <span class="header-hint">可一键自动采集市场数据，或手动输入指标判断趋势/波动率/宽度/情绪</span>
            </div>
          </template>

          <div style="margin-bottom: 16px; text-align: right;">
            <el-button type="success" :loading="autoRegimeLoading" @click="detectRegimeAuto">
              <el-icon><Aim /></el-icon> 一键自动采集并检测
            </el-button>
          </div>

          <el-form :model="regimeForm" label-position="top" size="default">
            <el-row :gutter="24">
              <el-col :span="6">
                <el-form-item label="指数当前价格">
                  <el-input-number v-model="regimeForm.index_price" :min="0" :step="1" :precision="2" style="width:100%" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="指数MA250">
                  <el-input-number v-model="regimeForm.index_ma250" :min="0" :step="1" :precision="2" style="width:100%" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="波动率分位(0-1)">
                  <el-slider v-model="regimeForm.volatility_percentile" :min="0" :max="1" :step="0.01" show-input />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="市场宽度(站上均线占比)">
                  <el-slider v-model="regimeForm.breadth_ratio" :min="0" :max="1" :step="0.01" show-input />
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="24">
              <el-col :span="8">
                <el-form-item label="融资余额变化(%)">
                  <el-input-number v-model="regimeForm.margin_balance_change_pct" :step="0.1" :precision="2" style="width:100%" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="换手率(%)">
                  <el-input-number v-model="regimeForm.turnover_ratio" :min="0" :step="0.1" :precision="2" style="width:100%" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="换手率MA20(%)">
                  <el-input-number v-model="regimeForm.turnover_ma20" :min="0" :step="0.1" :precision="2" style="width:100%" />
                </el-form-item>
              </el-col>
            </el-row>
            <div style="text-align:center; margin-top:12px;">
              <el-button type="primary" size="large" :loading="regimeLoading" @click="detectRegime">
                <el-icon><Aim /></el-icon> 手动检测市场环境
              </el-button>
            </div>
          </el-form>
        </el-card>

        <!-- 市场环境结果 -->
        <el-card v-if="regimeResult" shadow="never" style="margin-top:16px;">
          <template #header>
            <div class="card-header">
              <el-icon><Odometer /></el-icon>
              <span class="panel-title">环境检测结果</span>
              <el-tag v-if="regimeDataMode === 'auto'" type="success" size="small" effect="plain">数据来源：自动采集</el-tag>
              <el-tag v-else type="info" size="small" effect="plain">数据来源：手动输入</el-tag>
            </div>
          </template>
          <el-row :gutter="16">
            <el-col :span="6">
              <div class="regime-box">
                <div class="regime-label">趋势</div>
                <el-tag :type="getTrendType(regimeResult.trend)" size="large">{{ getTrendLabel(regimeResult.trend) }}</el-tag>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="regime-box">
                <div class="regime-label">波动率</div>
                <el-tag :type="getVolType(regimeResult.volatility)" size="large">{{ getVolLabel(regimeResult.volatility) }}</el-tag>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="regime-box">
                <div class="regime-label">市场宽度</div>
                <el-tag :type="getBreadthType(regimeResult.breadth)" size="large">{{ getBreadthLabel(regimeResult.breadth) }}</el-tag>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="regime-box">
                <div class="regime-label">情绪</div>
                <el-tag :type="getSentimentType(regimeResult.sentiment)" size="large">{{ getSentimentLabel(regimeResult.sentiment) }}</el-tag>
              </div>
            </el-col>
          </el-row>
          <el-divider />
          <div class="regime-summary">
            <el-icon><InfoFilled /></el-icon>
            <span>{{ regimeResult.summary }}</span>
          </div>
          <el-divider content-position="left">当前环境建议激活的策略</el-divider>
          <div class="active-strategies">
            <el-tag
              v-for="s in ['extreme_reversal','turnaround','small_cap_value','convertible_arbitrage']"
              :key="s"
              :type="regimeResult.active_strategies.includes(s) ? 'success' : 'info'"
              :effect="regimeResult.active_strategies.includes(s) ? 'dark' : 'plain'"
              size="large"
              style="margin-right: 12px;"
            >
              {{ getStrategyLabel(s) }}{{ regimeResult.active_strategies.includes(s) ? ' ✓' : ' ✗' }}
            </el-tag>
          </div>
          <!-- 自动采集的原始数据 -->
          <template v-if="regimeRawData">
            <el-divider content-position="left">自动采集的原始市场数据</el-divider>
            <el-descriptions :column="4" border size="small">
              <el-descriptions-item label="沪深300价格">{{ regimeRawData.index_price.toFixed(2) }}</el-descriptions-item>
              <el-descriptions-item label="沪深300 MA250">{{ regimeRawData.index_ma250.toFixed(2) }}</el-descriptions-item>
              <el-descriptions-item label="波动率分位">{{ (regimeRawData.volatility_percentile * 100).toFixed(1) }}%</el-descriptions-item>
              <el-descriptions-item label="市场宽度">{{ (regimeRawData.breadth_ratio * 100).toFixed(1) }}%</el-descriptions-item>
              <el-descriptions-item label="融资余额5日变化">{{ (regimeRawData.margin_balance_change_pct * 100).toFixed(2) }}%</el-descriptions-item>
              <el-descriptions-item label="全市场换手率">{{ regimeRawData.turnover_ratio.toFixed(2) }}%</el-descriptions-item>
              <el-descriptions-item label="换手率MA20">{{ regimeRawData.turnover_ma20.toFixed(2) }}%</el-descriptions-item>
              <el-descriptions-item label="指数vs MA250">
                <span :style="{color: regimeRawData.index_price >= regimeRawData.index_ma250 ? '#e6232a' : '#19a519', fontWeight:'bold'}">
                  {{ regimeRawData.index_price >= regimeRawData.index_ma250 ? '在MA250上方（多头）' : '在MA250下方（空头）' }}
                </span>
              </el-descriptions-item>
            </el-descriptions>
          </template>
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Aim, Wallet, DataLine, Warning,
  Clock, TrendCharts, Odometer, InfoFilled, MagicStick,
  ArrowRight, ArrowDown
} from '@element-plus/icons-vue'
import { retailApi, type PositionAdvice, type ExitResp, type MarketRegime, type RegimeRawData, type StrategiesResp, type StrategiesPerformanceResp, type StrategyPerformance } from '@/api/retail'
import { paperApi } from '@/api/paper'

const router = useRouter()

const activeTab = ref('strategies')

// ---- 策略说明 ----
const strategyLoading = ref(false)
const strategyList = ref<Record<string, any>>({})
const riskParams = ref<Record<string, any>>({})
const strategyDetailVisible = ref(false)

const strategyQuickEntries = [
  {
    key: 'extreme_reversal',
    name: '极端反转',
    description: '市场情绪极端恐慌时抄底，高胜率短线策略',
    marketTag: '熊市/震荡市',
    tagType: 'danger',
    borderColor: '#e6232a',
    route: '/screening/extreme-reversal'
  },
  {
    key: 'small_cap_value',
    name: '小盘价值',
    description: '低估值小盘股价值投资，中长期持有策略',
    marketTag: '震荡市/牛市',
    tagType: 'success',
    borderColor: '#19a519',
    route: '/screening/small-cap-value'
  },
  {
    key: 'turnaround',
    name: '困境反转',
    description: '基本面拐点型公司，困境反转超额收益',
    marketTag: '熊市末期/牛市',
    tagType: 'warning',
    borderColor: '#e6a23c',
    route: '/screening/turnaround'
  },
  {
    key: 'convertible_arbitrage',
    name: '转债下修',
    description: '可转债下修博弈，低风险套利策略',
    marketTag: '全市场',
    tagType: 'primary',
    borderColor: '#409eff',
    route: '/screening/convertible-arbitrage'
  },
  {
    key: 'limit_up_pullback',
    name: '涨停回调',
    description: '强势股涨停后回调买入，短线波段策略',
    marketTag: '牛市/震荡市',
    tagType: 'danger',
    borderColor: '#f56c6c',
    route: '/screening/limit-up-pullback'
  },
  {
    key: 'three_buys_three_sells',
    name: '三买三卖',
    description: '缠论三买三卖策略，技术面趋势跟踪',
    marketTag: '趋势市',
    tagType: 'warning',
    borderColor: '#e6a23c',
    route: '/screening/three-buys-three-sells'
  }
]

const goToStrategy = (route: string) => {
  router.push(route)
}

const loadStrategies = async () => {
  strategyLoading.value = true
  try {
    const res = await retailApi.getStrategies()
    strategyList.value = res.strategies || {}
    riskParams.value = res.risk_params || {}
  } catch (e: any) {
    ElMessage.error('加载策略列表失败：' + (e.message || e))
  } finally {
    strategyLoading.value = false
  }
}

// ---- 策略表现统计 ----
const perfLoading = ref(false)
const perfData = ref<StrategiesPerformanceResp | null>(null)
const perfTableData = computed<StrategyPerformance[]>(() => {
  if (!perfData.value?.strategies) return []
  return Object.values(perfData.value.strategies).filter(s => s.strategy !== 'default')
})

const loadPerformance = async () => {
  perfLoading.value = true
  try {
    perfData.value = await retailApi.getStrategiesPerformance()
  } catch (e: any) {
    ElMessage.error('加载策略表现统计失败：' + (e.message || e))
  } finally {
    perfLoading.value = false
  }
}

// ---- 仓位计算器 ----
const posLoading = ref(false)
const posAdvice = ref<PositionAdvice | null>(null)
const posForm = reactive({
  account_size: 100000,
  symbol: '',
  price: 10,
  strategy: 'default',
  industry: '未知',
  theme: '未知',
  win_rate: 0.55,
  profit_loss_ratio: 1.5,
  daily_volume_amount: null as number | null,
  holdings: [] as any[],
})

const calcPosition = async () => {
  if (!posForm.symbol) { ElMessage.warning('请输入目标股票代码'); return }
  if (!posForm.price || posForm.price <= 0) { ElMessage.warning('请输入有效的股价'); return }
  posLoading.value = true
  try {
    const payload = {
      account_size: posForm.account_size,
      holdings: posForm.holdings.filter(h => h.symbol),
      symbol: posForm.symbol,
      strategy: posForm.strategy,
      price: posForm.price,
      win_rate: posForm.win_rate,
      profit_loss_ratio: posForm.profit_loss_ratio,
      industry: posForm.industry || '未知',
      theme: posForm.theme || '未知',
      daily_volume_amount: posForm.daily_volume_amount,
    }
    posAdvice.value = await retailApi.calculatePosition(payload)
  } catch (e: any) {
    ElMessage.error('仓位计算失败：' + (e.message || e))
  } finally {
    posLoading.value = false
  }
}

// ---- 持仓监控 ----
const exitLoading = ref(false)
const exitResult = ref<ExitResp | null>(null)
const exitHoldings = ref<any[]>([])
const loadPositionsLoading = ref(false)

const addExitHolding = () => {
  exitHoldings.value.push({
    symbol: '',
    strategy: 'default',
    buy_price: 0,
    buy_date: new Date().toISOString().slice(0, 10),
    current_price: 0,
    current_ma: null,
    thesis_invalid: false,
    thesis_invalid_reason: '',
  })
}

// 从 paper_positions 加载真实持仓，填充到退出信号检查表
const loadRealPositions = async () => {
  loadPositionsLoading.value = true
  try {
    const resp: any = await paperApi.getPositions()
    const items = resp?.items || []
    if (!items.length) {
      ElMessage.info('暂无模拟交易持仓，请先在策略筛选页买入或手动添加')
      return
    }
    exitHoldings.value = items.map((p: any) => ({
      symbol: p.code || p.symbol || '',
      strategy: p.strategy || 'default',
      buy_price: p.avg_cost || p.cost_price || 0,
      buy_date: p.buy_date || (p.updated_at ? String(p.updated_at).slice(0, 10) : new Date().toISOString().slice(0, 10)),
      current_price: p.last_price || 0,
      current_ma: null,
      thesis_invalid: false,
      thesis_invalid_reason: '',
      _real: true,  // 标记为真实持仓，部分字段不可编辑
    }))
    ElMessage.success(`已加载 ${items.length} 条真实持仓，请补充当前价后检查退出信号`)
  } catch (e: any) {
    ElMessage.error('加载持仓失败：' + (e?.message || e))
  } finally {
    loadPositionsLoading.value = false
  }
}

const checkExits = async () => {
  const valid = exitHoldings.value.filter(h => h.symbol && h.buy_price > 0 && h.current_price > 0)
  if (!valid.length) { ElMessage.warning('请至少添加一条有效的持仓记录（含代码、买入价、当前价）'); return }
  exitLoading.value = true
  try {
    exitResult.value = await retailApi.checkExits({ holdings: valid })
    if (exitResult.value.exits_count > 0) {
      ElMessage.warning(`检测到 ${exitResult.value.exits_count} 个持仓触发退出信号！`)
    } else {
      ElMessage.success('所有持仓暂无退出信号，可继续持有')
    }
  } catch (e: any) {
    ElMessage.error('退出信号检查失败：' + (e.message || e))
  } finally {
    exitLoading.value = false
  }
}

// ---- 市场环境 ----
const regimeLoading = ref(false)
const autoRegimeLoading = ref(false)
const regimeResult = ref<MarketRegime | null>(null)
const regimeRawData = ref<RegimeRawData | null>(null)
const regimeDataMode = ref<'auto' | 'manual'>('manual')
const regimeForm = reactive({
  index_price: 3800,
  index_ma250: 3700,
  volatility_percentile: 0.5,
  breadth_ratio: 0.5,
  margin_balance_change_pct: 0,
  turnover_ratio: 1.5,
  turnover_ma20: 1.5,
})

const detectRegime = async () => {
  regimeLoading.value = true
  try {
    regimeResult.value = await retailApi.detectRegime({ ...regimeForm })
    regimeRawData.value = null
    regimeDataMode.value = 'manual'
  } catch (e: any) {
    ElMessage.error('市场环境检测失败：' + (e.message || e))
  } finally {
    regimeLoading.value = false
  }
}

const detectRegimeAuto = async () => {
  autoRegimeLoading.value = true
  try {
    const res = await retailApi.detectRegimeAuto()
    regimeResult.value = {
      trend: res.trend,
      volatility: res.volatility,
      breadth: res.breadth,
      sentiment: res.sentiment,
      active_strategies: res.active_strategies,
      summary: res.summary,
    }
    regimeRawData.value = res.raw_data
    regimeDataMode.value = 'auto'
    // 同步回填表单，方便用户微调
    if (res.raw_data) {
      regimeForm.index_price = res.raw_data.index_price
      regimeForm.index_ma250 = res.raw_data.index_ma250
      regimeForm.volatility_percentile = res.raw_data.volatility_percentile
      regimeForm.breadth_ratio = res.raw_data.breadth_ratio
      regimeForm.margin_balance_change_pct = res.raw_data.margin_balance_change_pct * 100
      regimeForm.turnover_ratio = res.raw_data.turnover_ratio
      regimeForm.turnover_ma20 = res.raw_data.turnover_ma20
    }
    ElMessage.success('市场数据自动采集完成')
  } catch (e: any) {
    ElMessage.error('自动采集市场数据失败：' + (e.message || e))
  } finally {
    autoRegimeLoading.value = false
  }
}

// ---- 辅助函数 ----
const getStrategyTagType = (key: string) => {
  const map: Record<string, string> = { extreme_reversal: 'danger', turnaround: 'warning', small_cap_value: 'success', convertible_arbitrage: 'primary' }
  return map[key] || 'info'
}
const getStrategyLabel = (s: string) => {
  const map: Record<string, string> = { extreme_reversal: '极端反转', turnaround: '困境反转', small_cap_value: '小盘价值', convertible_arbitrage: '转债博弈' }
  return map[s] || s
}
const getExitReasonType = (reason: string) => {
  const map: Record<string, string> = { stop_loss: 'danger', take_profit: 'success', time_stop: 'warning', thesis_invalid: 'danger', none: 'info' }
  return map[reason] || 'info'
}
const getExitReasonLabel = (reason: string) => {
  const map: Record<string, string> = { stop_loss: '止损', take_profit: '止盈', time_stop: '时间止损', thesis_invalid: '逻辑证伪', none: '无' }
  return map[reason] || reason
}
const getTrendType = (t: string) => ({ bull: 'success', bear: 'danger', range: 'warning' }[t] || 'info')
const getTrendLabel = (t: string) => ({ bull: '牛市', bear: '熊市', range: '震荡' }[t] || t)
const getVolType = (v: string) => ({ high: 'danger', normal: 'info', low: 'success' }[v] || 'info')
const getVolLabel = (v: string) => ({ high: '高波动', normal: '正常', low: '低波动' }[v] || v)
const getBreadthType = (b: string) => ({ broad: 'success', narrow: 'danger', normal: 'warning' }[b] || 'info')
const getBreadthLabel = (b: string) => ({ broad: '宽度健康', narrow: '宽度收窄', normal: '宽度正常' }[b] || b)
const getSentimentType = (s: string) => ({ euphoric: 'danger', neutral: 'info', panic: 'success' }[s] || 'info')
const getSentimentLabel = (s: string) => ({ euphoric: '过热', neutral: '中性', panic: '恐慌' }[s] || s)

onMounted(() => {
  loadStrategies()
  loadPerformance()
})
</script>

<style scoped>
.retail-center { padding: 16px; }
.page-header { margin-bottom: 16px; }
.page-title { font-size: 22px; font-weight: 700; margin: 0 0 6px 0; display: flex; align-items: center; gap: 8px; }
.page-description { color: #909399; font-size: 13px; margin: 0; }
.retail-tabs { margin-top: 8px; }
.card-header { display: flex; align-items: center; gap: 8px; }
.panel-title { font-weight: 600; font-size: 15px; }
.header-hint { color: #909399; font-size: 12px; margin-left: 8px; }
.strategy-card { height: 100%; }
.strategy-card-header { display: flex; justify-content: space-between; align-items: center; }
.strategy-name { font-weight: 600; font-size: 15px; }
.strategy-info-body { font-size: 13px; line-height: 1.8; }
.info-row { margin-bottom: 4px; }
.info-label { color: #909399; font-weight: 500; }
.risk-params { display: flex; gap: 8px; flex-wrap: wrap; }
.advice-result { margin-top: 8px; }
.advice-details { margin-top: 12px; }
.advice-warnings { margin-top: 12px; }
.regime-box { text-align: center; padding: 16px; background: #f5f7fa; border-radius: 8px; }
.regime-label { font-size: 13px; color: #909399; margin-bottom: 10px; }
.regime-summary { font-size: 14px; line-height: 1.8; color: #606266; display: flex; align-items: flex-start; gap: 8px; }
.active-strategies { display: flex; flex-wrap: wrap; gap: 4px; }

/* 仪表盘样式 */
.dashboard-container { display: flex; flex-direction: column; gap: 16px; }
.dashboard-card { border-radius: 8px; }

/* 市场环境概览 */
.market-overview-card .metric-card {
  text-align: center;
  padding: 20px 16px;
  background: linear-gradient(135deg, #f5f7fa 0%, #eef1f6 100%);
  border-radius: 8px;
  transition: all 0.3s ease;
}
.market-overview-card .metric-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}
.metric-label {
  font-size: 13px;
  color: #909399;
  margin-bottom: 12px;
  font-weight: 500;
}
.metric-value {
  display: flex;
  justify-content: center;
}
.metric-empty {
  font-size: 12px;
  color: #c0c4cc;
  font-style: italic;
}
.market-summary {
  margin-top: 16px;
  padding: 12px 16px;
  background: #ecf5ff;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.6;
  color: #409eff;
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

/* 策略快速入口卡片 */
.strategy-quick-card {
  background: #fff;
  border: 1px solid #e4e7ed;
  border-top: 3px solid;
  border-radius: 8px;
  padding: 16px;
  transition: all 0.3s ease;
  height: 100%;
  display: flex;
  flex-direction: column;
}
.strategy-quick-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.1);
}
.strategy-quick-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.strategy-quick-name {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}
.strategy-quick-desc {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
  margin-bottom: 16px;
  flex: 1;
}
.strategy-quick-btn {
  align-self: flex-end;
}
</style>

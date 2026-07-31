<template>
  <div class="limit-up-pullback">
    <!-- 页面标题 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><TrendCharts /></el-icon>
        涨停回调（龙回头）
      </h1>
      <p class="page-description">
        涨停板回调战法，筛选主力建仓后缩量洗盘、即将启动主升浪的强势股
      </p>
    </div>

    <!-- 策略说明卡片 -->
    <el-collapse class="strategy-intro-collapse" v-model="introCollapsed">
      <el-collapse-item name="intro">
        <template #title>
          <div class="collapse-title">
            <el-icon><InfoFilled /></el-icon>
            <span>策略原理</span>
            <el-tag type="warning" size="small" effect="plain">龙回头/N字反包</el-tag>
          </div>
        </template>

        <div class="strategy-detail">
          <p class="strategy-overview">
            <strong>核心逻辑：</strong>主力用涨停板快速建仓或拉升后，会进行3-5天的缩量洗盘，清洗浮筹、测试支撑。
            当洗盘末端出现<strong>地量+长下影线</strong>（抛压衰竭）或<strong>放量突破5日线</strong>（洗盘结束）时，
            就是最佳介入时机，博弈主升浪启动。
          </p>
          
          <el-row :gutter="16" style="margin-top: 16px;">
            <el-col :span="4">
              <div class="step-item">
                <div class="step-number">1</div>
                <div class="step-content">
                  <h4>涨停建仓</h4>
                  <p>涨停板是主力信号：快速吸筹或启动，表明有市场地位和资金关注。筛选近期涨停股作为候选池。</p>
                </div>
              </div>
            </el-col>
            <el-col :span="4">
              <div class="step-item">
                <div class="step-number">2</div>
                <div class="step-content">
                  <h4>缩量洗盘</h4>
                  <p>涨停后3-8天缩量回调，成交量萎缩至涨停日的1/3以下，主力锁仓不动，散户恐慌抛售。回调期间收盘价基本在10日线上方。</p>
                </div>
              </div>
            </el-col>
            <el-col :span="4">
              <div class="step-item">
                <div class="step-number">3</div>
                <div class="step-content">
                  <h4>地量止跌</h4>
                  <p>洗盘末端第3-5天出现地量（近20日最低且涨停日1/3以下）+长下影线（实体比≥2倍），抛压衰竭，左侧潜伏买点。</p>
                </div>
              </div>
            </el-col>
            <el-col :span="4">
              <div class="step-item">
                <div class="step-number">4</div>
                <div class="step-content">
                  <h4>放量突破</h4>
                  <p>放量（≥1.5倍均量）站上5日线和回调前高，5日线走平上翘且上穿10日线，上影线≤2.5%，洗盘确认结束，右侧确认买点。</p>
                </div>
              </div>
            </el-col>
            <el-col :span="4">
              <div class="step-item">
                <div class="step-number" style="background: #f56c6c;">5</div>
                <div class="step-content">
                  <h4>动态止盈止损</h4>
                  <p>ATR止损（优先）：买入价下方0.4倍ATR；10日线止损（备选）；8天时间止盈；放量滞涨高位止盈；盈利后5日线/ATR移动止盈（取较高者）。</p>
                </div>
              </div>
            </el-col>
            <el-col :span="4">
              <div class="step-item">
                <div class="step-number" style="background: #409eff;">6</div>
                <div class="step-content">
                  <h4>大盘环境过滤</h4>
                  <p>市场上涨比例低于30%时空仓回避，极端熊市不交易，只在市场环境较好时操作，大幅降低系统性风险。</p>
                </div>
              </div>
            </el-col>
          </el-row>

          <!-- 信号演化路径 - 垂直时间轴布局，与三买三卖统一 -->
          <div class="evolution-panel" style="margin-top: 16px;">
            <div class="card-header" style="margin-bottom: 12px;">
              <div style="display: flex; align-items: center; gap: 12px;">
                <el-icon :size="20"><TrendCharts /></el-icon>
                <span class="panel-title">信号演化路径（按时间顺序）</span>
              </div>
              <el-tag type="info" size="small" effect="plain">从涨停到止盈止损的完整交易周期</el-tag>
            </div>

            <div class="evolution-timeline">
              <div v-for="(step, idx) in evolutionSteps" :key="idx" class="evolution-step">
                <div class="step-marker">
                  <div class="step-dot" :class="'phase-' + (idx + 1)">{{ idx + 1 }}</div>
                  <div v-if="idx < evolutionSteps.length - 1" class="step-line"></div>
                </div>
                <div class="step-content">
                  <div class="step-phase-row">
                    <span class="step-phase">{{ step.phase }}</span>
                    <div class="step-signals">
                      <el-tag
                        v-for="sig in step.signals"
                        :key="sig"
                        :type="getEvolutionSignalTag(sig) as any"
                        size="small"
                        effect="dark"
                        class="step-signal-tag"
                      >
                        {{ sig }}
                      </el-tag>
                    </div>
                  </div>
                  <div class="step-desc">{{ step.desc }}</div>
                  <div class="step-action">
                    <el-icon size="14" color="#409eff"><Position /></el-icon>
                    <span class="step-action-text"><strong>操作指南：</strong>{{ step.action }}</span>
                  </div>
                  <div class="step-meta">
                    <el-tag size="small" type="warning" effect="plain" class="step-meta-tag">{{ step.risk }}</el-tag>
                    <el-tag size="small" type="primary" effect="plain" class="step-meta-tag">{{ step.position }}</el-tag>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </el-collapse-item>
    </el-collapse>

    <!-- Tab切换 -->
    <el-tabs v-model="activeTab" style="margin-top: 16px;">
      <!-- 扫描结果Tab -->
      <el-tab-pane label="扫描结果" name="scan">
        <el-card class="result-panel" shadow="never">
          <template #header>
            <div class="card-header">
              <div style="display: flex; align-items: center; justify-content: space-between; width: 100%;">
                <div style="display: flex; align-items: center; gap: 12px;">
                  <el-icon><List /></el-icon>
                  <span class="panel-title">扫描结果</span>
                  <el-tag v-if="results.length > 0" type="success" size="small" effect="plain">
                    找到 {{ results.length }} 只
                  </el-tag>
                  <el-tag v-if="scannedCount > 0" type="warning" size="small" effect="plain">
                    覆盖 {{ scannedCount }} 只
                  </el-tag>
                  <el-tag v-if="tookMs" type="info" size="small" effect="plain">
                    耗时 {{ (tookMs / 1000).toFixed(1) }}s
                  </el-tag>
                </div>
                <div style="display: flex; align-items: center; gap: 12px;">
                  <el-form-item label="返回数量" label-width="70px" style="margin-bottom: 0;">
                    <el-input-number v-model="params.limit" :min="10" :max="200" :step="10" size="default" style="width: 130px;" />
                  </el-form-item>
                  <el-button type="primary" :loading="loading" @click="doScan" size="default">
                    <el-icon><Search /></el-icon>
                    开始扫描
                  </el-button>
                </div>
              </div>
            </div>
          </template>

          <!-- 评分分析 -->
          <el-row v-if="results.length > 0" :gutter="16" style="margin-bottom: 16px;">
            <el-col :span="24">
              <el-card shadow="never" class="score-stats-card">
                <template #header>
                  <div class="card-header">
                    <div style="display: flex; align-items: center; gap: 12px;">
                      <el-icon><DataLine /></el-icon>
                      <span class="panel-title">扫描结果统计</span>
                    </div>
                  </div>
                </template>
                <el-row :gutter="16">
                  <el-col :span="6">
                    <div class="stat-item">
                      <div class="stat-value">{{ results.length }}</div>
                      <div class="stat-label">符合条件股票</div>
                    </div>
                  </el-col>
                  <el-col :span="6">
                    <div class="stat-item">
                      <div class="stat-value">{{ avgScore.toFixed(1) }}</div>
                      <div class="stat-label">平均综合评分</div>
                    </div>
                  </el-col>
                  <el-col :span="6">
                    <div class="stat-item">
                      <div class="stat-value">{{ highScoreCount }}</div>
                      <div class="stat-label">高分股(≥70分)</div>
                    </div>
                  </el-col>
                  <el-col :span="6">
                    <div class="stat-item">
                      <div class="stat-value">{{ (tookMs / 1000).toFixed(1) }}s</div>
                      <div class="stat-label">扫描耗时</div>
                    </div>
                  </el-col>
                </el-row>
              </el-card>
            </el-col>
          </el-row>

          <!-- 空状态 -->
          <div v-if="!loading && results.length === 0 && !hasSearched" class="empty-state">
            <el-empty description="调整参数后点击开始扫描">
              <el-button type="primary" @click="doScan">立即扫描</el-button>
            </el-empty>
          </div>

          <!-- 加载中 -->
          <div v-if="loading" class="loading-state">
            <el-loading fullscreen-text="正在扫描全市场股票，请稍候..." />
          </div>

          <!-- 结果表格 -->
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
            <el-table-column prop="code" label="代码" width="80" fixed="left">
              <template #default="{ row }">
                <router-link :to="`/stocks/${row.code}`" class="stock-code">{{ row.code }}</router-link>
              </template>
            </el-table-column>
            <el-table-column prop="name" label="名称" width="100" fixed="left">
              <template #default="{ row }">
                <router-link :to="`/stocks/${row.code}`" class="stock-name">{{ row.name }}</router-link>
              </template>
            </el-table-column>
            <el-table-column prop="industry" label="行业" width="100" />
            <el-table-column prop="close" label="现价" width="90" sortable>
              <template #default="{ row }">
                <span class="price">{{ row.close.toFixed(2) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="pct_chg" label="涨跌幅" width="100" sortable>
              <template #default="{ row }">
                <span :class="['pct', row.pct_chg >= 0 ? 'up' : 'down']">
                  {{ row.pct_chg >= 0 ? '+' : '' }}{{ row.pct_chg.toFixed(2) }}%
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="limit_up_date" label="涨停日期" width="110" />
            <el-table-column label="缩量回调" width="200">
              <template #default="{ row }">
                <div class="date-range">
                  <span class="date-item">{{ row.pullback_start_date || '-' }}</span>
                  <span class="date-arrow">→</span>
                  <span class="date-item">{{ row.pullback_end_date || '-' }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="底部观察日" width="140">
              <template #default="{ row }">
                <span v-if="row.bottom_watch_start_date" class="date-tag info">{{ row.bottom_watch_start_date }}~{{ row.bottom_watch_end_date }}</span>
                <span v-else class="empty-tag">-</span>
              </template>
            </el-table-column>
            <el-table-column prop="left_buy_date" label="左侧买点" width="110">
              <template #default="{ row }">
                <span v-if="row.left_buy_date" class="date-tag warning">{{ row.left_buy_date }}</span>
                <span v-else class="empty-tag">-</span>
              </template>
            </el-table-column>
            <el-table-column prop="right_buy_date" label="右侧买点" width="110">
              <template #default="{ row }">
                <span v-if="row.right_buy_date" class="date-tag success">{{ row.right_buy_date }}</span>
                <span v-else class="empty-tag">-</span>
              </template>
            </el-table-column>
            <el-table-column prop="days_since_limit_up" label="回调天数" width="100" sortable>
              <template #default="{ row }">{{ row.days_since_limit_up }}天</template>
            </el-table-column>
            <el-table-column prop="pullback_depth" label="回调幅度" width="100" sortable>
              <template #default="{ row }">-{{ row.pullback_depth.toFixed(1) }}%</template>
            </el-table-column>
            <el-table-column prop="volume_shrink_ratio" label="缩量比例" width="100" sortable>
              <template #default="{ row }">{{ (row.volume_shrink_ratio * 100).toFixed(1) }}%</template>
            </el-table-column>
            <el-table-column prop="ground_volume_ratio" label="地量比例" width="100" sortable>
              <template #default="{ row }">{{ (row.ground_volume_ratio * 100).toFixed(1) }}%</template>
            </el-table-column>
            <el-table-column prop="signal_type" label="信号类型" width="110">
              <template #default="{ row }">
                <el-tag :type="getSignalTypeTag(row.signal_type)" size="small">
                  {{ row.signal_type }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="score" label="综合评分" width="120" sortable fixed="right">
              <template #default="{ row }">
                <el-popover placement="left" :width="400" trigger="click">
                  <template #reference>
                    <div class="score-cell">
                      <el-progress :percentage="row.score" :color="getScoreColor(row.score)" :show-text="true" :stroke-width="12" />
                      <span class="score-hint">点击查看明细</span>
                    </div>
                  </template>
                  <div class="score-detail-popover">
                    <div class="score-detail-title">评分明细</div>
                    <div v-if="getScoreRadarOption(row)" class="score-radar-wrap">
                      <v-chart :option="getScoreRadarOption(row)" style="height: 220px;" autoresize />
                    </div>
                    <div v-if="row.score_details && row.score_details.length" class="score-detail-list">
                      <div v-for="(detail, idx) in row.score_details" :key="idx" class="score-detail-text-item">
                        {{ detail }}
                      </div>
                    </div>
                    <div v-else class="score-detail-empty">暂无评分明细</div>
                  </div>
                </el-popover>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="200" fixed="right">
              <template #default="{ row }">
                <router-link :to="{ path: '/analysis/single', query: { stock: row.code } }" class="table-link">分析</router-link>
                <el-button type="success" link @click="addToFavorites(row)">自选</el-button>
                <el-button type="primary" link @click="openBuyDialog(row)">买入</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- 回测分析Tab -->
      <el-tab-pane label="回测分析" name="backtest">
        <!-- 回测参数配置 -->
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

        <!-- 回测空状态 -->
        <el-card v-if="!backtestResult && !backtestLoading" shadow="never">
          <el-empty description="配置回测参数后点击开始回测，回测可能耗时2-5分钟">
            <el-button type="success" @click="doBacktest">立即回测</el-button>
          </el-empty>
        </el-card>

        <!-- 回测loading -->
        <el-card v-if="backtestLoading" shadow="never" v-loading="backtestLoading" element-loading-text="正在回测，请耐心等待（可能需要2-5分钟）...">
          <div style="height: 200px;"></div>
        </el-card>

        <!-- 回测结果 -->
        <div v-if="backtestResult">
          <!-- 核心指标卡片 -->
          <el-row :gutter="16">
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">回测期间所有买入信号触发的交易总数。每只股票每天只能买入一次，同一只股票不同日期会产生多笔交易。</div>
                  </template>
                  <div class="metric-label">总交易次数</div>
                </el-tooltip>
                <div class="metric-value">{{ backtestResult.total_trades }}</div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">盈利交易数 ÷ 总交易数 × 100%。盈利定义为卖出价 > 买入价。胜率高不代表策略好，需要结合盈亏比分析。</div>
                  </template>
                  <div class="metric-label">胜率</div>
                </el-tooltip>
                <div class="metric-value" :class="backtestResult.win_rate >= 50 ? 'up' : 'down'">
                  {{ backtestResult.win_rate.toFixed(2) }}%
                </div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">所有交易收益率的简单平均值。计算公式：(盈利交易收益 + 亏损交易收益) ÷ 总交易数。反映单笔交易的平均表现。</div>
                  </template>
                  <div class="metric-label">平均收益</div>
                </el-tooltip>
                <div class="metric-value" :class="backtestResult.avg_return >= 0 ? 'up' : 'down'">
                  {{ backtestResult.avg_return >= 0 ? '+' : '' }}{{ backtestResult.avg_return.toFixed(2) }}%
                </div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">从历史最高点到最低点的最大跌幅，按复利计算。计算公式：(最高点净值 - 当前净值) ÷ 最高点净值 × 100%。反映策略的最大风险暴露。</div>
                  </template>
                  <div class="metric-label">最大回撤</div>
                </el-tooltip>
                <div class="metric-value down">{{ backtestResult.max_drawdown.toFixed(2) }}%</div>
              </el-card>
            </el-col>
          </el-row>

          <!-- 其他指标 -->
          <el-row :gutter="16" style="margin-top: 16px;">
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">回测期间的累计收益，按复利计算。计算公式：期末净值 ÷ 期初净值 - 1。期初净值=1，每天收益=当日选中股票平均收益。</div>
                  </template>
                  <div class="metric-label">总收益</div>
                </el-tooltip>
                <div class="metric-value" :class="backtestResult.total_return >= 0 ? 'up' : 'down'">
                  {{ backtestResult.total_return >= 0 ? '+' : '' }}{{ backtestResult.total_return.toFixed(2) }}%
                </div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">仅计算盈利交易的平均收益率。反映赚钱交易的平均盈利幅度。理想值应显著大于平均亏损的绝对值。</div>
                  </template>
                  <div class="metric-label">平均盈利</div>
                </el-tooltip>
                <div class="metric-value up">+{{ backtestResult.avg_win.toFixed(2) }}%</div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">仅计算亏损交易的平均收益率（取负值）。反映亏钱交易的平均亏损幅度。策略能否盈利的关键：平均盈利 > 平均亏损 × 胜率补偿。</div>
                  </template>
                  <div class="metric-label">平均亏损</div>
                </el-tooltip>
                <div class="metric-value down">{{ backtestResult.avg_loss.toFixed(2) }}</div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">回测期间实际有交易的天数（不包含无信号的交易日）。总交易次数 ÷ 回测天数 = 日均交易笔数。</div>
                  </template>
                  <div class="metric-label">回测天数</div>
                </el-tooltip>
                <div class="metric-value">{{ backtestResult.backtest_days }}</div>
              </el-card>
            </el-col>
          </el-row>

          <!-- 风险收益指标 -->
          <el-row :gutter="16" style="margin-top: 16px;">
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">平均盈利 ÷ 平均亏损的绝对值。反映盈亏不对称性。>1表示赚的时候比亏的时候多，配合胜率评估策略质量。</div>
                  </template>
                  <div class="metric-label">盈亏比</div>
                </el-tooltip>
                <div class="metric-value" :class="backtestResult.profit_loss_ratio >= 1 ? 'up' : 'down'">
                  {{ backtestResult.profit_loss_ratio.toFixed(2) }}
                </div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">年化超额收益 ÷ 年化波动率。衡量风险调整后收益。>1良好，>2优秀，>3卓越。</div>
                  </template>
                  <div class="metric-label">夏普比率</div>
                </el-tooltip>
                <div class="metric-value" :class="backtestResult.sharpe_ratio >= 1 ? 'up' : 'down'">
                  {{ backtestResult.sharpe_ratio.toFixed(2) }}
                </div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">年化收益 ÷ 最大回撤。衡量每承担1单位回撤能获得多少收益。>1良好，>3优秀。</div>
                  </template>
                  <div class="metric-label">卡玛比率</div>
                </el-tooltip>
                <div class="metric-value" :class="backtestResult.calmar_ratio >= 1 ? 'up' : 'down'">
                  {{ backtestResult.calmar_ratio.toFixed(2) }}
                </div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">按252个交易日年化后的收益率。便于不同周期的策略横向对比。</div>
                  </template>
                  <div class="metric-label">年化收益</div>
                </el-tooltip>
                <div class="metric-value" :class="backtestResult.annualized_return >= 0 ? 'up' : 'down'">
                  {{ backtestResult.annualized_return >= 0 ? '+' : '' }}{{ backtestResult.annualized_return.toFixed(2) }}%
                </div>
              </el-card>
            </el-col>
          </el-row>

          <!-- 资金统计 -->
          <el-row :gutter="16" style="margin-top: 16px;">
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">连续亏损交易的最大次数。反映策略的心理承受压力，连续亏损太多容易让人放弃。</div>
                  </template>
                  <div class="metric-label">最大连续亏损</div>
                </el-tooltip>
                <div class="metric-value down">{{ backtestResult.max_consecutive_losses }} 次</div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">回测期间所有交易的手续费和滑点估算。双边手续费0.1%+滑点0.3%。</div>
                  </template>
                  <div class="metric-label">手续费估算</div>
                </el-tooltip>
                <div class="metric-value down">¥{{ backtestResult.total_fees_est.toLocaleString() }}</div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">回测结束时的总资产（现金 + 持仓市值清算后）。</div>
                  </template>
                  <div class="metric-label">最终资金</div>
                </el-tooltip>
                <div class="metric-value" :class="backtestResult.final_capital >= backtestResult.initial_capital ? 'up' : 'down'">
                  ¥{{ backtestResult.final_capital.toLocaleString() }}
                </div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="metric-card">
                <el-tooltip effect="dark" placement="top">
                  <template #content>
                    <div class="tooltip-detail">回测开始时的初始资金。</div>
                  </template>
                  <div class="metric-label">初始资金</div>
                </el-tooltip>
                <div class="metric-value">¥{{ backtestResult.initial_capital.toLocaleString() }}</div>
              </el-card>
            </el-col>
          </el-row>

          <el-card shadow="never" style="margin-top: 16px;">
            <template #header>
              <div class="card-header">
                <div style="display: flex; align-items: center; gap: 12px;">
                  <el-icon><TrendCharts /></el-icon>
                  <span class="panel-title">收益曲线</span>
                </div>
              </div>
            </template>
            <v-chart :option="equityCurveOption" style="height: 300px;" autoresize />
          </el-card>

          <!-- 信号类型统计 + 卖出原因统计 -->
          <el-row :gutter="16" style="margin-top: 16px;">
            <el-col :span="12">
              <el-card shadow="never">
                <template #header>
                  <div class="card-header">
                    <span>信号类型统计</span>
                  </div>
                </template>
                <el-table :data="signalStatsList" stripe style="width: 100%">
                  <el-table-column prop="signal_type" label="信号类型" width="150">
                    <template #default="{ row }">
                      <el-tag :type="getSignalTypeTag(row.signal_type)" size="small">
                        {{ row.signal_type }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column prop="count" label="交易次数" width="120" />
                  <el-table-column prop="win_rate" label="胜率" width="120">
                    <template #default="{ row }">
                      <span :class="['pct', row.win_rate >= 50 ? 'up' : 'down']">{{ row.win_rate.toFixed(2) }}%</span>
                    </template>
                  </el-table-column>
                  <el-table-column prop="avg_return" label="平均收益">
                    <template #default="{ row }">
                      <span :class="['pct', row.avg_return >= 0 ? 'up' : 'down']">
                        {{ row.avg_return >= 0 ? '+' : '' }}{{ row.avg_return.toFixed(2) }}%
                      </span>
                    </template>
                  </el-table-column>
                </el-table>
              </el-card>
            </el-col>

            <el-col :span="12">
              <el-card shadow="never">
                <template #header>
                  <div class="card-header">
                    <span>卖出原因统计</span>
                  </div>
                </template>
                <el-table :data="sellReasonStatsList" stripe style="width: 100%">
                  <el-table-column prop="sell_reason" label="卖出原因" width="150">
                    <template #default="{ row }">
                      <el-tag :type="getSellReasonTag(row.sell_reason)" size="small">
                        {{ row.sell_reason }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column prop="count" label="交易次数" width="120" />
                  <el-table-column prop="win_rate" label="胜率" width="120">
                    <template #default="{ row }">
                      <span :class="['pct', row.win_rate >= 50 ? 'up' : 'down']">{{ row.win_rate.toFixed(2) }}%</span>
                    </template>
                  </el-table-column>
                  <el-table-column prop="avg_return" label="平均收益">
                    <template #default="{ row }">
                      <span :class="['pct', row.avg_return >= 0 ? 'up' : 'down']">
                        {{ row.avg_return >= 0 ? '+' : '' }}{{ row.avg_return.toFixed(2) }}%
                      </span>
                    </template>
                  </el-table-column>
                </el-table>
              </el-card>
            </el-col>
          </el-row>

          <!-- 盈利最多交易 -->
          <el-card shadow="never" style="margin-top: 16px;">
            <template #header>
              <div class="card-header">
                <span>盈利最多交易</span>
              </div>
            </template>
            <el-table :data="backtestResult.top_trades" stripe style="width: 100%">
              <el-table-column prop="code" label="代码" width="80">
                <template #default="{ row }">
                  <router-link :to="`/stocks/${row.code}`" class="stock-code">{{ row.code }}</router-link>
                </template>
              </el-table-column>
              <el-table-column prop="name" label="名称" width="100">
                <template #default="{ row }">
                  <router-link :to="`/stocks/${row.code}`" class="stock-name">{{ row.name }}</router-link>
                </template>
              </el-table-column>
              <el-table-column prop="limit_up_date" label="涨停日" width="105" />
              <el-table-column label="左侧买点" width="105">
                <template #default="{ row }">
                  <span v-if="row.left_buy_date" class="date-tag warning">{{ row.left_buy_date }}</span>
                  <span v-else class="empty-tag">-</span>
                </template>
              </el-table-column>
              <el-table-column label="右侧买点" width="105">
                <template #default="{ row }">
                  <span v-if="row.right_buy_date" class="date-tag success">{{ row.right_buy_date }}</span>
                  <span v-else class="empty-tag">-</span>
                </template>
              </el-table-column>
              <el-table-column prop="buy_date" label="实际买入" width="105" />
              <el-table-column prop="sell_date" label="卖出日期" width="105" />
              <el-table-column label="止损卖点" width="105">
                <template #default="{ row }">
                  <span v-if="row.stop_loss_date" class="date-tag danger">{{ row.stop_loss_date }}</span>
                  <span v-else class="empty-tag">-</span>
                </template>
              </el-table-column>
              <el-table-column label="时间止盈" width="105">
                <template #default="{ row }">
                  <span v-if="row.time_stop_date" class="date-tag warning">{{ row.time_stop_date }}</span>
                  <span v-else class="empty-tag">-</span>
                </template>
              </el-table-column>
              <el-table-column label="高位止盈" width="105">
                <template #default="{ row }">
                  <span v-if="row.high_stop_date" class="date-tag success">{{ row.high_stop_date }}</span>
                  <span v-else class="empty-tag">-</span>
                </template>
              </el-table-column>
              <el-table-column label="5日线止盈" width="105">
                <template #default="{ row }">
                  <span v-if="row.ma5_stop_date" class="date-tag success">{{ row.ma5_stop_date }}</span>
                  <span v-else class="empty-tag">-</span>
                </template>
              </el-table-column>
              <el-table-column prop="buy_price" label="买入价" width="80">
                <template #default="{ row }">{{ row.buy_price.toFixed(2) }}</template>
              </el-table-column>
              <el-table-column prop="sell_price" label="卖出价" width="80">
                <template #default="{ row }">{{ row.sell_price.toFixed(2) }}</template>
              </el-table-column>
              <el-table-column prop="return_pct" label="收益率" width="100" sortable>
                <template #default="{ row }">
                  <span :class="['pct', row.return_pct >= 0 ? 'up' : 'down']">
                    {{ row.return_pct >= 0 ? '+' : '' }}{{ row.return_pct.toFixed(2) }}%
                  </span>
                </template>
              </el-table-column>
              <el-table-column prop="signal_type" label="信号类型" width="100">
                <template #default="{ row }">
                  <el-tag :type="getSignalTypeTag(row.signal_type)" size="small">{{ row.signal_type }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="sell_reason" label="卖出原因" width="110">
                <template #default="{ row }">
                  <el-tag :type="getSellReasonTag(row.sell_reason)" size="small">{{ row.sell_reason }}</el-tag>
                </template>
              </el-table-column>
            </el-table>
          </el-card>

          <!-- 亏损最多交易 -->
          <el-card shadow="never" style="margin-top: 16px;">
            <template #header>
              <div class="card-header">
                <span>亏损最多交易</span>
              </div>
            </template>
            <el-table :data="backtestResult.worst_trades" stripe style="width: 100%">
              <el-table-column prop="code" label="代码" width="80">
                <template #default="{ row }">
                  <router-link :to="`/stocks/${row.code}`" class="stock-code">{{ row.code }}</router-link>
                </template>
              </el-table-column>
              <el-table-column prop="name" label="名称" width="100">
                <template #default="{ row }">
                  <router-link :to="`/stocks/${row.code}`" class="stock-name">{{ row.name }}</router-link>
                </template>
              </el-table-column>
              <el-table-column prop="limit_up_date" label="涨停日" width="105" />
              <el-table-column label="左侧买点" width="105">
                <template #default="{ row }">
                  <span v-if="row.left_buy_date" class="date-tag warning">{{ row.left_buy_date }}</span>
                  <span v-else class="empty-tag">-</span>
                </template>
              </el-table-column>
              <el-table-column label="右侧买点" width="105">
                <template #default="{ row }">
                  <span v-if="row.right_buy_date" class="date-tag success">{{ row.right_buy_date }}</span>
                  <span v-else class="empty-tag">-</span>
                </template>
              </el-table-column>
              <el-table-column prop="buy_date" label="实际买入" width="105" />
              <el-table-column prop="sell_date" label="卖出日期" width="105" />
              <el-table-column label="止损卖点" width="105">
                <template #default="{ row }">
                  <span v-if="row.stop_loss_date" class="date-tag danger">{{ row.stop_loss_date }}</span>
                  <span v-else class="empty-tag">-</span>
                </template>
              </el-table-column>
              <el-table-column label="时间止盈" width="105">
                <template #default="{ row }">
                  <span v-if="row.time_stop_date" class="date-tag warning">{{ row.time_stop_date }}</span>
                  <span v-else class="empty-tag">-</span>
                </template>
              </el-table-column>
              <el-table-column label="高位止盈" width="105">
                <template #default="{ row }">
                  <span v-if="row.high_stop_date" class="date-tag success">{{ row.high_stop_date }}</span>
                  <span v-else class="empty-tag">-</span>
                </template>
              </el-table-column>
              <el-table-column label="5日线止盈" width="105">
                <template #default="{ row }">
                  <span v-if="row.ma5_stop_date" class="date-tag success">{{ row.ma5_stop_date }}</span>
                  <span v-else class="empty-tag">-</span>
                </template>
              </el-table-column>
              <el-table-column prop="buy_price" label="买入价" width="80">
                <template #default="{ row }">{{ row.buy_price.toFixed(2) }}</template>
              </el-table-column>
              <el-table-column prop="sell_price" label="卖出价" width="80">
                <template #default="{ row }">{{ row.sell_price.toFixed(2) }}</template>
              </el-table-column>
              <el-table-column prop="return_pct" label="收益率" width="100" sortable>
                <template #default="{ row }">
                  <span :class="['pct', row.return_pct >= 0 ? 'up' : 'down']">
                    {{ row.return_pct >= 0 ? '+' : '' }}{{ row.return_pct.toFixed(2) }}%
                  </span>
                </template>
              </el-table-column>
              <el-table-column prop="signal_type" label="信号类型" width="100">
                <template #default="{ row }">
                  <el-tag :type="getSignalTypeTag(row.signal_type)" size="small">{{ row.signal_type }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="sell_reason" label="卖出原因" width="110">
                <template #default="{ row }">
                  <el-tag :type="getSellReasonTag(row.sell_reason)" size="small">{{ row.sell_reason }}</el-tag>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </div>
      </el-tab-pane>
    </el-tabs>

    <RetailBuyDialog
      v-model:visible="buyDialogVisible"
      :code="buyTarget.code"
      :stock-name="buyTarget.stockName"
      :price="buyTarget.price"
      :strategy="buyTarget.strategy"
      @success="onBuySuccess"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  TrendCharts,
  InfoFilled,
  Refresh,
  Search,
  List,
  DataLine,
  DataAnalysis,
  QuestionFilled,
  Position
} from '@element-plus/icons-vue'
import { use as echartsUse } from 'echarts/core'
import { RadarChart, LineChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import {
  screeningApi,
  type LimitUpPullbackItem,
  type LimitUpPullbackScanReq,
  type LimitUpPullbackBacktestReq,
  type LimitUpPullbackBacktestResp
} from '@/api/screening'
import { favoritesApi } from '@/api/favorites'
import RetailBuyDialog from './components/RetailBuyDialog.vue'

echartsUse([RadarChart, LineChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent, CanvasRenderer])

const router = useRouter()

const STORAGE_KEY = 'limit_up_pullback_scan_result'
const BACKTEST_STORAGE_KEY = 'limit_up_pullback_backtest_result'

const activeTab = ref<'scan' | 'backtest'>('scan')

const loading = ref(false)
const results = ref<LimitUpPullbackItem[]>([])
const tookMs = ref(0)
const scannedCount = ref(0)
const hasSearched = ref(false)
const introCollapsed = ref<string[]>([])

function saveScanResult() {
  if (!results.value || results.value.length === 0) {
    console.log(`[${STORAGE_KEY}] saveScanResult: skipped (empty results)`)
    return
  }
  const data = {
    results: results.value,
    tookMs: tookMs.value,
    scannedCount: scannedCount.value,
    scanParams: { ...params },
    timestamp: Date.now()
  }
  try {
    const jsonStr = JSON.stringify(data)
    console.log(`[${STORAGE_KEY}] saveScanResult:`, jsonStr.length, 'chars')
    localStorage.setItem(STORAGE_KEY, jsonStr)
    console.log(`[${STORAGE_KEY}] saveScanResult: saved successfully`)
  } catch (e) {
    console.warn(`[${STORAGE_KEY}] Failed to save scan result to localStorage`, e)
  }
}

function loadScanResult() {
  console.log(`[${STORAGE_KEY}] loadScanResult called`)
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    console.log(`[${STORAGE_KEY}] loadScanResult: stored=${stored ? 'found (' + stored.length + ' chars)' : 'null'}`)
    if (stored) {
      const data = JSON.parse(stored)
      console.log(`[${STORAGE_KEY}] loadScanResult: parsed, results=${data.results?.length}`)
      if (data.results && data.results.length > 0) {
        results.value = data.results
        tookMs.value = data.tookMs || 0
        scannedCount.value = data.scannedCount || 0
        if (data.scanParams) {
          Object.assign(params, defaultParams, data.scanParams)
        }
        hasSearched.value = true
        console.log(`[${STORAGE_KEY}] loadScanResult: loaded successfully, ${data.results.length} items`)
        return true
      } else {
        console.log(`[${STORAGE_KEY}] loadScanResult: empty results`)
      }
    }
  } catch (e) {
    console.warn(`[${STORAGE_KEY}] Failed to load scan result from localStorage`, e)
  }
  return false
}

function clearScanResult() {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch (e) {
    console.warn('Failed to clear scan result from localStorage', e)
  }
}

function saveBacktestResult() {
  if (!backtestResult.value) return
  const data = {
    backtestResult: backtestResult.value,
    backtestParams: { ...backtestParams },
    timestamp: Date.now()
  }
  try {
    localStorage.setItem(BACKTEST_STORAGE_KEY, JSON.stringify(data))
  } catch (e) {
    console.warn('Failed to save backtest result to localStorage', e)
  }
}

function loadBacktestResult() {
  try {
    const stored = localStorage.getItem(BACKTEST_STORAGE_KEY)
    if (stored) {
      const data = JSON.parse(stored)
      if (data.backtestResult) {
        backtestResult.value = data.backtestResult
        if (data.backtestParams) {
          Object.assign(backtestParams, defaultBacktestParams, data.backtestParams)
        }
        return true
      }
    }
  } catch (e) {
    console.warn('Failed to load backtest result from localStorage', e)
  }
  return false
}

function clearBacktestResult() {
  try {
    localStorage.removeItem(BACKTEST_STORAGE_KEY)
  } catch (e) {
    console.warn('Failed to clear backtest result from localStorage', e)
  }
}

const evolutionSteps = [
  {
    phase: '阶段一：涨停建仓 · 强势启动',
    signals: ['涨停板信号'],
    desc: '主力用涨停板快速建仓或拉升，标志着股票进入强势状态。涨停板是市场地位和资金关注度的直接体现。筛选标准：近20日内有涨停板，且涨停当日放量（≥2倍均量），收盘价在10日线以上。操作建议：将涨停股纳入自选观察池，等待回调机会，不追高。',
    risk: '观察期：只跟踪不买入，避免追高被套',
    position: '空仓观察，纳入自选池',
    action: '操作：发现涨停后加入自选，标记涨停日和涨停价，等待后续缩量回调机会'
  },
  {
    phase: '阶段二：缩量洗盘 · 观察等待',
    signals: ['缩量回调中', '底部观察'],
    desc: '涨停后3-8天缩量回调，成交量逐步萎缩至涨停日的1/3以下，说明主力锁仓不动，散户恐慌抛售。回调期间收盘价基本在10日线上方，不有效跌破涨停启动位。操作建议：每日观察成交量变化和10日线支撑，地量出现时进入重点关注列表。',
    risk: '低风险：仅观察，不建仓，等待明确信号',
    position: '空仓观望，耐心等待洗盘结束信号',
    action: '操作：成交量萎缩到涨停日1/3以下时进入底部观察，地量出现后准备好资金，随时准备介入'
  },
  {
    phase: '阶段三：地量止跌 · 左侧潜伏',
    signals: ['买点1：左侧潜伏'],
    desc: '洗盘末端第3-5天出现地量（近20日最低量且≤涨停日1/3）+长下影线（实体比≥2倍），说明抛压衰竭，卖盘已出尽。这是左侧潜伏买点，博弈洗盘结束后的反弹。操作建议：地量日尾盘轻仓试探（20%-30%仓位），止损设在长下影线最低点下方，跌破则止损。',
    risk: '中等风险：可能还有最后一跌，需严格止损',
    position: '轻仓试探（20%-30%），左侧潜伏',
    action: '买入：地量+长下影线当日尾盘买入20%；止损：跌破下影线最低点或亏损5%立即止损'
  },
  {
    phase: '阶段四：放量突破 · 右侧加仓',
    signals: ['买点2：右侧确认'],
    desc: '放量（≥1.5倍均量）站上5日线和回调前高，5日线走平上翘且上穿10日线，上影线≤2.5%，确认洗盘结束、主升浪启动。这是最安全、性价比最高的买点，成功率远高于左侧。操作建议：确认突破后果断加仓至60%-80%仓位，这是主力拉升阶段，收益最快。',
    risk: '低风险：趋势确认，顺势而为，成功率高',
    position: '重仓参与（60%-80%），主升浪行情',
    action: '买入：放量突破5日线和回调前高当日加仓至60%以上；止损：跌破10日线止损'
  },
  {
    phase: '阶段五：动态止盈 · 止损离场',
    signals: ['ATR止损', '10日止损', '时间止盈', '高位止盈', '移动止盈'],
    desc: '买入后严格执行止损止盈纪律。止损优先级：ATR止损（买入价下方0.4倍ATR）优先，其次是10日线止损。止盈策略：8天时间止盈（8天不过高）、高位放量滞涨止盈、移动止盈（盈利>3%开启，5日线与高点下方1倍ATR取较高者）。操作建议：到止损位无条件卖出，到止盈位分批卖出，让利润奔跑。',
    risk: '执行纪律：严格止损，保住本金；让利润奔跑，不提前下车',
    position: '动态调整，盈利上移止盈位，亏损立即止损',
    action: '止损：跌破ATR或10日线立即卖出；止盈：8天不过高减仓1/2，高位放量滞涨清仓，移动止盈跟随'
  }
]

function getEvolutionSignalTag(type: string): string {
  if (type.includes('涨停')) return 'danger'
  if (type.includes('缩量') || type.includes('底部')) return 'info'
  if (type.includes('买点1') || type.includes('左侧')) return 'warning'
  if (type.includes('买点2') || type.includes('右侧')) return 'success'
  if (type.includes('止损')) return 'danger'
  if (type.includes('止盈')) return 'success'
  return 'info'
}

// 回测相关状态
const backtestLoading = ref(false)
const backtestResult = ref<LimitUpPullbackBacktestResp | null>(null)

const defaultBacktestParams = {
  start_date: '',
  end_date: '',
  hold_days: 20,
  top_n: 10,
  limit: 50
}

const backtestParams = reactive<LimitUpPullbackBacktestReq>({ ...defaultBacktestParams })

// 信号类型统计列表
const signalStatsList = computed(() => {
  if (!backtestResult.value) return []
  return Object.entries(backtestResult.value.signal_stats).map(([signal_type, v]) => ({
    signal_type,
    count: v.count,
    win_rate: v.win_rate,
    avg_return: v.avg_return
  }))
})

// 卖出原因统计列表
const sellReasonStatsList = computed(() => {
  if (!backtestResult.value) return []
  return Object.entries(backtestResult.value.sell_reason_stats).map(([sell_reason, v]) => ({
    sell_reason,
    count: v.count,
    win_rate: v.win_rate,
    avg_return: v.avg_return
  }))
})

const equityCurveOption = computed(() => {
  if (!backtestResult.value?.daily_results?.length) return {}
  const initial = backtestResult.value.initial_capital || backtestResult.value.daily_results[0]?.total_value || 1
  const dates = backtestResult.value.daily_results.map((d: any) => d.date)
  const values = backtestResult.value.daily_results.map((d: any) => {
    return ((d.total_value - initial) / initial * 100).toFixed(2)
  })
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const p = params[0]
        return `${p.name}<br/>收益率: <strong>${p.value}%</strong>`
      }
    },
    grid: { left: 50, right: 20, top: 20, bottom: 30 },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { fontSize: 10, rotate: 30 }
    },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: '{value}%', fontSize: 10 }
    },
    series: [{
      type: 'line',
      data: values,
      smooth: true,
      lineStyle: { color: '#409eff', width: 2 },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(64, 158, 255, 0.3)' },
            { offset: 1, color: 'rgba(64, 158, 255, 0.02)' }
          ]
        }
      },
      itemStyle: { color: '#409eff' },
      symbol: 'none'
    }]
  }
})

const defaultParams = {
  limit: 50
}

const params = reactive<LimitUpPullbackScanReq>({ ...defaultParams })

const resetBacktestParams = () => {
  Object.assign(backtestParams, defaultBacktestParams)
  ElMessage.info('回测参数已重置')
}

const doScan = async () => {
  loading.value = true
  hasSearched.value = true
  results.value = []
  tookMs.value = 0
  scannedCount.value = 0

  try {
    const resp = await screeningApi.scanLimitUpPullback(params)
    results.value = resp.items
    tookMs.value = resp.took_ms || 0
    scannedCount.value = resp.scanned_count || 0
    saveScanResult()

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

const goToStock = (code: string) => {
  router.push(`/stocks/${code}`)
}

const goToAnalysis = (code: string) => {
  router.push({ path: '/analysis/single', query: { stock: code } })
}

const addToFavorites = async (row: LimitUpPullbackItem) => {
  try {
    await favoritesApi.add({
      stock_code: row.code,
      stock_name: row.name || '',
      market: 'A股'
    })
    ElMessage.success(`已添加 ${row.name}(${row.code}) 到自选`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '添加自选失败')
  }
}

const buyDialogVisible = ref(false)
const buyTarget = reactive({
  code: '',
  stockName: '',
  price: 0,
  strategy: 'limit_up_pullback',
})

const openBuyDialog = (row: any) => {
  buyTarget.code = row.code
  buyTarget.stockName = row.name || ''
  buyTarget.price = row.close || row.price || 0
  buyTarget.strategy = 'limit_up_pullback'
  buyDialogVisible.value = true
}

const onBuySuccess = () => {
  ElMessage.info('持仓已更新，可在模拟交易或持仓监控中查看')
}

const doBacktest = async () => {
  if (!backtestParams.start_date || !backtestParams.end_date) {
    ElMessage.warning('请选择回测开始和结束日期')
    return
  }

  backtestLoading.value = true
  backtestResult.value = null
  clearBacktestResult()
  activeTab.value = 'backtest'

  try {
    // 合并扫描参数到回测请求
    const payload: LimitUpPullbackBacktestReq = {
      ...backtestParams,
      limit: params.limit
    }

    const resp = await screeningApi.backtestLimitUpPullback(payload, { timeout: 600000 })
    backtestResult.value = resp
    saveBacktestResult()

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

const getSignalTypeTag = (type: string) => {
  const map: Record<string, string> = {
    '右侧确认': 'success',
    '左侧潜伏': 'warning',
    '底部观察': 'info',
    '缩量回调中': 'primary',
    '观察': ''
  }
  return map[type] || ''
}

const getSellReasonTag = (reason: string) => {
  const map: Record<string, string> = {
    'ATR止损': 'danger',
    '10日止损': 'danger',
    '8日时间止盈': 'warning',
    '高位止盈': 'success',
    '5日线止盈': 'success',
    'ATR止盈': 'success',
    '到期卖出': 'info'
  }
  return map[reason] || ''
}

const getScoreColor = (score: number) => {
  if (score >= 80) return '#67C23A'
  if (score >= 60) return '#E6A23C'
  if (score >= 40) return '#F56C6C'
  return '#909399'
}

const windowHeight = ref(window.innerHeight)

function handleResize() {
  windowHeight.value = window.innerHeight
}

const tableHeight = computed(() => {
  const headerOffset = 420
  return Math.max(400, windowHeight.value - headerOffset)
})

const scoreDimMax: Record<string, number> = {
  '缩量评分': 20,
  '回调幅度': 15,
  '地量评分': 15,
  '下影线评分': 15,
  '空间位置': 10,
  '站上10日线': 10,
  '小阴小阳': 5,
  '突破5日线': 25,
}

function getScoreRadarOption(row: any) {
  const details = row.score_details
  if (!details || (Array.isArray(details) ? details.length === 0 : Object.keys(details).length === 0)) return null

  const dims: { name: string; value: number; max: number }[] = []

  if (Array.isArray(details)) {
    details.forEach((d: any) => {
      if (typeof d === 'string') {
        const match = d.match(/^(.+?)[:：]\s*(\d+(?:\.\d+)?)(?:\/(\d+))?/)
        if (match) {
          const name = match[1].trim()
          const value = parseFloat(match[2])
          const max = match[3] ? parseFloat(match[3]) : (scoreDimMax[name] || 100)
          dims.push({ name, value: (value / max) * 100, max: 100 })
        }
      }
    })
  } else {
    Object.entries(details).forEach(([key, val]: [string, any]) => {
      let value = 0
      const max = scoreDimMax[key] || 100
      if (typeof val === 'number') {
        value = val
      } else if (typeof val === 'string') {
        const match = val.match(/(\d+(?:\.\d+)?)\/(\d+)/)
        if (match) {
          value = parseFloat(match[1])
          dims.push({ name: key, value: (value / parseFloat(match[2])) * 100, max: 100 })
          return
        }
      }
      dims.push({ name: key, value: (value / max) * 100, max: 100 })
    })
  }

  if (!dims.length) return null

  return {
    tooltip: {
      formatter: (params: any) => {
        const data = params.value
        return dims.map((d, i) => `${d.name}: ${data[i].toFixed(0)}%`).join('<br/>')
      }
    },
    radar: {
      indicator: dims.map(d => ({ name: d.name, max: 100 })),
      radius: '60%',
      center: ['50%', '55%'],
      axisName: { fontSize: 11, color: '#606266' },
      splitArea: {
        areaStyle: {
          color: ['rgba(64, 158, 255, 0.02)', 'rgba(64, 158, 255, 0.05)', 'rgba(64, 158, 255, 0.08)', 'rgba(64, 158, 255, 0.12)']
        }
      }
    },
    series: [{
      type: 'radar',
      data: [{
        value: dims.map(d => d.value),
        areaStyle: { color: 'rgba(64, 158, 255, 0.2)' },
        lineStyle: { color: '#409eff', width: 2 },
        itemStyle: { color: '#409eff' }
      }]
    }]
  }
}

const avgScore = computed(() => {
  if (!results.value.length) return 0
  return results.value.reduce((sum, r) => sum + (r.score || 0), 0) / results.value.length
})

const highScoreCount = computed(() => {
  return results.value.filter(r => r.score >= 70).length
})

const backtestTableHeight = computed(() => {
  return Math.min(500, Math.max(300, windowHeight.value - 500))
})

onMounted(() => {
  loadScanResult()
  loadBacktestResult()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
})
</script>

<style lang="scss" scoped>
.limit-up-pullback {
  padding: 16px;
}

.page-header {
  margin-bottom: 20px;

  .page-title {
    font-size: 24px;
    font-weight: 600;
    margin: 0 0 8px 0;
    display: flex;
    align-items: center;
    gap: 10px;
    color: var(--el-text-color-primary);
  }

  .page-description {
    margin: 0;
    color: var(--el-text-color-secondary);
    font-size: 14px;
  }
}

.panel-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;

  .header-actions {
    display: flex;
    gap: 8px;
  }
}

.strategy-intro-collapse {
  margin-bottom: 0;
  :deep(.el-collapse-item__header) {
    height: 50px;
    font-weight: 500;
  }
  .collapse-title {
    display: flex; align-items: center; gap: 10px;
    font-size: 14px;
  }
  .step-item {
    display: flex;
    gap: 12px;
    padding: 8px;
    border-radius: 8px;
    transition: all 0.2s;

    &:hover {
      background-color: var(--el-fill-color-light);
    }

    .step-number {
      flex-shrink: 0;
      width: 36px;
      height: 36px;
      border-radius: 50%;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: white;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 600;
      font-size: 16px;
    }

    .step-content {
      h4 {
        margin: 0 0 4px 0;
        font-size: 14px;
        color: var(--el-text-color-primary);
      }

      p {
        margin: 0;
        font-size: 12px;
        color: var(--el-text-color-secondary);
        line-height: 1.5;
      }
    }
  }
}

/* 信号演化路径 - 垂直时间轴 */
.evolution-panel {
  border-radius: 8px;
}

.evolution-timeline {
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 8px 0;
}

.evolution-step {
  display: flex;
  gap: 16px;
  padding: 12px 0;
  position: relative;
}

.step-marker {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex-shrink: 0;
  width: 40px;
}

.step-dot {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-weight: 700;
  font-size: 15px;
  flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
  z-index: 1;

  &.phase-1 { background: linear-gradient(135deg, #f56c6c, #e6a23c); }
  &.phase-2 { background: linear-gradient(135deg, #e6a23c, #f0c78a); }
  &.phase-3 { background: linear-gradient(135deg, #67c23a, #85ce61); }
  &.phase-4 { background: linear-gradient(135deg, #409eff, #66b1ff); }
  &.phase-5 { background: linear-gradient(135deg, #909399, #a6a9ad); }
}

.step-line {
  width: 2px;
  flex: 1;
  min-height: 30px;
  background: linear-gradient(to bottom, var(--el-border-color-light), var(--el-border-color-lighter));
}

.step-content {
  flex: 1;
  min-width: 0;
  padding-top: 8px;
}

.step-phase-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.step-phase {
  font-size: 15px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.step-signals {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.step-signal-tag {
  margin: 0;
}

.step-desc {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
  margin-bottom: 10px;
}

.step-action {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-bottom: 10px;
  padding: 8px 12px;
  background: var(--el-color-primary-light-9);
  border-radius: 6px;
  border-left: 3px solid var(--el-color-primary);

  .step-action-text {
    font-size: 12px;
    color: var(--el-text-color-regular);
    line-height: 1.6;
  }
}

.step-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.step-meta-tag {
  margin: 0;
}

.params-form {
  :deep(.el-form-item) {
    margin-bottom: 18px;
  }

  :deep(.el-form-item__label) {
    font-weight: 500;
    color: var(--el-text-color-regular);
  }
}

.params-panel {
  border-radius: 8px;
}

.form-actions {
  display: flex;
  justify-content: center;
  gap: 16px;
  margin-top: 8px;
  padding-top: 16px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.result-panel {
  border-radius: 8px;

  .empty-state {
    padding: 40px 0;
  }

  .stock-code, .stock-name {
    cursor: pointer;
    color: var(--el-color-primary);
    text-decoration: none;
    font-size: 13px;

    &:hover {
      text-decoration: underline;
    }
  }

  .price {
    font-family: 'Monaco', 'Consolas', monospace;
    font-weight: 500;
  }

  .pct {
    font-family: 'Monaco', 'Consolas', monospace;
    font-weight: 500;

    &.up {
      color: var(--el-color-danger);
    }

    &.down {
      color: var(--el-color-success);
    }
  }
}

.param-tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.4;
  margin-top: 2px;
}

.strategy-detail {
  .strategy-overview {
    font-size: 14px;
    color: var(--el-text-color-regular);
    line-height: 1.6;
    margin-bottom: 0;
  }
}

.signal-types {
  .signal-desc {
    font-size: 11px;
    color: var(--el-text-color-secondary);
    line-height: 1.4;
    margin-top: 4px;
  }

  .signal-flow {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 16px;
    flex-wrap: wrap;

    .signal-buy-point,
    .signal-watch {
      min-width: 140px;
      text-align: center;
      padding: 12px 16px;
    }
  }

  .flow-arrow {
    font-size: 20px;
    color: var(--el-text-color-placeholder);
    flex-shrink: 0;
  }

  .signal-buy-point {
    padding: 8px 10px;
    border: 1px dashed var(--el-color-warning);
    border-radius: 6px;
    background: var(--el-color-warning-light-9);

    .signal-desc {
      color: var(--el-color-warning-dark-2);
    }
  }

  .signal-sell-point {
    padding: 8px 10px;
    border: 1px dashed var(--el-color-danger);
    border-radius: 6px;
    background: var(--el-color-danger-light-9);

    .signal-desc {
      color: var(--el-color-danger-dark-2);
    }
  }

  .signal-watch {
    padding: 8px 10px;
    border: 1px solid var(--el-border-color-light);
    border-radius: 6px;
    background: var(--el-fill-color-lighter);
  }

  .signal-tip {
    margin-top: 12px;
    padding: 8px 12px;
    background: var(--el-color-primary-light-9);
    border-radius: 4px;
    font-size: 12px;
    color: var(--el-color-primary);
    display: flex;
    align-items: center;
    gap: 6px;
  }
}

.table-link {
  color: var(--el-color-primary);
  text-decoration: none;
  cursor: pointer;
  margin-right: 8px;
  font-size: 13px;

  &:hover {
    color: var(--el-color-primary-light-3);
    text-decoration: underline;
  }
}

.date-range {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  font-size: 12px;
  color: var(--el-text-color-primary);
}

.date-item {
  white-space: nowrap;
}

.date-arrow {
  color: var(--el-text-color-placeholder);
  flex-shrink: 0;
}

.date-tag {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 12px;
  line-height: 1.4;

  &.warning {
    background: var(--el-color-warning-light-9);
    color: var(--el-color-warning);
    border: 1px solid var(--el-color-warning-light-5);
  }

  &.success {
    background: var(--el-color-success-light-9);
    color: var(--el-color-success);
    border: 1px solid var(--el-color-success-light-5);
  }

  &.danger {
    background: var(--el-color-danger-light-9);
    color: var(--el-color-danger);
    border: 1px solid var(--el-color-danger-light-5);
  }

  &.info {
    background: var(--el-color-info-light-9);
    color: var(--el-color-info);
    border: 1px solid var(--el-color-info-light-5);
  }
}

.empty-tag {
  color: var(--el-text-color-placeholder);
  font-size: 12px;
}

.tooltip-detail {
  font-size: 13px;
  line-height: 1.5;
  max-width: 300px;
}

.help-icon {
  margin-left: 4px;
  font-size: 14px;
  color: var(--el-text-color-secondary);
  cursor: help;
  vertical-align: middle;

  &:hover {
    color: var(--el-color-primary);
  }
}

.metric-card {
  text-align: center;
  border-radius: 8px;

  :deep(.el-card__body) {
    padding: 16px 12px;
  }

  .metric-label {
    font-size: 13px;
    color: var(--el-text-color-secondary);
    margin-bottom: 10px;
  }

  .metric-value {
    font-size: 24px;
    font-weight: 700;
    font-family: 'Monaco', 'Consolas', monospace;
    color: var(--el-text-color-primary);
    line-height: 1.2;
    letter-spacing: -0.5px;

    &.up {
      color: var(--el-color-danger);
    }

    &.down {
      color: var(--el-color-success);
    }
  }
}

.radar-card, .score-stats-card {
  height: 100%;
}

.score-cell {
  cursor: pointer;
  .score-hint {
    display: block;
    font-size: 10px;
    color: #909399;
    margin-top: 2px;
    text-align: center;
  }
}

.score-detail-popover {
  .score-detail-title {
    font-weight: 600;
    font-size: 13px;
    margin-bottom: 8px;
    color: var(--el-text-color-primary);
  }
  .score-radar-wrap {
    margin-bottom: 12px;
    border-bottom: 1px solid var(--el-border-color-lighter);
    padding-bottom: 8px;
  }
  .score-detail-list {
    max-height: 240px;
    overflow-y: auto;
  }
  .score-detail-text-item {
    font-size: 12px;
    color: var(--el-text-color-regular);
    margin-bottom: 4px;
    line-height: 1.5;
  }
  .score-detail-empty {
    font-size: 12px;
    color: #909399;
    text-align: center;
    padding: 8px 0;
  }
}

.stat-item {
  text-align: center;
  padding: 16px 0;
  .stat-value {
    font-size: 28px;
    font-weight: 700;
    color: var(--el-color-primary);
    margin-bottom: 4px;
  }
  .stat-label {
    font-size: 12px;
    color: #909399;
  }
}
</style>

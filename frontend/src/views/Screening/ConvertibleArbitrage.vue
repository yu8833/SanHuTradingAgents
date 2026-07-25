<template>
  <div class="convertible-arbitrage-page">
    <!-- 页面标题 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><TrendCharts /></el-icon>
        转债下修博弈
      </h1>
      <p class="page-description">
        可转债接近债底时博弈上市公司下修转股价的转债套利策略
      </p>
    </div>

    <!-- 数据源已接入提示 -->
    <el-alert
      title="转债数据源已接入（akshare bond_zh_cov）"
      type="success"
      :closable="false"
      show-icon
      style="margin-bottom: 16px;"
    >
      <template #default>
        通过 akshare bond_zh_cov 接口获取全市场已上市可转债行情，基于「正股/转股价偏离度 + 转债价格 + 转股溢价率 + 信用评级」四维评分筛选下修博弈候选。
      </template>
    </el-alert>

    <!-- 策略原理卡片 -->
    <el-collapse class="strategy-intro-collapse" v-model="introCollapsed">
      <el-collapse-item name="intro">
        <template #title>
          <div class="collapse-title">
            <el-icon><InfoFilled /></el-icon>
            <span>策略原理</span>
            <el-tag type="primary" size="small" effect="plain">转债套利/下修博弈</el-tag>
          </div>
        </template>
        <div class="strategy-detail">
          <p class="strategy-overview">
            <strong>核心逻辑：</strong>可转债本质是"债券+看涨期权"，当转债价格跌至接近债底（纯债价值）时下行空间有限。
            上市公司为避免回售（投资者将转债按约定价卖回给公司造成现金流压力），往往会主动下修转股价，
            下修后转债的期权价值重估，价格出现一次性跳涨。
          </p>
          <p class="strategy-overview" style="margin-top: 12px;">
            <strong>关键信号：</strong>转债价格≤110元、转股溢价率&gt;50%、距回售期&lt;1年、正股价格持续低于回售触发价、
            公司有下修动机（避免回售、促转股融资）、债券评级AA-及以上，信号类型分为左侧潜伏与下修公告后右侧确认两种。
          </p>
          <p class="strategy-overview" style="margin-top: 12px;">
            <strong>风险提示：</strong>下修存在不确定性（董事会可提议不下修或下修不到底）；
            转债流动性弱于正股；下修博弈需结合公司基本面与董事会意愿综合判断；
            即使不下修，债底保护下亏损有限，但仍需控制仓位。
          </p>
        </div>
      </el-collapse-item>
    </el-collapse>

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
        <el-row :gutter="24">
          <el-col :span="6">
            <el-form-item label="转债价格上限(元)">
              <el-input-number v-model="params.max_bond_price" :min="80" :max="200" :step="5" style="width: 100%;" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="正股/转股价最大比值">
              <el-input-number v-model="params.max_stock_vs_conversion" :min="0.3" :max="0.95" :step="0.05" :precision="2" style="width: 100%;" />
              <div class="param-hint">越低表示正股越深跌，下修动力越强</div>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="最小发行规模(亿元)">
              <el-input-number v-model="params.min_issue_size" :min="0.1" :max="50" :step="0.5" :precision="1" style="width: 100%;" />
              <div class="param-hint">流动性保障</div>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="最低评分(100分制)">
              <el-slider v-model="params.min_score" :min="0" :max="100" :step="5" show-stops />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="24">
          <el-col :span="6">
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
                  找到 {{ results.length }} 只符合条件的转债
                </el-tag>
                <el-tag v-if="tookMs" type="info" size="small" effect="plain">
                  耗时 {{ (tookMs / 1000).toFixed(1) }}s
                </el-tag>
              </div>
            </div>
          </template>

          <!-- 评分分析 -->
          <el-row v-if="results.length > 0" :gutter="16" style="margin-bottom: 16px;">
            <el-col :span="8">
              <el-card shadow="never" class="radar-card">
                <template #header>
                  <div class="card-header">
                    <div style="display: flex; align-items: center; gap: 12px;">
                      <el-icon><DataAnalysis /></el-icon>
                      <span class="panel-title">评分维度雷达图</span>
                    </div>
                  </div>
                </template>
                <v-chart :option="radarOption" style="height: 280px;" autoresize />
              </el-card>
            </el-col>
            <el-col :span="16">
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
                      <div class="stat-label">符合条件转债</div>
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
                      <div class="stat-label">高分(≥70分)</div>
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

          <div v-if="!loading && results.length === 0 && !hasSearched" class="empty-state">
            <el-empty description="调整参数后点击开始扫描，将获取全市场已上市可转债并筛选下修博弈候选">
              <el-button type="primary" @click="doScan">立即扫描</el-button>
            </el-empty>
          </div>

          <!-- 扫描后无结果的提示 -->
          <div v-if="!loading && results.length === 0 && hasSearched" class="data-source-tip">
            <el-result icon="info" title="未找到符合条件的转债" sub-title="可尝试调低最低评分或放宽筛选参数后重试">
              <template #extra>
                <el-button type="primary" @click="doScan">重新扫描</el-button>
              </template>
            </el-result>
          </div>

          <el-table
            v-if="results.length > 0"
            :data="results"
            v-loading="loading"
            element-loading-text="扫描中..."
            stripe
            :height="tableHeight"
            row-key="bond_code"
            style="width: 100%"
          >
            <el-table-column prop="bond_code" label="转债代码" width="100" fixed="left">
              <template #default="{ row }">
                <span class="stock-code">{{ row.bond_code }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="bond_name" label="转债名称" width="120" fixed="left">
              <template #default="{ row }">
                <span class="stock-name">{{ row.bond_name }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="stock_name" label="正股" width="100" />
            <el-table-column prop="bond_price" label="转债现价" width="100" sortable>
              <template #default="{ row }">
                <span class="price">{{ formatNum(row.bond_price) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="stock_price" label="正股价" width="90" sortable>
              <template #default="{ row }">{{ formatNum(row.stock_price) }}</template>
            </el-table-column>
            <el-table-column prop="conversion_price" label="转股价" width="90" sortable>
              <template #default="{ row }">{{ formatNum(row.conversion_price) }}</template>
            </el-table-column>
            <el-table-column prop="stock_vs_conversion" label="正股/转股价" width="120" sortable>
              <template #default="{ row }">
                <span :class="['pct', row.stock_vs_conversion <= 0.5 ? 'down' : '']">
                  {{ (row.stock_vs_conversion * 100).toFixed(1) }}%
                </span>
                <div class="param-hint" style="font-size:11px;">{{ row.down_revision_motivation }}</div>
              </template>
            </el-table-column>
            <el-table-column prop="conversion_premium" label="转股溢价率" width="120" sortable>
              <template #default="{ row }">
                <span :class="['pct', row.conversion_premium >= 0.5 ? 'up' : '']">
                  {{ (row.conversion_premium * 100).toFixed(1) }}%
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="double_low" label="双低值" width="100" sortable>
              <template #default="{ row }">{{ formatNum(row.double_low) }}</template>
            </el-table-column>
            <el-table-column prop="rating" label="评级" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="getRatingTagType(row.rating)">{{ row.rating || '-' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="issue_size" label="发行规模(亿)" width="110" sortable>
              <template #default="{ row }">{{ formatNum(row.issue_size) }}</template>
            </el-table-column>
            <el-table-column prop="years_to_maturity" label="剩余年限(年)" width="120" sortable>
              <template #default="{ row }">
                {{ row.years_to_maturity ? row.years_to_maturity.toFixed(1) : '-' }}
                <el-tag v-if="row.in_put_period" size="small" type="warning" style="margin-left:4px;">回售期</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="signal_type" label="信号类型" width="100">
              <template #default="{ row }">
                <el-tag :type="getSignalTypeTag(row.signal_type)" size="small">
                  {{ row.signal_type || '-' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="score" label="综合评分" width="130" sortable fixed="right">
              <template #default="{ row }">
                <el-popover placement="left" :width="240" trigger="click">
                  <template #reference>
                    <div class="score-cell">
                      <el-progress :percentage="row.score" :color="getScoreColor(row.score)" :stroke-width="12" />
                      <span class="score-hint">点击查看明细</span>
                    </div>
                  </template>
                  <div class="score-detail-popover">
                    <div class="score-detail-title">评分明细</div>
                    <div v-if="row.score_details && Object.keys(row.score_details).length" class="score-detail-list">
                      <div v-for="(val, key) in row.score_details" :key="key" class="score-detail-item">
                        <span class="score-detail-label">{{ key }}</span>
                        <div class="score-detail-bar-wrap">
                          <el-progress :percentage="typeof val === 'number' ? Math.min(100, val) : 0" :stroke-width="8" :show-text="false" :color="getScoreColor(val as number)" />
                        </div>
                        <span class="score-detail-val">{{ typeof val === 'number' ? val.toFixed(1) : val }}分</span>
                      </div>
                    </div>
                    <div v-else class="score-detail-empty">暂无评分明细</div>
                  </div>
                </el-popover>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="200" fixed="right">
              <template #default="{ row }">
                <el-button type="success" link @click="addToFavorites(row)">自选</el-button>
                <el-button type="primary" link @click="openBuyDialog(row)">买入</el-button>
              </template>
            </el-table-column>
          </el-table>

          <!-- 评分明细展开 -->
          <el-card v-if="results.length > 0" shadow="never" style="margin-top: 12px;">
            <template #header>
              <div class="card-header">
                <span class="panel-title">评分明细（前5名）</span>
              </div>
            </template>
            <el-table :data="results.slice(0, 5)" size="small" border>
              <el-table-column prop="bond_name" label="转债" width="120" />
              <el-table-column label="下修动力" min-width="180">
                <template #default="{ row }">{{ row.score_details?.['下修动力'] || '-' }}</template>
              </el-table-column>
              <el-table-column label="转债价格" min-width="140">
                <template #default="{ row }">{{ row.score_details?.['转债价格'] || '-' }}</template>
              </el-table-column>
              <el-table-column label="转股溢价率" min-width="140">
                <template #default="{ row }">{{ row.score_details?.['转股溢价率'] || '-' }}</template>
              </el-table-column>
              <el-table-column label="信用评级" min-width="120">
                <template #default="{ row }">{{ row.score_details?.['信用评级'] || '-' }}</template>
              </el-table-column>
              <el-table-column prop="score" label="总分" width="80">
                <template #default="{ row }">
                  <span style="font-weight:bold;color:#e6232a;">{{ row.score }}</span>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
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
                  <el-input-number v-model="backtestParams.hold_days" :min="1" :max="120" :step="1" style="width: 100%;" />
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

          <el-card shadow="never" style="margin-top: 16px;">
            <template #header><div class="card-header"><span>盈利最多交易</span></div></template>
            <el-table :data="backtestResult.top_trades" stripe style="width: 100%">
              <el-table-column prop="code" label="转债代码" width="110" />
              <el-table-column prop="name" label="转债名称" width="140" />
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

          <el-card shadow="never" style="margin-top: 16px;">
            <template #header><div class="card-header"><span>亏损最多交易</span></div></template>
            <el-table :data="backtestResult.worst_trades" stripe style="width: 100%">
              <el-table-column prop="code" label="转债代码" width="110" />
              <el-table-column prop="name" label="转债名称" width="140" />
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

    <!-- 买入对话框 -->
    <RetailBuyDialog
      v-model="buyDialogVisible"
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
import { ElMessage } from 'element-plus'
import { TrendCharts, InfoFilled, Refresh, Search, List, DataLine, DataAnalysis } from '@element-plus/icons-vue'
import { use as echartsUse } from 'echarts/core'
import { RadarChart, LineChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import { screeningApi, type RetailScanReq, type RetailBacktestReq, type RetailScanResp, type RetailBacktestResp } from '@/api/screening'
import { favoritesApi } from '@/api/favorites'
import RetailBuyDialog from './components/RetailBuyDialog.vue'

echartsUse([RadarChart, LineChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent, CanvasRenderer])

const STORAGE_KEY = 'convertible_arbitrage_scan_result'
const BACKTEST_STORAGE_KEY = 'convertible_arbitrage_backtest_result'

const activeTab = ref<'scan' | 'backtest'>('scan')

const loading = ref(false)
const results = ref<RetailScanResp['items']>([])
const tookMs = ref(0)
const hasSearched = ref(false)
const introCollapsed = ref<string[]>([])

function saveScanResult() {
  const data = {
    results: results.value,
    tookMs: tookMs.value,
    scanParams: { ...params },
    timestamp: Date.now()
  }
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
  } catch (e) {
    console.warn('Failed to save scan result to localStorage', e)
  }
}

function loadScanResult() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      const data = JSON.parse(stored)
      if (data.results && data.results.length > 0) {
        results.value = data.results
        tookMs.value = data.tookMs || 0
        if (data.scanParams) {
          Object.assign(params, defaultParams, data.scanParams)
        }
        hasSearched.value = true
        return true
      }
    }
  } catch (e) {
    console.warn('Failed to load scan result from localStorage', e)
  }
  return false
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

const defaultParams = { max_bond_price: 110, max_stock_vs_conversion: 0.7, min_issue_size: 1.0, min_score: 40, limit: 50 }
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
    const resp = await screeningApi.scanConvertibleArbitrage(params)
    results.value = resp.items
    tookMs.value = resp.took_ms || 0
    saveScanResult()
    if (resp.items.length > 0) {
      ElMessage.success(`扫描完成：共扫描 ${resp.scanned_count || 0} 只转债，找到 ${resp.items.length} 只下修博弈候选`)
    } else {
      ElMessage.warning('未找到符合条件的转债，可尝试调低最低评分或放宽筛选参数')
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
  hold_days: 30,
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
    const resp = await screeningApi.backtestConvertibleArbitrage(payload)
    backtestResult.value = resp
    saveBacktestResult()
    if (resp.total_trades > 0) {
      ElMessage.success(`回测完成，共 ${resp.total_trades} 笔交易，胜率 ${resp.win_rate.toFixed(2)}%`)
    } else {
      ElMessage.warning('回测完成，但未产生交易（可能历史数据不足）')
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '回测失败，请稍后重试')
  } finally {
    backtestLoading.value = false
  }
}

const addToFavorites = async (row: any) => {
  try {
    await favoritesApi.add({ stock_code: row.bond_code, stock_name: row.bond_name || '', market: '可转债' })
    ElMessage.success(`已添加 ${row.bond_name}(${row.bond_code}) 到自选`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '添加自选失败')
  }
}

// 买入对话框
const buyDialogVisible = ref(false)
const buyTarget = reactive({
  code: '',
  stockName: '',
  price: 0,
  strategy: 'convertible_arbitrage',
})

const openBuyDialog = (row: any) => {
  buyTarget.code = row.bond_code
  buyTarget.stockName = row.bond_name || ''
  buyTarget.price = row.bond_price || 0
  buyTarget.strategy = 'convertible_arbitrage'
  buyDialogVisible.value = true
}

const onBuySuccess = () => {
  ElMessage.info('持仓已更新，可在模拟交易或持仓监控中查看')
}

const getSignalTypeTag = (type?: string) => {
  if (!type) return ''
  if (type.includes('右侧') || type.includes('确认')) return 'success'
  if (type.includes('左侧') || type.includes('潜伏')) return 'warning'
  if (type.includes('观察')) return 'info'
  if (type.includes('下修')) return 'primary'
  return ''
}

const getRatingTagType = (rating?: string) => {
  if (!rating) return 'info'
  const r = rating.toUpperCase()
  if (r.startsWith('AAA')) return 'success'
  if (r.startsWith('AA')) return 'primary'
  if (r.startsWith('A')) return 'warning'
  if (r.startsWith('BB') || r.startsWith('B')) return 'danger'
  if (r.startsWith('C')) return 'danger'
  return 'info'
}

const getScoreColor = (score: number) => {
  if (score >= 80) return '#67C23A'
  if (score >= 60) return '#E6A23C'
  if (score >= 40) return '#F56C6C'
  return '#909399'
}

const formatNum = (n: any) => (typeof n === 'number' ? n.toFixed(2) : '-')

const avgScoreDetails = computed(() => {
  if (!results.value.length) return {}
  const first = results.value[0]
  if (!first?.score_details) return {}
  const keys = Object.keys(first.score_details)
  const avg: Record<string, number> = {}
  keys.forEach(key => {
    const values = results.value
      .map(r => {
        const v = r.score_details?.[key]
        if (typeof v === 'number') return v
        if (typeof v === 'string') {
          const match = v.match(/(\d+(?:\.\d+)?)\/(\d+)/)
          if (match) return (parseFloat(match[1]) / parseFloat(match[2])) * 100
        }
        return 0
      })
      .filter(v => typeof v === 'number' && !isNaN(v))
    avg[key] = values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0
  })
  return avg
})

const radarOption = computed(() => {
  const details = avgScoreDetails.value
  const indicators = Object.keys(details).map(key => ({
    name: key,
    max: 100
  }))
  return {
    tooltip: {},
    radar: {
      indicator: indicators.length ? indicators : [{ name: '暂无数据', max: 100 }],
      radius: '65%',
      center: ['50%', '55%'],
      axisName: {
        fontSize: 11,
        color: '#606266'
      }
    },
    series: [{
      type: 'radar',
      data: [{
        value: indicators.length ? Object.values(details) : [0],
        name: '平均得分',
        areaStyle: {
          color: 'rgba(64, 158, 255, 0.2)'
        },
        lineStyle: {
          color: '#409eff'
        },
        itemStyle: {
          color: '#409eff'
        }
      }]
    }]
  }
})

const avgScore = computed(() => {
  if (!results.value.length) return 0
  return results.value.reduce((sum, r) => sum + (r.score || 0), 0) / results.value.length
})

const highScoreCount = computed(() => {
  return results.value.filter(r => r.score >= 70).length
})

const windowHeight = ref(window.innerHeight)
function handleResize() { windowHeight.value = window.innerHeight }
const tableHeight = computed(() => Math.max(400, windowHeight.value - 420))

onMounted(() => {
  window.addEventListener('resize', handleResize)
  loadScanResult()
  loadBacktestResult()
})
onUnmounted(() => { window.removeEventListener('resize', handleResize) })
</script>

<style lang="scss" scoped>
.convertible-arbitrage-page { padding: 16px; }

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
}

.strategy-detail .strategy-overview {
  font-size: 14px; color: var(--el-text-color-regular); line-height: 1.7; margin-bottom: 0;
}

.params-form {
  :deep(.el-form-item) { margin-bottom: 18px; }
  :deep(.el-form-item__label) { font-weight: 500; color: var(--el-text-color-regular); }
  .param-hint {
    font-size: 11px; color: var(--el-text-color-secondary); margin-top: 2px; line-height: 1.4;
  }
}

.form-actions {
  display: flex; justify-content: center; gap: 16px;
  margin-top: 8px; padding-top: 16px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.result-panel {
  .empty-state { padding: 40px 0; }
  .data-source-tip { padding: 20px 0; }
  .stock-code, .stock-name {
    color: var(--el-color-primary);
    font-size: 13px;
  }
  .price { font-family: 'Monaco', 'Consolas', monospace; font-weight: 500; }
  .pct {
    font-family: 'Monaco', 'Consolas', monospace; font-weight: 500;
    &.up { color: var(--el-color-danger); }
    &.down { color: var(--el-color-success); }
  }
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
  .score-detail-list {
    max-height: 240px;
    overflow-y: auto;
  }
  .score-detail-item {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
    &:last-child { margin-bottom: 0; }
  }
  .score-detail-label {
    font-size: 12px;
    color: var(--el-text-color-regular);
    white-space: nowrap;
    width: 70px;
    flex-shrink: 0;
  }
  .score-detail-bar-wrap {
    flex: 1;
  }
  .score-detail-val {
    font-size: 12px;
    font-weight: 600;
    color: var(--el-text-color-primary);
    width: 40px;
    text-align: right;
    flex-shrink: 0;
  }
  .score-detail-empty {
    font-size: 12px;
    color: #909399;
    text-align: center;
    padding: 8px 0;
  }
}

.radar-card, .score-stats-card {
  height: 100%;
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

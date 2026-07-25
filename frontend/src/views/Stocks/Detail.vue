<template>
  <div class="stock-detail">
    <!-- 顶部：代码 / 名称 / 操作 -->
    <div class="header">
      <div class="title">
        <div class="code">{{ code }}</div>
        <div class="name">{{ stockName || '-' }}</div>
        <el-tag size="small">{{ market || '-' }}</el-tag>
      </div>
      <div class="actions">
        <el-button @click="onToggleFavorite">
          <el-icon><Star /></el-icon> {{ isFav ? '已自选' : '加自选' }}
        </el-button>
        <!-- 🔥 港股和美股不显示"同步数据"按钮 -->
        <el-button
          v-if="market !== 'HK' && market !== 'US'"
          type="primary"
          @click="showSyncDialog"
          :loading="syncLoading"
        >
          <el-icon><Refresh /></el-icon> 同步数据
        </el-button>
        <el-button type="warning" @click="clearCache" :loading="clearCacheLoading">
          <el-icon><Delete /></el-icon> 清除缓存
        </el-button>
        <el-button type="success" @click="goPaperTrading">
          <el-icon><CreditCard /></el-icon> 模拟交易
        </el-button>
      </div>
    </div>

    <!-- 报价条 -->
    <el-card class="quote-card" shadow="hover">
      <div class="quote">
        <div class="price-row">
          <div class="price" :class="changeClass">{{ fmtPrice(quote.price) }}</div>
          <div class="change" :class="changeClass">
            <span>{{ fmtPercent(quote.changePercent) }}</span>
          </div>
          <el-tag type="info" size="small">{{ refreshText }}</el-tag>
          <el-button text size="small" @click="refreshMockQuote" :icon="Refresh">刷新</el-button>
        </div>
        <div class="stats">
          <div class="item">
            <span>
              今开
              <el-tooltip content="今日开盘价，即当天第一笔成交的价格。若高开说明市场情绪偏多，低开说明偏空。" placement="top">
                <el-icon class="help-icon-inline"><QuestionFilled /></el-icon>
              </el-tooltip>
            </span>
            <b>{{ fmtPrice(quote.open) }}</b>
          </div>
          <div class="item">
            <span>
              最高
              <el-tooltip content="今日盘中最高成交价。离最高价越远，说明上方抛压越重。" placement="top">
                <el-icon class="help-icon-inline"><QuestionFilled /></el-icon>
              </el-tooltip>
            </span>
            <b>{{ fmtPrice(quote.high) }}</b>
          </div>
          <div class="item">
            <span>
              最低
              <el-tooltip content="今日盘中最低成交价。离最低价越远，说明下方支撑越强。" placement="top">
                <el-icon class="help-icon-inline"><QuestionFilled /></el-icon>
              </el-tooltip>
            </span>
            <b>{{ fmtPrice(quote.low) }}</b>
          </div>
          <div class="item">
            <span>
              昨收
              <el-tooltip content="昨日收盘价，是今日涨跌幅计算的基准价。" placement="top">
                <el-icon class="help-icon-inline"><QuestionFilled /></el-icon>
              </el-tooltip>
            </span>
            <b>{{ fmtPrice(quote.prevClose) }}</b>
          </div>
          <div class="item">
            <span>
              成交量
              <el-tooltip content="今日成交的股票总手数（1手=100股）。放量说明交易活跃，缩量说明市场观望。" placement="top">
                <el-icon class="help-icon-inline"><QuestionFilled /></el-icon>
              </el-tooltip>
            </span>
            <b>
              {{ fmtVolume(quote.volume) }}
              <el-tooltip v-if="quote.tradeDate && !isToday(quote.tradeDate)" :content="getDataExpiredWarning(quote.tradeDate)" placement="top">
                <el-tag size="small" :type="getDataExpiredType(quote.tradeDate)" style="margin-left: 4px;">{{ formatDateTag(quote.tradeDate) }}</el-tag>
              </el-tooltip>
            </b>
          </div>
          <div class="item">
            <span>
              成交额
              <el-tooltip content="今日成交的总金额（元）。成交额比成交量更能反映资金参与度。" placement="top">
                <el-icon class="help-icon-inline"><QuestionFilled /></el-icon>
              </el-tooltip>
            </span>
            <b>
              {{ fmtAmount(quote.amount) }}
              <el-tooltip v-if="quote.tradeDate && !isToday(quote.tradeDate)" :content="getDataExpiredWarning(quote.tradeDate)" placement="top">
                <el-tag size="small" :type="getDataExpiredType(quote.tradeDate)" style="margin-left: 4px;">{{ formatDateTag(quote.tradeDate) }}</el-tag>
              </el-tooltip>
            </b>
          </div>
          <div class="item">
            <span>
              换手率
              <el-tooltip content="今日成交量占流通股本的比例。换手率高（>5%）说明交投活跃，低（<1%）说明关注度高但交易清淡。" placement="top">
                <el-icon class="help-icon-inline"><QuestionFilled /></el-icon>
              </el-tooltip>
            </span>
            <b>
              {{ fmtPercent(quote.turnover) }}
              <el-tooltip v-if="quote.turnoverDate && !isToday(quote.turnoverDate)" :content="getDataExpiredWarning(quote.turnoverDate)" placement="top">
                <el-tag size="small" :type="getDataExpiredType(quote.turnoverDate)" style="margin-left: 4px;">{{ formatDateTag(quote.turnoverDate) }}</el-tag>
              </el-tooltip>
            </b>
          </div>
          <div class="item">
            <span>
              振幅
              <el-tooltip content="今日最高价与最低价之差占昨收价的比例。振幅大说明多空分歧大，波动剧烈。" placement="top">
                <el-icon class="help-icon-inline"><QuestionFilled /></el-icon>
              </el-tooltip>
            </span>
            <b>
              {{ Number.isFinite(quote.amplitude) ? quote.amplitude.toFixed(2) + '%' : '-' }}
              <el-tooltip v-if="quote.amplitudeDate && !isToday(quote.amplitudeDate)" :content="getDataExpiredWarning(quote.amplitudeDate)" placement="top">
                <el-tag size="small" :type="getDataExpiredType(quote.amplitudeDate)" style="margin-left: 4px;">{{ formatDateTag(quote.amplitudeDate) }}</el-tag>
              </el-tooltip>
            </b>
          </div>
        </div>
        <!-- 🔥 数据过期醒目提示 -->
        <el-alert
          v-if="quote.tradeDate && getDataExpiredDays(quote.tradeDate) > 1"
          :type="getDataExpiredDays(quote.tradeDate) > 7 ? 'error' : 'warning'"
          show-icon
          :closable="false"
          style="margin-top: 8px;"
        >
          <template #title>
            ⚠️ 数据已过期 {{ getDataExpiredDays(quote.tradeDate) }} 天（数据日期：{{ quote.tradeDate }}）
          </template>
          <div style="font-size: 12px;">
            当前显示的数据可能不是最新的，建议点击"同步数据"获取最新行情。
          </div>
        </el-alert>
        <!-- 同步状态提示 -->
        <div class="sync-status" v-if="quote.updatedAt || syncStatus">
          <el-icon><Clock /></el-icon>
          <span class="sync-info">
            <!-- 🔥 优先显示股票自己的更新时间 -->
            <template v-if="quote.updatedAt">
              数据更新: {{ formatQuoteUpdateTime(quote.updatedAt) }}
            </template>
            <template v-else-if="syncStatus">
              后端同步: {{ formatSyncTime(syncStatus.last_sync_time) }}
              <span v-if="syncStatus.interval_seconds">{{ formatSyncInterval(syncStatus.interval_seconds) }}</span>
            </template>
            <el-tag
              v-if="syncStatus?.data_source"
              size="small"
              type="success"
              style="margin-left: 4px"
            >
              {{ syncStatus.data_source }}
            </el-tag>
          </span>
        </div>
      </div>
    </el-card>

    <el-row :gutter="16" class="body">
      <el-col :span="18">
        <!-- K线蜡烛图 -->
        <el-card shadow="hover">
          <template #header>
            <div class="card-hd">
              <div>价格K线</div>
              <div class="periods">
                <el-segmented v-model="period" :options="periodOptions" size="small" />
              </div>
            </div>
          </template>
          <div class="kline-container">
            <v-chart class="k-chart" :option="kOption" autoresize />
            <div class="legend">当前周期：{{ period }} · 数据源：{{ klineSource || '-' }} · 最近：{{ lastKTime || '-' }} · 收：{{ fmtPrice(lastKClose) }}</div>
          </div>
        </el-card>

        <!-- 详细分析结果：超链接到分析报告 -->
        <el-card v-if="analysisStatus==='running' || lastAnalysis" shadow="hover" class="analysis-detail-card" id="analysis-detail">
          <template #header><div class="card-hd">详细分析结果</div></template>
          <div v-if="analysisStatus==='running'" class="running">
            <el-progress :percentage="analysisProgress" :text-inside="true" style="width:100%" />
            <div class="hint">{{ analysisMessage || '正在生成分析报告…' }}</div>
          </div>
          <div v-else class="detail">
            <!-- 分析时间和信心度 -->
            <div class="analysis-meta">
              <span class="analysis-time">
                <el-icon><Clock /></el-icon>
                分析时间：{{ formatAnalysisTime(lastTaskInfo?.end_time) }}
              </span>
              <span class="confidence">
                <el-icon><TrendCharts /></el-icon>
                信心度：{{ fmtConf(lastAnalysis?.confidence_score ?? lastAnalysis?.overall_score) }}
              </span>
            </div>

            <!-- 超链接到完整分析报告 -->
            <div class="report-link-section">
              <el-button type="primary" plain @click="goToReportPage">
                <el-icon style="margin-right: 4px"><Document /></el-icon>
                查看完整分析报告
              </el-button>
            </div>
          </div>
        </el-card>


        <!-- 新闻与公告：位于详细分析结果下方 -->
        <el-card shadow="hover" class="news-card">
          <template #header>
            <div class="card-hd">
              <div>近期新闻与公告</div>
              <el-select v-model="newsFilter" size="small" style="width: 160px">
                <el-option label="全部" value="all" />
                <el-option label="新闻" value="news" />
                <el-option label="公告" value="announcement" />
              </el-select>
            </div>
          </template>
          <el-empty v-if="newsItems.length === 0" description="暂无新闻" />
          <div v-else class="news-list">
            <div v-for="(n, i) in filteredNews" :key="i" class="news-item">
              <div class="row">
                <div class="left">
                  <el-tag size="small" effect="plain" :type="n.type==='announcement' ? 'warning' : 'info'" class="tag">{{ n.type==='announcement' ? '公告' : '新闻' }}</el-tag>
                  <div class="title">
                    <template v-if="n.url && n.url !== '#'">
                      <a :href="n.url" target="_blank" rel="noopener">{{ n.title || '查看详情' }}</a>
                      <el-icon class="ext"><Link /></el-icon>
                    </template>
                    <template v-else>
                      <span>{{ n.title || '（无标题）' }}</span>
                    </template>
                  </div>
                </div>
                <div class="right">{{ formatNewsTime(n.time) }}</div>
              </div>
              <div class="meta">{{ n.source || '-' }} · {{ newsSource || '-' }}</div>
            </div>
          </div>
        </el-card>

        <!-- 🔥 板块联动分析 -->
        <el-card shadow="hover" class="sector-card" style="margin-top: 16px;">
          <template #header>
            <div class="card-hd">
              <div>
                板块联动分析
                <el-tooltip content="展示该股票所属行业的其他股票涨跌情况，帮助判断是板块联动还是个股异动。" placement="top">
                  <el-icon class="help-icon-inline"><QuestionFilled /></el-icon>
                </el-tooltip>
              </div>
              <el-tag v-if="sectorData?.sector_name" type="info" size="small">{{ sectorData.sector_name }}</el-tag>
            </div>
          </template>
          <el-empty v-if="!sectorData || !sectorData.sector_name" description="暂无板块数据（该股票行业信息未同步）" :image-size="60" />
          <div v-else>
            <!-- 板块概况 -->
            <el-descriptions :column="3" border size="small" style="margin-bottom: 12px;">
              <el-descriptions-item label="板块名称">{{ sectorData.sector_name }}</el-descriptions-item>
              <el-descriptions-item label="板块均涨幅">
                <span :style="{color: sectorData.sector_avg_change >= 0 ? '#e53935' : '#16a34a', fontWeight: 'bold'}">
                  {{ sectorData.sector_avg_change >= 0 ? '+' : '' }}{{ sectorData.sector_avg_change }}%
                </span>
              </el-descriptions-item>
              <el-descriptions-item label="个股排名">
                <el-tag v-if="sectorData.sector_rank" type="warning" size="small">第{{ sectorData.sector_rank }}名 / {{ sectorData.total_in_sector }}</el-tag>
                <span v-else>-</span>
              </el-descriptions-item>
            </el-descriptions>
            <!-- 同板块股票 -->
            <el-table :data="sectorData.sector_stocks" size="small" border style="width: 100%" max-height="240">
              <el-table-column label="代码" prop="code" width="80" />
              <el-table-column label="名称" prop="name" width="100" />
              <el-table-column label="最新价" prop="price" width="80">
                <template #default="{ row }">{{ row.price?.toFixed(2) || '-' }}</template>
              </el-table-column>
              <el-table-column label="涨跌幅" prop="change_pct" width="100">
                <template #default="{ row }">
                  <span :style="{color: row.change_pct >= 0 ? '#e53935' : '#16a34a', fontWeight: 'bold'}">
                    {{ row.change_pct >= 0 ? '+' : '' }}{{ row.change_pct?.toFixed(2) || '0.00' }}%
                  </span>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-card>

        <!-- 🔥 主力资金追踪 -->
        <el-card shadow="hover" class="money-flow-card" style="margin-top: 16px;">
          <template #header>
            <div class="card-hd">
              <div>
                主力资金追踪
                <el-tooltip content="展示主力资金（超大单+大单）的净流入流出情况。主力净流入为正说明大资金在买入，为负说明在卖出。" placement="top">
                  <el-icon class="help-icon-inline"><QuestionFilled /></el-icon>
                </el-tooltip>
              </div>
              <div style="display: flex; gap: 6px; align-items: center;">
                <el-tag v-if="moneyFlowData?.trend" :type="moneyFlowData.trend === 'inflow' ? 'danger' : moneyFlowData.trend === 'outflow' ? 'success' : 'info'" size="small">
                  {{ moneyFlowData.trend === 'inflow' ? '资金流入' : moneyFlowData.trend === 'outflow' ? '资金流出' : '资金均衡' }}
                </el-tag>
              </div>
            </div>
          </template>
          <!-- 数据不可用：展示明确的错误信息，不再用估算数据伪装 -->
          <el-alert
            v-if="moneyFlowData?.data_source === 'unavailable'"
            type="warning"
            :closable="false"
            :title="moneyFlowData.error_message || '资金流向数据暂时不可用，请稍后重试'"
          >
            <template #default>
              <div style="font-size: 12px; line-height: 1.6;">
                {{ moneyFlowData.error_message || '资金流向数据暂时不可用' }}
                <div style="margin-top: 4px; color: var(--el-text-color-secondary);">
                  数据源（AKShare）可能临时不可用。真实资金流向数据对交易决策至关重要，系统不会用估算值替代。
                </div>
              </div>
            </template>
          </el-alert>
          <el-empty v-else-if="!moneyFlowData || !moneyFlowData.realtime || Object.keys(moneyFlowData.realtime).length === 0" description="暂无资金流向数据" :image-size="60" />
          <div v-else>
            <!-- 实时资金流向 -->
            <el-descriptions :column="2" border size="small" style="margin-bottom: 12px;">
              <el-descriptions-item label="主力净流入">
                <span :style="{color: moneyFlowData.realtime.main_net_inflow >= 0 ? '#e53935' : '#16a34a', fontWeight: 'bold'}">
                  {{ fmtAmount(moneyFlowData.realtime.main_net_inflow) }} 元
                </span>
              </el-descriptions-item>
              <el-descriptions-item label="主力净占比">
                <span :style="{color: moneyFlowData.realtime.main_net_inflow >= 0 ? '#e53935' : '#16a34a'}">
                  {{ moneyFlowData.realtime.main_net_inflow_pct?.toFixed(2) || '0.00' }}%
                </span>
              </el-descriptions-item>
              <el-descriptions-item label="超大单净流入">
                <span :style="{color: moneyFlowData.realtime.super_large_net >= 0 ? '#e53935' : '#16a34a'}">
                  {{ fmtAmount(moneyFlowData.realtime.super_large_net) }}
                </span>
              </el-descriptions-item>
              <el-descriptions-item label="大单净流入">
                <span :style="{color: moneyFlowData.realtime.large_net >= 0 ? '#e53935' : '#16a34a'}">
                  {{ fmtAmount(moneyFlowData.realtime.large_net) }}
                </span>
              </el-descriptions-item>
              <el-descriptions-item label="中单净流入">
                <span :style="{color: moneyFlowData.realtime.medium_net >= 0 ? '#e53935' : '#16a34a'}">
                  {{ fmtAmount(moneyFlowData.realtime.medium_net) }}
                </span>
              </el-descriptions-item>
              <el-descriptions-item label="小单净流入">
                <span :style="{color: moneyFlowData.realtime.small_net >= 0 ? '#e53935' : '#16a34a'}">
                  {{ fmtAmount(moneyFlowData.realtime.small_net) }}
                </span>
              </el-descriptions-item>
            </el-descriptions>
            <!-- 近期资金流向趋势 -->
            <div v-if="moneyFlowData.history && moneyFlowData.history.length > 0">
              <div style="font-size: 12px; color: var(--el-text-color-secondary); margin-bottom: 8px;">近{{ moneyFlowData.days }}日资金流向</div>
              <div v-for="(h, i) in moneyFlowData.history" :key="i" class="flow-history-item">
                <span class="flow-date">{{ h.date }}</span>
                <span class="flow-change" :style="{color: h.change_pct >= 0 ? '#e53935' : '#16a34a'}">
                  {{ h.change_pct >= 0 ? '+' : '' }}{{ h.change_pct?.toFixed(2) || '0.00' }}%
                </span>
                <span class="flow-inflow" :style="{color: h.main_net_inflow >= 0 ? '#e53935' : '#16a34a'}">
                  {{ h.main_net_inflow >= 0 ? '+' : '' }}{{ fmtAmount(h.main_net_inflow) }}
                </span>
              </div>
            </div>
          </div>
        </el-card>

      </el-col>

      <el-col :span="6">
        <!-- 基本面快照 -->
        <el-card shadow="hover">
          <template #header><div class="card-hd">基本面快照</div></template>
          <div class="facts">
            <div class="fact"><span>行业</span><b>{{ basics.industry }}</b></div>
            <div class="fact"><span>板块</span><b>{{ basics.sector }}</b></div>
            <div class="fact"><span>总市值</span><b>{{ fmtAmount(basics.marketCap) }}</b></div>
            <div class="fact">
              <span>PE(TTM)</span>
              <b>
                {{ Number.isFinite(basics.pe) ? basics.pe.toFixed(2) : '-' }}
                <el-tag v-if="basics.peIsRealtime" type="success" size="small" style="margin-left: 4px">实时</el-tag>
              </b>
            </div>
            <div class="fact">
              <span>PB(市净率)</span>
              <b>
                {{ Number.isFinite(basics.pb) ? basics.pb.toFixed(2) : '-' }}
                <el-tag v-if="basics.peIsRealtime" type="success" size="small" style="margin-left: 4px">实时</el-tag>
              </b>
            </div>
            <div class="fact"><span>PS(TTM)</span><b>{{ Number.isFinite(basics.ps) ? basics.ps.toFixed(2) : '-' }}</b></div>
            <div class="fact"><span>ROE</span><b>{{ fmtPercent(basics.roe) }}</b></div>
            <div class="fact"><span>负债率</span><b>{{ fmtPercent(basics.debtRatio) }}</b></div>
          </div>
        </el-card>

        <!-- 主要财务指标 -->
        <el-card v-if="financialDetail" shadow="hover" class="financial-card">
          <template #header>
            <div class="card-hd">
              <span>主要财务指标</span>
              <span class="fin-period">{{ financialDetail.report_period || '-' }}</span>
            </div>
          </template>
          <div class="financial-content">
            <div class="fin-section">
              <div class="fin-section-title">利润与成长</div>
              <div class="fin-grid">
                <div class="fin-item">
                  <span class="fin-label">营业收入</span>
                  <span class="fin-value">{{ fmtFinAmount(financialDetail.revenue_ttm || financialDetail.revenue) }}</span>
                  <span v-if="financialDetail.revenue_yoy !== undefined && financialDetail.revenue_yoy !== null" class="fin-change" :class="getChangeClass(financialDetail.revenue_yoy)">
                    {{ fmtPercent(financialDetail.revenue_yoy) }}
                  </span>
                </div>
                <div class="fin-item">
                  <span class="fin-label">净利润</span>
                  <span class="fin-value">{{ fmtFinAmount(financialDetail.net_profit_ttm || financialDetail.net_profit) }}</span>
                  <span v-if="financialDetail.net_profit_yoy !== undefined && financialDetail.net_profit_yoy !== null" class="fin-change" :class="getChangeClass(financialDetail.net_profit_yoy)">
                    {{ fmtPercent(financialDetail.net_profit_yoy) }}
                  </span>
                </div>
                <div class="fin-item">
                  <span class="fin-label">毛利率</span>
                  <span class="fin-value">{{ fmtPercent(financialDetail.gross_margin) }}</span>
                </div>
                <div class="fin-item">
                  <span class="fin-label">净利率</span>
                  <span class="fin-value">{{ fmtPercent(financialDetail.net_margin) }}</span>
                </div>
              </div>
            </div>

            <div class="fin-section">
              <div class="fin-section-title">盈利能力</div>
              <div class="fin-grid">
                <div class="fin-item">
                  <span class="fin-label">ROE</span>
                  <span class="fin-value">{{ fmtPercent(basics.roe) }}</span>
                </div>
                <div class="fin-item">
                  <span class="fin-label">ROA</span>
                  <span class="fin-value">{{ fmtPercent(financialDetail.roa) }}</span>
                </div>
                <div class="fin-item">
                  <span class="fin-label">每股收益</span>
                  <span class="fin-value">{{ financialDetail.eps !== undefined && financialDetail.eps !== null ? financialDetail.eps.toFixed(2) + '元' : '-' }}</span>
                </div>
                <div class="fin-item">
                  <span class="fin-label">每股净资产</span>
                  <span class="fin-value">{{ financialDetail.bps !== undefined && financialDetail.bps !== null ? financialDetail.bps.toFixed(2) + '元' : '-' }}</span>
                </div>
              </div>
            </div>

            <div class="fin-section">
              <div class="fin-section-title">偿债能力</div>
              <div class="fin-grid">
                <div class="fin-item">
                  <span class="fin-label">资产负债率</span>
                  <span class="fin-value">{{ fmtPercent(basics.debtRatio) }}</span>
                </div>
                <div class="fin-item">
                  <span class="fin-label">流动比率</span>
                  <span class="fin-value">{{ financialDetail.current_ratio !== undefined && financialDetail.current_ratio !== null ? financialDetail.current_ratio.toFixed(2) : '-' }}</span>
                </div>
                <div class="fin-item">
                  <span class="fin-label">速动比率</span>
                  <span class="fin-value">{{ financialDetail.quick_ratio !== undefined && financialDetail.quick_ratio !== null ? financialDetail.quick_ratio.toFixed(2) : '-' }}</span>
                </div>
              </div>
            </div>
          </div>
        </el-card>



        <!-- 快捷操作 -->
        <el-card shadow="hover" class="actions-card">
          <template #header><div class="card-hd">快捷操作</div></template>
          <div class="quick-actions">
            <el-button type="primary" @click="onAnalyze" :icon="TrendCharts" plain>发起分析</el-button>
            <el-button @click="onToggleFavorite" :icon="Star">{{ isFav ? '移出自选' : '加入自选' }}</el-button>
            <el-button type="success" :icon="CreditCard" @click="goPaperTrading">模拟交易</el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 详细报告对话框 -->
    <el-dialog
      v-model="showReportsDialog"
      title="📊 详细分析报告"
      width="80%"
      :close-on-click-modal="false"
      class="reports-dialog"
    >
      <el-tabs v-model="activeReportTab" type="border-card">
        <el-tab-pane
          v-for="reportKey in reportKeys"
          :key="reportKey"
          :label="formatReportName(reportKey)"
          :name="reportKey"
        >
          <div class="report-content">
            <el-scrollbar height="500px">
              <div class="markdown-body" v-html="renderMarkdown(lastAnalysis?.reports?.[reportKey] || '')"></div>
            </el-scrollbar>
          </div>
        </el-tab-pane>
      </el-tabs>

      <template #footer>
        <el-button @click="showReportsDialog = false">关闭</el-button>
        <el-button type="primary" @click="exportReport">导出报告</el-button>
      </template>
    </el-dialog>

    <!-- 数据同步对话框 -->
    <el-dialog
      v-model="syncDialogVisible"
      title="同步股票数据"
      width="500px"
    >
      <el-form :model="syncForm" label-width="120px">
        <el-form-item label="股票代码">
          <el-input v-model="code" disabled />
        </el-form-item>
        <el-form-item label="股票名称">
          <el-input v-model="stockName" disabled />
        </el-form-item>
        <el-form-item label="同步内容">
          <el-checkbox-group v-model="syncForm.syncTypes">
            <el-checkbox label="realtime">实时行情</el-checkbox>
            <el-checkbox label="historical">历史行情数据</el-checkbox>
            <el-checkbox label="financial">财务数据</el-checkbox>
            <el-checkbox label="basic">基础数据</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="数据源">
          <el-radio-group v-model="syncForm.dataSource">
            <el-radio label="tushare">Tushare</el-radio>
            <el-radio label="akshare">AKShare</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="历史数据天数" v-if="syncForm.syncTypes.includes('historical')">
          <el-input-number v-model="syncForm.days" :min="1" :max="3650" />
          <span style="margin-left: 10px; color: #909399; font-size: 12px;">
            (最多3650天，约10年)
          </span>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="syncDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSync" :loading="syncLoading">
          开始同步
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { TrendCharts, Star, Refresh, Link, Document, Clock, Reading, CreditCard, Delete, Warning, WarningFilled, CircleCheckFilled, CaretBottom, CaretTop, QuestionFilled } from '@element-plus/icons-vue'
import { marked } from 'marked'
import { sanitizeHtml } from '@/utils/sanitize'
import { stocksApi } from '@/api/stocks'
import { analysisApi } from '@/api/analysis'
import { ApiClient } from '@/api/request'
import { stockSyncApi } from '@/api/stockSync'
import { clearAllCache } from '@/api/cache'
import { use as echartsUse } from 'echarts/core'
import { CandlestickChart } from 'echarts/charts'

import { GridComponent, TooltipComponent, DataZoomComponent, LegendComponent, TitleComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'
import { favoritesApi } from '@/api/favorites'
import { subscribeQuotesUpdate } from '@/utils/quotesSSE'


echartsUse([CandlestickChart, GridComponent, TooltipComponent, DataZoomComponent, LegendComponent, TitleComponent, CanvasRenderer])

const route = useRoute()
const router = useRouter()


// 分析状态
const analysisStatus = ref<'idle' | 'running' | 'completed' | 'failed'>('idle')
const analysisProgress = ref(0)
const analysisMessage = ref('')
const currentTaskId = ref<string | null>(null)
const lastAnalysis = ref<any | null>(null)
const lastTaskInfo = ref<any | null>(null) // 保存任务信息（包含 end_time 等）

// 报告对话框
const showReportsDialog = ref(false)
const activeReportTab = ref('')

// 股票代码（从路由参数获取）
const code = computed(() => {
  const routeCode = String(route.params.code || '').toUpperCase()
  if (!routeCode) {
    ElMessage.error('股票代码不能为空')
    router.push({ name: 'Dashboard' })
    return ''
  }
  return routeCode
})
const symbol = computed(() => code.value.split('.')[0])  // 提取6位代码
const stockName = ref('')
const market = ref('')
const isFav = ref(false)

// ECharts K线配置
const kOption = ref<EChartsOption>({
  grid: { left: 40, right: 20, top: 20, bottom: 40 },
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'cross' }
  },
  xAxis: {
    type: 'category',
    data: [],
    boundaryGap: true,
    axisLine: { onZero: false }
  },
  yAxis: {
    scale: true,
    type: 'value'
  },
  dataZoom: [
    { type: 'inside', start: 70, end: 100 },
    { start: 70, end: 100 }
  ],
  series: [
    {
      type: 'candlestick',
      name: 'K线',
      data: [],
      itemStyle: {
        color: '#ef4444',
        color0: '#16a34a',
        borderColor: '#ef4444',
        borderColor0: '#16a34a'
      }
    }
  ]
})
const lastKTime = ref<string | null>(null)
const lastKClose = ref<number | null>(null)

// 报价（初始化）
const quote = reactive({
  price: NaN,
  changePercent: NaN,
  open: NaN,
  high: NaN,
  low: NaN,
  prevClose: NaN,
  volume: NaN,
  amount: NaN,
  turnover: NaN,
  amplitude: NaN,  // 振幅（替代量比）
  tradeDate: null as string | null,  // 交易日期（用于成交量、成交额）
  turnoverDate: null as string | null,  // 换手率数据日期
  amplitudeDate: null as string | null,  // 振幅数据日期
  updatedAt: null as string | null  // 🔥 数据更新时间
})

const lastRefreshAt = ref<Date | null>(null)
const refreshText = computed(() => lastRefreshAt.value ? `已刷新 ${lastRefreshAt.value.toLocaleTimeString()}` : '未刷新')
const changeClass = computed(() => quote.changePercent > 0 ? 'up' : quote.changePercent < 0 ? 'down' : '')

// 🔥 日期判断和格式化函数
function isToday(dateStr: string | null): boolean {
  if (!dateStr) return false
  const today = new Date().toISOString().split('T')[0].replace(/-/g, '')
  const targetDate = dateStr.replace(/-/g, '')
  return today === targetDate
}

function formatDateTag(dateStr: string | null): string {
  if (!dateStr) return ''
  // 将 YYYYMMDD 或 YYYY-MM-DD 格式转换为 MM-DD
  const cleaned = dateStr.replace(/-/g, '')
  if (cleaned.length === 8) {
    return `${cleaned.substring(4, 6)}-${cleaned.substring(6, 8)}`
  }
  return dateStr
}

// 🔥 计算数据过期天数
function getDataExpiredDays(dateStr: string | null): number {
  if (!dateStr) return 0
  const cleaned = dateStr.replace(/-/g, '')
  if (cleaned.length !== 8) return 0
  const targetDate = new Date(
    parseInt(cleaned.substring(0, 4)),
    parseInt(cleaned.substring(4, 6)) - 1,
    parseInt(cleaned.substring(6, 8))
  )
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  targetDate.setHours(0, 0, 0, 0)
  const diffMs = today.getTime() - targetDate.getTime()
  return Math.floor(diffMs / (1000 * 60 * 60 * 24))
}

// 🔥 数据过期警告文本
function getDataExpiredWarning(dateStr: string | null): string {
  const days = getDataExpiredDays(dateStr)
  if (days <= 1) return `数据日期: ${dateStr}`
  if (days <= 7) return `⚠️ 数据已过期${days}天（${dateStr}），可能不是最新行情`
  return `❌ 数据已过期${days}天（${dateStr}），建议立即同步数据`
}

// 🔥 数据过期标签类型
function getDataExpiredType(dateStr: string | null): 'warning' | 'danger' | 'info' {
  const days = getDataExpiredDays(dateStr)
  if (days > 7) return 'danger'
  if (days > 1) return 'warning'
  return 'info'
}

// 同步状态
const syncStatus = ref<any>(null)

// 数据同步对话框
const syncDialogVisible = ref(false)
const syncLoading = ref(false)
const syncForm = reactive({
  syncTypes: ['realtime'],  // 默认选中实时行情
  dataSource: 'tushare' as 'tushare' | 'akshare',
  days: 365
})

// 清除缓存
const clearCacheLoading = ref(false)

// 显示同步对话框
function showSyncDialog() {
  syncDialogVisible.value = true
}

// 执行同步
async function handleSync() {
  if (syncForm.syncTypes.length === 0) {
    ElMessage.warning('请至少选择一种同步内容')
    return
  }

  syncLoading.value = true
  try {
    const res = await stockSyncApi.syncSingle({
      symbol: code.value,
      sync_realtime: syncForm.syncTypes.includes('realtime'),
      sync_historical: syncForm.syncTypes.includes('historical'),
      sync_financial: syncForm.syncTypes.includes('financial'),
      sync_basic: syncForm.syncTypes.includes('basic'),
      data_source: syncForm.dataSource,
      days: syncForm.days
    })

    if (res.success) {
      const data = res.data
      const lines: string[] = [`股票 ${code.value} 数据同步结果`]

      if (data.realtime_sync) {
        if (data.realtime_sync.success) {
          // 🔥 如果切换了数据源，显示提示信息
          if (data.realtime_sync.data_source_used && data.realtime_sync.data_source_used !== syncForm.dataSource) {
            lines.push(`✅ 实时行情同步成功（已自动切换到 ${data.realtime_sync.data_source_used.toUpperCase()} 数据源）`)
          } else {
            lines.push('✅ 实时行情同步成功')
          }
        } else {
          lines.push(`❌ 实时行情同步失败: ${data.realtime_sync.error || data.realtime_sync.message || '未知错误'}`)
        }

        if (data.realtime_sync.attempted_sources?.length) {
          lines.push(`尝试数据源: ${data.realtime_sync.attempted_sources.join(' -> ')}`)
        }

        if (data.realtime_sync.primary_error?.error) {
          lines.push(`主链路错误: ${data.realtime_sync.primary_error.error}`)
        }

        if (data.realtime_sync.fallback_error?.error) {
          lines.push(`回退错误: ${data.realtime_sync.fallback_error.error}`)
        }

        if (data.realtime_sync.market_quote_available) {
          const snapshot = data.realtime_sync.market_quote_snapshot
          lines.push(`行情已写入 market_quotes${snapshot?.trade_date ? `（交易日: ${snapshot.trade_date}）` : ''}`)
        } else if (syncForm.syncTypes.includes('realtime')) {
          lines.push('行情未写入 market_quotes')
        }
      }

      if (data.historical_sync) {
        if (data.historical_sync.success) {
          lines.push(`✅ 历史数据: ${data.historical_sync.records || 0} 条记录`)
        } else {
          lines.push(`❌ 历史数据同步失败: ${data.historical_sync.error || '未知错误'}`)
        }
      }

      if (data.financial_sync) {
        if (data.financial_sync.success) {
          lines.push('✅ 财务数据同步成功')
        } else {
          lines.push(`❌ 财务数据同步失败: ${data.financial_sync.error || '未知错误'}`)
        }
      }

      if (data.basic_sync) {
        if (data.basic_sync.success) {
          lines.push('✅ 基础数据同步成功')
        } else {
          lines.push(`❌ 基础数据同步失败: ${data.basic_sync.error || '未知错误'}`)
        }
      }

      const messageHtml = lines.map(line => line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')).join('<br/>')
      await ElMessageBox.alert(messageHtml, data.overall_success ? '同步成功' : '同步部分失败', {
        dangerouslyUseHTMLString: true,
        confirmButtonText: '知道了',
        type: data.overall_success ? 'success' : 'warning'
      })
      syncDialogVisible.value = false

      // 刷新页面数据
      await fetchQuote()
      await fetchFundamentals()
    } else {
      ElMessage.error(res.message || '同步失败')
    }
  } catch (error: any) {
    console.error('同步失败:', error)
    ElMessage.error(error.message || '同步失败，请稍后重试')
  } finally {
    syncLoading.value = false
  }
}

async function refreshMockQuote() {
  // 改为调用后端接口获取真实数据，并强制刷新
  await fetchQuote(true)
}

// 清除缓存
async function clearCache() {
  try {
    await ElMessageBox.confirm(
      '确定要清除所有缓存吗？清除后需要重新从数据源获取数据。',
      '清除缓存',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    clearCacheLoading.value = true
    await clearAllCache()
    ElMessage.success('缓存已清除，正在刷新数据...')

    // 刷新当前页面数据
    await Promise.all([
      fetchQuote(),
      fetchFundamentals(),
      fetchKline(),
      fetchNews(),
      fetchSectorInfo(),  // 🔥 板块联动
      fetchMoneyFlow()    // 🔥 主力资金
    ])

    ElMessage.success('数据已刷新')
  } catch (error: any) {
    if (error !== 'cancel') {
      console.error('清除缓存失败:', error)
      ElMessage.error(error.message || '清除缓存失败')
    }
  } finally {
    clearCacheLoading.value = false
  }
}

async function fetchQuote(forceRefresh = false) {
  // 🔥 参数验证：确保股票代码不为空
  if (!code.value) {
    console.warn('股票代码为空，跳过获取报价')
    return
  }

  try {
    const res = await stocksApi.getQuote(code.value, forceRefresh)
    const d: any = (res as any)?.data || {}
    // 后端为 snake_case，前端状态为 camelCase，这里进行映射
    quote.price = Number(d.price ?? d.close ?? quote.price)
    quote.changePercent = Number(d.change_percent ?? quote.changePercent)
    quote.open = Number(d.open ?? quote.open)
    quote.high = Number(d.high ?? quote.high)
    quote.low = Number(d.low ?? quote.low)
    quote.prevClose = Number(d.prev_close ?? quote.prevClose)
    quote.volume = Number.isFinite(d.volume) ? Number(d.volume) : quote.volume
    quote.amount = Number.isFinite(d.amount) ? Number(d.amount) : quote.amount
    quote.turnover = Number.isFinite(d.turnover_rate) ? Number(d.turnover_rate) : quote.turnover
    quote.amplitude = Number.isFinite(d.amplitude) ? Number(d.amplitude) : quote.amplitude

    // 🔥 获取数据日期（用于标注非当天数据）
    quote.tradeDate = d.trade_date || null  // 交易日期（用于成交量、成交额）
    quote.turnoverDate = d.turnover_rate_date || d.trade_date || null
    quote.amplitudeDate = d.amplitude_date || d.trade_date || null
    quote.updatedAt = d.updated_at || null  // 🔥 数据更新时间

    if (d.name) stockName.value = d.name
    if (d.market) market.value = d.market
    lastRefreshAt.value = new Date()
  } catch (e) {
    console.error('获取报价失败', e)
  }
}

async function fetchFundamentals() {
  try {
    const res = await stocksApi.getFundamentals(code.value)
    const f: any = (res as any)?.data || {}
    // 基本面快照映射（以后台为准）
    if (f.name) stockName.value = f.name
    if (f.market) market.value = f.market
    basics.industry = f.industry || basics.industry
    basics.sector = f.sector || basics.sector || '—'
    // 后端 total_mv 单位：亿元，这里转为元以便与金额格式化函数配合
    basics.marketCap = Number.isFinite(f.total_mv) ? Number(f.total_mv) * 1e8 : basics.marketCap
    // 优先使用 pe_ttm，其次 pe
    basics.pe = Number.isFinite(f.pe_ttm) ? Number(f.pe_ttm) : (Number.isFinite(f.pe) ? Number(f.pe) : basics.pe)
    // 🔥 新增：PB（市净率）
    basics.pb = Number.isFinite(f.pb) ? Number(f.pb) : basics.pb
    // 🔥 新增：PS（市销率）- 优先使用 ps_ttm，其次 ps
    basics.ps = Number.isFinite(f.ps_ttm) ? Number(f.ps_ttm) : (Number.isFinite(f.ps) ? Number(f.ps) : basics.ps)
    // ROE 和负债率
    basics.roe = Number.isFinite(f.roe) ? Number(f.roe) : basics.roe
    const ff: any = f
    basics.debtRatio = Number.isFinite(ff.debt_ratio) ? Number(ff.debt_ratio) : basics.debtRatio

    // 财务详情数据
    if (f.financial_detail) {
      financialDetail.value = f.financial_detail
    }

    // 获取PE/PB的实时标识
    basics.peIsRealtime = ff.pe_is_realtime || false
    basics.peSource = ff.pe_source || ''
    basics.peUpdatedAt = ff.pe_updated_at || null
  } catch (e) {
    console.error('获取基本面失败', e)
  }
}

async function fetchSyncStatus() {
  try {
    const res = await ApiClient.get('/api/stock-data/sync-status/quotes')
    const d: any = (res as any)?.data || {}
    syncStatus.value = d
  } catch (e) {
    console.warn('获取同步状态失败', e)
  }
}

let timer: any = null
let sseUnsubscribe: (() => void) | null = null
async function checkFavorite() {
  try {
    const res: any = await favoritesApi.check(code.value)
    const d: any = (res as any)?.data || {}
    isFav.value = !!d.is_favorite
  } catch (e) {
    console.warn('检查自选失败', e)
  }
}

async function loadPageData() {
  await Promise.all([
    fetchQuote(),
    fetchFundamentals(),
    fetchKline(),
    fetchNews(),
    checkFavorite(),
    fetchLatestAnalysis(),  // 获取最新的历史分析报告
    fetchSyncStatus(),  // 获取同步状态
    fetchSectorInfo(),  // 🔥 板块联动
    fetchMoneyFlow()    // 🔥 主力资金
  ])
}

function resetPageState() {
  stockName.value = ''
  market.value = ''
  isFav.value = false
  syncStatus.value = null
  newsItems.value = []
  newsSource.value = undefined
  lastAnalysis.value = null
  lastTaskInfo.value = null
  analysisStatus.value = 'idle'
  analysisProgress.value = 0
  analysisMessage.value = ''
  currentTaskId.value = null
}

onMounted(async () => {
  // 首次加载：打通后端（并行）
  await loadPageData()
  // 每30秒刷新一次报价（兜底机制）
  timer = setInterval(fetchQuote, 30000)
  // 订阅实时行情 SSE 信号（后端入库后立即推送，延迟约 0-2 秒）
  sseUnsubscribe = subscribeQuotesUpdate((signal) => {
    // 收到行情更新信号，立即拉取最新报价（SSE 优先，轮询兜底）
    fetchQuote(false)
  })
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
  if (sseUnsubscribe) {
    sseUnsubscribe()
    sseUnsubscribe = null
  }
})

watch(() => route.params.code, async (newCode, oldCode) => {
  if (!newCode || newCode === oldCode) {
    return
  }

  resetPageState()
  await loadPageData()
})



// K线占位相关
const periodOptions = ['日K','周K','月K']
const period = ref('日K')

const klineSource = ref<string | undefined>(undefined)

function periodLabelToParam(p: string): string {
  if (p.includes('5')) return '5m'
  if (p.includes('15')) return '15m'
  if (p.includes('60')) return '60m'
  if (p.includes('日')) return 'day'
  if (p.includes('周')) return 'week'
  if (p.includes('月')) return 'month'
  return '5m'
}

// 当周期切换时刷新K线
watch(period, () => { fetchKline() })

async function fetchKline() {
  try {
    const param = periodLabelToParam(period.value)
    const res = await stocksApi.getKline(code.value, param as any, 200, 'none')
    const d: any = (res as any)?.data || {}
    klineSource.value = d.source
    const items: any[] = Array.isArray(d.items) ? d.items : []

    // 🔥 检查是否有有效数据
    if (items.length === 0) {
      console.warn('K线数据为空，可能数据源超时或无数据')
      ElMessage.warning('K线数据暂时不可用，请稍后重试或刷新页面')
      return
    }

    const category: string[] = []
    const values: number[][] = [] // [open, close, low, high]

    for (const it of items) {
      const t = String(it.time || it.trade_time || it.trade_date || '')
      const o = Number(it.open ?? NaN)
      const h = Number(it.high ?? NaN)
      const l = Number(it.low ?? NaN)
      const c = Number(it.close ?? NaN)
      if (!Number.isFinite(o) || !Number.isFinite(h) || !Number.isFinite(l) || !Number.isFinite(c) || !t) continue
      category.push(t)
      values.push([o, c, l, h])
    }

    if (category.length) {
      lastKTime.value = category[category.length - 1]
      lastKClose.value = values[values.length - 1][1]
    }

    kOption.value = {
      ...kOption.value,
      xAxis: { type: 'category', data: category, boundaryGap: true, axisLine: { onZero: false } },
      series: [
        {
          type: 'candlestick',
          name: 'K线',
          data: values,
          itemStyle: {
            color: '#ef4444',
            color0: '#16a34a',
            borderColor: '#ef4444',
            borderColor0: '#16a34a'
          }
        }
      ]
    }
  } catch (e: any) {
    console.error('获取K线失败', e)
    // 🔥 增强错误提示
    if (e.message?.includes('timeout') || e.message?.includes('超时')) {
      ElMessage.error('K线数据获取超时，请稍后重试')
    } else {
      ElMessage.error('获取K线数据失败，请刷新页面重试')
    }
  }
}


// 新闻
const newsFilter = ref('all')
const newsItems = ref<any[]>([])
const newsSource = ref<string | undefined>(undefined)

function cleanTitle(s: any): string {
  const t = String(s || '')
  return t.replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').trim()
}

async function fetchNews() {
  try {
    const res = await stocksApi.getNews(code.value, 30, 50, true)
    const d: any = (res as any)?.data || {}
    const itemsRaw: any[] = Array.isArray(d.items) ? d.items : []
    newsItems.value = itemsRaw.map((it: any) => {
      const title = cleanTitle(it.title || it.summary || it.name || '')
      const url = it.url || it.link || '#'
      const source = it.source || d.source || ''
      const time = it.time || it.pub_time || it.publish_time || it.pub_date || ''
      const type = it.type || 'news'
      return { title, url, source, time, type }
    })
    newsSource.value = d.source
  } catch (e) {
    console.error('获取新闻失败', e)
  }
}

// 🔥 板块联动数据
const sectorData = ref<any>(null)
async function fetchSectorInfo() {
  try {
    const res = await stocksApi.getSectorInfo(code.value)
    sectorData.value = (res as any)?.data || null
  } catch (e) {
    console.error('获取板块信息失败', e)
  }
}

// 🔥 主力资金流向数据
const moneyFlowData = ref<any>(null)
async function fetchMoneyFlow() {
  try {
    const res = await stocksApi.getMoneyFlow(code.value, 5)
    moneyFlowData.value = (res as any)?.data || null
  } catch (e) {
    console.error('获取资金流向失败', e)
  }
}

const filteredNews = computed(() => {
  if (newsFilter.value === 'news') return newsItems.value.filter(x => x.type === 'news')
  if (newsFilter.value === 'announcement') return newsItems.value.filter(x => x.type === 'announcement')
  return newsItems.value
})

// 基本面（mock）
const basics = reactive({
  industry: '-',
  sector: '-',
  marketCap: NaN,
  pe: NaN,
  pb: NaN,              // 🔥 新增：市净率
  ps: NaN,              // 🔥 新增：市销率
  roe: NaN,
  debtRatio: NaN,
  peIsRealtime: false,  // PE是否为实时数据
  peSource: '',         // PE数据来源
  peUpdatedAt: null     // PE更新时间
})

// 财务详情数据
const financialDetail = ref<any>(null)

// 操作
function onAnalyze() {
  router.push({ name: 'SingleAnalysis', query: { stock: code.value } })
}
async function onToggleFavorite() {
  try {
    if (!isFav.value) {
      const payload = {
        symbol: symbol.value,
        stock_code: symbol.value,  // 兼容字段
        stock_name: stockName.value,
        market: market.value
      }
      await favoritesApi.add(payload)
      isFav.value = true
      ElMessage.success('已加入自选')
    } else {
      await favoritesApi.remove(code.value)
      isFav.value = false
      ElMessage.success('已移出自选')
    }
  } catch (e: any) {
    console.error('自选操作失败', e)
    ElMessage.error(e?.message || '自选操作失败')
  }
}

function goPaperTrading() {
  router.push({ name: 'PaperTradingHome', query: { code: code.value } })
}

// 跳转到分析报告详情页
function goToReportPage() {
  const reportId = lastTaskInfo.value?.task_id || lastTaskInfo.value?._id
  if (reportId) {
    router.push(`/reports/view/${reportId}`)
  } else {
    ElMessage.warning('未找到分析报告ID')
  }
}

// 获取最新的历史分析报告
async function fetchLatestAnalysis() {
  try {
    console.log('🔍 [fetchLatestAnalysis] 开始获取历史分析报告, symbol:', symbol.value)

    const resp: any = await analysisApi.getHistory({
      symbol: symbol.value,
      stock_code: symbol.value,  // 兼容字段
      page: 1,
      page_size: 1,
      status: 'completed'
    })

    console.log('🔍 [fetchLatestAnalysis] API响应:', resp)
    console.log('🔍 [fetchLatestAnalysis] resp.data:', resp?.data)
    console.log('🔍 [fetchLatestAnalysis] resp.data.data:', resp?.data?.data)

    // 修复：API返回格式是 { success: true, data: { tasks: [...] } }
    // 所以需要先取 resp.data，再取 data.tasks
    const responseData = resp?.data || resp
    console.log('🔍 [fetchLatestAnalysis] responseData:', responseData)

    // 如果responseData有success字段，说明是标准响应格式，需要再取一层data
    const actualData = responseData?.success ? responseData.data : responseData
    console.log('🔍 [fetchLatestAnalysis] actualData:', actualData)

    const tasks = actualData?.tasks || actualData?.analyses || []
    console.log('🔍 [fetchLatestAnalysis] tasks:', tasks)
    console.log('🔍 [fetchLatestAnalysis] tasks.length:', tasks?.length)
    console.log('🔍 [fetchLatestAnalysis] tasks && tasks.length > 0:', tasks && tasks.length > 0)

    if (tasks && tasks.length > 0) {
      const latestTask = tasks[0]
      console.log('✅ [fetchLatestAnalysis] 找到任务:', latestTask)
      console.log('🔍 [fetchLatestAnalysis] latestTask.result_data:', latestTask.result_data)
      console.log('🔍 [fetchLatestAnalysis] latestTask.result:', latestTask.result)
      console.log('🔍 [fetchLatestAnalysis] latestTask.task_id:', latestTask.task_id)
      console.log('🔍 [fetchLatestAnalysis] latestTask.end_time:', latestTask.end_time)

      // 保存任务信息（包含 end_time 等）
      lastTaskInfo.value = latestTask

      // 优先使用 result_data 字段（后端实际返回的字段名）
      if (latestTask.result_data) {
        lastAnalysis.value = latestTask.result_data
        analysisStatus.value = 'completed'
        console.log('✅ 加载历史分析报告成功 (result_data):', latestTask.result_data)
        console.log('🔍 [fetchLatestAnalysis] lastAnalysis.value.reports:', lastAnalysis.value?.reports)
      }
      // 兼容旧的 result 字段
      else if (latestTask.result) {
        lastAnalysis.value = latestTask.result
        analysisStatus.value = 'completed'
        console.log('✅ 加载历史分析报告成功 (result):', latestTask.result)
        console.log('🔍 [fetchLatestAnalysis] lastAnalysis.value.reports:', lastAnalysis.value?.reports)
      }
      // 否则尝试通过 task_id 获取结果
      else if (latestTask.task_id) {
        console.log('🔍 [fetchLatestAnalysis] 通过task_id获取结果:', latestTask.task_id)
        try {
          const resultResp: any = await analysisApi.getTaskResult(latestTask.task_id)
          console.log('🔍 [fetchLatestAnalysis] getTaskResult响应:', resultResp)
          lastAnalysis.value = resultResp?.data || resultResp
          analysisStatus.value = 'completed'
          console.log('✅ 通过 task_id 加载分析报告成功:', lastAnalysis.value)
          console.log('🔍 [fetchLatestAnalysis] lastAnalysis.value.reports:', lastAnalysis.value?.reports)
        } catch (e) {
          console.warn('⚠️ 获取任务结果失败:', e)
        }
      }
    } else {
      console.log('ℹ️ 该股票暂无历史分析报告')
      console.log('🔍 [fetchLatestAnalysis] 判断条件: tasks=', tasks, ', tasks.length=', tasks?.length)
    }
  } catch (e) {
    console.warn('⚠️ 获取历史分析报告失败:', e)
  }
}

// 格式化
function fmtPrice(v: any) { const n = Number(v); return Number.isFinite(n) ? n.toFixed(2) : '-' }
function fmtPercent(v: any) { const n = Number(v); return Number.isFinite(n) ? `${n>0?'+':''}${n.toFixed(2)}%` : '-' }
function fmtVolume(v: any) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '-'

  // 🔥 数据库存储的是"股"，直接显示为"万股"或"亿股"
  if (n >= 1e8) return (n/1e8).toFixed(2) + '亿股'
  if (n >= 1e4) return (n/1e4).toFixed(2) + '万股'
  return n.toFixed(0) + '股'
}
function fmtAmount(v: any) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '-'
  if (n >= 1e12) return (n/1e12).toFixed(2) + '万亿'
  if (n >= 1e8) return (n/1e8).toFixed(2) + '亿'
  if (n >= 1e4) return (n/1e4).toFixed(2) + '万'
  return n.toFixed(0)
}

// 财务金额格式化（后端可能为元，也可能为亿元，统一做友好显示）
function fmtFinAmount(v: any) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '-'
  // 如果数值很大（大于1万），认为单位是元
  if (Math.abs(n) >= 10000) {
    if (Math.abs(n) >= 1e12) return (n/1e12).toFixed(2) + '万亿'
    if (Math.abs(n) >= 1e8) return (n/1e8).toFixed(2) + '亿'
    if (Math.abs(n) >= 1e4) return (n/1e4).toFixed(2) + '万'
    return n.toFixed(0)
  }
  // 数值较小，可能已经是亿元或其他单位，直接保留两位小数
  return n.toFixed(2)
}

// 获取涨跌幅颜色类
function getChangeClass(v: any): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return ''
  if (n > 0) return 'up'
  if (n < 0) return 'down'
  return ''
}
// 🔥 新增：格式化同步时间（添加时区标识）
function formatSyncTime(timeStr: string | null | undefined): string {
  if (!timeStr) return '未同步'
  // 后端返回的时间已经是 UTC+8 时区，添加时区标识
  return `${timeStr} (UTC+8)`
}

// 🔥 新增：格式化股票更新时间
function formatQuoteUpdateTime(timeStr: string | null | undefined): string {
  if (!timeStr) return '未更新'
  try {
    // 后端返回的时间已经是 UTC+8 时区，但没有时区标识
    // 需要手动添加 +08:00 时区标识，然后转换为本地时间显示
    let isoString = timeStr
    if (!timeStr.includes('+') && !timeStr.includes('Z')) {
      // 如果没有时区标识，添加 +08:00
      isoString = timeStr.replace(/(\.\d+)?$/, '+08:00')
    }
    const date = new Date(isoString)
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    const hours = String(date.getHours()).padStart(2, '0')
    const minutes = String(date.getMinutes()).padStart(2, '0')
    const seconds = String(date.getSeconds()).padStart(2, '0')
    return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`
  } catch (e) {
    return timeStr
  }
}

// 🔥 新增：格式化同步间隔
function formatSyncInterval(seconds: number): string {
  if (!seconds || seconds <= 0) return ''

  if (seconds < 60) {
    // 小于60秒，显示秒数
    return `(每${seconds}秒)`
  } else if (seconds < 3600) {
    // 小于1小时，显示分钟数
    const minutes = Math.round(seconds / 60)
    return `(每${minutes}分钟)`
  } else {
    // 大于等于1小时，显示小时数
    const hours = Math.round(seconds / 3600)
    return `(每${hours}小时)`
  }
}
function fmtConf(v: any) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '-'
  const pct = n <= 1 ? n * 100 : n
  return `${Math.round(pct)}%`
}

import { formatDateTimeWithRelative, formatDateTime } from '@/utils/datetime'

// 格式化分析时间（处理UTC时间转换为中国本地时间）
function formatAnalysisTime(dateStr: any): string {
  return formatDateTimeWithRelative(dateStr)
}

// 格式化新闻时间（简洁格式：MM-DD HH:mm）
function formatNewsTime(dateStr: string | null | undefined): string {
  if (!dateStr) return '-'

  try {
    // 使用 formatDateTime 工具函数，自定义格式
    return formatDateTime(dateStr, {
      timeZone: 'Asia/Shanghai',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    }).replace(/\//g, '-').replace(/,/g, '')  // 移除逗号和斜杠
  } catch (e) {
    console.error('新闻时间格式化错误:', e, dateStr)
    return String(dateStr)
  }
}

// 格式化报告名称
function formatReportName(key: string): string {
  const nameMap: Record<string, string> = {
    // 分析师团队 (7个)
    'market_report': '📈 市场技术分析',
    'sentiment_report': '💭 市场情绪分析',
    'news_report': '📰 新闻事件分析',
    'fundamentals_report': '💰 基本面分析',
    'policy_report': '🏛️ 政策分析',
    'hot_money_report': '💹 游资追踪分析',
    'lockup_report': '🔒 限售解禁分析',

    // 研究团队 (3个)
    'bull_researcher': '🐂 看涨研究员',
    'bear_researcher': '🐻 看跌研究员',
    'research_team_decision': '👔 研究经理决策',

    // 交易团队 (1个)
    'trader_investment_plan': '💼 交易员投资计划',

    // 风险管理团队 (5个)
    'risky_analyst': '🔥 激进风险分析',
    'safe_analyst': '🛡️ 保守风险分析',
    'neutral_analyst': '⚖️ 中性风险分析',
    'risk_control_decision': '📋 风控约束决策',
    'risk_management_decision': '👔 风险经理决策',

    // 最终决策 (1个)
    'final_trade_decision': '🎯 决策建议',

    // 数据质量
    'data_quality_summary': '📊 数据质量评估',
    'quality_gate': '🚦 数据质量门控',

    // 兼容旧字段
    'investment_plan': '📋 投资建议',
    'investment_debate_state': '🔬 研究团队决策（旧）',
    'risk_debate_state': '⚖️ 风险管理团队（旧）'
  }
  return nameMap[key] || key
}

// 渲染Markdown
function renderMarkdown(content: string): string {
  if (!content) return '<p>暂无内容</p>'
  try {
    return sanitizeHtml(marked.parse(content))
  } catch (e) {
    console.error('Markdown渲染失败:', e)
    return sanitizeHtml(`<pre>${content}</pre>`)
  }
}

const reportKeys = computed<string[]>(() => {
  const reports = lastAnalysis.value?.reports
  return reports ? Object.keys(reports) : []
})

// 打开指定报告
function openReport(reportKey: string) {
  showReportsDialog.value = true
  activeReportTab.value = reportKey
}

// 导出报告
function exportReport() {
  if (!lastAnalysis.value?.reports) {
    ElMessage.warning('暂无报告可导出')
    return
  }

  // 生成Markdown格式的完整报告
  let fullReport = `# ${code.value} 股票分析报告\n\n`

  // 格式化分析时间用于报告
  const reportTime = lastTaskInfo.value?.end_time
    ? new Date(lastTaskInfo.value.end_time).toLocaleString('zh-CN', {
        timeZone: 'Asia/Shanghai',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false
      })
    : lastAnalysis.value?.analysis_date

  fullReport += `**分析时间**: ${reportTime}\n`
  fullReport += `**投资建议**: ${lastAnalysis.value.recommendation}\n`
  fullReport += `**信心度**: ${fmtConf(lastAnalysis.value.confidence_score)}\n\n`
  fullReport += `---\n\n`

  for (const [key, content] of Object.entries(lastAnalysis.value.reports)) {
    fullReport += `## ${formatReportName(key)}\n\n`
    fullReport += `${content}\n\n`
    fullReport += `---\n\n`
  }

  // 创建下载链接
  const blob = new Blob([fullReport], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url

  // 使用分析日期作为文件名（简化格式）
  const fileDate = lastAnalysis.value.analysis_date || new Date().toISOString().slice(0, 10)
  link.download = `${code.value}_分析报告_${fileDate}.md`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)

  ElMessage.success('报告已导出')
}

</script>

<style scoped lang="scss">
.stock-detail {
  display: flex; flex-direction: column; gap: 16px;
}

.header { display: flex; justify-content: space-between; align-items: center; }
.title { display: flex; align-items: center; gap: 12px; }
.code { font-size: 22px; font-weight: 700; }
.name { font-size: 18px; color: var(--el-text-color-regular); }
.actions { display: flex; gap: 8px; }

.quote-card { border-radius: 12px; }
.quote { display: flex; flex-direction: column; gap: 8px; }
.price-row { display: flex; align-items: center; gap: 12px; }
.price { font-size: 32px; font-weight: 800; }
.change { font-size: 16px; font-weight: 700; }
.up { color: #e53935; }
.down { color: #16a34a; }
.stats { display: grid; grid-template-columns: repeat(8, 1fr); gap: 10px; margin-top: 6px; }
.stats .item { display: flex; flex-direction: column; font-size: 12px; color: var(--el-text-color-secondary); }
.stats .item b { color: var(--el-text-color-primary); font-size: 14px; }
.stats .item span { display: flex; align-items: center; gap: 2px; }
.help-icon-inline { font-size: 12px; color: var(--el-text-color-placeholder); cursor: help; }
.help-icon-inline:hover { color: var(--el-color-primary); }

.body { margin-top: 4px; }
.card-hd { display: flex; align-items: center; justify-content: space-between; }
.k-chart { height: 320px; }
.legend { margin-top: 8px; font-size: 12px; color: var(--el-text-color-secondary); }

.news-card .news-list { display: flex; flex-direction: column; }
.flow-history-item { display: flex; justify-content: space-between; align-items: center; padding: 4px 0; border-bottom: 1px solid var(--el-border-color-lighter); font-size: 12px; }
.flow-history-item:last-child { border-bottom: none; }
.flow-date { color: var(--el-text-color-secondary); width: 100px; }
.flow-change { font-weight: bold; width: 80px; text-align: right; }
.flow-inflow { width: 120px; text-align: right; }
.news-item { padding: 10px 12px; border-bottom: 1px solid var(--el-border-color-lighter); transition: background-color .2s ease; }
.news-item:last-child { border-bottom: none; }
.news-item:hover { background: var(--el-fill-color-light); border-radius: 8px; }
.news-item .row { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.news-item .left { display: flex; align-items: flex-start; gap: 8px; flex: 1 1 auto; min-width: 0; }
.news-item .tag { flex: 0 0 auto; }
.news-item .title { font-weight: 600; display: flex; align-items: center; gap: 6px; flex: 1 1 auto; min-width: 0; }
.news-item .title a, .news-item .title span { color: var(--el-text-color-primary); text-decoration: none; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; }
.news-item .title a:hover { text-decoration: underline; }
.news-item .ext { color: var(--el-text-color-placeholder); font-size: 14px; }
.news-item .title:hover .ext { color: var(--el-color-primary); }
.news-item .right { color: var(--el-text-color-secondary); font-size: 12px; white-space: nowrap; margin-left: 8px; }
.news-item .meta { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 4px; }

.sentiment { font-size: 12px; }
.sentiment.pos { color: #ef4444; }
.sentiment.neu { color: #64748b; }
.sentiment.neg { color: #10b981; }

.facts { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.fact { display: flex; flex-direction: column; font-size: 12px; }
.fact b { font-size: 14px; color: var(--el-text-color-primary); }

.quick-actions { display: flex; flex-direction: column; gap: 8px; }

@media (max-width: 1024px) {
  .stats { grid-template-columns: repeat(4, 1fr); }
}

/* 报告相关样式 */
.reports-section {
  margin-top: 8px;
}

.reports-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  margin-top: 8px;
}

.reports-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  display: flex;
  align-items: center;
  gap: 6px;
}

.reports-preview {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 12px;
  background: var(--el-fill-color-lighter);
  border-radius: 8px;
}

.report-tag {
  cursor: pointer;
  transition: all 0.2s ease;
  font-size: 13px;
  padding: 6px 12px;
}

.report-tag:hover {
  transform: translateY(-2px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

/* 报告对话框样式 */
.reports-dialog :deep(.el-dialog__body) {
  padding: 0;
}

.report-content {
  padding: 20px;
}

.markdown-body {
  font-size: 14px;
  line-height: 1.8;
  color: var(--el-text-color-primary);
}

.markdown-body h1 {
  font-size: 24px;
  font-weight: 700;
  margin: 20px 0 16px;
  padding-bottom: 8px;
  border-bottom: 2px solid var(--el-border-color);
}

.markdown-body h2 {
  font-size: 20px;
  font-weight: 600;
  margin: 16px 0 12px;
}

.markdown-body h3 {
  font-size: 16px;
  font-weight: 600;
  margin: 12px 0 8px;
}

.markdown-body p {
  margin: 8px 0;
}

.markdown-body ul, .markdown-body ol {
  margin: 8px 0;
  padding-left: 24px;
}

.markdown-body li {
  margin: 4px 0;
}

.markdown-body code {
  background: var(--el-fill-color-light);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'Courier New', monospace;
}

.markdown-body pre {
  background: var(--el-fill-color-light);
  padding: 12px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 12px 0;
}

.markdown-body blockquote {
  border-left: 4px solid var(--el-color-primary);
  padding-left: 12px;
  margin: 12px 0;
  color: var(--el-text-color-secondary);
}

.markdown-body table {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
}

.markdown-body th, .markdown-body td {
  border: 1px solid var(--el-border-color);
  padding: 8px 12px;
  text-align: left;
}

.markdown-body th {
  background: var(--el-fill-color-light);
  font-weight: 600;
}

.analysis-detail-card .detail {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 分析时间元信息 */
.analysis-meta {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 8px 12px;
  background: var(--el-fill-color-lighter);
  border-radius: 6px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.analysis-meta .analysis-time,
.analysis-meta .confidence {
  display: flex;
  align-items: center;
  gap: 6px;
}

.analysis-meta .el-icon {
  font-size: 14px;
}

/* 投资建议盒子 - 重点突出 */
.recommendation-box {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 12px;
  padding: 20px 24px;
  box-shadow: 0 4px 16px rgba(102, 126, 234, 0.25);
  transition: all 0.3s ease;
  margin: 16px 0;
}

.recommendation-box:hover {
  box-shadow: 0 6px 20px rgba(102, 126, 234, 0.35);
  transform: translateY(-2px);
}

.recommendation-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  color: rgba(255, 255, 255, 0.95);
  font-size: 15px;
  font-weight: 600;
}

.recommendation-header .icon {
  font-size: 20px;
}

.recommendation-content {
  background: rgba(255, 255, 255, 0.98);
  border-radius: 8px;
  padding: 16px 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.recommendation-text {
  color: #1f2937;
  font-size: 15px;
  line-height: 1.8;
  font-weight: 500;
  word-wrap: break-word;
  word-break: break-word;
  white-space: pre-wrap;
}

/* 分析摘要 */
.summary-section {
  padding: 18px 20px;
  background: #f8fafc;
  border-radius: 8px;
  border-left: 4px solid #3b82f6;
  margin-top: 16px;
}

.summary-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: #1e40af;
  margin-bottom: 12px;
}

.summary-title .el-icon {
  font-size: 18px;
  color: #3b82f6;
}

.summary-text {
  color: #334155;
  line-height: 1.8;
  font-size: 14px;
  word-wrap: break-word;
  word-break: break-word;
  white-space: pre-wrap;
}

/* 同步状态提示 */
.sync-status {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
  padding: 8px 12px;
  background: #f0f9ff;
  border-radius: 6px;
  border: 1px solid #bae6fd;
  font-size: 13px;
  color: #0369a1;
}

.sync-status .el-icon {
  font-size: 14px;
  color: #0284c7;
}

.sync-info {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

/* 主要财务指标卡片 */
.financial-card {
  margin-top: 16px;

  .card-hd {
    .fin-period {
      font-size: 12px;
      color: var(--el-text-color-secondary);
      font-weight: normal;
    }
  }

  .financial-content {
    display: flex;
    flex-direction: column;
    gap: 16px;

    .fin-section {
      .fin-section-title {
        font-size: 13px;
        font-weight: 600;
        color: var(--el-text-color-primary);
        margin-bottom: 10px;
        padding-bottom: 6px;
        border-bottom: 1px solid var(--el-border-color-lighter);
      }

      .fin-grid {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 8px 12px;
      }

      .fin-item {
        display: flex;
        flex-direction: column;
        gap: 2px;

        .fin-label {
          font-size: 12px;
          color: var(--el-text-color-secondary);
        }

        .fin-value {
          font-size: 14px;
          font-weight: 600;
          color: var(--el-text-color-primary);
        }

        .fin-change {
          font-size: 12px;
          font-weight: 500;

          &.up {
            color: #f56c6c;
          }

          &.down {
            color: #67c23a;
          }
        }
      }
    }
  }
}
</style>

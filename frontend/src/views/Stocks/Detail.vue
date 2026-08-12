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
            ⚠️ 数据已过期 {{ getDataExpiredDays(quote.tradeDate) }} 个交易日（数据日期：{{ quote.tradeDate }}）
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
        <!-- 详细分析结果：超链接到分析报告（移到K线上方） -->
        <el-card v-if="analysisStatus==='running' || lastAnalysis" shadow="hover" class="analysis-detail-card" id="analysis-detail">
          <template #header><div class="card-hd">详细分析结果</div></template>
          <div v-if="analysisStatus==='running'" class="running">
            <el-progress :percentage="analysisProgress" :text-inside="true" style="width:100%" />
            <div class="hint">{{ analysisMessage || '正在生成分析报告…' }}</div>
          </div>
          <div v-else class="detail">
            <!-- 决策建议（仅呈现结果标签，不显示内容） -->
            <div v-if="decisionRecommendation" class="decision-box">
              <div class="decision-header">
                <span class="decision-icon">🎯</span>
                <span class="decision-label">决策建议</span>
                <el-tag :type="recommendationTagType" effect="dark" size="small">{{ recommendationLabel }}</el-tag>
              </div>
            </div>

            <!-- 短线博弈 -->
            <div v-if="shortTermScores.length" class="score-section">
              <div class="score-section-title">⚡ 短线博弈</div>
              <div class="score-grid">
                <el-tooltip
                  v-for="item in shortTermScores"
                  :key="item.field"
                  placement="top"
                  effect="dark"
                >
                  <template #content>
                    <div style="max-width: 250px; line-height: 1.6;">
                      <div style="font-weight: bold; margin-bottom: 6px;">{{ item.analyst }} · {{ item.max_score }}分制</div>
                      <div style="font-size: 12px; opacity: 0.9;">{{ item.basis }}</div>
                    </div>
                  </template>
                  <div class="score-card" :class="scoreClass(item.score)">
                    <div class="score-name">{{ item.name }}</div>
                    <div class="score-value">{{ formatScore(item.score) }}<span class="score-unit">分</span></div>
                    <div class="score-bar">
                      <div class="score-bar-fill" :style="{ width: getScorePercent(item.score) + '%' }"></div>
                    </div>
                  </div>
                </el-tooltip>
              </div>
            </div>

            <!-- 长线博弈 -->
            <div v-if="longTermScores.length" class="score-section">
              <div class="score-section-title">💎 长线博弈</div>
              <div class="score-grid">
                <el-tooltip
                  v-for="item in longTermScores"
                  :key="item.field"
                  placement="top"
                  effect="dark"
                >
                  <template #content>
                    <div style="max-width: 250px; line-height: 1.6;">
                      <div style="font-weight: bold; margin-bottom: 6px;">{{ item.analyst }} · {{ item.max_score }}分制</div>
                      <div style="font-size: 12px; opacity: 0.9;">{{ item.basis }}</div>
                    </div>
                  </template>
                  <div class="score-card" :class="scoreClass(item.score)">
                    <div class="score-name">{{ item.name }}</div>
                    <div class="score-value">{{ formatScore(item.score) }}<span class="score-unit">分</span></div>
                    <div class="score-bar">
                      <div class="score-bar-fill" :style="{ width: getScorePercent(item.score) + '%' }"></div>
                    </div>
                  </div>
                </el-tooltip>
              </div>
            </div>

            <!-- 分析时间和信心度（放在最后） -->
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

        <!-- 🔥 三买三卖买卖点检查（检测当前股价处于三买三卖哪个阶段） -->
        <el-card shadow="hover" class="tbs-check-card" style="margin-top: 16px;">
          <template #header>
            <div class="card-hd">
              <div>
                三买三卖买卖点检查
                <el-tooltip content="基于三买三卖交易系统，检测当前股价是否触发买点（B1/B2/B3）或卖点（S1/S2/S3），判断当前所处买卖阶段。" placement="top">
                  <el-icon class="help-icon-inline"><QuestionFilled /></el-icon>
                </el-tooltip>
              </div>
              <el-tag v-if="buySellCheckData" type="info" size="small">{{ buySellCheckData.trigger_date }}</el-tag>
            </div>
          </template>

          <el-empty v-if="buySellCheckLoading" description="检查中..." :image-size="60" />
          <el-alert
            v-else-if="!buySellCheckData"
            type="info"
            :closable="false"
            title="三买三卖数据暂不可用"
          >
            仅A股支持，或历史数据不足。
          </el-alert>
          <div v-else>
            <!-- 个股/大盘趋势 + 收盘概览 -->
            <div class="tbs-overview">
              <el-tag :type="tbsTrendTone(buySellCheckData.stock_trend)" effect="dark" size="small">
                个股 {{ tbsTrendLabel(buySellCheckData.stock_trend) }}
              </el-tag>
              <el-tag :type="tbsTrendTone(buySellCheckData.market_trend)" size="small">
                大盘 {{ tbsTrendLabel(buySellCheckData.market_trend) }}
              </el-tag>
              <span class="tbs-close">收盘 {{ fmtPrice(buySellCheckData.close) }}（{{ fmtNum(buySellCheckData.pct_chg) }}%）</span>
            </div>

            <!-- 当前所处阶段 -->
            <div class="tbs-stage">
              <template v-if="buySellCheckData.signals && buySellCheckData.signals.length">
                <div class="tbs-stage-title">当前触发信号</div>
                <div v-for="sig in buySellCheckData.signals" :key="sig.type" class="tbs-signal" :class="tbsSignalClass(sig.type)">
                  <span class="tbs-signal-type">{{ sig.type }}</span>
                  <span class="tbs-signal-label">{{ sig.type_label }}</span>
                  <span class="tbs-signal-desc">{{ tbsSignalDesc(sig.type) }}</span>
                </div>
              </template>
              <el-empty v-else description="当前未触发三买三卖信号" :image-size="50" />
            </div>
          </div>
        </el-card>

        <!-- 🔥 量价分析（价格K线+成交量融合图 + 五步分析法 + 综合结论） -->
        <el-card shadow="hover" class="volume-price-card" style="margin-top: 16px;">
          <template #header>
            <div class="card-hd">
              <div>
                量价分析
                <el-tooltip content="价格K线与成交量同图联动，支持日/周/月切换；下方为五步量价分析。" placement="top">
                  <el-icon class="help-icon-inline"><QuestionFilled /></el-icon>
                </el-tooltip>
              </div>
              <div class="periods">
                <el-segmented v-model="period" :options="periodOptions" size="small" />
              </div>
              <el-tag v-if="volumePriceData" type="info" size="small">{{ volumePriceData.date }}</el-tag>
            </div>
          </template>

          <!-- 价格K线+成交量 融合图（数据来自 getKline，随周期切换） -->
          <div v-if="klineItems.length" class="vp-chart-wrap">
            <v-chart class="vp-chart" :option="vpOption" autoresize />
            <div class="legend">当前周期：{{ period }} · 数据源：{{ klineSource || '-' }} · 最近：{{ lastKTime || '-' }} · 收：{{ fmtPrice(lastKClose) }}</div>
          </div>

          <el-empty v-if="volumePriceLoading" description="分析中..." :image-size="60" />
          <el-alert
            v-else-if="!volumePriceData"
            type="info"
            :closable="false"
            title="量价分析数据暂不可用"
          >
            仅A股支持量价分析，或历史数据不足。
          </el-alert>
          <div v-else>
            <!-- 综合结论 -->
            <div class="vp-overall" :class="'vp-bias-' + vpBiasClass(volumePriceData.overall?.bias)">
              <div class="vp-overall-head">
                <span class="vp-overall-label">综合判断</span>
                <!-- 偏多/偏空/中性 标签：悬浮展示该判断的详细依据（信号列表） -->
                <el-tooltip placement="top" :show-after="200">
                  <template #content>
                    <div class="vp-bias-tip">
                      <div>{{ vpBiasTip(volumePriceData.overall) }}</div>
                      <div v-if="volumePriceData.overall?.bias_basis?.length" class="vp-bias-basis">
                        <div class="vp-bias-basis-title">判断依据</div>
                        <div v-for="s in volumePriceData.overall.bias_basis" :key="s" class="vp-bias-basis-item">· {{ s }}</div>
                      </div>
                    </div>
                  </template>
                  <el-tag :type="vpBiasTagType(volumePriceData.overall?.bias)" effect="dark" size="small" class="vp-bias-tag">
                    {{ volumePriceData.overall?.bias || '中性' }}
                  </el-tag>
                </el-tooltip>
                <el-tooltip
                  v-if="volumePriceData.overall?.scenario"
                  placement="top"
                >
                  <template #content>
                    <div class="vp-scenario-tip">{{ volumePriceData.overall.scenario_meaning || volumePriceData.overall.scenario }}</div>
                  </template>
                  <el-tag
                    type="warning"
                    effect="plain"
                    size="small"
                    class="vp-scenario-tag"
                  >
                    {{ volumePriceData.overall.scenario }}
                  </el-tag>
                </el-tooltip>
              </div>
              <!-- 当前量价状态（结构化模块，替代长段落） -->
              <div v-if="volumePriceData.overall?.current_state" class="vp-block">
                <span class="vp-block-label vp-label-state">当前状态</span>
                <span class="vp-block-text">{{ volumePriceData.overall.current_state }}</span>
              </div>

              <!-- 情景关键信号（低位缩量等情景给出可落地企稳/见顶信号） -->
              <div v-if="volumePriceData.overall?.signal_note" class="vp-block">
                <span class="vp-block-label vp-label-signal">关键信号</span>
                <span class="vp-block-text">{{ volumePriceData.overall.signal_note }}</span>
              </div>
            </div>

            <!-- 五步分析明细（默认折叠，需要时点击展开） -->
            <el-collapse v-model="vpStepsActive" class="vp-collapse">
              <el-collapse-item name="steps">
                <template #title>
                  <span class="vp-collapse-title">五步分析明细</span>
                  <el-tag size="small" type="info" effect="plain" class="vp-collapse-hint">点击展开 / 收起</el-tag>
                </template>
                <div class="vp-steps">
              <div v-for="step in volumePriceData.steps" :key="step.step" class="vp-step">
                <div class="vp-step-header">
                  <span class="vp-step-num">{{ step.step }}</span>
                  <span class="vp-step-title">{{ step.title }}</span>
                  <!-- 每个分析内容的具体含义：鼠标停留显示 -->
                  <el-tooltip v-if="step.meaning" :content="step.meaning" placement="top">
                    <el-icon class="help-icon-inline"><QuestionFilled /></el-icon>
                  </el-tooltip>
                  <!-- 第一步：位置标签 -->
                  <el-tag v-if="step.step === 1 && step.position" :type="vpPositionTagType(step.position)" size="small">
                    {{ step.position }}
                  </el-tag>
                  <!-- 第二步：趋势标签 + OBV 背离辅助 -->
                  <el-tag v-if="step.step === 2 && step.trend" :type="step.trend === '多头排列' ? 'danger' : step.trend === '空头排列' ? 'success' : 'info'" size="small">
                    {{ step.trend }}
                  </el-tag>
                  <el-tag v-if="step.step === 2 && step.divergence && step.divergence !== '无背离'" :type="step.divergence === '底背离' ? 'success' : 'warning'" size="small">
                    {{ step.divergence }}
                  </el-tag>
                  <!-- 第三步：活跃度 -->
                  <el-tag v-if="step.step === 3 && step.level" :type="vpLevelTagType(step.level)" size="small">
                    {{ step.level }}
                  </el-tag>
                  <!-- 第四步：主导象限 -->
                  <el-tag v-if="step.step === 4 && step.dominant" :type="vpQuadrantTagType(step.dominant)" size="small">
                    {{ step.dominant }}
                  </el-tag>
                </div>
                <!-- 第一步：位置 -->
                <div v-if="step.step === 1" class="vp-step-body">
                  <el-descriptions :column="3" border size="small">
                    <el-descriptions-item label="收盘价">{{ fmtNum(step.close) }}</el-descriptions-item>
                    <el-descriptions-item label="60日高点">{{ fmtNum(step.high_60d) }}</el-descriptions-item>
                    <el-descriptions-item label="60日低点">{{ fmtNum(step.low_60d) }}</el-descriptions-item>
                  </el-descriptions>
                </div>
                <!-- 第二步：趋势（含 OBV 辅助验证） -->
                <div v-if="step.step === 2" class="vp-step-body">
                  <el-descriptions :column="4" border size="small" style="margin-bottom: 8px;">
                    <el-descriptions-item label="收盘价">{{ fmtNum(step.close) }}</el-descriptions-item>
                    <el-descriptions-item label="MA5">{{ fmtNum(step.ma5) }}</el-descriptions-item>
                    <el-descriptions-item label="MA20">{{ fmtNum(step.ma20) }}</el-descriptions-item>
                    <el-descriptions-item label="MA60">{{ fmtNum(step.ma60) }}</el-descriptions-item>
                  </el-descriptions>
                  <div class="vp-obv-row">
                    <span class="vp-obv-label">OBV 辅助</span>
                    <el-tag size="small" effect="plain" :type="step.obv_direction === '上升' ? 'danger' : step.obv_direction === '下降' ? 'success' : 'info'">
                      OBV {{ step.obv_direction }}
                    </el-tag>
                    <el-tag size="small" effect="plain" :type="step.price_direction === '上升' ? 'danger' : step.price_direction === '下降' ? 'success' : 'info'">
                      价格 {{ step.price_direction }}
                    </el-tag>
                    <el-tag v-if="step.divergence" size="small" :type="step.divergence === '底背离' ? 'success' : step.divergence === '顶背离' ? 'warning' : 'info'">
                      {{ step.divergence }}
                    </el-tag>
                  </div>
                </div>
                <!-- 第三步：量能 -->
                <div v-if="step.step === 3" class="vp-step-body">
                  <el-descriptions :column="3" border size="small">
                    <el-descriptions-item label="量比(5日)">{{ fmtNum(step.vol_ratio_5d) }}</el-descriptions-item>
                    <el-descriptions-item label="5日均量">{{ fmtVol(step.vol_ma5) }}</el-descriptions-item>
                    <el-descriptions-item label="量能趋势">{{ step.vol_trend }}</el-descriptions-item>
                  </el-descriptions>
                </div>
                <!-- 第四步：象限分布（每个象限鼠标停留显示含义） -->
                <div v-if="step.step === 4" class="vp-step-body">
                  <div class="vp-quad-grid">
                    <el-tooltip
                      v-for="(cnt, name) in step.distribution"
                      :key="name"
                      placement="top"
                      :content="step.quadrant_meanings?.[name] || name"
                    >
                      <div class="vp-quad-cell" :class="{ 'vp-quad-active': name === step.dominant }">
                        <span class="vp-quad-name">{{ name }}</span>
                        <span class="vp-quad-cnt">{{ cnt }}/5</span>
                      </div>
                    </el-tooltip>
                  </div>
                </div>
                <!-- 第五步：关键位量能 -->
                <div v-if="step.step === 5" class="vp-step-body">
                  <div v-for="lv in step.levels" :key="lv.name" class="vp-level-row">
                    <span class="vp-level-name">{{ lv.name }}</span>
                    <span class="vp-level-val">{{ fmtNum(lv.value) }}</span>
                    <span class="vp-level-note" :class="{ 'vp-level-near': lv.nearby }">{{ lv.note }}</span>
                  </div>
                </div>
                <!-- 结论 -->
                <div class="vp-conclusion">{{ step.conclusion }}</div>
              </div>
            </div>
              </el-collapse-item>
            </el-collapse>
          </div>
        </el-card>

        <!-- 🔥 辅助检查点（MACD辅助确认/抄底信号/上影洗筹模型/密集成交突破模型/大盘-个股联动分析） -->
        <el-card shadow="hover" class="checkpoint-card" style="margin-top: 16px;">
          <template #header>
            <div class="card-hd">
              <div>
                辅助检查点
                <el-tooltip content="基于三买三卖交易系统（教材第三章辅助信号系统），滚动验证主信号的可靠性：MACD辅助确认、抄底信号、上影洗筹模型、密集成交突破模型、大盘-个股联动分析。辅助信号不独立产生买卖，只对三买三卖主信号做确认/降权/预警。" placement="top">
                  <el-icon class="help-icon-inline"><QuestionFilled /></el-icon>
                </el-tooltip>
              </div>
              <el-tag v-if="buySellCheckData && buySellCheckData.aux_score != null" type="info" size="small">
                辅助综合分 {{ buySellCheckData.aux_score }}
              </el-tag>
            </div>
          </template>

          <el-empty v-if="buySellCheckLoading" description="检查中..." :image-size="60" />
          <el-alert
            v-else-if="!buySellCheckData || !buySellCheckData.checkpoints"
            type="info"
            :closable="false"
            title="辅助检查点暂不可用"
          >
            仅A股支持，或历史数据不足。
          </el-alert>
          <div v-else>
            <div class="cp-grid">
              <div
                v-for="item in auxCheckpoints"
                :key="item.key"
                class="cp-item"
                :class="'cp-level-' + item.value?.level"
              >
                <div class="cp-head">
                  <span class="cp-title">{{ checkpointTitle(item.key) }}</span>
                  <el-tag :type="checkpointLevelType(item.value?.level)" size="small" effect="dark">
                    {{ checkpointLevelLabel(item.value?.level) }}
                  </el-tag>
                </div>
                <div class="cp-label">{{ item.value?.label || '无信号' }}</div>
                <div class="cp-detail">{{ item.value?.detail || '—' }}</div>
              </div>
            </div>
            <div v-if="buySellCheckData.aux_warnings && buySellCheckData.aux_warnings.length" class="cp-warnings">
              <div class="cp-warnings-title">预警提示</div>
              <div v-for="(w, i) in buySellCheckData.aux_warnings" :key="i" class="cp-warning">
                <el-icon class="cp-warning-icon"><Warning /></el-icon>
                {{ w }}
              </div>
            </div>
          </div>
        </el-card>

        <!-- 🔥 通达信风险扫描（放在K线下方） -->
        <el-card shadow="hover" class="risk-scan-card" style="margin-top: 16px;">
          <template #header>
            <div class="card-hd">
              <div>
                通达信风险扫描
                <el-tooltip content="数据来源：通达信，包含财务风险、经营风险、市场风险等多个维度的扫描结果。" placement="top">
                  <el-icon class="help-icon-inline"><QuestionFilled /></el-icon>
                </el-tooltip>
              </div>
              <div v-if="riskAnalysisData" style="display: flex; gap: 8px; align-items: center;">
                <span class="risk-score" :style="{color: getRiskScoreColor(riskAnalysisData.score)}">
                  风险评分: {{ riskAnalysisData.score }}分
                </span>
                <el-tag :type="getRiskLevelTagType(riskAnalysisData.score)" size="small">
                  {{ getRiskLevelText(riskAnalysisData.score) }}
                </el-tag>
              </div>
            </div>
          </template>
          <el-empty v-if="riskAnalysisLoading" description="加载中..." :image-size="60" />
          <el-alert
            v-else-if="!riskAnalysisData"
            type="info"
            :closable="false"
            title="风险分析数据暂不可用"
          >
            仅A股支持风险扫描，或通达信接口临时不可用。
          </el-alert>
          <div v-else>
            <!-- 风险概览 -->
            <el-descriptions :column="4" border size="small" style="margin-bottom: 16px;">
              <el-descriptions-item label="总检查项">
                <span class="risk-stat">{{ riskAnalysisData.total }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="风险项">
                <span class="risk-stat risk">{{ riskAnalysisData.risk_count }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="安全项">
                <span class="risk-stat safe">{{ riskAnalysisData.safe_count }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="数据来源">
                <el-tag type="success" size="small">{{ riskAnalysisData.source }}</el-tag>
              </el-descriptions-item>
            </el-descriptions>

            <!-- 风险分类详情 -->
            <div v-for="(cat, idx) in riskAnalysisData.categories" :key="idx" class="risk-category">
              <div class="risk-category-header">
                <span class="risk-category-name">{{ cat.name }}</span>
                <span class="risk-category-count">
                  <span v-if="cat.risk_count > 0" class="risk-badge">{{ cat.risk_count }}风险</span>
                  <span v-if="cat.safe_count > 0" class="safe-badge">{{ cat.safe_count }}安全</span>
                </span>
              </div>
              <div v-if="cat.risk_items && cat.risk_items.length > 0" class="risk-items">
                <div v-for="(item, i) in cat.risk_items" :key="i" class="risk-item">
                  <el-icon class="risk-icon"><Warning /></el-icon>
                  <div class="risk-item-content">
                    <div class="risk-item-name">{{ item.name }}</div>
                    <div v-if="item.reason" class="risk-item-reason">{{ item.reason }}</div>
                    <div v-if="item.sub_items && item.sub_items.length > 0" class="risk-sub-items">
                      <div v-for="(sub, si) in item.sub_items" :key="si" class="risk-sub-item">
                        <el-icon :class="sub.trig ? 'sub-risk-icon' : 'sub-safe-icon'">
                          <Warning v-if="sub.trig" />
                          <CircleCheckFilled v-else />
                        </el-icon>
                        <span>{{ sub.name }}</span>
                        <span v-if="sub.reason" class="sub-reason">{{ sub.reason }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              <div v-else class="risk-no-items">
                <el-icon class="safe-icon"><CircleCheckFilled /></el-icon>
                <span>该分类暂无风险项</span>
              </div>
            </div>
          </div>
        </el-card>

        <!-- 新闻与公告 -->
        <el-card shadow="hover" class="news-card" style="margin-top: 16px;">
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
              <el-table-column label="代码" prop="code" width="80">
                <template #default="{ row }">
                  <router-link :to="`/stocks/${row.code}`" class="stock-code">{{ row.code }}</router-link>
                </template>
              </el-table-column>
              <el-table-column label="名称" prop="name" width="100">
                <template #default="{ row }">
                  <router-link :to="`/stocks/${row.code}`" class="stock-name">{{ row.name }}</router-link>
                </template>
              </el-table-column>
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
                <span class="flow-change" :style="{color: h.main_net_inflow_pct >= 0 ? '#e53935' : '#16a34a'}">
                  {{ h.main_net_inflow_pct >= 0 ? '+' : '' }}{{ h.main_net_inflow_pct?.toFixed(2) || '0.00' }}%
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
        <el-card shadow="hover" style="margin-top: 16px;">
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
          <div class="data-source-footer" v-if="basics.peSource || basics.peUpdatedAt">
            <el-icon><InfoFilled /></el-icon>
            <span class="source-text">
              <span v-if="basics.peSource">数据源: {{ basics.peSource }}</span>
              <span v-if="basics.peUpdatedAt" class="source-sep">·</span>
              <span v-if="basics.peUpdatedAt">更新: {{ formatQuoteUpdateTime(basics.peUpdatedAt) }}</span>
            </span>
          </div>
        </el-card>

        <!-- 主要财务指标 -->
        <el-card v-if="financialDetail" shadow="hover" class="financial-card" style="margin-top: 16px;">
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
        <el-card shadow="hover" class="actions-card" style="margin-top: 16px;">
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
import { TrendCharts, Star, Refresh, Link, Document, Clock, Reading, CreditCard, Delete, Warning, WarningFilled, CircleCheckFilled, CaretBottom, CaretTop, QuestionFilled, InfoFilled } from '@element-plus/icons-vue'
import { marked } from 'marked'
import { sanitizeHtml } from '@/utils/sanitize'
import { stocksApi } from '@/api/stocks'
import { analysisApi } from '@/api/analysis'
import { ApiClient } from '@/api/request'
import { stockSyncApi } from '@/api/stockSync'
import { clearAllCache } from '@/api/cache'
import { use as echartsUse } from 'echarts/core'
import { CandlestickChart, LineChart, BarChart } from 'echarts/charts'

import { GridComponent, TooltipComponent, DataZoomComponent, LegendComponent, TitleComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'
import { favoritesApi } from '@/api/favorites'
import { subscribeQuotesUpdate } from '@/utils/quotesSSE'


echartsUse([CandlestickChart, LineChart, BarChart, GridComponent, TooltipComponent, DataZoomComponent, LegendComponent, TitleComponent, CanvasRenderer])

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

// K线原始数据（价格K线+成交量融合图的数据源，来自 getKline）
const klineItems = ref<any[]>([])
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
  updatedAt: null as string | null,  // 🔥 数据更新时间
  staleDays: 0  // 后端计算的交易日过期天数（0=最新）
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

// 🔥 获取数据过期交易日天数（后端已排除周末和节假日）
function getDataExpiredDays(_dateStr: string | null): number {
  return quote.staleDays
}

// 🔥 数据过期警告文本
function getDataExpiredWarning(dateStr: string | null): string {
  const days = getDataExpiredDays(dateStr)
  if (days <= 1) return `数据日期: ${dateStr}`
  if (days <= 7) return `⚠️ 数据已过期${days}个交易日（${dateStr}），可能不是最新行情`
  return `❌ 数据已过期${days}个交易日（${dateStr}），建议立即同步数据`
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
    quote.staleDays = d.stale_days ?? 0  // 后端计算的交易日过期天数

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
  // 所有数据请求并行发起，避免串行等待拖慢页面加载
  await Promise.allSettled([
    fetchKline(),
    fetchNews(),
    checkFavorite(),
    fetchLatestAnalysis(),
    fetchSyncStatus(),
    fetchSectorInfo(),
    fetchMoneyFlow(),
    fetchQuote(),
    fetchFundamentals(),
    fetchVolumePriceAnalysis(),
    fetchRiskAnalysis(),
    fetchBuySellCheck()
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
  volumePriceData.value = null
  klineItems.value = []
  buySellCheckData.value = null
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

// ── 详细分析结果：决策建议 + 短线/长线博弈各面分数 ──
const dimensionScoreFields = ['技术面评分', '基本面评分', '情绪面评分', '消息面评分', '资金面评分', '政策面评分', '解禁面评分']
const defaultBasis: Record<string, { analyst: string; basis: string }> = {
  '技术面评分': { analyst: '技术分析师', basis: '基于技术指标（均线、KDJ、MACD、RSI等）、趋势形态、量价关系等综合评估，满分100分。' },
  '基本面评分': { analyst: '基本面分析师', basis: '基于财务数据（营收、利润、ROE等）、行业地位、护城河、估值水平等综合评估，满分100分。' },
  '情绪面评分': { analyst: '市场情绪分析师', basis: '基于市场情绪指标、舆情热度、散户情绪逆向指标等综合评估，满分100分。' },
  '消息面评分': { analyst: '新闻分析师', basis: '基于公司公告、研报动态、新闻事件冲击、重要消息面影响等综合评估，满分100分。' },
  '资金面评分': { analyst: '游资追踪师', basis: '基于主力资金流向、龙虎榜数据、北向资金动向、机构持仓变化等综合评估，满分100分。' },
  '政策面评分': { analyst: '政策分析师', basis: '基于产业政策、宏观调控、监管动向、行业利好/利空政策等综合评估，满分100分。' },
  '解禁面评分': { analyst: '解禁追踪师', basis: '基于限售股解禁规模、大股东减持计划、解禁压力与市场承接能力等综合评估，满分100分。' }
}

interface DimensionScoreItem {
  name: string
  field: string
  score: number
  max_score: number
  analyst: string
  basis: string
}

const dimensionScoreList = computed((): DimensionScoreItem[] => {
  const analysis = lastAnalysis.value
  if (!analysis) return []
  // 优先使用结构化详情
  const detail = analysis['维度评分详情']
  if (Array.isArray(detail) && detail.length > 0) {
    return detail.map((d: any) => ({
      name: (d.name || String(d.field || '')).replace('评分', ''),
      field: d.field || d.name,
      score: Number(d.score ?? 0),
      max_score: d.max_score || 100,
      analyst: d.analyst || '分析师',
      basis: d.basis || ''
    }))
  }
  // 兜底：从顶层字段读取
  const result: DimensionScoreItem[] = []
  for (const field of dimensionScoreFields) {
    const val = analysis[field]
    if (val === null || val === undefined || val === '') continue
    const num = Number(val)
    if (isNaN(num)) continue
    const info = defaultBasis[field] || { analyst: '分析师', basis: '' }
    result.push({ name: field.replace('评分', ''), field, score: num, max_score: 100, analyst: info.analyst, basis: info.basis })
  }
  return result
})

const shortTermFields = ['技术面评分', '情绪面评分', '消息面评分', '资金面评分']
const longTermFields = ['基本面评分', '政策面评分', '解禁面评分']
const shortTermScores = computed(() => dimensionScoreList.value.filter(i => shortTermFields.includes(i.field)))
const longTermScores = computed(() => dimensionScoreList.value.filter(i => longTermFields.includes(i.field)))

// 决策建议
const decisionRecommendation = computed(() => {
  const a = lastAnalysis.value
  if (!a) return ''
  return a.recommendation || a.investment_recommendation || ''
})
const recommendationLabel = computed(() => {
  const text = decisionRecommendation.value || ''
  if (/卖出|Sell|清仓|强烈看空/i.test(text)) return '卖出'
  if (/减持|减仓|看空/i.test(text)) return '减持'
  if (/买入|Buy|加仓|强烈看多/i.test(text)) return '买入'
  if (/增持|看多/i.test(text)) return '增持'
  if (/持有|Hold|观望/i.test(text)) return '持有'
  return '参考'
})
const recommendationTagType = computed(() => {
  const l = recommendationLabel.value
  if (l === '买入' || l === '增持') return 'danger'
  if (l === '卖出') return 'success'
  if (l === '减持') return 'warning'
  if (l === '持有') return 'info'
  return 'info'
})

function formatScore(v: number | null): string {
  if (v === null || v === undefined) return '暂无'
  if (Number.isInteger(v)) return v.toString()
  return v.toFixed(1)
}
function getScorePercent(v: number | null): number {
  if (v === null || v === undefined) return 0
  if (v <= 10) return (v / 10) * 100
  if (v <= 100) return v
  return 100
}
function scoreClass(v: number): string {
  if (v >= 80) return 'score-high'
  if (v >= 60) return 'score-mid'
  return 'score-low'
}
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

    klineItems.value = items
    const last = items[items.length - 1]
    lastKTime.value = String(last.time || last.trade_time || last.trade_date || '')
    lastKClose.value = Number(last.close ?? NaN)

    // 重建融合图（价格K线+成交量）
    buildVpOption()
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

// 🔥 通达信风险分析数据
const riskAnalysisData = ref<any>(null)
const riskAnalysisLoading = ref(false)
async function fetchRiskAnalysis() {
  riskAnalysisLoading.value = true
  try {
    const res = await stocksApi.getRiskAnalysis(code.value)
    riskAnalysisData.value = (res as any)?.data || null
  } catch (e) {
    console.error('获取风险分析失败', e)
    riskAnalysisData.value = null
  } finally {
    riskAnalysisLoading.value = false
  }
}

// 🔥 量价分析（五步分析法）
const volumePriceData = ref<any>(null)
const volumePriceLoading = ref(false)
const vpOption = ref<EChartsOption>({})
// 五步分析明细默认折叠（综合判断常显），点击展开查看每一步明细
const vpStepsActive = ref<string[]>([])
async function fetchVolumePriceAnalysis() {
  volumePriceLoading.value = true
  try {
    const res = await stocksApi.getVolumePriceAnalysis(code.value)
    volumePriceData.value = (res as any)?.data || null
  } catch (e) {
    console.error('获取量价分析失败', e)
    volumePriceData.value = null
  } finally {
    volumePriceLoading.value = false
  }
}

// 🔥 三买三卖买卖点检查 + 辅助检查点
const buySellCheckData = ref<any>(null)
const buySellCheckLoading = ref(false)
async function fetchBuySellCheck() {
  buySellCheckLoading.value = true
  try {
    const res = await stocksApi.getBuySellCheck(code.value)
    buySellCheckData.value = (res as any)?.data || null
  } catch (e) {
    console.error('获取三买三卖检查失败', e)
    buySellCheckData.value = null
  } finally {
    buySellCheckLoading.value = false
  }
}

// 三买三卖信号中文说明
const TBS_SIGNAL_DESC: Record<string, string> = {
  B1: '左侧买点：BIAS(60) 深度超卖（-30%~-20%），配合 W底/放量/MACD金叉三重确认，逢低左侧建仓',
  B2: '突破买点：放量中阳站上 MA55/MA60，趋势突破，右侧加仓',
  B3: '主升买点：强势放量中阳突破，趋势加速，顺应主升浪',
  B2G: '加仓信号：GMMA 强多状态下的突破加仓',
  S1: '加速卖点：BIAS 超阈值或 GMMA 慢组压缩，先减仓 1/3 预警',
  S2: '主减仓：连续跌破 MA5/MA8/MA13，趋势转弱，主减仓',
  S3: '清仓卖出：跌破 MA55/MA60 且 MA60 拐头向下，中期趋势破坏，清仓',
  SafetyNet: '安全网：ATR×3 急跌破位，无条件止损',
  TrailingStop: '移动止损：跟随趋势抬高止盈位，跌破即止盈'
}
function tbsSignalDesc(type: string): string {
  return TBS_SIGNAL_DESC[type] || ''
}
function tbsSignalClass(type: string): string {
  if (type.startsWith('B')) return 'tbs-signal-buy'
  if (type === 'S1') return 'tbs-signal-s1'
  return 'tbs-signal-sell'
}
function tbsTrendLabel(t: string): string {
  return t === 'up' ? '↑偏多' : t === 'down' ? '↓偏空' : '→震荡'
}
function tbsTrendTone(t: string): string {
  return t === 'up' ? 'danger' : t === 'down' ? 'success' : 'info'
}

// 辅助检查点中文标题
const CHECKPOINT_TITLES: Record<string, string> = {
  macd: 'MACD辅助确认',
  bottom_fishing: '抄底信号',
  washout: '上影洗筹模型',
  dense_break: '密集成交突破模型',
  regime_quadrant: '大盘-个股联动分析',
  qty_verification: '量价关系确认'
}
function checkpointTitle(key: string): string {
  return CHECKPOINT_TITLES[key] || key
}
function checkpointLevelType(level: string): string {
  return level === 'confirm' ? 'danger' : level === 'warn' ? 'warning' : 'info'
}
function checkpointLevelLabel(level: string): string {
  return level === 'confirm' ? '确认' : level === 'warn' ? '预警' : '中性'
}
// 辅助检查点仅展示用户关心的 5 项（量价关系确认已由上方「量价分析」模块覆盖，故排除 qty_verification）
const AUX_KEY_ORDER = ['macd', 'bottom_fishing', 'washout', 'dense_break', 'regime_quadrant']
const auxCheckpoints = computed(() => {
  const cps = buySellCheckData.value?.checkpoints || {}
  const out: Array<{ key: string; value: any }> = []
  for (const key of AUX_KEY_ORDER) {
    if (cps[key] !== undefined) out.push({ key, value: cps[key] })
  }
  return out
})

// 价格K线+成交量融合图：K线 + MA5/MA20/MA60 + 成交量（数据来自 getKline，随周期切换）
function calculateMA(series: any[], n: number): Array<number | null> {
  return series.map((_, i) => {
    if (i < n - 1) return null
    let sum = 0
    for (let j = i - n + 1; j <= i; j++) sum += Number(series[j]?.close ?? 0)
    return sum / n
  })
}

function buildVpOption() {
  const series = klineItems.value
  if (!series || !series.length) return
  const dates = series.map((s: any) => String(s.time || s.trade_time || s.trade_date || ''))
  const klineData = series.map((s: any) => [Number(s.open ?? NaN), Number(s.close ?? NaN), Number(s.low ?? NaN), Number(s.high ?? NaN)])
  const volData = series.map((s: any) => ({
    value: Number(s.volume ?? 0),
    itemStyle: { color: (Number(s.close ?? 0) >= Number(s.open ?? 0)) ? '#ef4444' : '#16a34a' }
  }))
  const ma5 = calculateMA(series, 5)
  const ma20 = calculateMA(series, 20)
  const ma60 = calculateMA(series, 60)
  vpOption.value = {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    legend: { data: ['K线', 'MA5', 'MA20', 'MA60', '成交量'], top: 0, left: 0, textStyle: { fontSize: 11 } },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    grid: [
      { left: 48, right: 16, top: 24, height: '58%' },
      { left: 48, right: 16, top: '72%', height: '18%' }
    ],
    xAxis: [
      { type: 'category', data: dates, boundaryGap: true, axisLine: { onZero: false }, axisLabel: { fontSize: 10 } },
      { type: 'category', gridIndex: 1, data: dates, boundaryGap: true, axisLabel: { show: false }, axisTick: { show: false } }
    ],
    yAxis: [
      { scale: true, type: 'value', axisLabel: { fontSize: 10 } },
      { gridIndex: 1, scale: true, type: 'value', axisLabel: { fontSize: 10, formatter: (v: number) => v >= 1e8 ? (v / 1e8).toFixed(1) + '亿' : v >= 1e4 ? (v / 1e4).toFixed(0) + '万' : v } }
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 65, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1], start: 65, end: 100, height: 16, bottom: 4 }
    ],
    series: [
      {
        name: 'K线', type: 'candlestick', data: klineData,
        itemStyle: { color: '#ef4444', color0: '#16a34a', borderColor: '#ef4444', borderColor0: '#16a34a' }
      },
      { name: 'MA5', type: 'line', data: ma5, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#f97316' } },
      { name: 'MA20', type: 'line', data: ma20, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#f59e0b' } },
      { name: 'MA60', type: 'line', data: ma60, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#3b82f6' } },
      { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volData }
    ]
  }
}

function vpBiasClass(bias?: string): string {
  if (bias === '偏多') return 'bull'
  if (bias === '偏空') return 'bear'
  return 'flat'
}
function vpBiasTagType(bias?: string): string {
  if (bias === '偏多') return 'danger'
  if (bias === '偏空') return 'success'
  return 'info'
}

// 综合判断倾向的悬浮说明（重点解释"中性"的含义，并给出判断依据信号）
function vpBiasTip(overall: any): string {
  const bias = overall?.bias
  if (bias === '偏多') return '当前多数量价信号偏向看多，多空力量中多方占优，短期更可能延续上行。'
  if (bias === '偏空') return '当前多数量价信号偏向看空，多空力量中空方占优，短期更可能承压下行。'
  return '中性表示当前多空信号相互抵消、未形成明确方向，短期多半震荡整理，需等待放量突破或跌破关键位后才能确认方向。'
}

function vpQuadrantTagType(q: string): string {
  if (q === '价涨量增') return 'danger'
  if (q === '价跌量增') return 'warning'
  if (q === '价跌量缩') return 'success'
  return 'info'
}
function vpLevelTagType(level: string): string {
  if (level === '显著放量') return 'danger'
  if (level === '温和放量') return 'warning'
  if (level === '缩量') return 'info'
  return 'success'
}
function vpPositionTagType(pos: string): string {
  if (pos === '高位') return 'danger'
  if (pos === '低位') return 'success'
  return 'info'
}
function fmtNum(v: any): string {
  if (v === null || v === undefined || isNaN(v)) return '-'
  return Number(v).toFixed(2)
}
function fmtVol(v: any): string {
  if (v === null || v === undefined || isNaN(v)) return '-'
  const n = Number(v)
  if (n >= 1e8) return (n / 1e8).toFixed(2) + '亿'
  if (n >= 1e4) return (n / 1e4).toFixed(2) + '万'
  return n.toFixed(0)
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

// 风险评分颜色
function getRiskScoreColor(score: number): string {
  if (score >= 80) return '#10b981'
  if (score >= 60) return '#f59e0b'
  if (score >= 40) return '#ef4444'
  return '#ef4444'
}

// 风险等级标签类型
function getRiskLevelTagType(score: number): string {
  if (score >= 80) return 'success'
  if (score >= 60) return 'warning'
  return 'danger'
}

// 风险等级文本
function getRiskLevelText(score: number): string {
  if (score >= 80) return '低风险'
  if (score >= 60) return '中风险'
  return '高风险'
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
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 100vh;
  background: linear-gradient(135deg, var(--el-bg-color-page) 0%, var(--el-fill-color-lighter) 100%);
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  background: var(--el-bg-color);
  border-radius: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.title { display: flex; align-items: center; gap: 12px; }
.code { font-size: 24px; font-weight: 700; color: var(--el-text-color-primary); }
.name { font-size: 20px; color: var(--el-text-color-regular); }
.actions { display: flex; gap: 8px; }

.quote-card {
  border-radius: 16px;
  border: 1px solid var(--el-border-color-light);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
  overflow: hidden;
}

.quote {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.price-row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 20px;
  background: linear-gradient(90deg, var(--el-fill-color-light) 0%, transparent 100%);
}

.price { font-size: 36px; font-weight: 800; letter-spacing: -1px; }
.change { font-size: 18px; font-weight: 700; }
.up { color: #ef4444; }
.down { color: #10b981; }

.stats {
  display: grid;
  grid-template-columns: repeat(8, 1fr);
  gap: 12px;
  padding: 0 20px 16px;
}

.stats .item {
  display: flex;
  flex-direction: column;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  padding: 8px;
  background: var(--el-fill-color-lighter);
  border-radius: 8px;
  text-align: center;
}

.stats .item b {
  color: var(--el-text-color-primary);
  font-size: 14px;
  font-weight: 600;
  margin-top: 4px;
}

.stats .item span { display: flex; align-items: center; justify-content: center; gap: 2px; }
.help-icon-inline { font-size: 12px; color: var(--el-text-color-placeholder); cursor: help; }
.help-icon-inline:hover { color: var(--el-color-primary); }

.body { margin-top: 4px; }

.card-hd {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 4px;
}

.legend {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  padding: 0 8px;
}

.news-card {
  border-radius: 16px;
  border: 1px solid var(--el-border-color-light);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
}

.news-card .news-list { display: flex; flex-direction: column; }

.flow-history-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
  font-size: 12px;
}

.flow-history-item:last-child { border-bottom: none; }
.flow-date { color: var(--el-text-color-secondary); width: 100px; }
.flow-change { font-weight: bold; width: 80px; text-align: right; }
.flow-inflow { width: 120px; text-align: right; }

.news-item {
  padding: 12px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  transition: all .2s ease;
}

.news-item:last-child { border-bottom: none; }
.news-item:hover {
  background: var(--el-fill-color-light);
  border-radius: 8px;
  transform: translateX(4px);
}

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

.facts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.fact {
  display: flex;
  flex-direction: column;
  font-size: 12px;
  padding: 10px;
  background: var(--el-fill-color-lighter);
  border-radius: 8px;
}

.fact b {
  font-size: 14px;
  color: var(--el-text-color-primary);
  font-weight: 600;
  margin-top: 4px;
}

.data-source-footer {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 12px;
  padding-top: 8px;
  border-top: 1px solid var(--el-border-color-lighter);
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  .source-sep { margin: 0 4px; }
}

.quick-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* 右侧栏卡片美化 */
.el-col:last-child .el-card {
  border-radius: 16px;
  border: 1px solid var(--el-border-color-light);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
}

/* 分析详情卡片美化 */
.analysis-detail-card {
  border-radius: 16px;
  border: 1px solid var(--el-border-color-light);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
}

.analysis-meta {
  display: flex;
  gap: 24px;
  margin-bottom: 16px;
  padding: 12px;
  background: var(--el-fill-color-lighter);
  border-radius: 8px;
}

.analysis-time, .confidence {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.report-link-section {
  display: flex;
  justify-content: flex-start;
}

/* 决策建议盒子 */
.decision-box {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 12px;
  padding: 16px 20px;
  box-shadow: 0 4px 16px rgba(102, 126, 234, 0.25);
}
.decision-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  color: rgba(255, 255, 255, 0.95);
  font-size: 15px;
  font-weight: 600;
}
.decision-icon { font-size: 18px; }
.decision-label { flex: 0 0 auto; }
.decision-text {
  background: rgba(255, 255, 255, 0.98);
  border-radius: 8px;
  padding: 12px 16px;
  color: #1f2937;
  font-size: 14px;
  line-height: 1.8;
  font-weight: 500;
  word-wrap: break-word;
  word-break: break-word;
  white-space: pre-wrap;
}

/* 短线/长线博弈评分 */
.score-section {
  padding: 14px;
  background: var(--el-fill-color-lighter);
  border-radius: 10px;
}
.score-section-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  margin-bottom: 12px;
}
.score-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}
.score-card {
  padding: 10px 12px;
  background: var(--el-bg-color);
  border-radius: 8px;
  border: 1px solid var(--el-border-color-lighter);
  cursor: pointer;
  transition: transform .2s ease, box-shadow .2s ease;
}
.score-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}
.score-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 6px;
}
.score-value {
  font-size: 22px;
  font-weight: 800;
  line-height: 1;
  margin-bottom: 6px;
}
.score-unit { font-size: 12px; font-weight: 500; color: var(--el-text-color-secondary); margin-left: 2px; }
.score-high .score-value { color: #ef4444; }
.score-mid .score-value { color: #f59e0b; }
.score-low .score-value { color: #10b981; }
.score-bar {
  height: 6px;
  border-radius: 3px;
  background: var(--el-fill-color);
  overflow: hidden;
}
.score-bar-fill { height: 100%; border-radius: 3px; }
.score-high .score-bar-fill { background: linear-gradient(90deg, #fdba74, #ef4444); }
.score-mid .score-bar-fill { background: linear-gradient(90deg, #fde68a, #f59e0b); }
.score-low .score-bar-fill { background: linear-gradient(90deg, #86efac, #10b981); }

/* 量价综合判断增强 */
.vp-overall-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 8px 0 6px;
}
.vp-meta-chip {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 12px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  color: var(--el-text-color-regular);
}
.vp-scenario-tag { margin-left: 4px; }
.vp-scenario-tag .help-icon-inline { margin-left: 4px; }

/* 板块联动卡片美化 */
.sector-card {
  border-radius: 16px;
  border: 1px solid var(--el-border-color-light);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
}

/* 资金流向卡片美化 */
.money-flow-card {
  border-radius: 16px;
  border: 1px solid var(--el-border-color-light);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
}

/* 风险扫描样式 */
.risk-scan-card {
  border-radius: 16px;
  border: 1px solid var(--el-border-color-light);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
}

/* 量价分析卡片样式 */
.volume-price-card {
  border-radius: 16px;
  border: 1px solid var(--el-border-color-light);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
}
/* 五步分析明细折叠 */
.vp-collapse {
  border: none;
  background: transparent;
}
.vp-collapse :deep(.el-collapse-item__header) {
  background: transparent;
  border-bottom: 1px solid var(--el-border-color-lighter);
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.vp-collapse :deep(.el-collapse-item__wrap) {
  background: transparent;
  border-bottom: none;
}
.vp-collapse-title {
  margin-right: 8px;
}
.vp-collapse-hint {
  font-weight: 400;
}
/* 三买三卖买卖点检查卡片 */
.tbs-check-card {
  border-radius: 16px;
  border: 1px solid var(--el-border-color-light);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
}
.tbs-overview {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.tbs-close {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-left: auto;
}
.tbs-stage-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-regular);
  margin-bottom: 8px;
}
.tbs-signal {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  margin-bottom: 8px;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
}
.tbs-signal-buy { border-left: 4px solid var(--el-color-danger); }
.tbs-signal-sell { border-left: 4px solid var(--el-color-success); }
.tbs-signal-s1 { border-left: 4px solid var(--el-color-warning); }
.tbs-signal-type {
  flex-shrink: 0;
  font-weight: 700;
  font-size: 13px;
  color: var(--el-color-primary);
}
.tbs-signal-label {
  flex-shrink: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.tbs-signal-desc {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}
/* 辅助检查点卡片 */
.checkpoint-card {
  border-radius: 16px;
  border: 1px solid var(--el-border-color-light);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
}
.cp-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 12px;
}
.cp-item {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
  padding: 12px 14px;
  background: var(--el-bg-color);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.03);
}
.cp-item.cp-level-confirm { border-left: 4px solid var(--el-color-danger); }
.cp-item.cp-level-warn { border-left: 4px solid var(--el-color-warning); }
.cp-item.cp-level-neutral { border-left: 4px solid var(--el-color-info); }
.cp-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}
.cp-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.cp-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-regular);
  margin-bottom: 4px;
}
.cp-detail {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}
.cp-warnings {
  margin-top: 14px;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--el-color-warning-light-9);
  border: 1px solid var(--el-color-warning-light-7);
}
.cp-warnings-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-color-warning-dark-2);
  margin-bottom: 6px;
}
.cp-warning {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 13px;
  color: var(--el-text-color-regular);
  line-height: 1.6;
}
.cp-warning-icon {
  flex-shrink: 0;
  margin-top: 2px;
  color: var(--el-color-warning);
}
/* 综合结论横幅 */
.vp-overall {
  border-radius: 12px;
  padding: 14px 16px;
  margin-bottom: 14px;
  border: 1px solid var(--el-border-color-lighter);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}
.vp-bias-bull { background: linear-gradient(135deg, var(--el-color-danger-light-9) 0%, var(--el-color-danger-light-8) 100%); border-color: var(--el-color-danger-light-5); }
.vp-bias-bear { background: linear-gradient(135deg, var(--el-color-success-light-9) 0%, var(--el-color-success-light-8) 100%); border-color: var(--el-color-success-light-5); }
.vp-bias-flat { background: linear-gradient(135deg, var(--el-fill-color-light) 0%, var(--el-bg-color) 100%); border-color: var(--el-border-color-lighter); }
.vp-overall-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.vp-overall-label {
  font-size: 15px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}
.vp-bias-tag {
  cursor: help;
  transition: transform .15s ease;
}
.vp-bias-tag:hover {
  transform: translateY(-1px);
}
/* 综合判断：当前状态 / 关键信号 结构化模块展示 */
.vp-block {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
  padding: 4px 0;
}
.vp-block + .vp-block {
  margin-top: 2px;
}
.vp-block-label {
  flex: 0 0 auto;
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
}
.vp-label-state { color: var(--el-color-primary); background: var(--el-color-primary-light-9); border-color: var(--el-color-primary-light-5); }
.vp-label-signal { color: var(--el-color-warning); background: var(--el-color-warning-light-9); border-color: var(--el-color-warning-light-5); }
.vp-block-text {
  flex: 1 1 auto;
  color: var(--el-text-color-regular);
}
/* 综合判断：方向预判 + 操作建议 醒目展示 */
.vp-overall-decision {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
}
.vp-overall.vp-bias-bull .vp-overall-decision { border-left: 4px solid var(--el-color-danger); }
.vp-overall.vp-bias-bear .vp-overall-decision { border-left: 4px solid var(--el-color-success); }
.vp-overall.vp-bias-flat .vp-overall-decision { border-left: 4px solid var(--el-color-info); }
.vp-direction, .vp-action {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 13px;
  line-height: 1.7;
}
.vp-decision-label {
  flex: 0 0 auto;
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  color: #fff;
  background: var(--el-color-primary);
}
.vp-overall.vp-bias-bull .vp-decision-label { background: var(--el-color-danger); }
.vp-overall.vp-bias-bear .vp-decision-label { background: var(--el-color-success); }
.vp-overall.vp-bias-flat .vp-decision-label { background: var(--el-color-info); }
.vp-decision-text {
  flex: 1 1 auto;
  color: var(--el-text-color-primary);
  font-weight: 500;
}
/* 综合判断依据悬浮提示 */
.vp-bias-tip {
  max-width: 320px;
  line-height: 1.6;
  font-size: 12px;
}
.vp-bias-basis {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed rgba(255, 255, 255, 0.3);
}
.vp-bias-basis-title {
  font-weight: 600;
  margin-bottom: 4px;
}
.vp-bias-basis-item {
  color: inherit;
  opacity: 0.92;
}
.vp-scenario-tip {
  max-width: 300px;
  line-height: 1.6;
  font-size: 12px;
}
/* OBV 辅助验证行 */
.vp-obv-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 10px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
  border-left: 3px solid var(--el-color-info);
}
.vp-obv-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
  margin-right: 2px;
}
.vp-overall-signals {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.vp-signal-chip {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 20px;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
}
.vp-signal-chip.chip-多 { color: var(--el-color-danger); border-color: var(--el-color-danger-light-5); background: var(--el-color-danger-light-9); }
.vp-signal-chip.chip-空 { color: var(--el-color-success); border-color: var(--el-color-success-light-5); background: var(--el-color-success-light-9); }
.vp-signal-chip.chip-中性 { color: var(--el-text-color-secondary); }
.vp-chart-wrap {
  margin-bottom: 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  padding: 6px;
}
.vp-chart {
  width: 100%;
  height: 320px;
}
.vp-steps {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.vp-step {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
  padding: 14px 16px;
  background: var(--el-bg-color);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.03);
  transition: box-shadow .2s ease, transform .2s ease;
}
.vp-step:hover {
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.07);
  transform: translateY(-1px);
}
.vp-step-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.vp-step-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--el-color-primary) 0%, var(--el-color-primary-light-5) 100%);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
  box-shadow: 0 2px 6px rgba(64, 158, 255, 0.3);
}
.vp-step-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.vp-step-body {
  margin-bottom: 8px;
}
.vp-conclusion {
  font-size: 13px;
  color: var(--el-text-color-regular);
  line-height: 1.7;
  padding: 10px 12px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
  border-left: 3px solid var(--el-color-primary);
}
.vp-quad-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}
.vp-quad-cell {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 10px;
  border-radius: 6px;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
  font-size: 13px;
}
.vp-quad-active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  font-weight: 600;
}
.vp-quad-name {
  color: var(--el-text-color-primary);
}
.vp-quad-cnt {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.vp-level-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 0;
  font-size: 13px;
  border-bottom: 1px dashed var(--el-border-color-lighter);
}
.vp-level-row:last-child {
  border-bottom: none;
}
.vp-level-name {
  font-weight: 600;
  color: var(--el-text-color-primary);
  min-width: 70px;
}
.vp-level-val {
  color: var(--el-text-color-regular);
  min-width: 70px;
}
.vp-level-note {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.vp-level-near {
  color: var(--el-color-warning);
  font-weight: 600;
}

.risk-score {
  font-size: 16px;
  font-weight: 700;
}

.risk-stat {
  font-size: 16px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  &.risk { color: #ef4444; }
  &.safe { color: #10b981; }
}

.risk-category {
  margin-bottom: 16px;
  padding: 12px;
  background: var(--el-fill-color-lighter);
  border-radius: 8px;
  &:last-child { margin-bottom: 0; }
}

.risk-category-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.risk-category-name {
  font-weight: 600;
  font-size: 14px;
  color: var(--el-text-color-primary);
}

.risk-category-count {
  display: flex;
  gap: 8px;
}

.risk-badge {
  padding: 2px 8px;
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
}

.safe-badge {
  padding: 2px 8px;
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
}

.risk-items {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.risk-item {
  display: flex;
  gap: 10px;
  padding: 10px;
  background: rgba(239, 68, 68, 0.05);
  border-radius: 6px;
}

.risk-icon {
  color: #ef4444;
  font-size: 16px;
  flex-shrink: 0;
  margin-top: 2px;
}

.risk-item-content {
  flex: 1;
}

.risk-item-name {
  font-weight: 600;
  font-size: 13px;
  color: #ef4444;
  margin-bottom: 4px;
}

.risk-item-reason {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}

.risk-sub-items {
  margin-top: 8px;
  padding-left: 8px;
  border-left: 2px solid var(--el-border-color-lighter);
}

.risk-sub-item {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
  &:last-child { margin-bottom: 0; }
}

.sub-risk-icon { color: #ef4444; font-size: 12px; }
.sub-safe-icon { color: #10b981; font-size: 12px; }

.sub-reason {
  margin-left: 4px;
  color: var(--el-text-color-placeholder);
}

.risk-no-items {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #10b981;
}

.safe-icon {
  color: #10b981;
  font-size: 16px;
}

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

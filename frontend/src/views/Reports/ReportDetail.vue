<template>
  <div class="report-detail">
    <!-- 加载状态 -->
    <div v-if="loading" class="loading-container">
      <el-skeleton :rows="10" animated />
    </div>

    <!-- 报告内容 -->
    <div v-else-if="report" class="report-content">
      <!-- 报告头部 -->
      <el-card class="report-header" shadow="never">
        <div class="header-content">
          <div class="title-section">
            <h1 class="report-title">
              <el-icon><Document /></el-icon>
              {{ report.stock_name || report.stock_symbol }} 分析报告
            </h1>
            <div class="report-meta">
              <el-tag type="primary">{{ report.stock_symbol }}</el-tag>
              <el-tag v-if="report.stock_name && report.stock_name !== report.stock_symbol" type="info">{{ report.stock_name }}</el-tag>
              <el-tag type="success">{{ getStatusText(report.status) }}</el-tag>
              <span class="meta-item">
                <el-icon><Calendar /></el-icon>
                分析时间：{{ formatTime(report.created_at) }}
              </span>
              <span v-if="report.execution_time && report.execution_time > 0" class="meta-item">
                <el-icon><Timer /></el-icon>
                耗时：{{ formatDuration(report.execution_time) }}
              </span>
              <span class="meta-item">
                <el-icon><User /></el-icon>
                {{ formatAnalysts(report.analysts) }}
              </span>
              <span v-if="report.model_info && report.model_info !== 'Unknown'" class="meta-item">
                <el-icon><Cpu /></el-icon>
                <el-tooltip :content="getModelDescription(report.model_info)" placement="top">
                  <el-tag type="info" style="cursor: help;">{{ report.model_info }}</el-tag>
                </el-tooltip>
              </span>
            </div>
          </div>
          
          <div class="action-section">
            <el-button
              v-if="canApplyToTrading"
              type="success"
              @click="applyToTrading"
            >
              <el-icon><ShoppingCart /></el-icon>
              应用到交易
            </el-button>
            <el-dropdown trigger="click" @command="downloadReport">
              <el-button type="primary">
                <el-icon><Download /></el-icon>
                下载报告
                <el-icon class="el-icon--right"><arrow-down /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="markdown">
                    <el-icon><document /></el-icon> Markdown
                  </el-dropdown-item>
                  <el-dropdown-item command="docx">
                    <el-icon><document /></el-icon> Word 文档
                  </el-dropdown-item>
                  <el-dropdown-item command="pdf">
                    <el-icon><document /></el-icon> PDF
                  </el-dropdown-item>
                  <el-dropdown-item command="json" divided>
                    <el-icon><document /></el-icon> JSON (原始数据)
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-button @click="goBack">
              <el-icon><Back /></el-icon>
              返回
            </el-button>
          </div>
        </div>
      </el-card>

      <!-- 报告模块 - 与单股分析页一致的卡片式布局，点击弹出全屏对话框 -->
      <div class="pipeline-intro report-pipeline-intro">
        <!-- 最终决策 -->
        <div v-if="hasReport('final_trade_decision')" class="final-decision">
          <div class="decision-label">📈 决策建议</div>
          <div class="decision-options">
            <div
              class="decision-chip decision-chip--buy"
              :class="{
                'is-active': getFinalAction() === '买入',
                'is-disabled': getFinalAction() && getFinalAction() !== '买入'
              }"
              @click="getFinalAction() === '买入' && openReportDialog('final_trade_decision')"
            >买入</div>
            <div
              class="decision-chip decision-chip--overweight"
              :class="{
                'is-active': getFinalAction() === '增持',
                'is-disabled': getFinalAction() && getFinalAction() !== '增持'
              }"
              @click="getFinalAction() === '增持' && openReportDialog('final_trade_decision')"
            >增持</div>
            <div
              class="decision-chip decision-chip--hold"
              :class="{
                'is-active': getFinalAction() === '持有',
                'is-disabled': getFinalAction() && getFinalAction() !== '持有'
              }"
              @click="getFinalAction() === '持有' && openReportDialog('final_trade_decision')"
            >持有</div>
            <div
              class="decision-chip decision-chip--underweight"
              :class="{
                'is-active': getFinalAction() === '减持',
                'is-disabled': getFinalAction() && getFinalAction() !== '减持'
              }"
              @click="getFinalAction() === '减持' && openReportDialog('final_trade_decision')"
            >减持</div>
            <div
              class="decision-chip decision-chip--sell"
              :class="{
                'is-active': getFinalAction() === '卖出',
                'is-disabled': getFinalAction() && getFinalAction() !== '卖出'
              }"
              @click="getFinalAction() === '卖出' && openReportDialog('final_trade_decision')"
            >卖出</div>
          </div>
        </div>

        <!-- 多维度评分 -->
        <div v-if="hasAnyDimensionScore" class="scores-confidence-row">
          <div class="pipeline-section section--scores">
            <div class="section-header">
              <h3>📊 多维度评分</h3>
              <p class="section-subtitle">7位分析师从不同维度综合评估股票，覆盖短线博弈到长线价值</p>
            </div>

            <!-- 短线博弈组 -->
            <div class="dimension-group">
              <div class="dimension-group-title">⚡ 短线博弈</div>
              <div class="dimension-grid">
                <el-tooltip
                  v-for="item in shortTermScores"
                  :key="item.field"
                  placement="top"
                  effect="dark"
                >
                  <template #content>
                    <div style="max-width: 250px; line-height: 1.6;">
                      <div style="font-weight: bold; margin-bottom: 6px;">{{ item.name }}评分 · {{ item.analyst }}</div>
                      <div style="font-size: 12px; opacity: 0.9;">{{ item.basis }}</div>
                      <div v-if="item.source_type" style="margin-top: 6px; font-size: 11px; opacity: 0.7;">
                        数据来源：{{ item.source_type === '明确评分' ? '分析师报告明确给出' : '基于报告倾向估算' }}
                      </div>
                    </div>
                  </template>
                  <div
                    class="dimension-card"
                    :class="getDimensionCardClass(item.field)"
                    @click="openDimensionReport(item)"
                  >
                    <div class="dimension-header">
                      <span class="dimension-icon">{{ getDimensionIcon(item.field) }}</span>
                      <span class="dimension-name">{{ item.name }}</span>
                    </div>
                    <div class="dimension-score">
                      <span class="score-value">{{ formatScore(item.score) }}</span>
                      <span class="score-unit">分</span>
                    </div>
                    <div class="score-bar">
                      <div class="score-bar-fill" :style="{ width: getScorePercent(item.score) + '%' }"></div>
                    </div>
                    <div class="dimension-analyst">{{ item.analyst }}</div>
                  </div>
                </el-tooltip>
              </div>
            </div>

            <!-- 长线价值组 -->
            <div class="dimension-group">
              <div class="dimension-group-title">💎 长线价值</div>
              <div class="dimension-grid">
                <el-tooltip
                  v-for="item in longTermScores"
                  :key="item.field"
                  placement="top"
                  effect="dark"
                >
                  <template #content>
                    <div style="max-width: 250px; line-height: 1.6;">
                      <div style="font-weight: bold; margin-bottom: 6px;">{{ item.name }}评分 · {{ item.analyst }}</div>
                      <div style="font-size: 12px; opacity: 0.9;">{{ item.basis }}</div>
                      <div v-if="item.source_type" style="margin-top: 6px; font-size: 11px; opacity: 0.7;">
                        数据来源：{{ item.source_type === '明确评分' ? '分析师报告明确给出' : '基于报告倾向估算' }}
                      </div>
                    </div>
                  </template>
                  <div
                    class="dimension-card"
                    :class="getDimensionCardClass(item.field)"
                    @click="openDimensionReport(item)"
                  >
                    <div class="dimension-header">
                      <span class="dimension-icon">{{ getDimensionIcon(item.field) }}</span>
                      <span class="dimension-name">{{ item.name }}</span>
                    </div>
                    <div class="dimension-score">
                      <span class="score-value">{{ formatScore(item.score) }}</span>
                      <span class="score-unit">分</span>
                    </div>
                    <div class="score-bar">
                      <div class="score-bar-fill" :style="{ width: getScorePercent(item.score) + '%' }"></div>
                    </div>
                    <div class="dimension-analyst">{{ item.analyst }}</div>
                  </div>
                </el-tooltip>
              </div>
            </div>
          </div>
        </div>

        <!-- 第二部分：辩论与决策流程 -->
        <div v-if="hasAnyDebateOrRiskReport" class="pipeline-section section--debate">
          <div class="section-header">
            <h3>⚔️ 多空辩论 · 三方风控 · 决策建议</h3>
            <p class="section-subtitle">研究团队通过对抗性辩论形成共识，风控团队从三个视角兜底，最终给出可操作的投资建议</p>
          </div>
          <div class="debate-timeline">
            <div v-if="hasReport('bull_researcher') || hasReport('bear_researcher') || hasReport('research_team_decision')" class="timeline-phase">
              <div class="phase-label">📋 研究辩论</div>
              <div class="phase-flow debate-flow">
                <!-- 第一行：看涨和看跌研究员并排辩论 -->
                <div class="debate-row">
                  <div
                    v-if="hasReport('bull_researcher')"
                    class="debate-node node--bull is-clickable"
                    @click="openReportDialog('bull_researcher')"
                  >
                    <div class="node-header">
                      <span class="node-icon">🐂</span>
                      <span class="node-name">看涨研究员</span>
                    </div>
                    <div class="node-keypoints">
                      <div v-for="(pt, i) in extractKeyPoints('bull_researcher', 3)" :key="i" class="keypoint">
                        <span class="kp-dot"></span>
                        <span class="kp-text">{{ pt }}</span>
                      </div>
                      <div v-if="extractKeyPoints('bull_researcher', 3).length === 0" class="node-desc">构建买入逻辑</div>
                    </div>
                  </div>
                  <div v-if="hasReport('bull_researcher') && hasReport('bear_researcher')" class="vs-divider">
                    <div class="vs-line"></div>
                    <div class="vs-badge">⚡ VS ⚡</div>
                    <div class="vs-line"></div>
                  </div>
                  <div
                    v-if="hasReport('bear_researcher')"
                    class="debate-node node--bear is-clickable"
                    @click="openReportDialog('bear_researcher')"
                  >
                    <div class="node-header">
                      <span class="node-icon">🐻</span>
                      <span class="node-name">看跌研究员</span>
                    </div>
                    <div class="node-keypoints">
                      <div v-for="(pt, i) in extractKeyPoints('bear_researcher', 3)" :key="i" class="keypoint">
                        <span class="kp-dot"></span>
                        <span class="kp-text">{{ pt }}</span>
                      </div>
                      <div v-if="extractKeyPoints('bear_researcher', 3).length === 0" class="node-desc">识别做空风险</div>
                    </div>
                  </div>
                </div>
                <!-- 综合↓箭头 -->
                <div v-if="(hasReport('bull_researcher') || hasReport('bear_researcher')) && hasReport('research_team_decision')" class="debate-arrow-down">
                  <div class="arrow-line"></div>
                  <div class="arrow-badge">
                    <div class="arrow-badge-text">综合辩论</div>
                    <div class="arrow-badge-icon">↓</div>
                  </div>
                </div>
                <!-- 第二行：研究经理综合 -->
                <div v-if="hasReport('research_team_decision')" class="debate-row debate-row--manager">
                  <div
                    class="debate-node node--manager is-clickable"
                    @click="openReportDialog('research_team_decision')"
                  >
                    <div class="node-header">
                      <span class="node-icon">👔</span>
                      <span class="node-name">研究经理</span>
                    </div>
                    <div class="node-keypoints">
                      <div v-for="(pt, i) in extractKeyPoints('research_team_decision', 3)" :key="i" class="keypoint">
                        <span class="kp-dot"></span>
                        <span class="kp-text">{{ pt }}</span>
                      </div>
                      <div v-if="extractKeyPoints('research_team_decision', 3).length === 0" class="node-desc">综合共识</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div v-if="hasReport('risky_analyst') || hasReport('neutral_analyst') || hasReport('safe_analyst') || hasReport('risk_control_decision') || hasReport('risk_management_decision')" class="timeline-phase">
              <div class="phase-label">🛡️ 三方风控</div>
              <div class="risk-perspectives">
                <div
                  class="risk-card risk-card--aggressive"
                  :class="{ 'is-clickable': hasReport('risky_analyst') }"
                  @click="hasReport('risky_analyst') && openReportDialog('risky_analyst')"
                >
                  <span class="risk-icon">🔥</span>
                  <span class="risk-name">激进风险</span>
                  <span class="risk-desc">高仓位 · 高杠杆 · 快进快出</span>
                </div>
                <div
                  class="risk-card risk-card--neutral"
                  :class="{ 'is-clickable': hasReport('neutral_analyst') }"
                  @click="hasReport('neutral_analyst') && openReportDialog('neutral_analyst')"
                >
                  <span class="risk-icon">⚖️</span>
                  <span class="risk-name">中性风险</span>
                  <span class="risk-desc">均衡仓位 · 标准止损 · 趋势跟随</span>
                </div>
                <div
                  class="risk-card risk-card--conservative"
                  :class="{ 'is-clickable': hasReport('safe_analyst') }"
                  @click="hasReport('safe_analyst') && openReportDialog('safe_analyst')"
                >
                  <span class="risk-icon">🛡️</span>
                  <span class="risk-name">保守风险</span>
                  <span class="risk-desc">轻仓 · 宽止损 · 长周期持有</span>
                </div>
              </div>
              <div
                v-if="hasReport('risk_control_decision')"
                class="risk-manager risk-constraint is-clickable"
                @click="openReportDialog('risk_control_decision')"
              >
                <span class="node-icon">📋</span>
                <span class="node-name">风控约束</span>
                <span class="node-desc">风控经理：最大仓位 · 止损位 · 最大可接受亏损</span>
              </div>
              <div
                v-if="hasReport('risk_management_decision') && !hasReport('risk_control_decision')"
                class="risk-manager is-clickable"
                @click="openReportDialog('risk_management_decision')"
              >
                <span class="node-icon">🎯</span>
                <span class="node-name">风险经理</span>
                <span class="node-desc">综合三方风控视角 → 止损位 / 仓位上限 / 持有周期</span>
              </div>
            </div>

            <div v-if="hasReport('trader_investment_plan') || hasReport('final_trade_decision')" class="timeline-phase phase--final-strategy">
              <div class="phase-label">📈 决策建议</div>
              <div class="phase-flow">
                <div
                  v-if="hasReport('trader_investment_plan')"
                  class="trade-node is-clickable"
                  @click="openReportDialog('trader_investment_plan')"
                >
                  <span class="node-icon">💼</span>
                  <span class="node-name">交易员</span>
                  <span class="node-desc">制定具体策略：买入 / 持有 / 卖出 + 目标价位 + 仓位建议</span>
                </div>
                <div v-if="!hasReport('trader_investment_plan') && hasReport('final_trade_decision')" class="trade-node is-clickable" @click="openReportDialog('final_trade_decision')">
                  <span class="node-icon">📈</span>
                  <span class="node-name">决策建议</span>
                  <span class="node-desc">决策建议与执行方案</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 风险扫描（位于置信度评估上方） -->
        <div v-if="riskScanData || riskScanLoading" class="pipeline-section section--risk-scan">
          <div class="section-header">
            <div class="risk-header-title">
              <el-icon class="risk-icon"><Warning /></el-icon>
              <h3>风险扫描</h3>
            </div>
            <span class="risk-source">数据源：{{ riskScanData?.source || '通达信' }}</span>
          </div>
          <el-skeleton v-if="riskScanLoading" :rows="6" animated />
          <div v-else-if="riskScanData" class="risk-content">
            <!-- 评分概览 -->
            <div class="risk-overview">
              <div class="score-ring">
                <svg viewBox="0 0 120 120" class="score-svg">
                  <circle cx="60" cy="60" r="50" fill="none" stroke="#e8eaed" stroke-width="10" />
                  <circle
                    cx="60" cy="60" r="50" fill="none"
                    :stroke="getRiskScoreColor(riskScanData.score)"
                    stroke-width="10"
                    stroke-linecap="round"
                    :stroke-dasharray="(riskScanData.score / 100) * 314 + ' 314'"
                    transform="rotate(-90 60 60)"
                  />
                </svg>
                <div class="score-text">
                  <div class="score-num" :style="{ color: getRiskScoreColor(riskScanData.score) }">
                    {{ riskScanData.score }}
                  </div>
                  <div class="score-label">综合评分</div>
                </div>
              </div>
              <div class="score-stats">
                <div class="stat-item">
                  <div class="stat-num">{{ riskScanData.total }}</div>
                  <div class="stat-label">总检查项</div>
                </div>
                <div class="stat-item">
                  <div class="stat-num risk">{{ riskScanData.risk_count || 0 }}</div>
                  <div class="stat-label">风险项</div>
                </div>
                <div class="stat-item">
                  <div class="stat-num safe">{{ riskScanData.safe_count || 0 }}</div>
                  <div class="stat-label">安全项</div>
                </div>
              </div>
            </div>

            <!-- 风险分类 -->
            <div class="risk-categories">
              <div v-for="(cat, idx) in riskScanData.categories" :key="idx" class="risk-category">
                <div class="cat-header">
                  <span class="cat-name">{{ cat.name }}</span>
                  <el-tag size="small" :type="cat.risk_count > 0 ? 'danger' : 'success'" effect="plain">
                    {{ cat.risk_count > 0 ? cat.risk_count + ' 项风险' : '全部安全' }}
                  </el-tag>
                </div>
                <div class="cat-items">
                  <!-- 风险项（可展开） -->
                  <div
                    v-for="item in cat.risk_items"
                    :key="'r-' + item.id"
                    class="risk-item is-risk"
                    :class="{ 'has-detail': hasRiskItemDetail(item), 'expanded': expandedRiskItems.has(item.id) }"
                    @click="hasRiskItemDetail(item) && toggleRiskItem(item.id)"
                  >
                    <div class="item-head">
                      <el-icon class="item-icon"><WarningFilled /></el-icon>
                      <span class="item-name">{{ item.name }}</span>
                      <el-tag v-if="item.score !== undefined" size="small" type="danger" effect="plain" class="item-score">
                        {{ item.score }}分
                      </el-tag>
                      <el-icon v-if="hasRiskItemDetail(item)" class="expand-icon">
                        <ArrowDown v-if="!expandedRiskItems.has(item.id)" />
                        <ArrowUp v-else />
                      </el-icon>
                    </div>
                    <div v-if="hasRiskItemDetail(item) && expandedRiskItems.has(item.id)" class="item-detail">
                      <div v-if="item.reason" class="item-reason">
                        <div class="reason-title">风险原因：</div>
                        <div class="reason-content">{{ item.reason }}</div>
                      </div>
                      <div v-if="item.sub_items && item.sub_items.length > 0" class="sub-items">
                        <div class="sub-title">检查细项（{{ item.sub_items.length }}项）：</div>
                        <div
                          v-for="sub in item.sub_items"
                          :key="sub.id"
                          class="sub-item"
                          :class="sub.trig ? 'is-risk' : 'is-safe'"
                        >
                          <el-icon class="sub-icon">
                            <WarningFilled v-if="sub.trig" />
                            <CircleCheckFilled v-else />
                          </el-icon>
                          <span class="sub-name">{{ sub.name }}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                  <!-- 安全项（折叠） -->
                  <div v-if="cat.safe_items && cat.safe_items.length > 0" class="safe-items-collapse">
                    <el-collapse>
                      <el-collapse-item title="安全项（全部通过）">
                        <div
                          v-for="item in cat.safe_items"
                          :key="'s-' + item.id"
                          class="risk-item is-safe"
                        >
                          <div class="item-head">
                            <el-icon class="item-icon"><CircleCheckFilled /></el-icon>
                            <span class="item-name">{{ item.name }}</span>
                          </div>
                        </div>
                      </el-collapse-item>
                    </el-collapse>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 置信度评估（移到页面最下端） -->
        <div v-if="hasConfidenceDetail" class="pipeline-section section--confidence">
          <div class="section-header">
            <h3>🎯 置信度评估</h3>
            <p class="section-subtitle">综合评估分析结果的可靠程度，涵盖数据质量、分析深度、逻辑一致性等维度</p>
          </div>
          <div class="confidence-content">
            <div class="confidence-total">
              <div class="confidence-total-score">
                <span class="total-score-value">{{ getConfidenceTotalPercent() }}</span>
                <span class="total-score-unit">%</span>
              </div>
              <div class="confidence-total-label" :style="{ color: getConfidenceColor(getConfidenceTotalPercent()) }">
                {{ getConfidenceLabel(getConfidenceTotalPercent()) }}
              </div>
            </div>
            <div class="confidence-detail-list">
              <!-- 非满分项：正常展示 -->
              <div
                v-for="(item, index) in getNonFullScoreItems()"
                :key="index"
                class="confidence-detail-item"
              >
                <div class="detail-item-header">
                  <span class="detail-item-name">{{ item.name }}</span>
                  <span class="detail-item-score">{{ item.score }}/{{ item.max_score }}</span>
                </div>
                <div class="detail-item-bar">
                  <div
                    class="detail-item-bar-fill"
                    :style="{
                      width: getConfidenceItemPercent(item) + '%',
                      background: getConfidenceGradient(getConfidenceItemPercent(item))
                    }"
                  ></div>
                </div>
                <div class="detail-item-desc">{{ item.description }}</div>
              </div>

              <!-- 满分项：折叠展示 -->
              <div v-if="getFullScoreItems().length > 0" class="full-score-collapse">
                <el-collapse>
                  <el-collapse-item>
                    <template #title>
                      <div class="collapse-title">
                        <el-icon><CircleCheckFilled /></el-icon>
                        <span>满分项（{{ getFullScoreItems().length }}项全部达标）</span>
                      </div>
                    </template>
                    <div
                      v-for="(item, index) in getFullScoreItems()"
                      :key="'full-' + index"
                      class="confidence-detail-item is-full-score"
                    >
                      <div class="detail-item-header">
                        <span class="detail-item-name">{{ item.name }}</span>
                        <span class="detail-item-score">{{ item.score }}/{{ item.max_score }}</span>
                      </div>
                      <div class="detail-item-bar">
                        <div
                          class="detail-item-bar-fill"
                          :style="{
                            width: '100%',
                            background: 'linear-gradient(90deg, #10b981, #34d399)'
                          }"
                        ></div>
                      </div>
                      <div class="detail-item-desc">{{ item.description }}</div>
                    </div>
                  </el-collapse-item>
                </el-collapse>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 错误状态 -->
    <div v-else class="error-container">
      <el-result
        icon="error"
        title="报告加载失败"
        sub-title="请检查报告ID是否正确或稍后重试"
      >
        <template #extra>
          <el-button type="primary" @click="goBack">返回列表</el-button>
        </template>
      </el-result>
    </div>

    <!-- 报告详情全屏弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      fullscreen
      :show-close="true"
      :close-on-click-modal="false"
      :before-close="beforeDialogClose"
      class="report-dialog"
    >
      <template #header>
        <div class="dialog-header">
          <div class="dialog-title">
            <span class="dialog-icon">{{ currentDialogReport?.icon }}</span>
            <span class="dialog-name">{{ currentDialogReport?.title }}</span>
          </div>
          <div class="dialog-description">{{ currentDialogReport?.description }}</div>
        </div>
      </template>
      <div class="dialog-content-wrapper">
        <div
          v-if="currentDialogReport?.content"
          class="dialog-report-content"
          v-html="renderMarkdown(typeof currentDialogReport.content === 'string' ? currentDialogReport.content : JSON.stringify(currentDialogReport.content, null, 2))"
        ></div>
        <div v-else class="dialog-no-content">
          <el-empty description="暂无内容" />
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, h, reactive, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, ElInputNumber } from 'element-plus'
import { paperApi } from '@/api/paper'
import { stocksApi } from '@/api/stocks'
import { configApi, type LLMConfig } from '@/api/config'
import {
  Document,
  Calendar,
  Timer,
  User,
  Download,
  Back,
  InfoFilled,
  TrendCharts,
  Files,
  ShoppingCart,
  WarningFilled,
  DataAnalysis,
  Warning,
  StarFilled,
  List,
  Check,
  Cpu,
  QuestionFilled,
  ArrowDown,
  ArrowUp,
  CircleCheckFilled,
  CaretBottom,
  CaretTop,
  Reading,
  MoreFilled
} from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { marked } from 'marked'
import { getMarketByStockCode } from '@/utils/market'
import type { CurrencyAmount } from '@/api/paper'

type ReportModuleContent = string | Record<string, unknown>

type ConfidenceDetailItem = {
  name: string
  score: number
  max_score: number
  description: string
}

type ReportDetailData = {
  id: string
  analysis_id?: string
  stock_symbol: string
  stock_name?: string
  status: string
  created_at: string
  analysis_date?: string
  analysts: string[]
  model_info?: string
  recommendation?: string
  risk_level?: string
  confidence_score?: number
  置信度?: number
  置信度详情?: ConfidenceDetailItem[]
  key_points?: string[]
  summary?: string
  reports: Record<string, ReportModuleContent>
}

// 路由和认证
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

// 配置 marked 以获得更完整的 Markdown 支持
marked.setOptions({ breaks: true, gfm: true })

// 响应式数据
const loading = ref(true)
const report = ref<ReportDetailData | null>(null)
const activeModule = ref('')
const llmConfigs = ref<LLMConfig[]>([]) // 存储所有模型配置
const reportModuleKeys = computed<string[]>(() => report.value ? Object.keys(report.value.reports || {}) : [])

// 风险扫描数据
const riskScanData = ref<any>(null)
const riskScanLoading = ref(false)
const expandedRiskItems = ref<Set<number>>(new Set())

// 风险评分颜色
const getRiskScoreColor = (score: number): string => {
  if (score >= 80) return '#10b068'
  if (score >= 60) return '#f09832'
  return '#ff4d4f'
}

// 检查风险项是否有详情
const hasRiskItemDetail = (item: any): boolean => {
  return (item.reason && item.reason.length > 0) || (item.sub_items && item.sub_items.length > 0)
}

// 展开/折叠风险项
const toggleRiskItem = (id: number) => {
  if (expandedRiskItems.value.has(id)) {
    expandedRiskItems.value.delete(id)
  } else {
    expandedRiskItems.value.add(id)
  }
}

// 弹窗相关
const dialogVisible = ref(false)
const currentDialogReport = ref<{ title: string; content: any; icon: string; description: string } | null>(null)

// 报告key到信息的映射
const reportKeyToInfo: Record<string, { title: string; icon: string; description: string }> = {
  final_trade_decision: { title: '决策建议', icon: '📈', description: '综合所有分析后的交易策略建议' },
  market_report: { title: '技术分析师', icon: '📈', description: '技术指标、均线/KDJ/MACD分析' },
  sentiment_report: { title: '市场情绪分析师', icon: '💭', description: '情绪量化、舆情热度、正负面比例' },
  hot_money_report: { title: '游资追踪师', icon: '💰', description: '主力资金、龙虎榜、北向资金' },
  lockup_report: { title: '解禁追踪师', icon: '🔒', description: '限售股解禁、大股东减持' },
  fundamentals_report: { title: '基本面分析师', icon: '💼', description: '财务数据、护城河、内在价值' },
  news_report: { title: '新闻分析师', icon: '📰', description: '公告研报、事件冲击分析' },
  policy_report: { title: '政策分析师', icon: '🏛️', description: '产业政策、宏观调控、监管动向' },
  bull_researcher: { title: '看涨研究员', icon: '🐂', description: '构建买入逻辑，挖掘投资亮点' },
  bear_researcher: { title: '看跌研究员', icon: '🐻', description: '识别做空风险，警示潜在雷点' },
  research_team_decision: { title: '研究经理', icon: '👔', description: '多空辩论综合，研究经理裁决' },
  trader_investment_plan: { title: '交易员', icon: '💼', description: '具体交易执行策略与仓位建议' },
  risky_analyst: { title: '激进风险', icon: '🔥', description: '高仓位、高杠杆、快进快出视角' },
  neutral_analyst: { title: '中性风险', icon: '⚖️', description: '均衡仓位、标准止损、趋势跟随' },
  safe_analyst: { title: '保守风险', icon: '🛡️', description: '轻仓、宽止损、长周期持有' },
  risk_control_decision: { title: '风控约束', icon: '📋', description: '最大仓位、止损位、最大可接受亏损' },
  risk_management_decision: { title: '风险经理', icon: '👔', description: '综合三方风控，输出止损位与仓位上限' },
  data_quality_summary: { title: '数据质量评估', icon: '📊', description: '评估各维度数据的完整性和可靠性' },
  quality_gate: { title: '数据质量门控', icon: '🚦', description: '数据质量校验与置信度评估' }
}

const normalizeAction = (text: string): string => {
  if (!text || typeof text !== 'string') return ''
  const lower = text.toLowerCase()
  
  if (lower.includes('sell') || lower.includes('卖出') || lower.includes('清仓') || lower.includes('离场')) return '卖出'
  if (lower.includes('underweight') || lower.includes('减持') || lower.includes('减配') || lower.includes('减仓')) return '减持'
  if (lower.includes('hold') || lower.includes('持有') || lower.includes('观望') || lower.includes('中性')) return '持有'
  if (lower.includes('overweight') || lower.includes('增持') || lower.includes('加仓') || lower.includes('增配')) return '增持'
  if (lower.includes('buy') || lower.includes('买入') || lower.includes('建仓') || lower.includes('配置')) return '买入'
  
  return ''
}

const translateReportContent = (content: string): string => {
  if (!content || typeof content !== 'string') return content
  
  const translations: [RegExp, string][] = [
    [/\bUnderweight\b/gi, '减持（Underweight）'],
    [/\bOverweight\b/gi, '增持（Overweight）'],
    [/\bHold\b/g, '持有（Hold）'],
    [/\bBuy\b/gi, '买入（Buy）'],
    [/\bSell\b/gi, '卖出（Sell）'],
    [/\bRating\b/gi, '评级'],
    [/\bAction\b/gi, '操作建议'],
    [/\bStop Loss\b/gi, '止损'],
    [/\bTake Profit\b/gi, '止盈'],
    [/\bPosition\b/gi, '仓位'],
    [/\bPortfolio\b/gi, '投资组合'],
    [/\bRisk\b/gi, '风险'],
    [/\bReturn\b/gi, '收益'],
    [/\bVolatility\b/gi, '波动率'],
    [/\bMomentum\b/gi, '动量'],
    [/\bTrend\b/gi, '趋势'],
    [/\bSupport\b/gi, '支撑位'],
    [/\bResistance\b/gi, '阻力位'],
    [/\bVolume\b/gi, '成交量'],
    [/\bPrice\b/gi, '价格'],
    [/FINAL TRANSACTION PROPOSAL/gi, '最终交易提案'],
  ]
  
  let result = content
  for (const [pattern, replacement] of translations) {
    result = result.replace(pattern, replacement)
  }
  
  return result
}

const getReportContentByKey = (key: string): any => {
  if (!report.value) return null
  return report.value.reports?.[key] || null
}

// 从报告内容中提取要点（用于卡片简要展示）
const extractKeyPoints = (key: string, maxPoints: number = 3): string[] => {
  const content = getReportContentByKey(key)
  if (!content || typeof content !== 'string') return []

  const points: string[] = []
  const lines = content.split('\n')

  for (const line of lines) {
    const trimmed = line.trim()
    // 匹配以 -、*、• 或数字开头的列表项
    if (/^[-*•]\s+/.test(trimmed) || /^\d+[.、)]\s+/.test(trimmed)) {
      let text = trimmed.replace(/^[-*•]\s+/, '').replace(/^\d+[.、)]\s+/, '')
      // 去掉 markdown 加粗等标记
      text = text.replace(/\*\*/g, '').replace(/__/g, '')
      // 截取前60个字符
      if (text.length > 60) text = text.substring(0, 60) + '...'
      if (text.length > 5) points.push(text)
    }
    if (points.length >= maxPoints) break
  }

  // 如果没有找到列表项，尝试取前几行的关键句
  if (points.length === 0) {
    for (const line of lines) {
      const trimmed = line.trim()
      if (trimmed.length > 15 && !trimmed.startsWith('#') && !trimmed.startsWith('|') && !trimmed.startsWith('```')) {
        let text = trimmed.replace(/\*\*/g, '').replace(/__/g, '')
        if (text.length > 60) text = text.substring(0, 60) + '...'
        points.push(text)
        if (points.length >= maxPoints) break
      }
    }
  }

  return points
}

let isClosingFromPopState = false

const openReportDialog = (key: string) => {
  const content = getReportContentByKey(key)
  const info = reportKeyToInfo[key]
  if (!info) {
    ElMessage.warning('暂不支持该报告')
    return
  }
  currentDialogReport.value = {
    title: info.title,
    content: translateReportContent(content),
    icon: info.icon,
    description: info.description
  }
  dialogVisible.value = true
  document.body.style.overflow = 'hidden'
  history.pushState({ dialogOpen: true, reportKey: key }, '')
}

const onPopState = () => {
  if (dialogVisible.value) {
    isClosingFromPopState = true
    dialogVisible.value = false
    currentDialogReport.value = null
    document.body.style.overflow = ''
    setTimeout(() => {
      isClosingFromPopState = false
    }, 0)
  }
}

const beforeDialogClose = () => {
  if (isClosingFromPopState) {
    return true
  }
  history.back()
  return false
}

const closeReportDialog = () => {
  if (isClosingFromPopState) {
    return
  }
  history.back()
}

const hasReport = (key: string): boolean => {
  return !!getReportContentByKey(key)
}

const getFinalAction = (): string => {
  if (!report.value) return ''
  if (report.value.action) {
    return normalizeAction(report.value.action)
  }
  if (report.value.决策建议) {
    return normalizeAction(report.value.决策建议)
  }
  const decision = report.value.reports?.final_trade_decision
  if (!decision) return ''
  if (typeof decision !== 'string') return ''

  const ratingPatterns = [
    /最终投资评级[：:]\s*(\S+)/,
    /投资评级[：:]\s*(\S+)/,
    /评级[：:]\s*(\S+)/,
    /Rating[：:]\s*(\S+)/,
    /最终决策[：:]\s*(\S+)/,
    /决策[：:]\s*(\S+)/,
    /最终评级[：:]\s*(\S+)/,
  ]
  for (const pattern of ratingPatterns) {
    const match = decision.match(pattern)
    if (match) {
      const action = normalizeAction(match[1])
      if (action) return action
    }
  }

  const lines = decision.split('\n')
  for (const line of lines) {
    if (line.includes('评级') || line.includes('决策') || line.includes('Rating') || line.includes('Action')) {
      const action = normalizeAction(line)
      if (action) return action
    }
  }

  const action = normalizeAction(decision)
  return action || ''
}

// 7位分析师的报告key映射
const analystReportMap = {
  '技术分析师': 'market_report',
  '市场情绪分析师': 'sentiment_report',  // 修正：与卡片显示名称一致
  '游资追踪师': 'hot_money_report',
  '解禁追踪师': 'lockup_report',
  '基本面分析师': 'fundamentals_report',
  '新闻分析师': 'news_report',
  '政策分析师': 'policy_report'
}

// 多空辩论与风控的报告key映射
const debateReportMap = {
  '看涨研究员': 'bull_researcher',
  '看跌研究员': 'bear_researcher',
  '研究经理': 'research_team_decision',
  '交易员': 'trader_investment_plan',
  '激进风险': 'risky_analyst',
  '中性风险': 'neutral_analyst',
  '保守风险': 'safe_analyst',
  '风控约束': 'risk_control_decision',
  '风险经理': 'risk_management_decision',
  '决策建议': 'final_trade_decision'
}

const hasAnyAnalystReport = computed(() => {
  return Object.values(analystReportMap).some(key => hasReport(key))
})

const hasAnyDebateOrRiskReport = computed(() => {
  return Object.values(debateReportMap).some(key => hasReport(key))
})

const dimensionScoreFields = ['技术面评分', '基本面评分', '情绪面评分', '消息面评分', '资金面评分', '政策面评分', '解禁面评分']

const dimensionIconMap: Record<string, string> = {
  '技术面评分': '📈',
  '基本面评分': '💼',
  '情绪面评分': '💬',
  '消息面评分': '📰',
  '资金面评分': '💰',
  '政策面评分': '🏛️',
  '解禁面评分': '🔒'
}

const dimensionClassMap: Record<string, string> = {
  '技术面评分': 'dimension--technical',
  '基本面评分': 'dimension--fundamental',
  '情绪面评分': 'dimension--sentiment',
  '消息面评分': 'dimension--news',
  '资金面评分': 'dimension--capital',
  '政策面评分': 'dimension--policy',
  '解禁面评分': 'dimension--lockup'
}

interface DimensionScoreItem {
  name: string
  field: string
  score: number
  max_score: number
  analyst: string
  basis: string
  source_type: string
}

const dimensionScoreList = computed((): DimensionScoreItem[] => {
  if (!report.value) return []
  const detail = (report.value as any)['维度评分详情']
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
  }
  const result: DimensionScoreItem[] = []
  const defaultBasis: Record<string, { analyst: string; basis: string }> = {
    '技术面评分': { analyst: '技术分析师', basis: '基于技术指标（均线、KDJ、MACD、RSI等）、趋势形态、量价关系等综合评估，满分100分。' },
    '基本面评分': { analyst: '基本面分析师', basis: '基于财务数据（营收、利润、ROE等）、行业地位、护城河、估值水平等综合评估，满分100分。' },
    '情绪面评分': { analyst: '市场情绪分析师', basis: '基于市场情绪指标、舆情热度、散户情绪逆向指标等综合评估，满分100分。' },
    '消息面评分': { analyst: '新闻分析师', basis: '基于公司公告、研报动态、新闻事件冲击、重要消息面影响等综合评估，满分100分。' },
    '资金面评分': { analyst: '游资追踪师', basis: '基于主力资金流向、龙虎榜数据、北向资金动向、机构持仓变化等综合评估，满分100分。' },
    '政策面评分': { analyst: '政策分析师', basis: '基于产业政策、宏观调控、监管动向、行业利好/利空政策等综合评估，满分100分。' },
    '解禁面评分': { analyst: '解禁追踪师', basis: '基于限售股解禁规模、大股东减持计划、解禁压力与市场承接能力等综合评估，满分100分。' }
  }
  for (const field of dimensionScoreFields) {
    const score = getDimensionScore(field)
    if (score !== null) {
      const info = defaultBasis[field] || { analyst: '分析师', basis: '' }
      result.push({
        name: field.replace('评分', ''),
        field,
        score,
        max_score: 100,
        analyst: info.analyst,
        basis: info.basis,
        source_type: '估算评分'
      })
    }
  }
  return result
})

const shortTermFields = ['技术面评分', '情绪面评分', '消息面评分', '资金面评分']
const longTermFields = ['基本面评分', '政策面评分', '解禁面评分']

const dimensionToReportMap: Record<string, string> = {
  '技术面评分': 'market_report',
  '情绪面评分': 'sentiment_report',
  '消息面评分': 'news_report',
  '资金面评分': 'hot_money_report',
  '基本面评分': 'fundamentals_report',
  '政策面评分': 'policy_report',
  '解禁面评分': 'lockup_report'
}

const shortTermScores = computed((): DimensionScoreItem[] => {
  return dimensionScoreList.value.filter(item => shortTermFields.includes(item.field))
})

const longTermScores = computed((): DimensionScoreItem[] => {
  return dimensionScoreList.value.filter(item => longTermFields.includes(item.field))
})

const openDimensionReport = (item: DimensionScoreItem) => {
  const reportKey = dimensionToReportMap[item.field]
  if (reportKey && hasReport(reportKey)) {
    openReportDialog(reportKey)
  } else {
    const info = reportKeyToInfo[reportKey] || { title: item.name + '分析师', icon: '📊', description: item.name + '维度分析' }
    currentDialogReport.value = {
      title: info.title,
      icon: info.icon,
      description: info.description,
      content: `# ${item.name}分析报告暂不可用\n\n> **状态**：该维度详细分析报告尚未生成\n\n---\n\n## 当前评分信息\n\n| 项目 | 内容 |\n| --- | --- |\n| **维度** | ${item.name} |\n| **评分** | ${item.score} / ${item.max_score} 分 |\n| **分析师** | ${item.analyst} |\n| **评分来源** | ${item.source_type === '明确评分' ? '分析师明确打分' : '综合估算值'} |\n\n---\n\n## 评分依据\n\n${item.basis || '暂无详细评分依据说明。'}\n\n---\n\n*提示：完整的${item.name}分析报告将在后续版本中逐步完善。当前评分为系统根据多维度数据综合估算得出，仅供参考。*`
    }
    dialogVisible.value = true
    document.body.style.overflow = 'hidden'
    history.pushState({ dialogOpen: true, reportKey: reportKey || item.field }, '')
  }
}

const getDimensionIcon = (field: string): string => {
  return dimensionIconMap[field] || '📊'
}

const getDimensionCardClass = (field: string): string => {
  return dimensionClassMap[field] || ''
}

const getDimensionScore = (field: string): number | null => {
  if (!report.value) return null
  const val = (report.value as any)[field]
  if (val === null || val === undefined || val === '') return null
  const num = Number(val)
  if (isNaN(num)) return null
  return num
}

const formatScore = (score: number | null): string => {
  if (score === null) return '暂无'
  if (Number.isInteger(score)) return score.toString()
  return score.toFixed(1)
}

const getScorePercent = (score: number | null): number => {
  if (score === null) return 0
  if (score <= 10) return (score / 10) * 100
  if (score <= 100) return score
  return 100
}

const hasAnyDimensionScore = computed(() => {
  return dimensionScoreList.value.length > 0
})

const getConfidenceTotalScore = (): number | null => {
  if (!report.value) return null
  const score = (report.value as any)['置信度'] ?? report.value.confidence_score
  if (score === null || score === undefined || score === '') return null
  const num = Number(score)
  if (isNaN(num)) return null
  return num
}

const getConfidenceDetailList = (): ConfidenceDetailItem[] => {
  if (!report.value) return []
  const detail = (report.value as any)['置信度详情']
  if (Array.isArray(detail)) return detail
  return []
}

// 获取满分项列表
const getFullScoreItems = (): ConfidenceDetailItem[] => {
  const items = getConfidenceDetailList()
  return items.filter(item => item.score === item.max_score)
}

// 获取非满分项列表
const getNonFullScoreItems = (): ConfidenceDetailItem[] => {
  const items = getConfidenceDetailList()
  return items.filter(item => item.score !== item.max_score)
}

const hasConfidenceDetail = computed(() => {
  const total = getConfidenceTotalScore()
  const detail = getConfidenceDetailList()
  return total !== null || detail.length > 0
})

const getConfidenceItemPercent = (item: ConfidenceDetailItem): number => {
  if (!item.max_score || item.max_score <= 0) return 0
  return Math.min(100, Math.max(0, (item.score / item.max_score) * 100))
}

const formatConfidenceScore = (score: number | null): string => {
  if (score === null) return '暂无'
  if (Number.isInteger(score)) return score.toString()
  return score.toFixed(1)
}

const getConfidenceTotalPercent = (): number => {
  const score = getConfidenceTotalScore()
  if (score === null) return 0
  if (score <= 1) return Math.round(score * 100)
  if (score <= 100) return Math.round(score)
  return 100
}

// 获取模型配置列表
const fetchLLMConfigs = async () => {
  try {
    const systemConfig = await configApi.getSystemConfig()
    llmConfigs.value = systemConfig.llm_configs || []
  } catch (error) {
    console.error('获取模型配置失败:', error)
  }
}

// 获取报告详情
const fetchReportDetail = async () => {
  loading.value = true
  try {
    const reportId = route.params.id as string

    const response = await fetch(`/api/reports/${reportId}/detail`, {
      headers: {
        'Authorization': `Bearer ${authStore.token}`,
        'Content-Type': 'application/json'
      }
    })

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }

    const result = await response.json()

    if (result.success) {
      report.value = result.data

      // 设置默认激活的模块
      const reports = result.data.reports || {}
      const moduleNames = Object.keys(reports)
      if (moduleNames.length > 0) {
        activeModule.value = moduleNames[0]
      }

      // 获取风险扫描数据（仅A股）
      const stockSymbol = result.data.stock_code || result.data.stock_symbol
      if (stockSymbol && /^\d{6}$/.test(stockSymbol)) {
        fetchRiskScan(stockSymbol).catch(() => {})
      }
    } else {
      throw new Error(result.message || '获取报告详情失败')
    }
  } catch (error) {
    console.error('获取报告详情失败:', error)
    ElMessage.error('获取报告详情失败')
  } finally {
    loading.value = false
  }
}

// 获取风险扫描数据
const fetchRiskScan = async (symbol: string) => {
  try {
    riskScanLoading.value = true
    const res = await stocksApi.getRiskAnalysis(symbol)
    if (res && (res as any).success && (res as any).data) {
      riskScanData.value = (res as any).data
    }
  } catch (e) {
    console.warn('获取风险扫描数据失败', e)
  } finally {
    riskScanLoading.value = false
  }
}

// 下载报告
const downloadReport = async (format: string = 'markdown') => {
  try {
    if (!report.value) return
    const currentReport = report.value

    // 显示加载提示
    const loadingMsg = ElMessage({
      message: `正在生成${getFormatName(format)}格式报告...`,
      type: 'info',
      duration: 0
    })

    const response = await fetch(`/api/reports/${currentReport.id}/download?format=${format}`, {
      headers: {
        'Authorization': `Bearer ${authStore.token}`
      }
    })

    loadingMsg.close()

    if (!response.ok) {
      const errorText = await response.text()
      throw new Error(errorText || `HTTP ${response.status}`)
    }

    const blob = await response.blob()
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url

    // 根据格式设置文件扩展名
    const ext = getFileExtension(format)
    a.download = `${currentReport.stock_symbol}_分析报告_${currentReport.analysis_date || currentReport.created_at}.${ext}`

    document.body.appendChild(a)
    a.click()
    window.URL.revokeObjectURL(url)
    document.body.removeChild(a)

    ElMessage.success(`${getFormatName(format)}报告下载成功`)
  } catch (error: any) {
    console.error('下载报告失败:', error)

    // 显示详细错误信息
    if (error.message && error.message.includes('pandoc')) {
      ElMessage.error({
        message: 'PDF/Word 导出需要安装 pandoc 工具',
        duration: 5000
      })
    } else {
      ElMessage.error(`下载报告失败: ${error.message || '未知错误'}`)
    }
  }
}

// 辅助函数：获取格式名称
const getFormatName = (format: string): string => {
  const names: Record<string, string> = {
    'markdown': 'Markdown',
    'docx': 'Word',
    'pdf': 'PDF',
    'json': 'JSON'
  }
  return names[format] || format
}

// 辅助函数：获取文件扩展名
const getFileExtension = (format: string): string => {
  const extensions: Record<string, string> = {
    'markdown': 'md',
    'docx': 'docx',
    'pdf': 'pdf',
    'json': 'json'
  }
  return extensions[format] || 'txt'
}

// 判断是否可以应用到交易
const canApplyToTrading = computed(() => {
  if (!report.value) return false
  const rec = report.value.recommendation || ''
  // 检查是否包含买入或卖出建议
  return rec.includes('买入') || rec.includes('卖出') || rec.toLowerCase().includes('buy') || rec.toLowerCase().includes('sell')
})

// 解析投资建议
const parseRecommendation = () => {
  if (!report.value) return null

  const rec = report.value.recommendation || ''
  const traderPlan = report.value.reports?.trader_investment_plan || ''

  // 解析操作类型
  let action: 'buy' | 'sell' | null = null
  if (rec.includes('买入') || rec.toLowerCase().includes('buy')) {
    action = 'buy'
  } else if (rec.includes('卖出') || rec.toLowerCase().includes('sell')) {
    action = 'sell'
  }

  if (!action) return null

  // 解析目标价格（从recommendation或trader_investment_plan中提取）
  let targetPrice: number | null = null
  const traderPlanText = typeof traderPlan === 'string' ? traderPlan : ''
  const priceMatch = rec.match(/目标价[格]?[：:]\s*([0-9.]+)/) ||
                     traderPlanText.match(/目标价[格]?[：:]\s*([0-9.]+)/)
  if (priceMatch) {
    targetPrice = parseFloat(priceMatch[1])
  }

  return {
    action,
    targetPrice,
    confidence: report.value.confidence_score || 0,
    riskLevel: report.value.risk_level || '中等'
  }
}

// 辅助函数：根据股票代码获取对应货币的现金金额
const getCashByCurrency = (account: any, stockSymbol: string): number => {
  const cash = account.cash

  // 兼容旧格式（单一数字）
  if (typeof cash === 'number') {
    return cash
  }

  // 新格式（多货币对象）
  if (typeof cash === 'object' && cash !== null) {
    // 根据股票代码判断市场类型
    const marketType = getMarketByStockCode(stockSymbol)

    // 映射市场类型到货币
    const currencyMap: Record<string, keyof CurrencyAmount> = {
      'A股': 'CNY',
      '港股': 'HKD',
      '美股': 'USD'
    }

    const currency = currencyMap[marketType] || 'CNY'
    return cash[currency] || 0
  }

  return 0
}

// 应用到模拟交易
const applyToTrading = async () => {
  const recommendation = parseRecommendation()
  if (!recommendation) {
    ElMessage.warning('无法解析投资建议，请检查报告内容')
    return
  }
  if (!report.value) return
  const currentReport = report.value

  try {
    // 获取账户信息
    const accountRes = await paperApi.getAccount()
    if (!accountRes.success || !accountRes.data) {
      ElMessage.error('获取账户信息失败')
      return
    }

    const account = accountRes.data.account
    const positions = accountRes.data.positions

    // 查找当前持仓
    const currentPosition = positions.find(p => p.code === currentReport.stock_symbol)

    // 获取当前实时价格
    let currentPrice = 10 // 默认价格
    try {
      const quoteRes = await stocksApi.getQuote(currentReport.stock_symbol)
      if (quoteRes.success && quoteRes.data && quoteRes.data.price) {
        currentPrice = quoteRes.data.price
      }
    } catch (error) {
      console.warn('获取实时价格失败，使用默认价格')
    }

    // 获取对应货币的可用资金
    const availableCash = getCashByCurrency(account, currentReport.stock_symbol)

    // 计算建议交易数量
    let suggestedQuantity = 0
    let maxQuantity = 0

    if (recommendation.action === 'buy') {
      // 买入：根据可用资金和当前价格计算
      maxQuantity = Math.floor(availableCash / currentPrice / 100) * 100 // 100股为单位
      const suggested = Math.floor(maxQuantity * 0.2) // 建议使用20%资金
      suggestedQuantity = Math.floor(suggested / 100) * 100 // 向下取整到100的倍数
      suggestedQuantity = Math.max(100, suggestedQuantity) // 至少100股
    } else {
      // 卖出：根据当前持仓计算
      if (!currentPosition || currentPosition.quantity === 0) {
        ElMessage.warning('当前没有持仓，无法卖出')
        return
      }
      maxQuantity = currentPosition.quantity
      suggestedQuantity = Math.floor(maxQuantity / 100) * 100 // 向下取整到100的倍数
      suggestedQuantity = Math.max(100, suggestedQuantity) // 至少100股
    }

    // 用户可修改的价格和数量（使用reactive）
    const tradeForm = reactive({
      price: currentPrice,
      quantity: suggestedQuantity
    })

    // 显示可编辑的确认对话框
    const actionText = recommendation.action === 'buy' ? '买入' : '卖出'
    const actionColor = recommendation.action === 'buy' ? '#67C23A' : '#F56C6C'

    // 创建一个响应式的消息组件
    const MessageComponent = {
      setup() {
        // 计算预计金额
        const estimatedAmount = computed(() => {
          return (tradeForm.price * tradeForm.quantity).toFixed(2)
        })

        return () => h('div', { style: 'line-height: 2;' }, [
          // 风险提示横幅
          h('div', {
            style: 'background-color: #FEF0F0; border: 1px solid #F56C6C; border-radius: 4px; padding: 12px; margin-bottom: 16px;'
          }, [
            h('div', { style: 'color: #F56C6C; font-weight: 600; margin-bottom: 8px; display: flex; align-items: center;' }, [
              h('span', { style: 'font-size: 16px; margin-right: 6px;' }, '⚠️'),
              h('span', '风险提示')
            ]),
            h('div', { style: 'color: #606266; font-size: 12px; line-height: 1.6;' }, [
              h('p', { style: 'margin: 4px 0;' }, '• 本交易基于AI分析结果，仅供参考，不构成投资建议'),
              h('p', { style: 'margin: 4px 0;' }, '• 模拟交易使用虚拟资金，与实盘存在显著差异'),
              h('p', { style: 'margin: 4px 0;' }, '• 股票投资存在市场风险，可能导致本金损失'),
              h('p', { style: 'margin: 4px 0;' }, '• 请勿将模拟结果作为实盘投资决策依据')
            ])
          ]),
          h('p', [
            h('strong', '股票代码：'),
            h('span', currentReport.stock_symbol)
          ]),
          h('p', [
            h('strong', '操作类型：'),
            h('span', { style: `color: ${actionColor}; font-weight: bold;` }, actionText)
          ]),
          recommendation.targetPrice ? h('p', [
            h('strong', '目标价格：'),
            h('span', { style: 'color: #E6A23C;' }, `${recommendation.targetPrice.toFixed(2)}元`),
            h('span', { style: 'color: #909399; font-size: 12px; margin-left: 8px;' }, '(仅供参考)')
          ]) : null,
          h('p', [
            h('strong', '当前价格：'),
            h('span', `${currentPrice.toFixed(2)}元`)
          ]),
          h('div', { style: 'margin: 16px 0;' }, [
            h('p', { style: 'margin-bottom: 8px;' }, [
              h('strong', '交易价格：'),
              h('span', { style: 'color: #909399; font-size: 12px; margin-left: 8px;' }, '(可修改)')
            ]),
            h(ElInputNumber, {
              modelValue: tradeForm.price,
              'onUpdate:modelValue': (val?: number) => { tradeForm.price = val ?? tradeForm.price },
              min: 0.01,
              max: 9999,
              precision: 2,
              step: 0.01,
              style: 'width: 200px;',
              controls: true
            })
          ]),
          h('div', { style: 'margin: 16px 0;' }, [
            h('p', { style: 'margin-bottom: 8px;' }, [
              h('strong', '交易数量：'),
              h('span', { style: 'color: #909399; font-size: 12px; margin-left: 8px;' }, '(可修改，100股为单位)')
            ]),
            h(ElInputNumber, {
              modelValue: tradeForm.quantity,
              'onUpdate:modelValue': (val?: number) => { tradeForm.quantity = val ?? tradeForm.quantity },
              min: 100,
              max: maxQuantity,
              step: 100,
              style: 'width: 200px;',
              controls: true
            })
          ]),
          h('p', [
            h('strong', '预计金额：'),
            h('span', { style: 'color: #409EFF; font-weight: bold;' }, `${estimatedAmount.value}元`)
          ]),
          h('p', [
            h('strong', '模型置信度：'),
            h('span', `${(recommendation.confidence * 100).toFixed(1)}%`),
            h('span', { style: 'color: #909399; font-size: 12px; margin-left: 8px;' }, '(不代表实际成功率)')
          ]),
          h('p', [
            h('strong', '风险评估：'),
            h('span', recommendation.riskLevel),
            h('span', { style: 'color: #909399; font-size: 12px; margin-left: 8px;' }, '(实际风险可能更高)')
          ]),
          recommendation.action === 'buy' ? h('p', { style: 'color: #909399; font-size: 12px; margin-top: 12px;' },
            `可用资金：${availableCash.toFixed(2)}元，最大可买：${maxQuantity}股`
          ) : null,
          recommendation.action === 'sell' ? h('p', { style: 'color: #909399; font-size: 12px; margin-top: 12px;' },
            `当前持仓：${maxQuantity}股`
          ) : null
        ])
      }
    }

    await ElMessageBox({
      title: '确认交易',
      message: h(MessageComponent),
      confirmButtonText: '确认下单',
      cancelButtonText: '取消',
      type: 'warning',
      beforeClose: (action, _instance, done) => {
        if (action === 'confirm') {
          // 验证输入
          if (tradeForm.quantity < 100 || tradeForm.quantity % 100 !== 0) {
            ElMessage.error('交易数量必须是100的整数倍')
            return
          }
          if (tradeForm.quantity > maxQuantity) {
            ElMessage.error(`交易数量不能超过${maxQuantity}股`)
            return
          }
          if (tradeForm.price <= 0) {
            ElMessage.error('交易价格必须大于0')
            return
          }

          // 检查资金是否充足
          if (recommendation.action === 'buy') {
            const totalAmount = tradeForm.price * tradeForm.quantity
            if (totalAmount > availableCash) {
              ElMessage.error('可用资金不足')
              return
            }
          }
        }
        done()
      }
    })

    // 执行交易
    const orderRes = await paperApi.placeOrder({
      code: currentReport.stock_symbol,
      side: recommendation.action,
      quantity: tradeForm.quantity,
      analysis_id: currentReport.analysis_id || currentReport.id
    })

    if (orderRes.success) {
      ElMessage.success(`${actionText}订单已提交成功！`)
      // 可选：跳转到模拟交易页面
      setTimeout(() => {
        router.push({ name: 'PaperTradingHome' })
      }, 1500)
    } else {
      ElMessage.error(orderRes.message || '下单失败')
    }

  } catch (error: any) {
    if (error !== 'cancel') {
      console.error('应用到交易失败:', error)
      ElMessage.error(error.message || '操作失败')
    }
  }
}

// 返回列表
const goBack = () => {
  if (window.history.length > 1) {
    router.back()
  } else {
    router.push('/reports')
  }
}

// 工具函数
const getStatusText = (status: string) => {
  const statusMap: Record<string, string> = {
    completed: '已完成',
    processing: '生成中',
    failed: '失败'
  }
  return statusMap[status] || status
}

const formatTime = (time: string) => {
  return new Date(time).toLocaleString('zh-CN')
}

const formatDuration = (seconds: number) => {
  if (!seconds || seconds <= 0) return '-'
  if (seconds < 60) return `${Math.round(seconds)}秒`
  if (seconds < 3600) {
    const mins = Math.floor(seconds / 60)
    const secs = Math.round(seconds % 60)
    return secs > 0 ? `${mins}分${secs}秒` : `${mins}分钟`
  }
  const hours = Math.floor(seconds / 3600)
  const mins = Math.round((seconds % 3600) / 60)
  return mins > 0 ? `${hours}小时${mins}分` : `${hours}小时`
}

// 将分析师英文名称转换为中文
const formatAnalysts = (analysts: string[]) => {
  const analystNameMap: Record<string, string> = {
    'market': '技术分析师',
    'fundamentals': '基本面分析师',
    'news': '新闻分析师',
    'social': '市场情绪分析师',
    'policy': '政策分析师',
    'hot_money': '游资追踪师',
    'lockup': '解禁追踪师'
  }

  return analysts.map(analyst => analystNameMap[analyst] || analyst).join('、')
}

// 获取模型的详细描述（从后端配置中获取）
const getModelDescription = (modelInfo: string) => {
  if (!modelInfo || modelInfo === 'Unknown') {
    return '未知模型'
  }

  // 1. 优先从后端配置中查找精确匹配
  const config = llmConfigs.value.find(c => c.model_name === modelInfo)
  if (config?.description) {
    return config.description
  }

  // 2. 尝试模糊匹配（处理版本号等变化）
  const fuzzyConfig = llmConfigs.value.find(c =>
    modelInfo.toLowerCase().includes(c.model_name.toLowerCase()) ||
    c.model_name.toLowerCase().includes(modelInfo.toLowerCase())
  )
  if (fuzzyConfig?.description) {
    return fuzzyConfig.description
  }

  // 3. 根据模型名称前缀提供通用描述
  const modelLower = modelInfo.toLowerCase()
  if (modelLower.includes('gpt')) {
    return `OpenAI ${modelInfo} - 强大的语言模型`
  } else if (modelLower.includes('claude')) {
    return `Anthropic ${modelInfo} - 高性能推理模型`
  } else if (modelLower.includes('qwen')) {
    return `阿里通义千问 ${modelInfo} - 中文优化模型`
  } else if (modelLower.includes('glm')) {
    return `智谱 ${modelInfo} - 综合性能优秀`
  } else if (modelLower.includes('deepseek')) {
    return `DeepSeek ${modelInfo} - 高性价比模型`
  } else if (modelLower.includes('ernie')) {
    return `百度文心 ${modelInfo} - 中文能力强`
  } else if (modelLower.includes('spark')) {
    return `讯飞星火 ${modelInfo} - 专业模型`
  } else if (modelLower.includes('moonshot')) {
    return `Moonshot ${modelInfo} - 长上下文模型`
  } else if (modelLower.includes('yi')) {
    return `零一万物 ${modelInfo} - 高性能模型`
  }

  // 4. 默认返回
  return `${modelInfo} - AI 大语言模型`
}

const getModuleDisplayName = (moduleName: string) => {
  // 统一与单股分析的中文标签映射
  const nameMap: Record<string, string> = {
    // 分析师团队 (7个)
    market_report: '📈 市场技术分析',
    sentiment_report: '💭 市场情绪分析',
    news_report: '📰 新闻事件分析',
    fundamentals_report: '💰 基本面分析',
    policy_report: '🏛️ 政策分析',
    hot_money_report: '💹 游资追踪分析',
    lockup_report: '🔒 限售解禁分析',

    // 研究团队 (3个)
    bull_researcher: '🐂 看涨研究员',
    bear_researcher: '🐻 看跌研究员',
    research_team_decision: '👔 研究经理决策',

    // 交易团队 (1个)
    trader_investment_plan: '💼 交易员投资计划',

    // 风险管理团队 (5个)
    risky_analyst: '🔥 激进风险分析',
    safe_analyst: '🛡️ 保守风险分析',
    neutral_analyst: '⚖️ 中性风险分析',
    risk_control_decision: '📋 风控约束决策',
    risk_management_decision: '👔 风险经理决策',

    // 最终决策 (1个)
    final_trade_decision: '🎯 决策建议',

    // 数据质量
    data_quality_summary: '📊 数据质量评估',
    quality_gate: '🚦 数据质量门控',

    // 兼容旧字段
    investment_plan: '📋 投资建议',
    investment_debate_state: '🔬 研究团队（旧）',
    risk_debate_state: '⚖️ 风险管理（旧）',
    detailed_analysis: '📄 详细分析'
  }
  return nameMap[moduleName] || moduleName
}

const renderMarkdown = (content: string) => {
  if (!content) return ''
  try {
    return String(marked.parse(content))
  } catch (e) {
    return `<pre style="white-space: pre-wrap; font-family: inherit;">${content}</pre>`
  }
}

// 专门用于 insight 卡片的内容渲染
// —— 把 AI 生成的中文段落转成清晰易读的 HTML（清洗 Markdown 杂项、分段、加粗）
const renderInsight = (text: string) => {
  if (!text) return '<span class="insight-empty">暂无数据</span>'

  let html = String(text)

  // 预处理 1：跳过分隔线行 (--, ===, --- 等整行)
  html = html.replace(/(^|\n)[\-=_]{2,}(\n|$)/g, '\n')

  // 预处理 2：移除表格行 (Markdown 表格语法: |...|)
  //           连续的表格行整段删除
  html = html.split('\n').map(line => {
    const trimmed = line.trim()
    if (trimmed.startsWith('|') || trimmed.startsWith('｜')) return ''
    // 表格的分隔线行: | --- | --- |
    if (/^\s*\|?\s*:?-+:?\s*\|/.test(line)) return ''
    return line
  }).join('\n')

  // 预处理 3：跳过纯图片/纯链接行
  html = html.split('\n').map(line => {
    const trimmed = line.trim()
    if (trimmed.startsWith('![') && trimmed.includes(']')) return ''
    if (/^https?:\/\/\S+$/.test(trimmed)) return ''
    return line
  }).join('\n')

  // 预处理 4：跳过开头的套话段落
  html = html.replace(/^[\s\S]{0,200}(好的|数据已获取|下面我将|开始分析|尊敬的)[^\n]*\n/, '')

  // 1. 转义 HTML（要在内容清洗之后做，避免破坏标签）
  html = html
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  // 2. 处理 **加粗**
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  // 3. 处理行内 `代码`
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>')

  // 4. 把 Markdown 标题 (### ## #) 转为加粗的段落小标题
  html = html.split('\n').map(line => {
    const m = line.match(/^#{1,6}\s+(.+)$/)
    if (m) {
      let title = m[1].trim()
      // 清理：去掉 "一、二、" "1. 2." 前缀
      title = title.replace(/^[一二三四五六七八九十][、\.]\s*/, '')
      title = title.replace(/^\d+[\.、]\s*/, '')
      // 清理 emoji 前缀
      title = title.replace(/^[\u{1F000}-\u{1FFFF}]\s*/u, '')
      return `\n\n<strong class="insight-subtitle">${title}</strong>\n\n`
    }
    return line
  }).join('\n')

  // 5. 如果文本没有换行，按中文句号分段
  if (!html.includes('\n')) {
    const sentences = html.split(/([。！？]+)/)
    const paragraphs: string[] = []
    let currentParagraph = ''

    for (let i = 0; i < sentences.length; i += 2) {
      const sentence = sentences[i] + (sentences[i + 1] || '')
      if (sentence.trim()) {
        currentParagraph += sentence
        if (currentParagraph.length > 100) {
          paragraphs.push(currentParagraph.trim())
          currentParagraph = ''
        }
      }
    }
    if (currentParagraph.trim()) {
      paragraphs.push(currentParagraph.trim())
    }
    html = paragraphs.join('\n\n')
  }

  // 6. 按行处理：智能识别段落 / 列表 / 小标题
  const lines = html.split(/\r?\n/)
  const result: string[] = []
  let inList = false
  let currentParagraph = ''

  for (let raw of lines) {
    const line = raw.trim()

    if (!line) {
      // 空行 - 段落分隔
      if (currentParagraph) {
        result.push(`<p class="insight-paragraph">${currentParagraph}</p>`)
        currentParagraph = ''
      }
      if (inList) {
        result.push('</ul>')
        inList = false
      }
      continue
    }

    // 识别小标题行（以 strong/strong 标签开头的）
    const strongMatch = line.match(/^<strong[^>]*>(.+?)<\/strong>/)
    if (strongMatch && line.length <= 80) {
      if (currentParagraph) {
        result.push(`<p class="insight-paragraph">${currentParagraph}</p>`)
        currentParagraph = ''
      }
      if (inList) {
        result.push('</ul>')
        inList = false
      }
      result.push(`<div class="insight-heading">${line}</div>`)
      continue
    }

    // 列表项：1. / 2. / • / - / —
    const listMatch = line.match(/^(\d+[\.、]\s*|[•\-—·]\s*)(.+)/)
    if (listMatch) {
      if (currentParagraph) {
        result.push(`<p class="insight-paragraph">${currentParagraph}</p>`)
        currentParagraph = ''
      }
      if (!inList) {
        result.push('<ul class="insight-list">')
        inList = true
      }
      result.push(`<li>${listMatch[2]}</li>`)
      continue
    }

    // 普通文本 - 累积到当前段落
    if (inList) {
      result.push('</ul>')
      inList = false
    }
    currentParagraph += (currentParagraph ? ' ' : '') + line
  }

  // 处理最后的剩余内容
  if (currentParagraph) {
    result.push(`<p class="insight-paragraph">${currentParagraph}</p>`)
  }
  if (inList) {
    result.push('</ul>')
  }

  return result.join('\n')
}

// 渲染完整洞察内容（用于 popover 显示）
const renderInsightFull = (text: string) => {
  if (!text) return '<span class="insight-empty">暂无数据</span>'
  
  // 使用 renderInsight 的逻辑，但不截断
  let html = String(text)
  
  // 预处理：跳过分隔线行
  html = html.replace(/(^|\n)[\-=_]{2,}(\n|$)/g, '\n')
  
  // 移除表格行
  html = html.split('\n').map(line => {
    const trimmed = line.trim()
    if (trimmed.startsWith('|') || trimmed.startsWith('｜')) return ''
    if (/^\s*\|?\s*:?-+:?\s*\|/.test(line)) return ''
    return line
  }).join('\n')
  
  // 跳过纯图片/纯链接行
  html = html.split('\n').map(line => {
    const trimmed = line.trim()
    if (trimmed.startsWith('![') && trimmed.includes(']')) return ''
    if (/^https?:\/\/\S+$/.test(trimmed)) return ''
    return line
  }).join('\n')
  
  // 跳过开头的套话段落
  html = html.replace(/^[\s\S]{0,200}(好的|数据已获取|下面我将|开始分析|尊敬的)[^\n]*\n/, '')
  
  // 转义 HTML
  html = html
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  
  // 处理 Markdown 加粗
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/__([^_]+)__/g, '<strong>$1</strong>')
  
  // 处理行内代码
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>')
  
  // 把 Markdown 标题转为加粗的段落小标题
  html = html.split('\n').map(line => {
    const m = line.match(/^#{1,6}\s+(.+)$/)
    if (m) {
      let title = m[1].trim()
      title = title.replace(/^[一二三四五六七八九十][、\.]\s*/, '')
      title = title.replace(/^\d+[\.、]\s*/, '')
      title = title.replace(/^[\u{1F000}-\u{1FFFF}]\s*/u, '')
      return `\n\n<div class="insight-heading-full">${title}</div>\n`
    }
    return line
  }).join('\n')
  
  // 按行处理：智能识别段落 / 列表
  const lines = html.split(/\r?\n/)
  const result: string[] = []
  let inList = false
  let currentParagraph = ''
  
  for (let raw of lines) {
    const line = raw.trim()
    
    if (!line) {
      if (currentParagraph) {
        result.push(`<p class="insight-paragraph-full">${currentParagraph}</p>`)
        currentParagraph = ''
      }
      if (inList) {
        result.push('</ul>')
        inList = false
      }
      continue
    }
    
    // 检查是否是列表项
    const listMatch = line.match(/^([\-\*\•]|\d+[\.、])\s+(.+)$/)
    if (listMatch) {
      if (currentParagraph) {
        result.push(`<p class="insight-paragraph-full">${currentParagraph}</p>`)
        currentParagraph = ''
      }
      if (!inList) {
        result.push('<ul class="insight-list-full">')
        inList = true
      }
      result.push(`<li>${listMatch[2]}</li>`)
      continue
    }
    
    // 普通文本 - 累积到当前段落
    if (inList) {
      result.push('</ul>')
      inList = false
    }
    currentParagraph += (currentParagraph ? ' ' : '') + line
  }
  
  // 处理最后的剩余内容
  if (currentParagraph) {
    result.push(`<p class="insight-paragraph-full">${currentParagraph}</p>`)
  }
  if (inList) {
    result.push('</ul>')
  }
  
  return result.join('\n')
}

// 置信度评分相关函数
// 将后端返回的 0-1 小数转换为 0-100 的百分制
const normalizeConfidenceScore = (score: number) => {
  // 如果已经是 0-100 的范围，直接返回
  if (score > 1) {
    return Math.round(score)
  }
  // 如果是 0-1 的小数，转换为百分制
  return Math.round(score * 100)
}

const getConfidenceColor = (score: number) => {
  if (score >= 80) return '#67C23A' // 较高 - 绿色
  if (score >= 60) return '#409EFF' // 中上 - 蓝色
  if (score >= 40) return '#E6A23C' // 中等 - 橙色
  return '#F56C6C' // 较低 - 红色
}

const getConfidenceLabel = (score: number) => {
  if (score >= 80) return '较高'
  if (score >= 60) return '中上'
  if (score >= 40) return '中等'
  return '较低'
}

const getConfidenceGradient = (score: number): string => {
  if (score >= 80) return 'linear-gradient(90deg, #52c41a, #67C23A)'
  if (score >= 60) return 'linear-gradient(90deg, #1890ff, #409EFF)'
  if (score >= 40) return 'linear-gradient(90deg, #fa8c16, #E6A23C)'
  return 'linear-gradient(90deg, #ff4d4f, #F56C6C)'
}

// 风险等级相关函数
const getRiskStars = (riskLevel: string) => {
  const riskMap: Record<string, number> = {
    '低': 1,
    '中低': 2,
    '中等': 3,
    '中高': 4,
    '高': 5
  }
  return riskMap[riskLevel] || 3
}

const getRiskColor = (riskLevel: string) => {
  const colorMap: Record<string, string> = {
    '低': '#67C23A',      // 绿色
    '中低': '#95D475',    // 浅绿色
    '中等': '#E6A23C',    // 橙色
    '中高': '#F56C6C',    // 红色
    '高': '#F56C6C'       // 深红色
  }
  return colorMap[riskLevel] || '#E6A23C'
}

// 工具函数：从 report 或其 decision / reports 子对象中取值
// —— 优先取 report 顶层（后端 extract_structured_fields 已经处理好了）
// —— 取不到时，直接从对应模块的文本中截取
const pickField = (report: any, candidates: string[], maxChars: number = 1200): any => {
  if (!report) return null

  // 1) 先在顶层 / decision / reports 中找精确字段名
  const directSources = [report, report.decision || {}, report.reports || {}]
  for (const src of directSources) {
    if (!src || typeof src !== 'object') continue
    for (const key of candidates) {
      const v = src[key]
      if (v !== null && v !== undefined && v !== '' && v !== 'None') {
        return v
      }
    }
  }

  // 2) 在 reports 所有文本型模块中搜索"章节标题"匹配
  const moduleMap = report.reports || {}
  const moduleTexts = Object.values(moduleMap).filter(v => typeof v === 'string')
  for (const moduleText of moduleTexts) {
    for (const key of candidates) {
      try {
        const re = new RegExp(
          '(?:^|\\n)[#*_]*\\s*(?:\\d+[.、]\\s*)?' + key.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&') +
          '[*_]*\\s*[:：]?\\s*(?:\\n|[:：])?\\s*([\\s\\S]{0,' + maxChars + '}?)(?=\\n\\s*#+|\\n\\s*\\n|$)',
        )
        const m = moduleText.match(re)
        if (m && m[1] && m[1].trim()) {
          return m[1].trim().substring(0, maxChars)
        }
      } catch (e) {
        continue
      }
    }
  }

  // 3) 终极回退：从对应模块直接截取内容（最保险）
  // 注意：每个字段使用不同的优先模块，避免重复
  const fallbackMap: { [key: string]: string[] } = {
    '核心洞察': ['final_trade_decision', 'research_team_decision'],
    '投资逻辑': ['investment_plan', 'trader_investment_plan', 'bull_researcher', 'bear_researcher'],
    '趋势预测': ['market_report', 'trader_investment_plan'],
    '策略点位': ['trader_investment_plan', 'investment_plan'],
    '情绪分析': ['sentiment_report', 'news_report', 'hot_money_report'],
    '市场情绪': ['sentiment_report', 'news_report', 'hot_money_report'],
    '舆情分析': ['sentiment_report', 'news_report'],
    '情绪面分析': ['sentiment_report', 'news_report'],
    '风险提示': ['risk_management_decision', 'risky_analyst', 'safe_analyst', 'neutral_analyst'],
  }

  const smartTruncate = (text: string, limit: number): string => {
    if (!text) return ''
    // 第一步：逐行清洗
    const skipList = ['数据已获取', '下面我将', '分析报告', '分析时段', '参考日期', '报告', '总结如下']
    const rawLines = text.trim().split('\n')
    const cleanedLines: string[] = []
    for (const ln of rawLines) {
      const stripped = ln.trim()
      if (!stripped) continue
      // 跳过分隔线
      if (/^[-=_]{2,}$/.test(stripped)) continue
      // 跳过表格行
      if (stripped.startsWith('|') || stripped.startsWith('｜')) continue
      // 跳过 markdown 标题
      if (/^#{1,6}\s+/.test(stripped)) continue
      // 跳过套话行
      let skipLine = false
      for (const pat of skipList) {
        if (stripped.includes(pat) && stripped.length < 120) {
          skipLine = true
          break
        }
      }
      if (skipLine) continue
      // 移除 **/emoji/列表标记
      let cleaned = stripped
        .replace(/\*+/g, '')
        .replace(/^[\u{1F000}-\u{1FFFF}]\s*/u, '')
        .replace(/^(\d+[\.、]\s*|[•\-—·]\s*)/, '')
        .trim()
      if (cleaned.length < 8 && !/[。！？：]/.test(cleaned)) continue
      cleanedLines.push(cleaned)
    }

    // 第二步：合并成段落
    const paragraph = cleanedLines.join(' ')
      .replace(/\s{2,}/g, ' ').trim()

    if (paragraph.length <= limit) return paragraph

    // 第三步：句子级挑选（短限制 = 更激进）
    if (limit <= 350) {
      // 拆分成句子
      const parts = paragraph.split(/([。！？；])/)
      const sentences: string[] = []
      for (let i = 0; i < parts.length - 1; i += 2) {
        const sent = (parts[i] + parts[i + 1]).trim()
        if (sent.length >= 10) sentences.push(sent)
      }
      // 处理最后一句（无标点）
      if (parts.length % 2 === 1 && parts[parts.length - 1].trim().length >= 10) {
        sentences.push(parts[parts.length - 1].trim())
      }
      if (sentences.length === 0) {
        // 没有句号，按字符截断
        return paragraph.substring(0, limit)
      }
      // 评分 + 挑选
      const highValueKws = ['结论', '核心', '总结', '主要', '建议', '看好', '买入', '卖出',
        '评级', '预测', '趋势', '风险', '关键', '显著', '拐点', '确立', '利好', '利空',
        '正面', '负面', '机会', '信号', '逻辑', '重点']
      const scored = sentences.map((s, idx) => {
        let score = 0
        for (const kw of highValueKws) if (s.includes(kw)) score += 10
        score += Math.max(0, 10 - idx) // 靠前加分
        if (s.length < 12) score -= 5
        return { score, sent: s, idx }
      })
      // 按评分挑选句子，保持原顺序
      scored.sort((a, b) => b.score - a.score)
      const selected: number[] = []
      let total = 0
      for (const item of scored) {
        if (total + item.sent.length <= limit) {
          selected.push(item.idx)
          total += item.sent.length
          if (total >= limit - 20) break
        }
      }
      if (selected.length < 2) {
        // 不足2句，按顺序补充
        for (let i = 0; i < sentences.length; i++) {
          if (selected.includes(i)) continue
          if (total + sentences[i].length <= limit) {
            selected.push(i)
            total += sentences[i].length
            if (selected.length >= 3) break
          }
        }
      }
      selected.sort((a, b) => a - b)
      const resultText = selected.map(i => sentences[i]).join('')
      if (resultText.length > limit) {
        const pos = resultText.lastIndexOf('。', limit)
        if (pos > limit / 2) return resultText.substring(0, pos + 1)
        return resultText.substring(0, limit)
      }
      return resultText
    }

    // 长限制：保留段落，在句号处截断
    const pos = paragraph.lastIndexOf('。', limit)
    if (pos > limit / 2) return paragraph.substring(0, pos + 1)
    return paragraph.substring(0, limit)
  }

  for (const key of candidates) {
    const moduleKeys = fallbackMap[key]
    if (!moduleKeys) continue
    for (const mk of moduleKeys) {
      const text = moduleMap[mk]
      if (typeof text === 'string' && text.trim()) {
        return smartTruncate(text, maxChars)
      }
    }
  }

  // 4) 最后兜底：从所有模块中找第一个有内容的
  for (const v of Object.values(moduleMap)) {
    if (typeof v === 'string' && v.trim() && v.trim().length > 20) {
      return smartTruncate(v, Math.min(maxChars, 500))
    }
  }

  return null
}

const formatPriceValue = (report: any, candidates: string[]): string => {
  const val = pickField(report, candidates)
  if (val === null || val === undefined || val === '') return '--'
  
  let num: number | null = null
  
  if (typeof val === 'number') {
    num = val
  } else if (typeof val === 'string') {
    const cleaned = val.replace(/[¥$￥,，]/g, '').trim()
    const match = cleaned.match(/^\s*(\d+(\.\d+)?)\s*$/)
    if (match) {
      num = parseFloat(match[1])
    } else {
      const found = cleaned.match(/(\d+(\.\d+)?)/)
      if (found) {
        num = parseFloat(found[1])
      }
    }
  }
  
  if (num !== null && !isNaN(num)) {
    return num.toFixed(2)
  }
  return '--'
}

const formatPct = (val: any): string => {
  if (val === null || val === undefined || val === '') return '0'
  const num = Number(val)
  if (isNaN(num)) return String(val)
  if (num <= 1) return Math.round(num * 100).toString()
  return Math.round(num).toString()
}

// 判断当前操作建议是否为卖出类（卖出/减仓），此时策略点位无意义
const isSellAction = computed(() => {
  const action = pickField(report.value, ['评级', 'action', '操作建议'])
  if (!action) return false
  return action.includes('卖出') || action.includes('减仓')
})

// 根据评级/操作建议决定标签颜色
const getDecisionActionTagType = (action: string): 'primary' | 'success' | 'warning' | 'info' | 'danger' => {
  if (!action) return 'info'
  const map: Record<string, 'primary' | 'success' | 'warning' | 'info' | 'danger'> = {
    '强烈买入': 'success',
    '买入': 'success',
    '持有': 'warning',
    '观望': 'info',
    '减仓': 'danger',
    '卖出': 'danger',
  }
  for (const k of Object.keys(map)) {
    if (action.includes(k)) return map[k]
  }
  return 'info'
}

watch(
  () => route.params.id,
  async () => {
    report.value = null
    activeModule.value = ''
    await fetchLLMConfigs()
    await fetchReportDetail()
  },
  { immediate: true }
)

onMounted(() => {
  window.addEventListener('popstate', onPopState)
})

onBeforeUnmount(() => {
  window.removeEventListener('popstate', onPopState)
  document.body.style.overflow = ''
  if (dialogVisible.value) {
    history.back()
  }
})
</script>

<style lang="scss" scoped>
.report-detail {
  min-height: 100vh;
  background: var(--el-bg-color-page);
  padding: 24px;

  .loading-container {
    padding: 24px;
  }

  .report-content {
    .report-header {
      margin-bottom: 28px;
      border-radius: 16px;
      border: 1px solid #e2e8f0;
      background: linear-gradient(135deg, #fafbfc 0%, #f8fafc 100%);
      box-shadow: 0 4px 16px rgba(15, 23, 42, 0.04);

      :deep(.el-card__body) {
        background: transparent;
      }

      html.dark & {
        background: linear-gradient(135deg, #1e293b 0%, #1c1917 100%);
        border-color: #334155;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);

        .report-title {
          color: #f8fafc;

          .el-icon {
            color: #60a5fa;
          }
        }

        .meta-item {
          color: #94a3b8;

          .el-icon {
            color: #64748b;
          }
        }
      }

      .header-content {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 24px;

        @media (max-width: 640px) {
          flex-direction: column;
        }

        .title-section {
          flex: 1;
          min-width: 0;

          .report-title {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 26px;
            font-weight: 800;
            color: #0f172a;
            margin: 0 0 14px 0;
            letter-spacing: -0.3px;

            .el-icon {
              font-size: 28px;
              color: #3b82f6;
            }
          }

          .report-meta {
            display: flex;
            align-items: center;
            gap: 16px;
            flex-wrap: wrap;

            .meta-item {
              display: flex;
              align-items: center;
              gap: 6px;
              color: #475569;
              font-size: 14px;
              font-weight: 500;

              .el-icon {
                font-size: 16px;
                color: #64748b;
              }
            }
          }
        }

        .action-section {
          display: flex;
          gap: 12px;
          flex-shrink: 0;

          @media (max-width: 640px) {
            width: 100%;
            justify-content: flex-start;
          }
        }
      }
    }

    /* 风险提示样式 */
    .risk-disclaimer {
      margin-bottom: 24px;
      animation: fadeInDown 0.5s ease-out;
    }

    .risk-disclaimer :deep(.el-alert) {
      background: linear-gradient(135deg, #fff3cd 0%, #ffe69c 100%);
      border: 2px solid #ffc107;
      border-radius: 12px;
      padding: 16px 20px;
      box-shadow: 0 4px 12px rgba(255, 193, 7, 0.2);
    }

    .risk-disclaimer :deep(.el-alert__icon) {
      font-size: 24px;
      color: #ff6b00;
    }

    .disclaimer-content {
      display: flex;
      align-items: center;
      gap: 12px;
      font-size: 15px;
      line-height: 1.6;
    }

    .disclaimer-icon {
      font-size: 24px;
      color: #ff6b00;
      flex-shrink: 0;
      animation: pulse 2s ease-in-out infinite;
    }

    .disclaimer-text {
      color: #856404;
      flex: 1;
    }

    .disclaimer-text strong {
      color: #d63031;
      font-size: 16px;
      font-weight: 700;
    }

    @keyframes pulse {
      0%, 100% {
        transform: scale(1);
        opacity: 1;
      }
      50% {
        transform: scale(1.1);
        opacity: 0.8;
      }
    }

    @keyframes fadeInDown {
      from {
        opacity: 0;
        transform: translateY(-20px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }

    .summary-card,
    .strategy-card,
    .metrics-card,
    .modules-card {
      margin-bottom: 24px;
      border-radius: 16px;
      border: 1px solid #e2e8f0;
      box-shadow: 0 4px 16px rgba(15, 23, 42, 0.06);
      transition: all 0.3s ease;

      &:hover {
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.1);
        transform: translateY(-2px);
      }

      .card-header {
        display: flex;
        align-items: center;
        gap: 10px;
        font-size: 18px;
        font-weight: 700;
        color: #0f172a;
        margin-bottom: 16px;
        padding-bottom: 12px;
        border-bottom: 1px solid #f1f5f9;

        .header-tip {
          font-size: 12.5px;
          font-weight: 400;
          color: #9ca3af;
          margin-left: auto;
        }
      }
    }

    /* daily_stock_analysis 风格的策略点位卡片 */
    .strategy-card {
      .strategy-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 16px;
        margin-bottom: 20px;

        @media (max-width: 768px) {
          grid-template-columns: repeat(2, 1fr);
        }
      }

      .price-block {
        padding: 16px;
        border-radius: 10px;
        text-align: center;
        border: 1px solid var(--el-border-color-lighter);
        background: var(--el-fill-color-light);

        &.buy-block { background: linear-gradient(135deg, rgba(232, 245, 233, 0.6) 0%, rgba(187, 247, 208, 0.3) 100%); border-color: #a5d6a7; }
        &.add-block { background: linear-gradient(135deg, rgba(225, 245, 254, 0.6) 0%, rgba(186, 230, 253, 0.3) 100%); border-color: #81d4fa; }
        &.stop-block { background: linear-gradient(135deg, rgba(254, 226, 226, 0.6) 0%, rgba(252, 165, 165, 0.3) 100%); border-color: #ef9a9a; }
        &.target-block { background: linear-gradient(135deg, rgba(255, 243, 224, 0.6) 0%, rgba(255, 213, 128, 0.3) 100%); border-color: #ffb74d; }
        &.support-block { background: linear-gradient(135deg, rgba(237, 231, 246, 0.6) 0%, rgba(206, 188, 228, 0.3) 100%); border-color: #b39ddb; }
        &.resistance-block { background: linear-gradient(135deg, rgba(255, 235, 238, 0.6) 0%, rgba(244, 194, 194, 0.3) 100%); border-color: #e57373; }
      }

      .price-label {
        font-size: 13px;
        color: var(--el-text-color-regular);
        font-weight: 500;
        margin-bottom: 8px;
      }

      .price-value {
        font-size: 22px;
        font-weight: 700;
        color: var(--el-text-color-primary);
        margin-bottom: 4px;
        letter-spacing: 0.5px;
      }

      .price-sub {
        font-size: 12px;
        color: var(--el-text-color-secondary);
      }

      /* ========== 核心洞察 & 多维度评分 公共区块标题 */
      .block-title {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 16px;
        padding-bottom: 14px;
        border-bottom: 1px solid var(--el-border-color-lighter);

        .block-title-text {
          font-size: 17px;
          font-weight: 700;
          color: #111827;
          letter-spacing: 0.3px;
        }

        .help-icon {
          color: #9ca3af;
          cursor: help;
          margin-left: 4px;
        }
      }

      /* ========== 区块内卡片图标与颜色统一 */
      .dimension-card .dimension-icon {
        text-align: center;
      }
    }

    .summary-content {
      line-height: 1.6;
      color: var(--el-text-color-primary);
    }

    .metrics-content {
      .metric-item {
        text-align: center;
        padding: 24px;
        border: 1px solid var(--el-border-color-light);
        border-radius: 12px;
        background: var(--el-fill-color-blank);
        transition: all 0.3s ease;

        &:hover {
          box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
          transform: translateY(-2px);
        }

        .metric-label {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          font-size: 15px;
          font-weight: 500;
          color: var(--el-text-color-regular);
          margin-bottom: 16px;

          .el-icon {
            font-size: 18px;
          }
        }

        .metric-value {
          font-size: 18px;
          font-weight: 600;
          color: var(--el-color-primary);
        }

        .recommendation-value {
          font-size: 16px;
          line-height: 1.6;
          color: var(--el-text-color-primary);
        }
      }

      // 置信度评分样式
      .confidence-item {
        .confidence-display {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 12px;

          .el-progress {
            margin-bottom: 8px;
          }

          .confidence-text {
            display: flex;
            flex-direction: column;
            align-items: center;
            line-height: 1;

            .confidence-number {
              font-size: 32px;
              font-weight: 700;
            }

            .confidence-unit {
              font-size: 14px;
              margin-top: 4px;
              opacity: 0.8;
            }
          }

          .confidence-label {
            font-size: 16px;
            font-weight: 600;
            color: var(--el-text-color-primary);
          }
        }
      }

      // 风险等级样式
      .risk-item {
        .risk-display {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 12px;

          .risk-stars {
            display: flex;
            gap: 8px;
            font-size: 28px;

            .star-icon {
              color: #DCDFE6;
              transition: all 0.3s ease;

              &.active {
                color: #F7BA2A;
                animation: starPulse 0.6s ease-in-out;
              }
            }
          }

          .risk-label {
            font-size: 18px;
            font-weight: 700;
            margin-top: 4px;
          }

          .risk-description {
            font-size: 13px;
            color: var(--el-text-color-secondary);
            text-align: center;
            line-height: 1.4;
            max-width: 200px;
          }
        }
      }

      .key-points {
        margin-top: 32px;
        padding-top: 24px;
        border-top: 1px solid var(--el-border-color-lighter);

        h4 {
          display: flex;
          align-items: center;
          gap: 8px;
          margin: 0 0 16px 0;
          font-size: 16px;
          font-weight: 600;
          color: var(--el-text-color-primary);

          .el-icon {
            font-size: 18px;
            color: var(--el-color-primary);
          }
        }

        ul {
          margin: 0;
          padding: 0;
          list-style: none;

          li {
            display: flex;
            align-items: flex-start;
            gap: 8px;
            margin-bottom: 12px;
            padding: 12px;
            background: var(--el-fill-color-light);
            border-radius: 8px;
            line-height: 1.6;
            transition: all 0.2s ease;

            &:hover {
              background: var(--el-fill-color);
            }

            .point-icon {
              flex-shrink: 0;
              margin-top: 2px;
              font-size: 16px;
              color: var(--el-color-success);
            }
          }
        }
      }
    }

    /* 星星脉冲动画 */
    @keyframes starPulse {
      0%, 100% {
        transform: scale(1);
      }
      50% {
        transform: scale(1.2);
      }
    }

    /* 进度条闪烁动画 */
    @keyframes shimmer {
      0% { transform: translateX(-100%); }
      100% { transform: translateX(100%); }
    }

    .module-content {
      /* 报告模块内容的统一 markdown-body 样式 */
      .markdown-body {
        font-size: 15px;
        line-height: 1.9;
        color: #1f2937;

        /* 标题 */
        :deep(h1), :deep(h2), :deep(h3), :deep(h4) {
          margin: 22px 0 10px;
          color: #111827;
          font-weight: 700;
          line-height: 1.4;
        }

        :deep(h1) { font-size: 22px; border-bottom: 2px solid #e5e7eb; padding-bottom: 8px; }
        :deep(h2) { font-size: 19px; border-bottom: 1px solid #e5e7eb; padding-bottom: 6px; }
        :deep(h3) { font-size: 17px; }
        :deep(h4) { font-size: 15px; color: #374151; }

        /* 段落 */
        :deep(p) {
          margin: 10px 0;
          word-break: break-word;
        }

        /* 列表 */
        :deep(ul), :deep(ol) {
          margin: 10px 0;
          padding-left: 28px;
        }

        :deep(li) {
          margin-bottom: 6px;
          line-height: 1.9;
        }

        /* 加粗与强调 */
        :deep(strong), :deep(b) {
          color: #111827;
          font-weight: 700;
        }

        :deep(em) {
          color: #374151;
          font-style: italic;
        }

        /* 引用块 */
        :deep(blockquote) {
          margin: 14px 0;
          padding: 10px 16px;
          border-left: 4px solid #6366f1;
          background: #f5f3ff;
          color: #4338ca;
          border-radius: 0 8px 8px 0;
        }

        /* 行内代码 */
        :deep(code) {
          background: #f3f4f6;
          color: #111827;
          padding: 2px 8px;
          border-radius: 4px;
          font-size: 13.5px;
          font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
        }

        /* 代码块 */
        :deep(pre) {
          background: #0f172a;
          color: #e2e8f0;
          padding: 16px 18px;
          border-radius: 8px;
          overflow-x: auto;
          margin: 14px 0;

          code {
            background: transparent;
            color: inherit;
            padding: 0;
            font-size: 13px;
          }
        }

        /* 表格 */
        :deep(table) {
          width: 100%;
          border-collapse: collapse;
          margin: 14px 0;
          font-size: 14px;

          th, td {
            padding: 10px 12px;
            border: 1px solid #e5e7eb;
            text-align: left;
          }

          th {
            background: #f8fafc;
            color: #111827;
            font-weight: 700;
          }

          tr:nth-child(even) td {
            background: #fafafa;
          }
        }

        /* 水平分割线 */
        :deep(hr) {
          border: none;
          border-top: 1px dashed #d1d5db;
          margin: 18px 0;
        }

        /* 链接 */
        :deep(a) {
          color: #2563eb;
          text-decoration: none;
          border-bottom: 1px dotted #bfdbfe;

          &:hover {
            color: #1d4ed8;
            border-bottom-color: #93c5fd;
          }
        }
      }

      .json-content {
        pre {
          background: var(--el-fill-color-light);
          padding: 16px;
          border-radius: 8px;
          overflow-x: auto;
          font-size: 13px;
          line-height: 1.6;
          color: #1f2937;
        }
      }
    }
  }

  /* 报告模块 tabs 风格微调 */
  .report-tabs {
    :deep(.el-tabs__item) {
      font-size: 14px;
    }
  }

  .error-container {
    padding: 48px 24px;
  }
}

/* 与单股分析页一致的pipeline-intro样式 */
.report-pipeline-intro {
  margin-top: 28px;
  margin-bottom: 28px;
  display: flex;
  flex-direction: column;
  gap: 28px;

  .scores-confidence-row {
    display: grid;
    grid-template-columns: 1fr;
    gap: 28px;
    margin-top: 8px;
    margin-bottom: 8px;

    @media (max-width: 1200px) {
      grid-template-columns: 1fr;
      gap: 28px;
    }

    .pipeline-section {
      margin-bottom: 0;
    }
  }

  .section--scores {
    .section-header {
      margin-bottom: 28px;
      padding-bottom: 20px;
      border-bottom: 2px solid #f1f5f9;

      h3 {
        font-size: 22px;
        font-weight: 700;
        color: #0f172a;
        margin: 0 0 10px 0;
        letter-spacing: -0.3px;
      }
      .section-subtitle {
        font-size: 14px;
        color: #64748b;
        margin: 0;
        line-height: 1.6;
      }
    }

    .dimension-group {
      margin-bottom: 28px;

      &:last-child {
        margin-bottom: 0;
      }

      .dimension-group-title {
        font-size: 15px;
        font-weight: 700;
        color: #374151;
        margin-bottom: 16px;
        padding-left: 8px;
        border-left: 4px solid #6366f1;
        display: flex;
        align-items: center;
        gap: 8px;
      }
    }

    .dimension-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 20px;

      @media (max-width: 1280px) {
        grid-template-columns: repeat(3, 1fr);
      }
      @media (max-width: 768px) {
        grid-template-columns: repeat(2, 1fr);
      }
      @media (max-width: 480px) {
        grid-template-columns: 1fr;
      }

      .dimension-card {
        padding: 22px;
        border-radius: 16px;
        border: 1px solid var(--el-border-color);
        background: var(--el-fill-color-light);
        transition: all 0.35s cubic-bezier(0.16, 1, 0.3, 1);
        cursor: pointer;
        position: relative;
        overflow: hidden;

        &::before {
          content: '';
          position: absolute;
          top: 0;
          right: 0;
          width: 80px;
          height: 80px;
          border-radius: 0 16px 0 80px;
          opacity: 0.08;
          transition: all 0.35s ease;
        }

        &:hover {
          transform: translateY(-6px) scale(1.02);
          box-shadow: 0 20px 40px rgba(15, 23, 42, 0.12), 0 4px 12px rgba(15, 23, 42, 0.06);

          &::before {
            opacity: 0.15;
            width: 120px;
            height: 120px;
          }
        }

        .dimension-header {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 16px;

          .dimension-icon {
            font-size: 28px;
            width: 48px;
            height: 48px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
          }
          .dimension-name {
            font-size: 15px;
            font-weight: 700;
            color: var(--el-text-color-primary);
          }
        }

        .dimension-score {
          margin-bottom: 16px;
          display: flex;
          align-items: baseline;
          gap: 4px;

          .score-value {
            font-size: 36px;
            font-weight: 800;
            line-height: 1;
            letter-spacing: -0.5px;
          }
          .score-unit {
            font-size: 14px;
            color: var(--el-text-color-secondary);
            font-weight: 500;
          }
        }

        .score-bar {
          height: 10px;
          border-radius: 5px;
          background: rgba(15, 23, 42, 0.06);
          overflow: hidden;
          position: relative;

          .score-bar-fill {
            height: 100%;
            border-radius: 5px;
            transition: width 0.8s cubic-bezier(0.16, 1, 0.3, 1);
            position: relative;
            overflow: hidden;

            &::after {
              content: '';
              position: absolute;
              top: 0;
              left: 0;
              right: 0;
              bottom: 0;
              background: linear-gradient(90deg, transparent, rgba(255,255,255,0.4), transparent);
              animation: shimmer 2s infinite;
            }
          }
        }

        &.dimension--technical {
          background: linear-gradient(145deg, #fffbeb 0%, #fef3c7 50%, #ffffff 100%);
          border-color: #fde68a;
          .score-value { color: #92400e; }
          .score-bar-fill { background: linear-gradient(90deg, #f59e0b, #fbbf24); }
          .dimension-icon { background: linear-gradient(145deg, #fef3c7, #fde68a); }
          &::before { background: #f59e0b; }
        }
        &.dimension--fundamental {
          background: linear-gradient(145deg, #eef2ff 0%, #e0e7ff 50%, #ffffff 100%);
          border-color: #c7d2fe;
          .score-value { color: #3730a3; }
          .score-bar-fill { background: linear-gradient(90deg, #4f46e5, #818cf8); }
          .dimension-icon { background: linear-gradient(145deg, #e0e7ff, #c7d2fe); }
          &::before { background: #4f46e5; }
        }
        &.dimension--sentiment {
          background: linear-gradient(145deg, #fdf2f8 0%, #fce7f3 50%, #ffffff 100%);
          border-color: #fbcfe8;
          .score-value { color: #9d174d; }
          .score-bar-fill { background: linear-gradient(90deg, #ec4899, #f472b6); }
          .dimension-icon { background: linear-gradient(145deg, #fce7f3, #fbcfe8); }
          &::before { background: #ec4899; }
        }
        &.dimension--news {
          background: linear-gradient(145deg, #fefce8 0%, #fef9c3 50%, #ffffff 100%);
          border-color: #fef08a;
          .score-value { color: #854d0e; }
          .score-bar-fill { background: linear-gradient(90deg, #eab308, #facc15); }
          .dimension-icon { background: linear-gradient(145deg, #fef9c3, #fef08a); }
          &::before { background: #eab308; }
        }
        &.dimension--capital {
          background: linear-gradient(145deg, #f0fdf4 0%, #dcfce7 50%, #ffffff 100%);
          border-color: #bbf7d0;
          .score-value { color: #166534; }
          .score-bar-fill { background: linear-gradient(90deg, #22c55e, #4ade80); }
          .dimension-icon { background: linear-gradient(145deg, #dcfce7, #bbf7d0); }
          &::before { background: #22c55e; }
        }
        &.dimension--policy {
          background: linear-gradient(145deg, #f0fdfa 0%, #ccfbf1 50%, #ffffff 100%);
          border-color: #99f6e4;
          .score-value { color: #115e59; }
          .score-bar-fill { background: linear-gradient(90deg, #14b8a6, #2dd4bf); }
          .dimension-icon { background: linear-gradient(145deg, #ccfbf1, #99f6e4); }
          &::before { background: #14b8a6; }
        }
        &.dimension--lockup {
          background: linear-gradient(145deg, #faf5ff 0%, #f3e8ff 50%, #ffffff 100%);
          border-color: #e9d5ff;
          .score-value { color: #6b21a8; }
          .score-bar-fill { background: linear-gradient(90deg, #a855f7, #c084fc); }
          .dimension-icon { background: linear-gradient(145deg, #f3e8ff, #e9d5ff); }
          &::before { background: #a855f7; }
        }

        .dimension-analyst {
          margin-top: 14px;
          font-size: 12px;
          color: #64748b;
          text-align: center;
          padding-top: 12px;
          border-top: 1px dashed #e2e8f0;
          font-weight: 500;
        }
      }
    }
  }

  .section--risk-scan {
    .risk-header-title {
      display: flex;
      align-items: center;
      gap: 6px;
      font-weight: 600;

      .risk-icon {
        color: #f09832;
        font-size: 18px;
      }

      h3 {
        margin: 0;
        font-size: 18px;
        font-weight: 600;
      }
    }

    .risk-source {
      font-size: 12px;
      color: #94a3b8;
    }

    .risk-content {
      .risk-overview {
        display: flex;
        align-items: center;
        gap: 40px;
        padding: 20px;
        background: linear-gradient(135deg, #f5f7fa 0%, #e8eef5 100%);
        border-radius: 12px;
        margin-bottom: 20px;
      }

      .score-ring {
        position: relative;
        width: 120px;
        height: 120px;
        flex-shrink: 0;

        .score-svg {
          width: 100%;
          height: 100%;
        }

        .score-text {
          position: absolute;
          top: 50%;
          left: 50%;
          transform: translate(-50%, -50%);
          text-align: center;

          .score-num {
            font-size: 32px;
            font-weight: 700;
            line-height: 1;
          }

          .score-label {
            font-size: 12px;
            color: #64748b;
            margin-top: 4px;
          }
        }
      }

      .score-stats {
        display: flex;
        gap: 32px;
        flex: 1;

        .stat-item {
          text-align: center;

          .stat-num {
            font-size: 28px;
            font-weight: 700;
            color: #0f172a;
            line-height: 1;

            &.risk {
              color: #ef4444;
            }

            &.safe {
              color: #10b981;
            }
          }

          .stat-label {
            font-size: 13px;
            color: #64748b;
            margin-top: 8px;
          }
        }
      }

      .risk-categories {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 16px;
      }

      .risk-category {
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 16px;
        background: #ffffff;
        transition: all 0.2s ease;

        &:hover {
          border-color: #94a3b8;
          box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
        }

        .cat-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 12px;

          .cat-name {
            font-weight: 600;
            font-size: 14px;
            color: #0f172a;
          }
        }

        .cat-items {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .risk-item {
          font-size: 13px;
          border-radius: 6px;
          transition: all 0.2s ease;

          .item-head {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 6px 8px;

            .item-icon {
              flex-shrink: 0;
              font-size: 14px;
            }

            .item-name {
              flex: 1;
              line-height: 1.4;
            }

            .item-score {
              flex-shrink: 0;
              font-size: 11px;
            }

            .expand-icon {
              flex-shrink: 0;
              font-size: 12px;
              opacity: 0.6;
              transition: transform 0.2s ease;
            }
          }

          .item-detail {
            padding: 0 8px 10px 30px;
          }

          .item-reason {
            margin-bottom: 10px;

            .reason-title {
              font-size: 12px;
              font-weight: 600;
              color: #ef4444;
              margin-bottom: 4px;
            }

            .reason-content {
              font-size: 12px;
              color: #475569;
              line-height: 1.6;
              white-space: pre-wrap;
              word-break: break-all;
            }
          }

          .sub-items {
            .sub-title {
              font-size: 12px;
              font-weight: 600;
              color: #64748b;
              margin-bottom: 6px;
            }

            .sub-item {
              display: flex;
              align-items: center;
              gap: 6px;
              padding: 4px 6px;
              font-size: 12px;
              border-radius: 4px;

              .sub-icon {
                flex-shrink: 0;
                font-size: 12px;
              }

              .sub-name {
                flex: 1;
                line-height: 1.4;
              }
            }
          }

          &.is-risk {
            color: #ef4444;

            .item-icon {
              color: #ef4444;
            }

            &.has-detail {
              cursor: pointer;

              &:hover {
                background: rgba(239, 68, 68, 0.06);
              }
            }

            &.expanded {
              background: rgba(239, 68, 68, 0.06);
            }

            .sub-item.is-risk {
              color: #ef4444;
              .sub-icon { color: #ef4444; }
            }
          }

          &.is-safe {
            color: #475569;

            .item-icon {
              color: #10b981;
            }

            .sub-item.is-safe {
              color: #475569;
              .sub-icon { color: #10b981; }
            }
          }
        }

        .safe-items-collapse {
          margin-top: 8px;

          .el-collapse {
            border: none;

            .el-collapse-item__header {
              background: #f8fafc;
              border: 1px dashed #cbd5e1;
              border-radius: 6px;
              font-size: 13px;
              color: #64748b;
              height: 36px;
              line-height: 36px;
            }

            .el-collapse-item__wrap {
              border: none;
              background: transparent;
            }

            .el-collapse-item__content {
              padding: 8px 0;
            }
          }
        }
      }
    }
  }

  .section--confidence {
    .confidence-content {
      display: flex;
      flex-direction: column;
      gap: 24px;
    }

    .confidence-total {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 16px;
      padding: 28px 24px;
      background: linear-gradient(135deg, rgba(14, 165, 233, 0.1) 0%, rgba(6, 182, 212, 0.05) 100%);
      border-radius: 16px;
      border: 1px solid rgba(14, 165, 233, 0.15);
      position: relative;

      .confidence-total-score {
        display: flex;
        align-items: baseline;
        line-height: 1;

        .total-score-value {
          font-size: 56px;
          font-weight: 800;
          background: linear-gradient(135deg, #0ea5e9, #06b6d4, #0891b2);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          background-clip: text;
          letter-spacing: -2px;
        }

        .total-score-unit {
          font-size: 24px;
          font-weight: 700;
          color: #0891b2;
          margin-left: 4px;
        }
      }

      .confidence-total-label {
        font-size: 16px;
        font-weight: 700;
        color: #0ea5e9;
      }
    }

    .confidence-detail-list {
      display: flex;
      flex-direction: column;
      gap: 12px;

      .confidence-detail-item {
        padding: 16px 20px;
        background: #ffffff;
        border-radius: 12px;
        border: 1px solid #e2e8f0;
        transition: all 0.3s ease;

        &:hover {
          transform: translateY(-2px);
          box-shadow: 0 8px 24px rgba(14, 165, 233, 0.1);
          border-color: #7dd3fc;
        }

        .detail-item-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 10px;

          .detail-item-name {
            font-size: 14px;
            font-weight: 600;
            color: #0f172a;
          }

          .detail-item-score {
            font-size: 13px;
            font-weight: 700;
            color: #0891b2;
            font-family: ui-monospace, SFMono-Regular, "SF Mono", monospace;
          }
        }

        .detail-item-bar {
          height: 6px;
          border-radius: 3px;
          background: rgba(14, 165, 233, 0.08);
          overflow: hidden;
          margin-bottom: 8px;

          .detail-item-bar-fill {
            height: 100%;
            border-radius: 3px;
            transition: width 1s cubic-bezier(0.16, 1, 0.3, 1);
          }
        }

        .detail-item-desc {
          font-size: 13px;
          color: #64748b;
          line-height: 1.6;
        }
      }

      // 满分项折叠样式
      .full-score-collapse {
        .collapse-title {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 14px;
          font-weight: 600;
          color: #10b981;

          .el-icon {
            font-size: 16px;
          }
        }

        .confidence-detail-item.is-full-score {
          background: linear-gradient(135deg, rgba(16, 185, 129, 0.06) 0%, rgba(52, 211, 153, 0.03) 100%);
          border-color: rgba(16, 185, 129, 0.15);

          .detail-item-header .detail-item-score {
            color: #10b981;
          }

          .detail-item-bar-fill {
            background: linear-gradient(90deg, #10b981, #34d399) !important;
          }

          &:hover {
            border-color: #34d399;
            box-shadow: 0 4px 12px rgba(16, 185, 129, 0.12);
          }
        }
      }
    }
  }

  .pipeline-section {
    background: var(--el-bg-color);
    border-radius: 16px;
    padding: 28px;
    box-shadow: 0 4px 16px rgba(15, 23, 42, 0.06), 0 1px 3px rgba(15, 23, 42, 0.04);
    border: 1px solid #e2e8f0;

    .section-header {
      margin-bottom: 28px;
      padding-bottom: 20px;
      border-bottom: 2px solid #f1f5f9;

      h3 {
        margin: 0 0 12px 0;
        font-size: 22px;
        font-weight: 700;
        color: #0f172a;
        letter-spacing: -0.3px;
      }

      .section-subtitle {
        margin: 0;
        font-size: 14px;
        color: #64748b;
        line-height: 1.7;
      }
    }

    .analyst-teams {
      display: flex;
      flex-direction: column;
      gap: 16px;

      .team-group {
        .team-label {
          font-size: 13px;
          font-weight: 600;
          color: var(--el-text-color-secondary);
          margin-bottom: 10px;
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }

        .team-cards {
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
        }
      }

      .analyst-chip {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 10px 16px;
        border-radius: 10px;
        background: var(--el-fill-color-light);
        border: 1px solid var(--el-border-color);
        transition: all 0.2s ease;

        &:hover {
          transform: translateY(-2px);
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
        }

        &.is-clickable {
          cursor: pointer;

          &:hover {
            border-color: var(--el-color-primary-light-5);
            box-shadow: 0 4px 16px rgba(64, 158, 255, 0.15);
          }
        }

        .chip-icon {
          font-size: 18px;
        }

        .chip-name {
          font-size: 14px;
          font-weight: 600;
          color: var(--el-text-color-primary);
        }

        .chip-desc {
          font-size: 12px;
          color: var(--el-text-color-secondary);
        }

        &--market {
          background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
          border-color: #fbbf24;
          .chip-icon { font-size: 20px; }
          .chip-name { color: #92400e; }
          .chip-desc { color: #b45309; }
        }
        &--social {
          background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%);
          border-color: #60a5fa;
          .chip-name { color: #1e40af; }
          .chip-desc { color: #2563eb; }
        }
        &--fund {
          background: linear-gradient(135deg, #d1fae5 0%, #a7f3d0 100%);
          border-color: #34d399;
          .chip-name { color: #065f46; }
          .chip-desc { color: #059669; }
        }
        &--unlock {
          background: linear-gradient(135deg, #fce7f3 0%, #fbcfe8 100%);
          border-color: #f472b6;
          .chip-name { color: #9d174d; }
          .chip-desc { color: #be185d; }
        }
        &--fundamental {
          background: linear-gradient(135deg, #e0e7ff 0%, #c7d2fe 100%);
          border-color: #818cf8;
          .chip-name { color: #3730a3; }
          .chip-desc { color: #4f46e5; }
        }
        &--news {
          background: linear-gradient(135deg, #f3e8ff 0%, #e9d5ff 100%);
          border-color: #a78bfa;
          .chip-name { color: #6b21a8; }
          .chip-desc { color: #9333ea; }
        }
        &--policy {
          background: linear-gradient(135deg, #ccfbf1 0%, #99f6e4 100%);
          border-color: #2dd4bf;
          .chip-name { color: #115e59; }
          .chip-desc { color: #0d9488; }
        }
      }
    }

    @media (prefers-color-scheme: dark) {
      .analyst-chip {
        &--market {
          background: linear-gradient(135deg, #78350f 0%, #92400e 100%);
          border-color: #d97706;
          .chip-name { color: #fef3c7; }
          .chip-desc { color: #fde68a; }
        }
        &--social {
          background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%);
          border-color: #3b82f6;
          .chip-name { color: #dbeafe; }
          .chip-desc { color: #bfdbfe; }
        }
        &--fund {
          background: linear-gradient(135deg, #064e3b 0%, #065f46 100%);
          border-color: #10b981;
          .chip-name { color: #d1fae5; }
          .chip-desc { color: #a7f3d0; }
        }
        &--unlock {
          background: linear-gradient(135deg, #831843 0%, #9d174d 100%);
          border-color: #ec4899;
          .chip-name { color: #fce7f3; }
          .chip-desc { color: #fbcfe8; }
        }
        &--fundamental {
          background: linear-gradient(135deg, #312e81 0%, #3730a3 100%);
          border-color: #6366f1;
          .chip-name { color: #e0e7ff; }
          .chip-desc { color: #c7d2fe; }
        }
        &--news {
          background: linear-gradient(135deg, #581c87 0%, #6b21a8 100%);
          border-color: #a855f7;
          .chip-name { color: #f3e8ff; }
          .chip-desc { color: #e9d5ff; }
        }
        &--policy {
          background: linear-gradient(135deg, #134e4a 0%, #115e59 100%);
          border-color: #14b8a6;
          .chip-name { color: #ccfbf1; }
          .chip-desc { color: #99f6e4; }
        }
      }
    }

    .section--debate {
      background: var(--el-bg-color);
    }

    .debate-timeline {
      display: flex;
      flex-direction: column;
      gap: 20px;

      .timeline-phase {
        background: var(--el-bg-color);
        border-radius: 16px;
        padding: 24px;
        border: 1px solid #e2e8f0;
        box-shadow: 0 4px 16px rgba(15, 23, 42, 0.06);
        transition: all 0.3s ease;

        &:hover {
          border-color: #cbd5e1;
          box-shadow: 0 8px 24px rgba(15, 23, 42, 0.1);
          transform: translateY(-2px);
        }

        .phase-label {
          font-size: 13px;
          font-weight: 700;
          color: #475569;
          text-transform: uppercase;
          letter-spacing: 1px;
          margin-bottom: 16px;
          display: flex;
          align-items: center;
          gap: 8px;

          &::before {
            content: '';
            width: 4px;
            height: 16px;
            border-radius: 2px;
          }
        }

        .phase-flow {
          display: flex;
          align-items: center;
          gap: 12px;
          flex-wrap: wrap;

          // 研究辩论特殊布局：垂直排列
          &.debate-flow {
            flex-direction: column;
            align-items: center;
            gap: 16px;
          }
        }

        // 研究辩论行布局：看涨/看跌并排
        .debate-row {
          display: flex;
          align-items: stretch;
          gap: 16px;
          justify-content: center;

          .debate-node {
            flex: 1;
            max-width: 380px;
          }

          &.debate-row--manager {
            .debate-node {
              max-width: 420px;
            }
          }
        }

        // VS 分隔线
        .vs-divider {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 0 8px;
          flex-shrink: 0;

          .vs-line {
            display: none;
          }

          .vs-badge {
            font-size: 14px;
            font-weight: 800;
            color: #f59e0b;
            background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%);
            padding: 10px 18px;
            border-radius: 20px;
            letter-spacing: 1px;
            border: 2px solid #fde68a;
            box-shadow: 0 4px 12px rgba(245, 158, 11, 0.15);
            white-space: nowrap;
          }
        }

        .debate-arrow-down {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 6px;
          padding: 8px 0;

          .arrow-line {
            width: 2px;
            height: 24px;
            background: linear-gradient(180deg, #93c5fd, #60a5fa);
            border-radius: 1px;
          }

          .arrow-badge {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 2px;
            font-size: 12px;
            font-weight: 700;
            color: #1d4ed8;
            background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
            padding: 10px 20px;
            border-radius: 16px;
            border: 2px solid #bfdbfe;
            box-shadow: 0 4px 12px rgba(59, 130, 246, 0.12);
            white-space: nowrap;

            .arrow-badge-text {
              font-size: 13px;
              font-weight: 700;
              letter-spacing: 0.5px;
            }
            .arrow-badge-icon {
              font-size: 16px;
              line-height: 1;
              animation: bounceDown 1.5s ease-in-out infinite;
            }
          }
        }

        @keyframes bounceDown {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(3px); }
        }

        &.phase--trade {
          background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 50%, #ffffff 100%);
          border-color: #fde68a;

          .phase-label {
            color: #92400e;
            &::before { background: linear-gradient(180deg, #f59e0b, #fbbf24); }
          }
        }
      }

      .debate-node {
        display: flex;
        flex-direction: column;
        padding: 20px;
        border-radius: 12px;
        min-width: 160px;
        text-align: left;
        transition: all 0.2s ease;
        position: relative;
        overflow: hidden;
        border: 1px solid var(--el-border-color);
        background: var(--el-fill-color-light);

        &::before {
          content: '';
          position: absolute;
          top: 0;
          right: 0;
          width: 60px;
          height: 60px;
          border-radius: 0 12px 0 60px;
          opacity: 0.06;
          transition: all 0.2s ease;
        }

        &.is-clickable {
          cursor: pointer;

          &:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 20px rgba(15, 23, 42, 0.08), 0 2px 6px rgba(15, 23, 42, 0.04);

            &::before {
              opacity: 0.1;
            }
          }
        }

        .node-icon {
          font-size: 22px;
          width: 36px;
          height: 36px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: 8px;
        }

        .node-header {
          display: flex;
          align-items: center;
          gap: 10px;
          margin-bottom: 12px;
        }

        .node-name {
          font-size: 15px;
          font-weight: 700;
          color: var(--el-text-color-primary);
        }

        .node-keypoints {
          display: flex;
          flex-direction: column;
          gap: 8px;

          .keypoint {
            display: flex;
            align-items: flex-start;
            gap: 8px;
            font-size: 12px;
            line-height: 1.5;

            .kp-dot {
              width: 6px;
              height: 6px;
              border-radius: 50%;
              margin-top: 5px;
              flex-shrink: 0;
            }

            .kp-text {
              color: var(--el-text-color-regular);
              flex: 1;
            }
          }
        }

        .node-desc {
          font-size: 12px;
          color: var(--el-text-color-secondary);
          line-height: 1.6;
        }

        &.node--bull {
          background: linear-gradient(145deg, #f0fdf4 0%, #dcfce7 50%, #ffffff 100%);
          border-color: #bbf7d0;
          .node-name { color: #166534; }
          .node-icon { background: linear-gradient(145deg, #dcfce7, #bbf7d0); }
          .keypoint .kp-dot { background: #22c55e; }
          &::before { background: linear-gradient(135deg, #22c55e, #4ade80); }
        }
        &.node--bear {
          background: linear-gradient(145deg, #fef2f2 0%, #fee2e2 50%, #ffffff 100%);
          border-color: #fecaca;
          .node-name { color: #991b1b; }
          .node-icon { background: linear-gradient(145deg, #fee2e2, #fecaca); }
          .keypoint .kp-dot { background: #ef4444; }
          &::before { background: linear-gradient(135deg, #ef4444, #f87171); }
        }
        &.node--debate {
          background: linear-gradient(145deg, #f5f3ff 0%, #ede9fe 50%, #ffffff 100%);
          border-color: #ddd6fe;
          .node-name { color: #4c1d95; }
          .node-icon { background: linear-gradient(145deg, #ede9fe, #ddd6fe); }
          .keypoint .kp-dot { background: #8b5cf6; }
          &::before { background: linear-gradient(135deg, #8b5cf6, #a78bfa); }
        }
        &.node--manager {
          background: linear-gradient(145deg, #eff6ff 0%, #dbeafe 50%, #ffffff 100%);
          border-color: #bfdbfe;
          .node-name { color: #1e40af; }
          .node-icon { background: linear-gradient(145deg, #dbeafe, #bfdbfe); }
          .keypoint .kp-dot { background: #3b82f6; }
          &::before { background: linear-gradient(135deg, #3b82f6, #60a5fa); }
        }
      }

      .timeline-arrow {
        font-size: 18px;
        color: #94a3b8;
        font-weight: 700;
        padding: 0 8px;

        &--vs {
          color: #ef4444;
          font-weight: 800;
        }
      }

      .trade-node {
        display: flex;
        align-items: center;
        gap: 16px;
        padding: 22px;
        transition: all 0.35s cubic-bezier(0.16, 1, 0.3, 1);
        border-radius: 16px;
        background: linear-gradient(145deg, #fff7ed 0%, #ffedd5 50%, #ffffff 100%);
        border: 1px solid #fed7aa;
        position: relative;
        overflow: hidden;

        &::before {
          content: '';
          position: absolute;
          top: 0;
          right: 0;
          width: 80px;
          height: 80px;
          border-radius: 0 16px 0 80px;
          background: linear-gradient(135deg, #f97316, #fb923c);
          opacity: 0.08;
          transition: all 0.35s ease;
        }

        &.is-clickable {
          cursor: pointer;

          &:hover {
            transform: translateY(-6px) scale(1.02);
            box-shadow: 0 20px 40px rgba(249, 115, 22, 0.15), 0 4px 12px rgba(249, 115, 22, 0.08);

            &::before {
              opacity: 0.15;
              width: 120px;
              height: 120px;
            }
          }
        }

        .node-icon {
          font-size: 28px;
          width: 48px;
          height: 48px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: 12px;
          background: linear-gradient(145deg, #ffedd5, #fed7aa);
          box-shadow: 0 2px 8px rgba(249, 115, 22, 0.1);
          flex-shrink: 0;
        }
        .node-name {
          font-size: 15px;
          font-weight: 700;
          color: #9a3412;
          margin-bottom: 4px;
        }
        .node-desc {
          font-size: 12px;
          color: #c2410c;
          line-height: 1.6;
        }
      }

      .risk-perspectives {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 16px;
        margin-bottom: 16px;

        @media (max-width: 640px) {
          grid-template-columns: 1fr;
        }

        .risk-card {
          padding: 22px;
          border-radius: 16px;
          text-align: left;
          transition: all 0.35s cubic-bezier(0.16, 1, 0.3, 1);
          position: relative;
          overflow: hidden;
          border: 1px solid var(--el-border-color);
          background: var(--el-fill-color-light);

          &::before {
            content: '';
            position: absolute;
            top: 0;
            right: 0;
            width: 80px;
            height: 80px;
            border-radius: 0 16px 0 80px;
            opacity: 0.08;
            transition: all 0.35s ease;
          }

          &.is-clickable {
            cursor: pointer;

            &:hover {
              transform: translateY(-6px) scale(1.02);
              box-shadow: 0 20px 40px rgba(15, 23, 42, 0.12), 0 4px 12px rgba(15, 23, 42, 0.06);

              &::before {
                opacity: 0.15;
                width: 120px;
                height: 120px;
              }
            }
          }

          .risk-icon {
            font-size: 28px;
            width: 48px;
            height: 48px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
            margin-bottom: 14px;
          }

          .risk-name {
            font-size: 15px;
            font-weight: 700;
            color: var(--el-text-color-primary);
            display: block;
            margin-bottom: 8px;
          }

          .risk-desc {
            font-size: 12px;
            color: var(--el-text-color-secondary);
            line-height: 1.6;
          }

          &.risk-card--aggressive {
            background: linear-gradient(145deg, #fef2f2 0%, #fee2e2 50%, #ffffff 100%);
            border-color: #fecaca;
            color: #991b1b;
            .risk-name { color: #991b1b; }
            .risk-icon { background: linear-gradient(145deg, #fee2e2, #fecaca); }
            &::before { background: linear-gradient(135deg, #ef4444, #f87171); }
          }
          &.risk-card--neutral {
            background: linear-gradient(145deg, #fffbeb 0%, #fef3c7 50%, #ffffff 100%);
            border-color: #fde68a;
            color: #92400e;
            .risk-name { color: #92400e; }
            .risk-icon { background: linear-gradient(145deg, #fef3c7, #fde68a); }
            &::before { background: linear-gradient(135deg, #f59e0b, #fbbf24); }
          }
          &.risk-card--conservative {
            background: linear-gradient(145deg, #eef2ff 0%, #e0e7ff 50%, #ffffff 100%);
            border-color: #c7d2fe;
            color: #3730a3;
            .risk-name { color: #3730a3; }
            .risk-icon { background: linear-gradient(145deg, #e0e7ff, #c7d2fe); }
            &::before { background: linear-gradient(135deg, #6366f1, #818cf8); }
          }
        }
      }

      .risk-manager {
        display: flex;
        align-items: center;
        gap: 16px;
        padding: 22px;
        border-radius: 16px;
        border: 1px solid var(--el-border-color);
        transition: all 0.35s cubic-bezier(0.16, 1, 0.3, 1);
        position: relative;
        overflow: hidden;

        &::before {
          content: '';
          position: absolute;
          top: 0;
          right: 0;
          width: 80px;
          height: 80px;
          border-radius: 0 16px 0 80px;
          opacity: 0.08;
          transition: all 0.35s ease;
        }

        &.is-clickable {
          cursor: pointer;

          &:hover {
            transform: translateY(-6px) scale(1.02);
            box-shadow: 0 20px 40px rgba(15, 23, 42, 0.12), 0 4px 12px rgba(15, 23, 42, 0.06);

            &::before {
              opacity: 0.15;
              width: 120px;
              height: 120px;
            }
          }
        }

        .node-icon {
          font-size: 28px;
          width: 48px;
          height: 48px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: 12px;
          box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
          flex-shrink: 0;
        }
        .node-name {
          font-size: 15px;
          font-weight: 700;
          margin-bottom: 4px;
        }
        .node-desc {
          font-size: 12px;
          line-height: 1.6;
        }

        &:not(.risk-constraint) {
          background: linear-gradient(145deg, #fdf2f8 0%, #fce7f3 50%, #ffffff 100%);
          border-color: #fbcfe8;
          .node-name { color: #9d174d; }
          .node-desc { color: #be185d; }
          .node-icon { background: linear-gradient(145deg, #fce7f3, #fbcfe8); }
          &::before { background: linear-gradient(135deg, #ec4899, #f472b6); }

          &.is-clickable:hover {
            box-shadow: 0 20px 40px rgba(236, 72, 153, 0.15), 0 4px 12px rgba(236, 72, 153, 0.08);
          }
        }
        &.risk-constraint {
          background: linear-gradient(145deg, #eff6ff 0%, #dbeafe 50%, #ffffff 100%);
          border-color: #bfdbfe;
          .node-name { color: #1e40af; }
          .node-desc { color: #2563eb; }
          .node-icon { background: linear-gradient(145deg, #dbeafe, #bfdbfe); }
          &::before { background: linear-gradient(135deg, #3b82f6, #60a5fa); }

          &.is-clickable:hover {
            box-shadow: 0 20px 40px rgba(59, 130, 246, 0.15), 0 4px 12px rgba(59, 130, 246, 0.08);
          }
        }
      }

      .final-decision-card {
        margin-top: 16px;
        background: linear-gradient(145deg, #fff7ed 0%, #ffedd5 50%, #ffffff 100%);
        border: 1px solid #fed7aa;
        border-radius: 16px;
        padding: 24px;
        text-align: left;
        cursor: pointer;
        transition: all 0.35s cubic-bezier(0.16, 1, 0.3, 1);
        position: relative;
        overflow: hidden;

        &::before {
          content: '';
          position: absolute;
          top: 0;
          right: 0;
          width: 100px;
          height: 100px;
          border-radius: 0 16px 0 100px;
          background: linear-gradient(135deg, #f97316, #fb923c);
          opacity: 0.1;
          transition: all 0.35s ease;
        }

        &:hover {
          transform: translateY(-6px) scale(1.02);
          box-shadow: 0 20px 40px rgba(249, 115, 22, 0.15), 0 4px 12px rgba(249, 115, 22, 0.08);

          &::before {
            opacity: 0.18;
            width: 140px;
            height: 140px;
          }
        }

        .node-icon {
          font-size: 32px;
          width: 56px;
          height: 56px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: 14px;
          background: linear-gradient(145deg, #ffedd5, #fed7aa);
          box-shadow: 0 2px 8px rgba(249, 115, 22, 0.15);
          margin-bottom: 14px;
        }
        .node-name {
          font-size: 18px;
          font-weight: 800;
          color: #9a3412;
          display: block;
          margin-bottom: 8px;
        }
        .node-desc {
          font-size: 13px;
          color: #c2410c;
          line-height: 1.6;
        }
      }

      .phase--final-strategy {
        background: linear-gradient(145deg, #fff7ed 0%, #fffbf5 50%, #ffffff 100%);
        border-color: #fdba74;

        .phase-label {
          color: #c2410c;
          &::before { background: linear-gradient(180deg, #f97316, #fb923c); }
        }
      }

      // 多维度评分区域
      .section--scores {
        .section-header {
          h3 {
            font-size: 22px;
            font-weight: 700;
            color: #0f172a;
            margin: 0 0 10px 0;
            letter-spacing: -0.3px;
          }
          .section-subtitle {
            font-size: 14px;
            color: #64748b;
            margin: 0;
            line-height: 1.6;
          }
        }

        .dimension-group {
          .dimension-group-title {
            font-size: 15px;
            font-weight: 700;
            color: #374151;
            margin-bottom: 16px;
            padding-left: 8px;
            border-left: 4px solid #6366f1;
          }
        }
      }

      html.dark & {
        // 多维度评分卡片
        .section--scores {
          .section-header {
            border-bottom-color: #334155;
            h3 { color: #f8fafc; }
            .section-subtitle { color: #94a3b8; }
          }
          .dimension-group {
            .dimension-group-title {
              color: #e2e8f0;
              border-left-color: #818cf8;
            }
          }
        }

        // 多维度评分卡片
        .section--scores .dimension-grid .dimension-card {
          background: #1e293b !important;
          border-color: #334155 !important;
          
          .dimension-name {
            color: #f1f5f9 !important;
          }
          .score-unit {
            color: #94a3b8 !important;
          }
          .score-bar {
            background: rgba(15, 23, 42, 0.8) !important;
          }
          .dimension-analyst {
            color: #64748b !important;
            border-top-color: rgba(71, 85, 105, 0.5) !important;
          }
          .dimension-icon {
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3) !important;
          }

          &:hover {
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4), 0 4px 12px rgba(0, 0, 0, 0.2) !important;
          }

          &.dimension--technical {
            background: linear-gradient(135deg, #422006 0%, #1e293b 100%) !important;
            border-color: #d97706 !important;
            .score-value { color: #fbbf24 !important; }
            .dimension-icon { background: linear-gradient(135deg, rgba(217, 119, 6, 0.25), rgba(251, 191, 36, 0.15)) !important; }
            .score-bar-fill { background: linear-gradient(90deg, #d97706, #fbbf24) !important; }
            &::before { background: #f59e0b !important; }
          }
          &.dimension--fundamental {
            background: linear-gradient(135deg, #1e1b4b 0%, #1e293b 100%) !important;
            border-color: #6366f1 !important;
            .score-value { color: #a5b4fc !important; }
            .dimension-icon { background: linear-gradient(135deg, rgba(99, 102, 241, 0.25), rgba(165, 180, 252, 0.15)) !important; }
            .score-bar-fill { background: linear-gradient(90deg, #4f46e5, #818cf8) !important; }
            &::before { background: #6366f1 !important; }
          }
          &.dimension--sentiment {
            background: linear-gradient(135deg, #500724 0%, #1e293b 100%) !important;
            border-color: #ec4899 !important;
            .score-value { color: #f9a8d4 !important; }
            .dimension-icon { background: linear-gradient(135deg, rgba(236, 72, 153, 0.25), rgba(249, 168, 212, 0.15)) !important; }
            .score-bar-fill { background: linear-gradient(90deg, #db2777, #f472b6) !important; }
            &::before { background: #ec4899 !important; }
          }
          &.dimension--news {
            background: linear-gradient(135deg, #422006 0%, #1e293b 100%) !important;
            border-color: #eab308 !important;
            .score-value { color: #fde047 !important; }
            .dimension-icon { background: linear-gradient(135deg, rgba(234, 179, 8, 0.25), rgba(253, 224, 71, 0.15)) !important; }
            .score-bar-fill { background: linear-gradient(90deg, #ca8a04, #facc15) !important; }
            &::before { background: #eab308 !important; }
          }
          &.dimension--capital {
            background: linear-gradient(135deg, #052e16 0%, #1e293b 100%) !important;
            border-color: #22c55e !important;
            .score-value { color: #86efac !important; }
            .dimension-icon { background: linear-gradient(135deg, rgba(34, 197, 94, 0.25), rgba(134, 239, 172, 0.15)) !important; }
            .score-bar-fill { background: linear-gradient(90deg, #16a34a, #4ade80) !important; }
            &::before { background: #22c55e !important; }
          }
          &.dimension--policy {
            background: linear-gradient(135deg, #042f2e 0%, #1e293b 100%) !important;
            border-color: #14b8a6 !important;
            .score-value { color: #5eead4 !important; }
            .dimension-icon { background: linear-gradient(135deg, rgba(20, 184, 166, 0.25), rgba(94, 234, 212, 0.15)) !important; }
            .score-bar-fill { background: linear-gradient(90deg, #0d9488, #2dd4bf) !important; }
            &::before { background: #14b8a6 !important; }
          }
          &.dimension--lockup {
            background: linear-gradient(135deg, #2e1065 0%, #1e293b 100%) !important;
            border-color: #a855f7 !important;
            .score-value { color: #d8b4fe !important; }
            .dimension-icon { background: linear-gradient(135deg, rgba(168, 85, 247, 0.25), rgba(216, 180, 254, 0.15)) !important; }
            .score-bar-fill { background: linear-gradient(90deg, #9333ea, #c084fc) !important; }
            &::before { background: #a855f7 !important; }
          }
        }

        // 置信度评估
        .section--confidence {
          background: linear-gradient(135deg, #0c4a6e 0%, #1c1917 100%);
          border-color: #0369a1;

          .confidence-total {
            background: linear-gradient(135deg, rgba(14, 165, 233, 0.15) 0%, rgba(6, 182, 212, 0.08) 100%);

            .confidence-total-score {
              .total-score-value {
                background: linear-gradient(135deg, #38bdf8, #22d3ee);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
              }
              .total-score-unit {
                color: #22d3ee;
              }
            }
          }

          .confidence-detail-list .confidence-detail-item {
            background: rgba(15, 23, 42, 0.6);
            border-color: rgba(56, 189, 248, 0.2);

            // 暗色模式下的满分项样式
            &.is-full-score {
              background: linear-gradient(135deg, rgba(16, 185, 129, 0.12) 0%, rgba(52, 211, 153, 0.06) 100%);
              border-color: rgba(16, 185, 129, 0.3);

              .detail-item-header .detail-item-score {
                color: #34d399;
              }
            }
          }

          // 暗色模式下的满分项折叠
          .full-score-collapse .collapse-title {
            color: #34d399;
          }
        }

        // 辩论节点
        .debate-node {
          .node-keypoints .keypoint .kp-text { color: #94a3b8; }

          &.node--bull {
            background: linear-gradient(135deg, #14532d 0%, #1c1917 100%);
            border-color: #166534;
            .node-name { color: #d1fae5; }
            .node-desc { color: #6ee7b7; }
            .node-icon { background: linear-gradient(135deg, rgba(16, 185, 129, 0.2), rgba(52, 211, 153, 0.1)); }
            &::before { background: linear-gradient(135deg, #10b981, #34d399); }
          }
          &.node--bear {
            background: linear-gradient(135deg, #7f1d1d 0%, #1c1917 100%);
            border-color: #991b1b;
            .node-name { color: #fee2e2; }
            .node-desc { color: #fca5a5; }
            .node-icon { background: linear-gradient(135deg, rgba(239, 68, 68, 0.2), rgba(248, 113, 113, 0.1)); }
            &::before { background: linear-gradient(135deg, #ef4444, #f87171); }
          }
          &.node--debate {
            background: linear-gradient(135deg, #4c1d95 0%, #1c1917 100%);
            border-color: #5b21b6;
            .node-name { color: #ede9fe; }
            .node-desc { color: #c4b5fd; }
            .node-icon { background: linear-gradient(135deg, rgba(139, 92, 246, 0.2), rgba(167, 139, 250, 0.1)); }
            &::before { background: linear-gradient(135deg, #8b5cf6, #a78bfa); }
          }
          &.node--manager {
            background: linear-gradient(135deg, #1e3a8a 0%, #1c1917 100%);
            border-color: #1d4ed8;
            .node-name { color: #dbeafe; }
            .node-desc { color: #93c5fd; }
            .node-icon { background: linear-gradient(135deg, rgba(59, 130, 246, 0.2), rgba(96, 165, 250, 0.1)); }
            &::before { background: linear-gradient(135deg, #3b82f6, #60a5fa); }
          }
        }

        .timeline-arrow {
          color: #64748b;
          &--vs { color: #f87171; }
        }

        // 交易节点
        .trade-node {
          background: linear-gradient(135deg, #7c2d12 0%, #1c1917 100%);
          border-color: #9a3412;
          .node-name { color: #ffedd5; }
          .node-desc { color: #fdba74; }
          .node-icon { background: linear-gradient(135deg, rgba(249, 115, 22, 0.2), rgba(251, 146, 60, 0.1)); }
          &::before { background: linear-gradient(135deg, #f97316, #fb923c); }
        }

        // 风险卡片
        .risk-perspectives .risk-card {
          &.risk-card--aggressive {
            background: linear-gradient(135deg, #7f1d1d 0%, #1c1917 100%);
            border-color: #991b1b;
            color: #fee2e2;
            .risk-name { color: #fee2e2; }
            .risk-desc { color: #fca5a5; }
            .risk-icon { background: linear-gradient(135deg, rgba(239, 68, 68, 0.2), rgba(248, 113, 113, 0.1)); }
            &::before { background: linear-gradient(135deg, #ef4444, #f87171); }
          }
          &.risk-card--neutral {
            background: linear-gradient(135deg, #78350f 0%, #1c1917 100%);
            border-color: #92400e;
            color: #fef3c7;
            .risk-name { color: #fef3c7; }
            .risk-desc { color: #fcd34d; }
            .risk-icon { background: linear-gradient(135deg, rgba(245, 158, 11, 0.2), rgba(251, 191, 36, 0.1)); }
            &::before { background: linear-gradient(135deg, #f59e0b, #fbbf24); }
          }
          &.risk-card--conservative {
            background: linear-gradient(135deg, #312e81 0%, #1c1917 100%);
            border-color: #3730a3;
            color: #e0e7ff;
            .risk-name { color: #e0e7ff; }
            .risk-desc { color: #a5b4fc; }
            .risk-icon { background: linear-gradient(135deg, rgba(99, 102, 241, 0.2), rgba(129, 140, 248, 0.1)); }
            &::before { background: linear-gradient(135deg, #6366f1, #818cf8); }
          }
        }

        // 风控经理
        .risk-manager {
          &:not(.risk-constraint) {
            background: linear-gradient(135deg, #831843 0%, #1c1917 100%);
            border-color: #9d174d;
            .node-name { color: #fce7f3; }
            .node-desc { color: #f9a8d4; }
            .node-icon { background: linear-gradient(135deg, rgba(236, 72, 153, 0.2), rgba(244, 114, 182, 0.1)); }
            &::before { background: linear-gradient(135deg, #ec4899, #f472b6); }
          }
        }

        .risk-constraint {
          background: linear-gradient(135deg, #1e3a8a 0%, #1c1917 100%) !important;
          border-color: #1d4ed8 !important;
          .node-name { color: #dbeafe; }
          .node-desc { color: #93c5fd; }
          .node-icon { background: linear-gradient(135deg, rgba(59, 130, 246, 0.2), rgba(96, 165, 250, 0.1)) !important; }
          &::before { background: linear-gradient(135deg, #3b82f6, #60a5fa) !important; }
        }

        // 最终决策卡片
        .final-decision-card {
          margin-top: 16px;
          background: linear-gradient(135deg, #7c2d12 0%, #1c1917 100%);
          border: 1px solid #9a3412;
          border-radius: 16px;
          padding: 24px;
          text-align: left;
          cursor: pointer;
          transition: all 0.35s cubic-bezier(0.16, 1, 0.3, 1);

          &::before {
            background: linear-gradient(135deg, #f97316, #fb923c);
          }

          &:hover {
            transform: translateY(-6px) scale(1.02);
            box-shadow: 0 20px 40px rgba(249, 115, 22, 0.2), 0 4px 12px rgba(249, 115, 22, 0.1);
          }

          .node-icon {
            background: linear-gradient(135deg, rgba(249, 115, 22, 0.2), rgba(251, 146, 60, 0.1));
            box-shadow: 0 2px 8px rgba(249, 115, 22, 0.2);
          }
          .node-name {
            color: #ffedd5;
          }
          .node-desc {
            color: #fdba74;
          }
        }

        // 最终策略阶段
        .phase--final-strategy {
          background: linear-gradient(135deg, #431407 0%, #1c1917 100%);
          border-color: #9a3412;

          .phase-label {
            color: #fdba74;
          }
        }
      }
    }
  }
}

/* 最终决策样式 - 金融专业配色 */
.report-pipeline-intro .final-decision {
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  padding: 28px 32px;
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.06), 0 1px 3px rgba(15, 23, 42, 0.04);
  text-align: center;
  margin-top: 0;
  position: relative;
  overflow: hidden;

  &::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 4px;
    background: linear-gradient(90deg, #3b82f6, #8b5cf6, #ec4899, #f97316, #22c55e);
  }

  .decision-label {
    font-size: 16px;
    font-weight: 700;
    color: #0f172a;
    margin-bottom: 20px;
    letter-spacing: 0.5px;
  }

  .decision-options {
    display: flex;
    justify-content: center;
    gap: 20px;
    margin-bottom: 16px;
    flex-wrap: wrap;
  }

  .decision-chip {
    padding: 14px 32px;
    border-radius: 12px;
    font-size: 18px;
    font-weight: 700;
    letter-spacing: 2px;
    cursor: pointer;
    transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
    border: 2px solid transparent;
    position: relative;
    overflow: hidden;

    &::before {
      content: '';
      position: absolute;
      top: 0;
      left: -100%;
      width: 100%;
      height: 100%;
      background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent);
      transition: left 0.5s ease;
    }

    &:hover::before {
      left: 100%;
    }

    &.decision-chip--buy {
      background: linear-gradient(135deg, #10b981 0%, #059669 100%);
      color: white;
      box-shadow: 0 4px 14px rgba(16, 185, 129, 0.35);
      border-color: #34d399;
    }
    &.decision-chip--overweight {
      background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
      color: white;
      box-shadow: 0 4px 14px rgba(34, 197, 94, 0.35);
      border-color: #86efac;
    }
    &.decision-chip--hold {
      background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
      color: white;
      box-shadow: 0 4px 14px rgba(245, 158, 11, 0.35);
      border-color: #fbbf24;
    }
    &.decision-chip--underweight {
      background: linear-gradient(135deg, #f97316 0%, #ea580c 100%);
      color: white;
      box-shadow: 0 4px 14px rgba(249, 115, 22, 0.35);
      border-color: #fdba74;
    }
    &.decision-chip--sell {
      background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
      color: white;
      box-shadow: 0 4px 14px rgba(239, 68, 68, 0.35);
      border-color: #fca5a5;
    }

    &.is-active {
      transform: scale(1.08);
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
      animation: decisionPulse 0.6s ease-out;
    }

    &.is-disabled {
      opacity: 0.35;
      cursor: not-allowed;
      filter: grayscale(40%);
      transform: scale(0.98);
    }

    &:hover:not(.is-disabled):not(.is-active) {
      transform: translateY(-3px) scale(1.02);
    }
  }

  .decision-desc {
    margin: 0;
    font-size: 13px;
    color: #64748b;
  }
}

html.dark {
  .report-pipeline-intro .final-decision {
    background: linear-gradient(135deg, #1e293b 0%, #1c1917 100%);
    border-color: #334155;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3), 0 1px 3px rgba(0, 0, 0, 0.2);

    .decision-label {
      color: #f8fafc;
    }

    .decision-desc {
      color: #94a3b8;
    }
  }

  // 多维度评分卡片暗色模式
  .report-pipeline-intro .section--scores {
    .section-header {
      border-bottom-color: #334155;
      h3 { color: #f8fafc; }
      .section-subtitle { color: #94a3b8; }
    }
    .dimension-group {
      .dimension-group-title {
        color: #e2e8f0;
        border-left-color: #818cf8;
      }
    }
    .dimension-grid .dimension-card {
      background: #1e293b;
      border-color: #334155;

      .dimension-name {
        color: #f1f5f9;
      }
      .score-unit {
        color: #94a3b8;
      }
      .score-bar {
        background: rgba(15, 23, 42, 0.8);
      }
      .dimension-analyst {
        color: #64748b;
        border-top-color: rgba(71, 85, 105, 0.5);
      }
      .dimension-icon {
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
      }

      &:hover {
        box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4), 0 4px 12px rgba(0, 0, 0, 0.2);
      }

      &.dimension--technical {
        background: linear-gradient(135deg, #422006 0%, #1e293b 100%);
        border-color: #d97706;
        .score-value { color: #fbbf24; }
        .dimension-icon { background: linear-gradient(135deg, rgba(217, 119, 6, 0.25), rgba(251, 191, 36, 0.15)); }
        .score-bar-fill { background: linear-gradient(90deg, #d97706, #fbbf24); }
        &::before { background: #f59e0b; }
      }
      &.dimension--fundamental {
        background: linear-gradient(135deg, #1e1b4b 0%, #1e293b 100%);
        border-color: #6366f1;
        .score-value { color: #a5b4fc; }
        .dimension-icon { background: linear-gradient(135deg, rgba(99, 102, 241, 0.25), rgba(165, 180, 252, 0.15)); }
        .score-bar-fill { background: linear-gradient(90deg, #4f46e5, #818cf8); }
        &::before { background: #6366f1; }
      }
      &.dimension--sentiment {
        background: linear-gradient(135deg, #500724 0%, #1e293b 100%);
        border-color: #ec4899;
        .score-value { color: #f9a8d4; }
        .dimension-icon { background: linear-gradient(135deg, rgba(236, 72, 153, 0.25), rgba(249, 168, 212, 0.15)); }
        .score-bar-fill { background: linear-gradient(90deg, #db2777, #f472b6); }
        &::before { background: #ec4899; }
      }
      &.dimension--news {
        background: linear-gradient(135deg, #422006 0%, #1e293b 100%);
        border-color: #eab308;
        .score-value { color: #fde047; }
        .dimension-icon { background: linear-gradient(135deg, rgba(234, 179, 8, 0.25), rgba(253, 224, 71, 0.15)); }
        .score-bar-fill { background: linear-gradient(90deg, #ca8a04, #facc15); }
        &::before { background: #eab308; }
      }
      &.dimension--capital {
        background: linear-gradient(135deg, #052e16 0%, #1e293b 100%);
        border-color: #22c55e;
        .score-value { color: #86efac; }
        .dimension-icon { background: linear-gradient(135deg, rgba(34, 197, 94, 0.25), rgba(134, 239, 172, 0.15)); }
        .score-bar-fill { background: linear-gradient(90deg, #16a34a, #4ade80); }
        &::before { background: #22c55e; }
      }
      &.dimension--policy {
        background: linear-gradient(135deg, #042f2e 0%, #1e293b 100%);
        border-color: #14b8a6;
        .score-value { color: #5eead4; }
        .dimension-icon { background: linear-gradient(135deg, rgba(20, 184, 166, 0.25), rgba(94, 234, 212, 0.15)); }
        .score-bar-fill { background: linear-gradient(90deg, #0d9488, #2dd4bf); }
        &::before { background: #14b8a6; }
      }
      &.dimension--lockup {
        background: linear-gradient(135deg, #2e1065 0%, #1e293b 100%);
        border-color: #a855f7;
        .score-value { color: #d8b4fe; }
        .dimension-icon { background: linear-gradient(135deg, rgba(168, 85, 247, 0.25), rgba(216, 180, 254, 0.15)); }
        .score-bar-fill { background: linear-gradient(90deg, #9333ea, #c084fc); }
        &::before { background: #a855f7; }
      }
    }
  }

  // 风险扫描卡片暗色模式
  .report-pipeline-intro .section--risk-scan {
    .section-header {
      border-bottom-color: #334155;
      h3 { color: #f8fafc; }
      .section-subtitle { color: #94a3b8; }
    }

    .risk-content {
      .risk-overview {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        border-color: #334155;
      }

      .score-ring {
        .score-text {
          .score-label { color: #94a3b8; }
        }
      }

      .score-stats {
        .stat-item {
          .stat-num { color: #f1f5f9; }
          .stat-label { color: #94a3b8; }
        }
      }

      .risk-categories {
        .risk-category {
          background: #1e293b;
          border-color: #334155;

          &:hover {
            border-color: #475569;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
          }

          .cat-header {
            .cat-name { color: #f1f5f9; }
          }

          .risk-item {
            &.is-risk {
              .item-name { color: #fca5a5; }
              &.has-detail:hover { background: rgba(239, 68, 68, 0.1); }
              &.expanded { background: rgba(239, 68, 68, 0.1); }
            }

            &.is-safe {
              .item-name { color: #d1d5db; }
            }

            .item-detail {
              .item-reason {
                .reason-title { color: #f87171; }
                .reason-content { color: #94a3b8; }
              }
              .sub-items {
                .sub-title { color: #94a3b8; }
                .sub-item.is-risk { color: #fca5a5; .sub-icon { color: #f87171; } }
                .sub-item.is-safe { color: #d1d5db; .sub-icon { color: #34d399; } }
              }
            }
          }

          .safe-items-collapse .el-collapse {
            .el-collapse-item__header {
              background: #1e293b;
              border-color: #475569;
              color: #94a3b8;
            }
          }
        }
      }
    }
  }

  // 置信度评估暗色模式
  .report-pipeline-intro .section--confidence {
    background: linear-gradient(135deg, #0c4a6e 0%, #1e293b 100%);
    border-color: #0369a1;

    .section-header {
      border-bottom-color: #334155;
      h3 { color: #f8fafc; }
      .section-subtitle { color: #94a3b8; }
    }

    .confidence-total {
      background: linear-gradient(135deg, rgba(14, 165, 233, 0.15) 0%, rgba(6, 182, 212, 0.08) 100%);
      border-color: rgba(14, 165, 233, 0.2);

      .confidence-total-score {
        .total-score-value {
          background: linear-gradient(135deg, #38bdf8, #22d3ee);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          background-clip: text;
        }
        .total-score-unit {
          color: #22d3ee;
        }
      }
    }

    .confidence-detail-list .confidence-detail-item {
      background: rgba(15, 23, 42, 0.6);
      border-color: rgba(56, 189, 248, 0.2);

      .detail-item-header {
        .detail-item-name { color: #f1f5f9; }
      }

      .detail-item-bar {
        background: rgba(14, 165, 233, 0.1);
      }

      .detail-item-desc { color: #94a3b8; }

      &.is-full-score {
        background: linear-gradient(135deg, rgba(16, 185, 129, 0.12) 0%, rgba(52, 211, 153, 0.06) 100%);
        border-color: rgba(16, 185, 129, 0.3);

        .detail-item-header .detail-item-score {
          color: #34d399;
        }
      }
    }

    .full-score-collapse .collapse-title {
      color: #34d399;
    }
  }
}

@keyframes decisionPulse {
  0% { transform: scale(1.08); }
  50% { transform: scale(1.12); }
  100% { transform: scale(1.08); }
}

/* 全屏弹窗样式 */
.report-dialog {
  :deep(.el-dialog__header) {
    padding: 0;
    margin: 0;
  }

  :deep(.el-dialog__body) {
    padding: 0;
    height: calc(100vh - 60px);
    overflow: hidden;
  }
}

.dialog-header {
  padding: 20px 32px;
  border-bottom: 1px solid var(--el-border-color);
  background: var(--el-bg-color);

  .dialog-title {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 8px;

    .dialog-icon {
      font-size: 28px;
    }

    .dialog-name {
      font-size: 20px;
      font-weight: 700;
      color: var(--el-text-color-primary);
    }
  }

  .dialog-description {
    font-size: 14px;
    color: var(--el-text-color-secondary);
    padding-left: 40px;
  }
}

.dialog-content-wrapper {
  height: 100%;
  overflow-y: auto;
  padding: 32px;
  background: var(--el-bg-color-page);

  .dialog-report-content {
    max-width: 900px;
    margin: 0 auto;
    background: var(--el-bg-color);
    padding: 40px;
    border-radius: 12px;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
    line-height: 1.8;
    font-size: 14px;
    color: var(--el-text-color-primary);

    :deep(h1), :deep(h2), :deep(h3), :deep(h4), :deep(h5), :deep(h6) {
      margin-top: 24px;
      margin-bottom: 12px;
      color: var(--el-text-color-primary);
    }

    :deep(h1) { font-size: 24px; }
    :deep(h2) { font-size: 20px; }
    :deep(h3) { font-size: 18px; }

    :deep(p) {
      margin-bottom: 12px;
    }

    :deep(ul), :deep(ol) {
      padding-left: 24px;
      margin-bottom: 12px;
    }

    :deep(li) {
      margin-bottom: 6px;
    }

    :deep(table) {
      width: 100%;
      border-collapse: collapse;
      margin-bottom: 16px;
    }

    :deep(th), :deep(td) {
      border: 1px solid var(--el-border-color);
      padding: 8px 12px;
      text-align: left;
    }

    :deep(th) {
      background: var(--el-fill-color-light);
      font-weight: 600;
    }

    :deep(blockquote) {
      border-left: 4px solid var(--el-color-primary);
      margin: 16px 0;
      color: var(--el-text-color-regular);
      background: var(--el-fill-color-light);
      padding: 12px 16px;
      border-radius: 0 8px 8px 0;
    }

    :deep(code) {
      background: var(--el-fill-color);
      padding: 2px 6px;
      border-radius: 4px;
      font-family: monospace;
      font-size: 13px;
    }

    :deep(pre) {
      background: var(--el-fill-color);
      padding: 16px;
      border-radius: 8px;
      overflow-x: auto;
      margin-bottom: 16px;

      :deep(code) {
        background: none;
        padding: 0;
      }
    }
  }

  .dialog-no-content {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 300px;
  }
}
</style>

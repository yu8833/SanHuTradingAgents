<template>
  <div class="war-room app-page">
    <!-- 顶部横幅 -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><Aim /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">今日作战 · {{ todayText }}</h2>
          <p class="page-hero-sub">盘前 / 盘中 / 盘后 / 周度复盘一屏走完</p>
        </div>
      </div>
      <div class="page-hero-meta">
        <el-button type="primary" plain :icon="Refresh" :loading="loading" @click="refreshCurrent">
          刷新
        </el-button>
        <el-button :icon="Setting" @click="goScheduled">任务调度</el-button>
      </div>
    </div>

    <!-- 外层 Tab：今日作战（时段时间线）/ 参考（独立，保持原样） -->
    <el-tabs v-model="outerTab" class="war-tabs" @tab-change="onOuterTabChange">
      <el-tab-pane label="今日作战" name="ops">
      <!-- ============ 时间线 · 盘前 ============ -->
      <section class="tl-period" id="period-pre_market">
        <div class="tl-head" :class="{ on: activeTab === 'pre_market' }" @click="goPeriod('pre_market')">
          <span class="tl-dot">{{ currentPeriod === 'pre_market' ? '●' : '○' }}</span>
          <span class="tl-name">盘前</span>
          <span v-if="todayData?.pre_market?.todo" class="tl-badge">{{ todayData.pre_market.todo }}</span>
          <span class="tl-sub">晨间定方向 · 生成当日计划 · 大盘情势</span>
          <span class="tl-fold-tip">{{ activeTab === 'pre_market' ? '' : '展开 →' }}</span>
        </div>
        <div class="tl-body" v-show="activeTab === 'pre_market'">
          <!-- 盘前决策带：第一眼即知今日方向与待办 -->
          <div class="decision-bar">
            <span class="db-item"><span class="db-k">宏观方向</span><span class="db-v">{{ basis?.status ? statusLabel(basis.status) : '—' }}·{{ basis?.confidence ?? '—' }}%</span></span>
            <span class="db-item"><span class="db-k">待确认候选</span><span class="db-v">{{ planGen?.candidates?.length ?? 0 }}</span></span>
            <span class="db-item"><span class="db-k">卖出观测</span><span class="db-v">{{ planGen?.sell_candidates?.length ?? 0 }}</span></span>
          </div>
        <template v-if="macro">
          <!-- ① 宏观方向判断（置顶大卡） -->
          <section class="block">
            <div class="block-head">
              <span class="block-title"><el-icon><Compass /></el-icon> 宏观方向判断</span>
              <div class="block-actions">
                <span v-if="!macro.llm_available" class="block-hint llm-off">解读不可用（仅规则结果）</span>
                <span class="block-hint">快照生成于 {{ fmtClock(macro.created_at) }}<template v-if="gaugeLocked && basis?.locked_at"> · 方向锁定 {{ fmtClock(basis.locked_at) }}</template> · 点顶部「刷新」更新</span>
              </div>
            </div>
            <!-- 5.2 仪表盘式方向 + 置信度（当日基准静态快照） -->
            <el-card shadow="never" class="direction-dash">
              <div class="dash-top">
                <div class="dash-left">
                  <span class="dir-badge" :class="statusClass(basis?.status)">{{ statusLabel(basis?.status) }}</span>
                  <span class="dash-conf" :class="{ low: basis?.low_confidence }">
                    <span class="conf-num">{{ basis?.confidence ?? 0 }}<b>%</b></span>
                    <span class="conf-label">{{ confidenceLabel() }}</span>
                  </span>
                </div>
                <div class="dash-right">
                  <span class="dash-scale-hint">刻度 = 状态区间 · 指针 = 基准 score 定位</span>
                </div>
              </div>

              <!-- 三段刻度条-偏空─中性─偏多 -->
              <div class="gauge">
                <div class="gauge-track" :class="{ lock: gaugeLocked }">
                  <div class="gauge-seg seg-bear">偏空</div>
                  <div class="gauge-seg seg-neutral">中性</div>
                  <div class="gauge-seg seg-bull">偏多</div>
                  <div class="gauge-pointer" :style="{ left: gaugePos + '%' }">
                    <div class="gauge-needle"></div>
                  </div>
                </div>
                <div class="gauge-scale">
                  <span class="g-scale bear-zone">偏空 · 减仓避离</span>
                  <span class="g-scale neutral-zone">观望 · 不做多空断言</span>
                  <span class="g-scale bull-zone">偏多 · 可进取</span>
                </div>
              </div>

              <!-- 低置信度 / 观望解释 -->
              <div v-if="basis?.low_confidence" class="dash-note">
                <el-icon><WarningFilled /></el-icon>
                置信度 {{ basis?.confidence ?? 0 }}% &lt; 阈值 {{ basis?.confidence_threshold ?? 30 }}%，信号不足以形成强多空断言 → 指针停在「观望」；若执行，仓位减半。
              </div>
              <div v-else-if="basis?.status === '中性(观望)'" class="dash-note" :class="{ reminder: true }">
                <el-icon><WarningFilled /></el-icon>
                各维度信号多空均衡、方向呈中性 → 观望，不做多空强断言；若执行，仓位减半。
              </div>
              <div v-else-if="basis?.status === '数据不足'" class="dash-note"><el-icon><WarningFilled /></el-icon>数据不足，不足以形成方向基准。</div>
            </el-card>

            <!-- 5.1 方向拆解面板（信号溯源，可折叠：先看结论，需要时再逐条复核依据） -->
            <el-collapse v-model="signalCollapse" class="signal-collapse">
              <el-collapse-item name="signals">
                <template #title>
                  <span class="panel-collapse-title">
                    <el-icon><Magnet /></el-icon>
                    <span class="panel-title-inline">方向拆解 · 信号溯源</span>
                    <span class="panel-score">规则总分 <b>{{ rule?.score ?? 0 }}</b></span>
                    <span class="panel-hint">每只信号：数值 / 权重 / 判定 / 如何影响方向</span>
                  </span>
                </template>
                <div v-if="rule?.signals?.length" class="signal-panel">
                  <div v-for="(s, i) in signalRows" :key="i" class="signal-row">
                    <span class="sig-name">{{ s.name }}</span>
                    <span class="sig-value" :class="sigValueClass(s)">{{ sigValueText(s) }}</span>
                    <span class="sig-weight">权重 {{ s.weight ?? 0 }}</span>
                    <span class="sig-judge" :class="judgeClass(s.judge)">{{ judgeLabel(s.judge) }}</span>
                    <span class="sig-score" :class="s.score > 0 ? 'up' : s.score < 0 ? 'down' : ''">
                      {{ s.score > 0 ? `+${s.score}` : s.score }}
                    </span>
                    <span class="sig-explain">{{ s.detail || '—' }}</span>
                  </div>
                </div>
                <el-empty v-else :image-size="40" description="暂无规则依据" />
              </el-collapse-item>
            </el-collapse>
            <div v-if="llm" class="llm-card">
              <div class="llm-sec">
                <div class="llm-tag">今日关键词</div>
                <div class="llm-body">
                  <template v-if="llm.keywords?.length">
                    <span v-for="(k, i) in llm.keywords" :key="i" class="llm-kw">{{ k }}</span>
                  </template>
                  <span v-else>—</span>
                </div>
              </div>
              <div class="llm-sec">
                <div class="llm-tag">事件影响</div>
                <div class="llm-body">
                  <div v-for="(line, i) in splitItems(llm.event_impact)" :key="'ei' + i" class="llm-line">{{ line }}</div>
                  <span v-if="!llm.event_impact">—</span>
                </div>
              </div>
              <div class="llm-sec">
                <div class="llm-tag">风格倾向</div>
                <div class="llm-body">
                  <div v-for="(line, i) in splitItems(llm.style_tendency)" :key="'st' + i" class="llm-line">{{ line }}</div>
                  <span v-if="!llm.style_tendency">—</span>
                </div>
              </div>
              <div class="llm-sec">
                <div class="llm-tag">风险提示</div>
                <div class="llm-body risk">
                  <div v-for="(line, i) in splitItems(llm.risk_tips)" :key="'rt' + i" class="llm-line">{{ line }}</div>
                  <span v-if="!llm.risk_tips">—</span>
                </div>
              </div>
            </div>
          </section>
        </template>

        <template v-else-if="macroRefreshing">
          <el-empty loading description="正在生成今日宏观快照…" />
        </template>
        <el-empty v-else-if="macroAutoGenerating" loading description="今日宏观快照缺失，正在后台自动生成…" />
        <el-empty v-else-if="!loading" description="今日宏观快照未生成">
          <el-button size="small" type="primary" :icon="Refresh" :loading="macroRefreshing" @click="refreshMacro">立即生成</el-button>
        </el-empty>

        <!-- ② 当日计划生成流水线（5.3 带审计痕迹） -->
        <section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><Operation /></el-icon> 当日计划生成流水线</span>
            <div class="block-actions">
              <span v-if="planGen && (planGen.candidates_count ?? 0) > 0" class="block-hint">候选 {{ planGen.candidates_count }} 条 · 待人工确认</span>
              <span v-else-if="planGen?.filtered_count > 0" class="block-hint">已自动生成 · 候选已全部确认/过滤（{{ planGen.filtered_count }} 条）</span>
              <span v-else-if="planGen" class="block-hint">今日快照已生成 · 暂无候选</span>
              <el-button size="small" type="primary" :icon="MagicStick" :class="{ 'is-generating': genPlanLoading }" @click="generatePlan">
                {{ genPlanLoading ? '生成中…' : (planGen ? '重新生成' : '生成当日计划') }}
              </el-button>
            </div>
          </div>

          <template v-if="planGen?.audit?.steps?.length">
            <el-collapse v-model="planAuditCollapse" class="plan-audit-collapse">
              <el-collapse-item name="audit">
                <template #title>
                  <span class="audit-collapse-title">
                    五段决策漏斗（环境 → 行业 → 个股 → 计划 → 卖出）
                    <span class="audit-summary" v-if="planGen.generated_at">生成于 {{ fmtClock(planGen.generated_at) }}</span>
                  </span>
                </template>
                <div class="pipeline">
                  <template v-for="(st, i) in planGen.audit.steps" :key="i">
                    <div class="pipeline-step" :class="'p-step-' + pipelineKey(st.step)">
                      <div class="p-step-top">
                        <span class="p-step-name">{{ stepLabel(st.step) }}</span>
                        <span class="p-step-count">
                          扫描 <b>{{ st.scanned }}</b>
                          <template v-if="st.dropped"> → 保留 <b class="kept">{{ st.kept }}</b></template>
                        </span>
                      </div>
                      <div class="p-step-rule">{{ st.rule }}</div>
                      <div class="p-step-bar">
                        <span class="fill" :style="{ width: keptPct(st) + '%' }"></span>
                      </div>
                      <div class="p-step-reasons">
                        <span v-for="(r, ri) in st.reasons" :key="ri" class="p-reason">
                          <span class="r-dot"></span>{{ r }}
                        </span>
                      </div>
                    </div>
                    <div v-if="i < planGen.audit.steps.length - 1" class="pipeline-arrow">
                      <el-icon><Right /></el-icon>
                    </div>
                  </template>
                </div>
                <p class="pipeline-tip">
                  <el-icon><InfoFilled /></el-icon>
                  四段从「环境 → 行业 → 个股 → 计划」，每段展示扫描与过滤漏斗；宏观方向显式标注为过滤条件，非黑箱。
                </p>
                <!-- 行业方向预测 → 当日预测行业池（Stage2/Stage3 产品化展示） -->
                <div v-if="planGen?.industries?.length" class="ind-strip">
                  <span class="ind-strip-label">预测行业池</span>
                  <el-tag v-for="(ind, ii) in planGen.industries" :key="ii" size="small" type="info" effect="plain" class="ind-tag">
                    {{ ind.industry }} · {{ ind.confidence }}%
                  </el-tag>
                </div>
                <!-- 快照已自动生成、但候选被「当日计划去重」全部过滤时，明确说明而非让用户误以为没自动执行 -->
                <div v-if="planGen?.filtered_count > 0 && !planGen?.candidates?.length" class="plan-filtered-note">
                  <el-icon><InfoFilled /></el-icon>
                  盘前 8:15 已自动生成当日计划（共 {{ planGen.filtered_count }} 条候选），因其中标的已在你当日计划中确认/添加，此处不再重复展示。
                  如需重新运行流水线，可点右上角「重新生成」。
                </div>
              </el-collapse-item>
            </el-collapse>
          </template>
          <el-empty v-else :image-size="48" description="点击「生成当日计划」，查看 环境 → 行业 → 个股 → 计划 → 卖出 五段决策过程与过滤漏斗" />
        </section>

        <!-- ③ 待确认计划候选（5.4 来源 + 人工最后一道闸） -->
        <section class="block" v-if="planGen?.candidates?.length">
          <div class="block-head">
            <span class="block-title"><el-icon><Checked /></el-icon> 待确认计划候选</span>
            <span class="block-hint">自动生成 ≠ 自动下单 · 确认后写入当日计划</span>
          </div>
          <div class="cand-grid">
            <el-card v-for="(c, ci) in planGen.candidates" :key="c.code + ci" shadow="never" class="cand-card">
              <div class="cand-head">
                <span class="cand-name">
                  <a :href="stockHref(c.code)" target="_blank" rel="noopener" class="stock-link stock-code">{{ c.code }}</a>
                  <a :href="stockHref(c.code)" target="_blank" rel="noopener" class="stock-link">{{ c.name || c.code }}</a>
                </span>
                <span class="cand-meta">
                  <span v-if="c.hit_rate != null" class="cand-hit" :class="hitRateCls(c.hit_rate)" :title="'该信号历史命中率（' + (c.signal_count || 0) + ' 个已回填样本）'">
                    信效 {{ c.hit_rate }}%（{{ c.signal_count }}）
                  </span>
                  <span class="cand-sig" v-if="c.signal_label">{{ c.signal_label }}</span>
                </span>
              </div>
              <div class="cand-source" v-if="c.source?.label">
                <span class="src-dot"></span>{{ c.source.label }}
              </div>
              <div class="cand-fields">
                <div class="fld"><span class="k">触发价</span><span class="v">{{ c.trigger_price }}</span></div>
                <div class="fld"><span class="k">止损</span><span class="v down">{{ c.stop_loss }}</span></div>
                <div class="fld"><span class="k">卖出</span><span class="v">{{ shortSell(c.sell_condition) }}</span></div>
                <div class="fld"><span class="k">仓位</span><span class="v">{{ positionText(c.position) }}</span></div>
              </div>
              <div class="cand-actions">
                <el-button size="small" type="primary" :loading="confirmingIdx === ci" @click="confirmCandidate(ci)">确认写库</el-button>
                <el-button size="small" @click="editCandidate(ci)">改价</el-button>
                <el-button size="small" type="danger" plain @click="removeCandidate(ci)">删</el-button>
              </div>
            </el-card>
          </div>
        </section>

        <!-- ④ 今日卖出观测（持仓卖出评估：哪些需要卖 / 减仓 / 止损止盈） -->
        <section class="block" v-if="planGen?.sell_candidates?.length">
          <div class="block-head">
            <span class="block-title"><el-icon><Sell /></el-icon> 今日卖出观测</span>
            <span class="block-hint">持仓卖出评估（止损/止盈 + 三买三卖卖点）· 确认后写入当日计划</span>
          </div>
          <el-table v-loading="genPlanLoading" :data="planGen.sell_candidates" stripe size="small" class="app-table app-table--compact">
            <el-table-column label="代码" width="100">
              <template #default="{ row }">
                <a :href="stockHref(row.code)" target="_blank" rel="noopener" class="stock-link stock-code">{{ row.code }}</a>
              </template>
            </el-table-column>
            <el-table-column label="名称" min-width="110">
              <template #default="{ row }">
                <a :href="stockHref(row.code)" target="_blank" rel="noopener" class="stock-link">{{ row.name || row.code }}</a>
              </template>
            </el-table-column>
            <el-table-column label="建议" width="110">
              <template #default="{ row }">
                <span class="sell-advice" :class="sellAdviceTagClass(row)">{{ row.signal_label || row.advice_label || '卖出' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="参考价" width="90">
              <template #default="{ row }">{{ row.last_price ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="盈亏率" width="100">
              <template #default="{ row }">
                <span v-if="row.profit_loss_rate != null" :class="clsByVal(row.profit_loss_rate, '')">{{ fmtPct(row.profit_loss_rate) }}</span>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column label="卖出触发价" width="100">
              <template #default="{ row }">{{ row.trigger_price ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="原因" min-width="170" show-overflow-tooltip>
              <template #default="{ row }">{{ row.reason || row.sell_condition || '—' }}</template>
            </el-table-column>
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row, $index }">
                <el-button size="small" type="danger" plain :loading="confirmingSellIdx === $index" @click="confirmSellCandidate($index)">确认卖出</el-button>
                <el-button size="small" @click="removeSellCandidate($index)">否</el-button>
              </template>
            </el-table-column>
          </el-table>
        </section>

        <!-- ⑤ 当日计划 -->
        <section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><Tickets /></el-icon> 当日计划</span>
            <el-button size="small" type="primary" :icon="Plus" @click="openPlanDialog">添加计划</el-button>
          </div>
          <el-table v-loading="plansLoading" :data="plans" stripe size="small" class="app-table app-table--compact">
            <el-table-column label="代码" width="100">
              <template #default="{ row }">
                <a :href="stockHref(row.code)" target="_blank" rel="noopener" class="stock-link stock-code">{{ row.code }}</a>
              </template>
            </el-table-column>
            <el-table-column label="名称" min-width="100">
              <template #default="{ row }">
                <a :href="stockHref(row.code)" target="_blank" rel="noopener" class="stock-link">{{ row.name || row.code }}</a>
              </template>
            </el-table-column>
            <el-table-column label="来源" min-width="150">
              <template #default="{ row }">
                <span v-if="row.source?.label" class="plan-source">
                  <span class="src-dot"></span>{{ row.source.label }}
                </span>
                <span v-else class="plan-source manual"><span class="src-dot"></span>手动添加</span>
              </template>
            </el-table-column>
            <!-- 周度信号有效性：历史命中率突出展示（有数据才显示该列） -->
            <el-table-column v-if="hasPlanHitRate" label="信效" width="92">
              <template #default="{ row }">
                <span v-if="row.hit_rate != null" class="cand-hit" :class="hitRateCls(row.hit_rate)" :title="'该信号历史命中率（' + (row.signal_count || 0) + ' 个已回填样本）'">
                  信效 {{ row.hit_rate }}%（{{ row.signal_count }}）
                </span>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column label="方向" width="70">
              <template #default="{ row }">
                <span :class="row.direction === 'buy' ? 'up' : 'down'">{{ row.direction_label }}</span>
              </template>
            </el-table-column>
            <el-table-column label="触发价" width="90">
              <template #default="{ row }">{{ row.trigger_price ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="仓位" width="100">
              <template #default="{ row }">{{ positionText(row.position) }}</template>
            </el-table-column>
            <el-table-column prop="stop_loss" label="止损" width="90">
              <template #default="{ row }">{{ row.stop_loss ?? '—' }}</template>
            </el-table-column>
            <el-table-column prop="sell_condition" label="卖出条件" min-width="140" show-overflow-tooltip />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="planStatusTag(row)">{{ planStatusLabel(row) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button v-if="row.status === 'pending'" size="small" link type="primary" @click="editPlan(row)">改价</el-button>
                <el-button v-if="row.status === 'pending' && !row.confirmed" size="small" link type="primary" :loading="confirmingPlanId === row.id" @click="confirmPlanWrite(row)">确认</el-button>
                <el-button v-if="row.status === 'pending'" size="small" link type="danger" @click="removePlan(row)">删除</el-button>
                <span v-if="row.status !== 'pending'" class="no-op">—</span>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!plans.length" description="今日暂无计划：可点「生成当日计划」自动装配，或手动添加" />
        </section>
        </div><!-- /tl-body -->
        <div v-if="activeTab !== 'pre_market'" class="tl-folder" @click="goPeriod('pre_market')">
          <span class="tf-main">当日计划待确认 {{ plans.filter(p => p.status === 'pending').length }} · 宏观 {{ basis?.status ? statusLabel(basis.status) : '—' }}</span>
          <span class="tf-tip">点击回看 →</span>
        </div>
      </section><!-- /盘前 -->

      <!-- ============ 时间线 · 盘中 ============ -->
      <section class="tl-period" id="period-intraday">
        <div class="tl-head" :class="{ on: activeTab === 'intraday' }" @click="goPeriod('intraday')">
          <span class="tl-dot">{{ currentPeriod === 'intraday' ? '●' : '○' }}</span>
          <span class="tl-name">盘中</span>
          <span v-if="todayData?.intraday?.todo" class="tl-badge">{{ todayData.intraday.todo }}</span>
          <span class="tl-sub">买卖点实时指导 · 每 30s 刷新</span>
          <span class="tl-fold-tip">{{ activeTab === 'intraday' ? '' : '展开 →' }}</span>
        </div>
        <div class="tl-body" v-show="activeTab === 'intraday'">
        <section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><Odometer /></el-icon> 买卖点实时指导
              <span v-if="intradayExecutable > 0" class="exec-badge">待执行 {{ intradayExecutable }}</span>
            </span>
            <div class="block-actions">
              <span v-if="guide?.as_of" class="block-hint">评估于 {{ guide.as_of }} · 盘中每 30s 自动刷新 · 点顶部「刷新」手动更新</span>
            </div>
          </div>

          <el-alert v-if="quotesUnavailable" type="warning" :closable="false" show-icon style="margin-bottom: 12px">
            实时行情暂不可用，以下卖出建议基于信号快照价（止损/止盈实时触发不可用），可点「对照实时价评估」重试。
          </el-alert>

          <!-- 买入建议（未买入的股票：什么时候适合买） -->
          <div class="sub-block">
            <div class="sub-title"><el-icon><ShoppingCart /></el-icon> 买入建议 · 何时买
              <span v-if="guideBuys.length" class="guide-count">{{ guideBuys.length }}</span>
              <span class="block-hint">距触发价：负值 = 已低于触发价</span>
            </div>
            <el-table v-loading="guideLoading" :data="guideBuys" stripe size="small" class="app-table app-table--compact" max-height="320">
              <el-table-column label="代码" width="100">
                <template #default="{ row }">
                  <a :href="stockHref(row.code)" target="_blank" rel="noopener" class="stock-link stock-code">{{ row.code }}</a>
                </template>
              </el-table-column>
              <el-table-column label="名称" min-width="110">
                <template #default="{ row }">
                  <a :href="stockHref(row.code)" target="_blank" rel="noopener" class="stock-link">{{ row.name || row.code }}</a>
                </template>
              </el-table-column>
              <el-table-column label="信号" width="90">
                <template #default="{ row }">{{ row.signal_label || '计划' }}</template>
              </el-table-column>
              <el-table-column label="触发价" width="90">
                <template #default="{ row }">{{ row.trigger_price ?? '—' }}</template>
              </el-table-column>
              <el-table-column label="实时价" width="90">
                <template #default="{ row }">{{ row.last_price ?? '—' }}</template>
              </el-table-column>
              <el-table-column label="距触发价" width="90">
                <template #default="{ row }">
                  <span v-if="row.distance_pct != null" :class="clsByVal(-row.distance_pct, '')">{{ fmtPct(row.distance_pct) }}</span>
                  <span v-else>—</span>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="90">
                <template #default="{ row }">
                  <el-tag v-if="row.confirmed === false" type="warning" size="small">待确认</el-tag>
                  <el-tag v-else-if="row.triggered" type="danger" size="small">可执行</el-tag>
                  <el-tag v-else type="info" size="small">待触达</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="advice" label="建议" min-width="170" show-overflow-tooltip />
              <el-table-column label="操作" width="100">
                <template #default="{ row }">
                  <el-button v-if="row.triggered && row.confirmed !== false" size="small" type="primary" @click="goTrade(row)">去交易</el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-if="!guideBuys.length" :image-size="48" description="今日暂无待买入计划/候选，可到盘前 Tab 生成当日计划" />
          </div>

          <!-- 卖出建议（已买入的股票：是否卖 / 什么时候卖） -->
          <div class="sub-block">
            <div class="sub-title"><el-icon><Sell /></el-icon> 卖出建议 · 是否卖 / 何时卖
              <span v-if="guideSells.length" class="guide-count">{{ guideSells.length }}</span>
            </div>
            <el-table v-loading="guideLoading" :data="guideSells" stripe size="small" class="app-table app-table--compact" max-height="360">
              <el-table-column label="代码" width="100">
                <template #default="{ row }">
                  <a :href="stockHref(row.code)" target="_blank" rel="noopener" class="stock-link stock-code">{{ row.code }}</a>
                </template>
              </el-table-column>
              <el-table-column label="名称" min-width="100">
                <template #default="{ row }">
                  <a :href="stockHref(row.code)" target="_blank" rel="noopener" class="stock-link">{{ row.name || row.code }}</a>
                </template>
              </el-table-column>
              <!-- 操作指导：怎么做（卖多少/清仓/持有）+ 什么时候动手（触发价），放在最前 -->
              <el-table-column label="如何操作" width="150">
                <template #default="{ row }">
                  <template v-if="row.sell_pct != null && row.sell_pct > 0">
                    <el-tag size="small" :type="sellAdviceType(row)">{{ row.advice_label || '卖出' }}</el-tag>
                    <div class="sell-act">卖出 <b>{{ Math.round(row.sell_pct * 100) }}%</b> 持仓</div>
                  </template>
                  <el-tag v-else size="small" type="info">{{ row.advice_label || '持有' }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="卖出触发价" width="100">
                <template #default="{ row }">{{ row.trigger_price ?? '—' }}</template>
              </el-table-column>
              <el-table-column prop="reason" label="操作原因" min-width="190" show-overflow-tooltip />
              <el-table-column label="现价" width="90">
                <template #default="{ row }">{{ row.last_price ?? '—' }}</template>
              </el-table-column>
              <el-table-column label="盈亏率" width="100">
                <template #default="{ row }">
                  <span v-if="row.profit_loss_rate != null" :class="clsByVal(row.profit_loss_rate, '')">{{ fmtPct(row.profit_loss_rate) }}</span>
                  <span v-else>—</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="130" fixed="right">
                <template #default="{ row }">
                  <el-button v-if="row.sell_pct != null && row.sell_pct > 0" size="small" type="danger" plain @click="addSellToPlan(row)">加卖出计划</el-button>
                  <el-button v-else size="small" text disabled>持有中</el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-if="!guideSells.length" :image-size="48" description="暂无持仓，无需卖出评估" />
          </div>
        </section>
        </div><!-- /tl-body -->
        <div v-if="activeTab !== 'intraday'" class="tl-folder" @click="goPeriod('intraday')">
          <span class="tf-main">待执行指令 {{ intradayExecutable }} · 买卖点 {{ guideBuys.length + guideSells.length }} 条</span>
          <span class="tf-tip">点击回看 →</span>
        </div>
      </section><!-- /盘中 -->

      <!-- ============ 时间线 · 盘后 ============ -->
      <section class="tl-period" id="period-post_market">
        <div class="tl-head" :class="{ on: activeTab === 'post_market' }" @click="goPeriod('post_market')">
          <span class="tl-dot">{{ currentPeriod === 'post_market' ? '●' : '○' }}</span>
          <span class="tl-name">盘后</span>
          <span v-if="todayData?.post_market?.todo" class="tl-badge">{{ todayData.post_market.todo }}</span>
          <span class="tl-sub">交易复盘 · 信号验证 · 明日计划预填</span>
          <span class="tl-fold-tip">{{ activeTab === 'post_market' ? '' : '展开 →' }}</span>
        </div>
        <div class="tl-body" v-show="activeTab === 'post_market'">
          <!-- 盘后决策带：当日结果一目了然 -->
          <div class="decision-bar">
            <span class="db-item"><span class="db-k">今日成交</span><span class="db-v">{{ todayTrades.length }} 笔</span></span>
            <span class="db-item"><span class="db-k">当日盈亏</span><span class="db-v">{{ todayTradesPnl != null ? fmtSigned(todayTradesPnl) : '—' }}</span></span>
            <span class="db-item"><span class="db-k">信号待验证</span><span class="db-v">{{ signalStats?.pending_count ?? 0 }}</span></span>
            <span class="db-item"><span class="db-k">信号胜率</span><span class="db-v">{{ signalStats?.total?.win_rate != null ? fmtPct(signalStats.total.win_rate) : '—' }}</span></span>
          </div>
        <!-- ① 交易复盘 · 当日成交（盘后首位，先看结果） -->
        <section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><Document /></el-icon> 交易复盘 · 当日成交</span>
            <router-link to="/paper/review" class="more-link">交易复盘页 →</router-link>
          </div>
          <el-table v-loading="tradesLoading" :data="todayTrades" stripe size="small" class="app-table app-table--compact" max-height="360">
            <el-table-column label="代码" width="100">
              <template #default="{ row }">
                <a :href="stockHref(row.code)" target="_blank" rel="noopener" class="stock-link stock-code">{{ row.code }}</a>
              </template>
            </el-table-column>
            <el-table-column label="名称" min-width="120">
              <template #default="{ row }">
                <a :href="stockHref(row.code)" target="_blank" rel="noopener" class="stock-link">{{ row.name || row.code }}</a>
              </template>
            </el-table-column>
            <el-table-column label="方向" width="80">
              <template #default="{ row }">
                <span :class="row.side === 'buy' ? 'up' : 'down'">{{ row.side === 'buy' ? '买入' : '卖出' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="数量" width="90">
              <template #default="{ row }">{{ row.quantity }}</template>
            </el-table-column>
            <el-table-column label="价格" width="100">
              <template #default="{ row }">{{ row.price ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="金额" width="120">
              <template #default="{ row }">{{ row.amount != null ? Number(row.amount).toFixed(2) : '—' }}</template>
            </el-table-column>
            <el-table-column label="盈亏" width="110">
              <template #default="{ row }">
                <span v-if="row.pnl != null" :class="clsByVal(row.pnl, '')">{{ fmtSigned(row.pnl) }}</span>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column prop="strategy" label="策略" width="100" />
            <el-table-column label="时间" min-width="150">
              <template #default="{ row }">{{ tradeTime(row.timestamp) }}</template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!todayTrades.length" :image-size="48" description="今日暂无成交记录" />
          <p class="block-tip" style="margin-top: 10px">盘后 Step1 更新数据 · Step2 信号扫描落库 · Step3 次日计划预填，见上方信号跟踪与盘前 Tab 计划。</p>
        </section><!-- ② 次日计划预填（接近买点标的 → 一键加入计划；数据源 = 信号跟踪） -->
        <section class="block" v-if="prefillItems.length">
          <div class="block-head">
            <span class="block-title"><el-icon><Tickets /></el-icon> 次日计划预填</span>
            <span class="block-hint">来自信号跟踪 · 待验证买点信号，点击卡片加入明日计划</span>
          </div>
          <div class="scan-prefill-grid">
            <div v-for="row in prefillItems" :key="row.code" class="prefill-card" @click="addScanToPlan(row)">
              <div class="prefill-name">
                <a :href="stockHref(row.code)" target="_blank" rel="noopener" class="stock-link stock-code">{{ row.code }}</a>
                <a :href="stockHref(row.code)" target="_blank" rel="noopener" class="stock-link">{{ row.name }}</a>
              </div>
              <div class="prefill-line">触发 <b>{{ row.signal_price ?? row.signals?.[0]?.trigger_price ?? row.close ?? '—' }}</b> · 止损 {{ row.snapshot?.stop_price ?? row.stop_price ?? '—' }}</div>
              <div class="prefill-line sub">{{ row.signal_label || row.primary_signal_label || '三买三卖' }} · BIAS60 {{ row.snapshot?.bias60?.toFixed(2) ?? row.bias60?.toFixed(2) }}</div>
            </div>
          </div>
        </section><section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><Search /></el-icon> 信号跟踪</span>
            <div class="block-actions">
              <el-button size="small" type="primary" :loading="backfillLoading" @click="triggerBackfill">回填到期信号</el-button>
            </div>
          </div>
          <div class="kpi-row" v-if="signalStats?.total">
            <div class="kpi-cell">
              <div class="kpi-label">累计已回填</div>
              <div class="kpi-value" :title="`已回填样本数：${signalStats.total.count ?? 0}（按钮提示的 N 条为本次回填数）`">{{ signalStats.total.count ?? signalStats.total?.count ?? 0 }}</div>
            </div>
            <div class="kpi-cell">
              <div class="kpi-label">胜率</div>
              <div class="kpi-value up">{{ fmtPct(signalStats.total.win_rate) }}</div>
            </div>
            <div class="kpi-cell">
              <div class="kpi-label">待验证</div>
              <div class="kpi-value">{{ signalStats.pending_count ?? 0 }}</div>
            </div>
          </div>
          <el-table v-loading="signalsLoading" :data="signals" stripe size="small" class="app-table app-table--compact" max-height="420">
            <el-table-column prop="signal_type" label="信号" width="90" />
            <el-table-column label="代码" width="100">
              <template #default="{ row }">
                <a :href="stockHref(row.code)" target="_blank" rel="noopener" class="stock-link stock-code">{{ row.code }}</a>
              </template>
            </el-table-column>
            <el-table-column label="名称" min-width="110">
              <template #default="{ row }">
                <a :href="stockHref(row.code)" target="_blank" rel="noopener" class="stock-link">{{ row.name || row.code }}</a>
              </template>
            </el-table-column>
            <el-table-column prop="trigger_date" label="触发日" width="110" />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="row.status === 'filled' ? 'success' : 'info'">
                  {{ row.status === 'filled' ? '已回填' : '待验证' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="实际表现" min-width="140">
              <template #default="{ row }">
                <template v-if="row.filled">
                  <span :class="clsByVal(row.filled.ret, '')">{{ fmtPct(row.filled.ret) }}</span>
                  <span class="sep">·</span>
                  <span :class="row.filled.outcome === 'win' ? 'up' : row.filled.outcome === 'loss' ? 'down' : ''">{{ outcomeLabel(row.filled.outcome) }}</span>
                  <span v-if="row.filled.hit_stop" class="hit-stop">触止损</span>
                </template>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column label="快照" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">{{ snapshotText(row.snapshot) }}</template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!signals.length" :image-size="48" description="暂无信号记录，三买三卖扫描后自动落库" />
        </section><section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><MagicStick /></el-icon> 信号扫描结果</span>
            <el-button size="small" type="primary" :icon="Search" :loading="scanLoading" @click="runScan">
              运行三买三卖扫描（自动落库）
            </el-button>
          </div>
          <div v-if="scanResult" class="scan-summary">
            <span>共 <b>{{ scanResult.total }}</b> 只命中<template v-if="scanResult.scanned_count"> · 扫描 {{ scanResult.scanned_count }} 只</template></span>
            <span v-if="scanResult.market_trend"> · 大盘趋势 {{ scanResult.market_trend }}</span>
          </div>
          <el-alert v-if="scanTodaysCount > 0" type="info" :closable="false" show-icon style="margin-bottom: 10px">
            今日已有 {{ scanTodaysCount }} 条买点信号自动落库「信号跟踪」（盘后 16:00 自动扫描）；如需刷新数据可重新扫描。
          </el-alert>
          <el-table v-loading="scanLoading" :data="scanResult?.items || []" stripe size="small" class="app-table app-table--compact" max-height="420">
            <el-table-column label="代码" width="100">
              <template #default="{ row }">
                <a :href="stockHref(row.code)" target="_blank" rel="noopener" class="stock-link stock-code">{{ row.code }}</a>
              </template>
            </el-table-column>
            <el-table-column label="名称" min-width="110">
              <template #default="{ row }">
                <a :href="stockHref(row.code)" target="_blank" rel="noopener" class="stock-link">{{ row.name || row.code }}</a>
              </template>
            </el-table-column>
            <el-table-column prop="primary_signal_label" label="信号" width="100" />
            <el-table-column label="收盘" width="90">
              <template #default="{ row }">{{ row.close ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="BIAS60" width="90">
              <template #default="{ row }">{{ row.bias60?.toFixed(2) ?? '—' }}</template>
            </el-table-column>
            <el-table-column prop="ma60_direction" label="MA60" width="80" />
            <el-table-column label="触发价" width="90">
              <template #default="{ row }">{{ row.signals?.[0]?.trigger_price ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button size="small" :icon="Plus" @click="addScanToPlan(row)">加入计划</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!scanResult" :image-size="48" description="点击上方按钮运行盘后信号扫描，命中信号自动写入「信号跟踪」" />
        </section>
        </div><!-- /tl-body -->
        <div v-if="activeTab !== 'auto'" placeholder @click="goPeriod('post_market')">
          <span class="tf-main">今日成交 {{ todayTrades.length }} 笔 · 信号待验证 {{ signalStats?.pending_count ?? 0 }}</span>
          <span class="tf-tip">点击回看 →</span>
        </div>
      </section><!-- /盘后 -->

      <!-- ============ 时间线 · 周度 ============ -->
      <section class="tl-period" id="period-weekly">
        <div class="tl-head" :class="{ on: activeTab === 'weekly' }" @click="goPeriod('weekly')">
          <span class="tl-dot">{{ currentPeriod === 'weekly' ? '●' : '○' }}</span>
          <span class="tl-name">周度</span>
          <span v-if="todayData?.weekly?.todo" class="tl-badge">{{ todayData.weekly.todo }}</span>
          <span class="tl-sub">定量统计 · 信号有效性 · 定性回顾</span>
          <span class="tl-fold-tip">{{ activeTab === 'weekly' ? '' : '展开 →' }}</span>
        </div>
        <div class="tl-body" v-show="activeTab === 'weekly'">
          <!-- 周度决策带：本周结果汇总 -->
          <div class="decision-bar">
            <span class="db-item"><span class="db-k">本周收益率</span><span class="db-v">{{ weekly?.quant?.weekly_return != null ? fmtPct(weekly.quant.weekly_return) : '—' }}</span></span>
            <span class="db-item"><span class="db-k">vs 沪深300</span><span class="db-v">{{ weekly?.excess_return != null ? fmtPct(weekly.excess_return) : '—' }}</span></span>
            <span class="db-item"><span class="db-k">胜率</span><span class="db-v">{{ weekly?.quant?.win_rate != null ? fmtPct(weekly.quant.win_rate) : '—' }}</span></span>
            <span class="db-item"><span class="db-k">交易笔数</span><span class="db-v">{{ weekly?.quant?.trade_count ?? '—' }}</span></span>
          </div>
        <section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><Histogram /></el-icon> 定量统计</span>
            <div class="block-actions">
              <span v-if="weekly" class="block-hint">数据周 {{ weekly.week_start }} ~ {{ weekly.week_end }}<template v-if="!isCurrentWeek">（历史周）</template></span>
              <el-button v-if="!weekly" size="small" type="primary" :loading="genWeeklyLoading" @click="generateWeekly">
                生成周报
              </el-button>
              <el-button v-else size="small" :icon="Refresh" :loading="genWeeklyLoading" @click="generateWeekly">
                {{ isCurrentWeek ? '重新生成' : '生成本周复盘' }}
              </el-button>
            </div>
          </div>
          <el-alert v-if="weekly && !isCurrentWeek" type="warning" :closable="false" show-icon style="margin-bottom: 12px">
            当前展示为 {{ weekly.week_start }} 起的复盘（本周复盘尚未生成），可点右上角「生成本周复盘」，或等待周五 17:30 自动生成。
          </el-alert>
          <template v-if="weekly">
            <div class="kpi-row">
              <div class="kpi-cell" title="本周已实现盈亏 ÷ 当前总权益（近似口径，未计浮动盈亏变动）">
                <div class="kpi-label">本周收益率</div>
                <div class="kpi-value" :class="clsByVal(weekly.quant?.weekly_return, '')">{{ fmtPct(weekly.quant?.weekly_return) }}</div>
              </div>
              <div class="kpi-cell">
                <div class="kpi-label">vs 沪深300</div>
                <div class="kpi-value" :class="clsByVal(weekly.excess_return, '')">{{ fmtPct(weekly.excess_return) }}</div>
                <div class="kpi-sub">基准 {{ fmtPct(weekly.benchmark?.ret_pct) }}</div>
              </div>
              <div class="kpi-cell">
                <div class="kpi-label">交易笔数</div>
                <div class="kpi-value">{{ weekly.quant?.trade_count }}</div>
              </div>
              <div class="kpi-cell">
                <div class="kpi-label">胜率</div>
                <div class="kpi-value" :class="clsByVal(weekly.quant?.win_rate, '')">{{ fmtPct(weekly.quant?.win_rate) }}</div>
                <div class="kpi-sub">{{ weekly.quant?.win_count }}/{{ weekly.quant?.sell_count }} 笔盈利</div>
              </div>
              <div class="kpi-cell">
                <div class="kpi-label">持仓全红率</div>
                <div class="kpi-value" :class="clsByVal(weekly.quant?.all_red_rate, '')">{{ fmtPct(weekly.quant?.all_red_rate) }}</div>
                <div class="kpi-sub">{{ weekly.quant?.profitable_count }}/{{ weekly.quant?.holding_count }} 持仓</div>
              </div>
            </div>
            <div v-if="!weekly.benchmark?.available" class="benchmark-warn">
              <el-icon><Warning /></el-icon> 沪深300 数据不可用：{{ weekly.benchmark?.message }}
            </div>
          </template>
          <el-empty v-else :image-size="48" description="本周复盘待生成（顶部「周度」待办 1）：周五盘后自动生成，或点右上角立即生成" />
        </section><section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><Calendar /></el-icon> 下周计划</span>
            <router-link to="/war-room?tab=pre_market" class="more-link">去盘前写计划 →</router-link>
          </div>
          <p class="block-tip">大盘趋势判断 + 关注标的 + 预期操作，在盘前 Tab 的「当日计划」中落地。</p>
        </section><section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><Coin /></el-icon> 信号有效性（P1 回填聚合）</span>
          </div>
          <el-table v-if="weekly?.signal_stats?.by_type?.length" :data="weekly.signal_stats.by_type" stripe size="small" class="app-table app-table--compact">
            <el-table-column prop="signal_type" label="信号类型" width="110" />
            <el-table-column prop="count" label="样本数" width="90" />
            <el-table-column label="胜率" width="110">
              <template #default="{ row }">
                <span :class="clsByVal(row.win_rate, '')">{{ fmtPct(row.win_rate) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="平均收益" width="110">
              <template #default="{ row }">
                <span :class="clsByVal(row.avg_ret, '')">{{ fmtPct(row.avg_ret) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="触止损率" width="110">
              <template #default="{ row }">{{ fmtPct(row.hit_stop_rate) }}</template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!weekly?.signal_stats?.by_type?.length" :image-size="48" description="暂无已回填信号统计" />
        </section><section class="block">
          <div class="block-head">
            <span class="block-title"><el-icon><EditPen /></el-icon> 定性回顾</span>
            <router-link to="/paper/review" class="more-link">写复盘笔记 →</router-link>
          </div>
          <p class="block-tip">做对了什么 / 做错了什么 / 有没有违反系统规则 / 三系统信号一致性 —— 在交易复盘页记录。</p>
        </section>
        </div><!-- /tl-body -->
        <div v-if="activeTab !== 'weekly'" class="tl-folder" @click="goPeriod('weekly')">
          <span class="tf-main">本周收益 {{ weekly?.quant?.weekly_return != null ? fmtPct(weekly.quant.weekly_return) : '待生成（周五 17:30 自动）' }}</span>
          <span class="tf-tip">点击查看 →</span>
        </div>
      </section><!-- /周度 -->
      </el-tab-pane><!-- /今日作战 -->

    <!-- ============ 参考（独立 Tab：外围市场 / 财经日历 / 重要快讯，独立实时数据，保持原样） ============ -->
      <el-tab-pane label="参考" name="reference">
        <template v-if="reference">
          <!-- 今日财经日历：含昨天/今天已公布事件的实际值 + 规则化解读（外围市场快照已迁至大盘看板「外围市场」tab） -->
          <section class="block">
            <div class="block-head">
              <span class="block-title"><el-icon><Calendar /></el-icon> 今日财经日历</span>
              <div class="block-actions">
                <span class="block-hint">昨天 + 未来 7 日 · 已公布事件带实际值与解读</span>
                <el-button size="small" :icon="Refresh" :loading="referenceRefreshing" @click="refreshReference">刷新</el-button>
              </div>
            </div>
            <el-table v-loading="referenceLoading" :data="reference.calendar || []" stripe size="small" class="app-table app-table--compact" max-height="420">
              <el-table-column label="日期" width="104">
                <template #default="{ row }">
                  <span :class="{ 'cal-announced': row.announced }">{{ row.date }}</span>
                </template>
              </el-table-column>
              <el-table-column label="地区" width="72">
                <template #default="{ row }">{{ regionLabel(row.region) }}</template>
              </el-table-column>
              <el-table-column prop="event" label="事件" min-width="170" show-overflow-tooltip />
              <el-table-column label="状态" width="76">
                <template #default="{ row }">
                  <el-tag v-if="row.announced" size="small" type="success">已公布</el-tag>
                  <el-tag v-else size="small" type="info">待发布</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="预期" width="72">
                <template #default="{ row }">{{ row.forecast ?? '—' }}</template>
              </el-table-column>
              <el-table-column label="实际" width="80">
                <template #default="{ row }">
                  <b v-if="row.actual != null" class="up">{{ row.actual }}</b>
                  <span v-else>—</span>
                </template>
              </el-table-column>
              <el-table-column label="解读" min-width="260" show-overflow-tooltip>
                <template #default="{ row }">
                  <span v-if="row.announced" :class="{ 'cal-analysis': true }">{{ row.analysis || '已公布（数据待确认）' }}</span>
                  <span v-else class="cal-pending">公布后结合实际值分析</span>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-if="!reference.calendar?.length" description="暂无财经日历数据" />
          </section>

          <!-- 重要快讯：多源（财联社/东财 + 资讯雷达）· 仅保留宏观/市场级与自选/持仓/当日计划相关个股 -->
          <section class="block">
            <div class="block-head">
              <span class="block-title"><el-icon><Bell /></el-icon> 重要快讯</span>
              <span class="block-hint">近 24 小时 · 多源聚合（财联社 / 东财 / 资讯雷达）· 已按相关性过滤无关个股</span>
            </div>
            <div class="news-list">
              <div v-for="(n, i) in relevantNews" :key="i" class="news-row">
                <el-tag size="small" :type="importanceTag(n.importance)">{{ importanceLabel(n.importance) }}</el-tag>
                <el-tag v-if="n.source" size="small" effect="plain" type="info">{{ sourceShort(n.source) }}</el-tag>
                <a v-if="n.url" class="news-title" :href="n.url" target="_blank" rel="noopener noreferrer">{{ n.title }}</a>
                <span v-else class="news-title">{{ n.title }}</span>
                <span class="news-time">{{ newsTime(n.publish_time) }}</span>
              </div>
              <el-empty v-if="!reference.news_top?.length" :image-size="48" description="暂无快讯" />
              <p v-else-if="!relevantNews.length" class="block-tip">快讯均为无关个股/非市场级内容，已按相关性过滤（可在自选/持仓/当日计划中添加标的后再看）</p>
            </div>
            <p v-if="filteredNewsCount > 0" class="block-tip">已过滤 {{ filteredNewsCount }} 条与自选/持仓/当日计划无关的个股快讯</p>
          </section>
        </template>
        <el-empty v-else-if="!referenceLoading" :image-size="48" description="参考数据暂不可用（财经日历 / 重要快讯），可点「刷新」重试" />
        <p class="block-tip" style="margin: 12px 0 0">财经日历 / 重要快讯为全天参考信息：独立实时获取，不依赖盘前宏观快照，可点「刷新」更新（外围市场快照已迁至大盘看板「外围市场」tab）。</p>
      </el-tab-pane>
    </el-tabs>


    <!-- 添加计划弹窗 -->
    <el-dialog v-model="planDialog" title="添加当日计划" width="520px">
      <el-form :model="planForm" label-width="90px">
        <el-form-item label="代码">
          <el-input v-model="planForm.code" placeholder="如 600519" />
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="planForm.name" placeholder="可选，自动解析" />
        </el-form-item>
        <el-form-item label="方向">
          <el-radio-group v-model="planForm.direction">
            <el-radio value="buy">买入</el-radio>
            <el-radio value="sell">卖出</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="触发价">
          <el-input-number v-model="planForm.trigger_price" :controls="false" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="止损位">
          <el-input-number v-model="planForm.stop_loss" :controls="false" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="卖出条件">
          <el-input v-model="planForm.sell_condition" placeholder="如 跌破MA60 / 涨超+5% 减半" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="planDialog = false">取消</el-button>
        <el-button type="primary" :loading="creatingPlan" @click="submitPlan">保存</el-button>
      </template>
    </el-dialog>

    <!-- 改价 / 改止损（5.4 人工可改） -->
    <el-dialog v-model="editDialog" :title="editMode === 'candidate' ? '调整候选计划' : '调整当日计划'" width="480px">
      <el-form :model="editForm" label-width="90px">
        <el-form-item label="标的">
          <span class="edit-target">
            <a :href="stockHref(editTargetCode)" target="_blank" rel="noopener" class="stock-link stock-code">{{ editTargetCode }}</a>
            <a :href="stockHref(editTargetCode)" target="_blank" rel="noopener" class="stock-link">{{ editTargetName }}</a>
          </span>
        </el-form-item>
        <el-form-item label="触发价">
          <el-input-number v-model="editForm.trigger_price" :controls="false" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="止损位">
          <el-input-number v-model="editForm.stop_loss" :controls="false" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="卖出条件">
          <el-input v-model="editForm.sell_condition" placeholder="可留空" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingEdit" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 盘中买入·快速交易（同页直接成交，不再跳转模拟交易页） -->
    <el-dialog v-model="buyTradeDialog" title="盘中买入 · 快速交易" width="460px">
      <div v-if="buyTradeRow" class="quick-trade">
        <div class="qt-head">
          <a :href="stockHref(buyTradeRow.code)" target="_blank" rel="noopener" class="fav-code stock-link stock-code">{{ buyTradeRow.code }}</a>
          <a :href="stockHref(buyTradeRow.code)" target="_blank" rel="noopener" class="qt-name stock-link">{{ buyTradeRow.name }}</a>
          <el-tag size="small" :type="buyTradeRow.triggered ? 'danger' : 'info'">
            {{ buyTradeRow.triggered ? '可执行' : '待触达' }}
          </el-tag>
        </div>
        <p class="qt-advice">{{ buyTradeRow.advice }}</p>
        <div class="qt-grid">
          <div class="fld"><span class="k">触发价</span><span class="v">{{ buyTradeRow.trigger_price ?? '—' }}</span></div>
          <div class="fld"><span class="k">实时价</span><span class="v">{{ buyTradeRow.last_price ?? '—' }}</span></div>
          <div class="fld"><span class="k">距触发价</span><span class="v" :class="clsByVal(-(buyTradeRow.distance_pct ?? 0), '')">{{ fmtPct(buyTradeRow.distance_pct) }}</span></div>
        </div>
        <el-form label-width="90px" class="qt-form">
          <el-form-item label="买入数量">
            <el-input-number v-model="buyTradeQty" :min="100" :step="100" :precision="0" style="width: 100%" />
          </el-form-item>
          <el-form-item label="预计金额">
            <span class="qt-amount">≈ {{ fmtMoney((buyTradeRow.last_price ?? 0) * buyTradeQty) }} 元</span>
            <span v-if="!buyTradeRow.triggered" class="qt-warn">尚未触达触发价，当前为非推荐价格</span>
          </el-form-item>
        </el-form>
        <p class="qt-tip">按实时价市价成交；成交后自动关联当日计划并标记「已执行」。</p>
      </div>
      <template #footer>
        <el-button @click="buyTradeDialog = false">取消</el-button>
        <el-button type="primary" :loading="buyTradeLoading" :disabled="!canQuickBuy" @click="submitQuickBuy">确认买入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, onActivated, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Aim, Refresh, Setting, Compass, Calendar, Bell, Tickets, Plus,
          Odometer, TrendCharts, Bottom, Minus, InfoFilled, Coin, AlarmClock,
          Search, Document, Histogram, Warning, EditPen, Star, Lightning, MagicStick, DataLine,
          Magnet, Operation, Checked, Right, WarningFilled, Sell, ShoppingCart
} from '@element-plus/icons-vue'
import { warRoomApi, type WarRoomToday } from '@/api/warRoom'
import { portfolioApi } from '@/api/portfolio'
import { paperApi } from '@/api/paper'
import { favoritesApi } from '@/api/favorites'
import { screeningApi } from '@/api/screening'
import { subscribeQuotesUpdate, type QuotesUpdateSignal } from '@/utils/quotesSSE'
import { fmtPct, fmtSigned, fmtMoney, clsByVal } from '@/utils/format'

defineOptions({ name: 'WarRoomHome' })

// fetch 辅助：绕开 axios 拦截器（其 401 刷新 token 逻辑可能挂起）
async function _fetchJSON<T>(path: string, init: RequestInit = {}, timeoutMs = 20000): Promise<T> {
  const token = localStorage.getItem('auth-token') || ''
  const headers = new Headers(init.headers || {})
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  // 超时兜底：任何请求挂起都 abort，杜绝按钮无限"生成中"
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(path, { ...init, headers, signal: ctrl.signal })
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    const j = await res.json()
    return (j as any)?.data ?? j
  } finally {
    clearTimeout(timer)
  }
}
const _planGenerate = () => _fetchJSON<any>('/api/war-room/daily-plan/generate', { method: 'POST', body: '{}' }, 60000)
const _planStatus = (id: string) => _fetchJSON<any>('/api/war-room/daily-plan/status/' + id, {}, 15000)
const _planResult = (id: string) => _fetchJSON<any>('/api/war-room/daily-plan/result/' + id, {}, 15000)

const route = useRoute()
const router = useRouter()

const activeTab = ref('pre_market')
const loading = ref(false)
const plansLoading = ref(false)
const guideLoading = ref(false)
const signalsLoading = ref(false)
const backfillLoading = ref(false)
const genWeeklyLoading = ref(false)
const creatingPlan = ref(false)
const macroRefreshing = ref(false)
// 宏观快照缺失时后端已在后台自动补生成 → 展示"自动生成中…"，无需用户点「立即生成」
const macroAutoGenerating = ref(false)
const tradesLoading = ref(false)
const todayTrades = ref<any[]>([])
const todayAlerts = ref<any[]>([])
const alertsLoading = ref(false)

const todayData = ref<WarRoomToday | null>(null)
const macro = ref<any>(null)
// 参考 Tab 独立实时数据（外围指数 / 财经日历 / 重要快讯）：与盘前宏观快照解耦，不依赖快照是否生成
const reference = ref<any>(null)
const referenceLoading = ref(false)
const referenceRefreshing = ref(false)
const llm = computed(() => macro.value?.llm_interpretation || null)
const rule = computed(() => macro.value?.rule || null)
const plans = ref<any[]>([])
// 当日计划表格「信效」列：仅当存在带信号有效性数据的计划时才显示该列
const hasPlanHitRate = computed(() =>
  (plans.value || []).some(p => p.hit_rate != null)
)
const regime = ref<any>(null)
const posSummary = ref<any>(null)
const signals = ref<any[]>([])
const signalStats = ref<any>(null)
const weekly = ref<any>(null)
const favorites = ref<any[]>([])
const scanResult = ref<any>(null)
const scanLoading = ref(false)

const todayText = computed(() => {
  const d = new Date()
  const wd = ['日', '一', '二', '三', '四', '五', '六'][d.getDay()]
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} 周${wd}`
})

// 直达兼容：?tab=pre_market|intraday|post_market|weekly → 时间线时段；?tab=reference → 外层参考 Tab
const tabIndexMap: Record<string, string> = { pre_market: 'pre_market', intraday: 'intraday', post_market: 'post_market', weekly: 'weekly', reference: 'reference' }
const currentPeriod = computed(() => todayData.value?.current_period || 'pre_market')
// 外层 Tab：今日作战(ops) / 参考(reference)
const outerTab = ref('ops')
// 用户手动点击过时段节点后，不再随 currentPeriod 自动流转（● 标记仍指向真实当前时段，可再点回）
const periodPinned = ref(false)

// 将含编号（①.../1. 1、1)）的 LLM 解读文本切分为独立行，便于逐条阅读。
// 用「编号后不紧跟数字」排除百分比/小数（如 1.14%、0.94%）误切分。
function splitItems(text?: string | string[]): string[] {
  if (!text) return []
  // 后端可能直接返回数组（如 risk_tips 风险提示），无需再拆分
  if (Array.isArray(text)) return text
  return text
    .split(/(?=[①-⑩]|第[一二三四五六七八九十]+[、]|(?<![.\d])\d{1,2}[.、)](?!\d))/)
    .map(s => s.trim())
    .filter(Boolean)
}

// 快照生成时间格式化：今日显示「今日 HH:MM」，否则「M/D HH:MM」
function fmtClock(iso?: string): string {
  if (!iso) return '—'
  let s = String(iso).trim()
  // 统一截断多余小数秒到 3 位（后端微秒 .898000，部分浏览器解析 >3 位微秒失败）
  s = s.replace(/\.(\d{3})\d+/, '.$1')
  // 时区判定：Z / ±HH:MM（可有可无括号注释，如 "+08:00 (CST)"）都视为带时区；
  // 无时区的 naive ISO（如旧缓存）一律按 UTC 补 Z，避免按本地时区解析导致时间倒退
  if (!/([Z]|[+-]\d{2}:?\d{2}( ?\(.+\))?)$/.test(s)) s += 'Z'
  const d = new Date(s)
  if (isNaN(d.getTime())) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  return d.toDateString() === new Date().toDateString()
    ? `今日 ${hm}`
    : `${d.getMonth() + 1}/${d.getDate()} ${hm}`
}

// ---- 5.2 当日方向基准（basis 四态 + 置信度 + 锁定 + 指针）----
const basis = computed(() => macro.value?.basis || null)
// 状态是否锁定（盘前基准语义）：有 locked_at 即锁定
const gaugeLocked = computed(() => !!basis.value?.locked_at)

// 盘前信息密度控制：信号溯源 / 计划审计默认收起，第一眼只保留「方向结论 + 行动清单」
const signalCollapse = ref<string[]>([])
const planAuditCollapse = ref<string[]>([])

function statusLabel(s?: string) {
  return s || ruleDirection() || '—'
}
function ruleDirection() {
  const d = rule.value?.direction
  if (!d) return '数据不足'
  if (d.includes('多')) return '偏多'
  if (d.includes('空')) return '偏空'
  return '中性(观望)'
}
// 状态 → 视觉 class：偏空=绿(跌)，偏多=红(涨)，中性/数据不足=灰
function statusClass(s?: string) {
  if (s?.includes('空')) return 'bear'
  if (s?.includes('多')) return 'bull'
  if (s === '中性(观望)') return 'neutral'
  return 'nodata'
}
// 置信度等级文案
function confidenceLabel() {
  const c = basis.value?.confidence ?? 0
  if (basis.value?.status === '数据不足') return '数据不足'
  if (basis.value?.low_confidence || basis.value?.status === '中性(观望)') return '观望 · 低置信'
  if (c >= 70) return '高置信'
  if (c >= 50) return '中置信'
  return '低置信'
}
// 指针位置：低置信/数据不足 → 锁定在中心「观望」；否则按 score 映射到 [-46%, +46%]
const gaugePos = computed(() => {
  if (basis.value?.low_confidence || basis.value?.status === '数据不足' || basis.value?.status === '中性(观望)') {
    return 50
  }
  const score = Number(basis.value?.score ?? 0) || 0
  const norm = Math.max(-1, Math.min(1, score / 10))
  return Math.round(50 + norm * 46)
})

// ---- 5.1 信号溯源辅助 ----
function judgeLabel(j?: string) {
  return { 利多: '利多', 利空: '利空', 中性: '中性' }[j || ''] || j || '中性'
}
function judgeClass(j?: string) {
  if (j === '利多') return 'bull'
  if (j === '利空') return 'bear'
  return 'neutral'
}

// 5.1 信号溯源：按权重从高到低排列，且行内直接显示该信号的涨跌幅/数值
const PCT_SIGNAL_NAMES = new Set(['标普500', '纳斯达克', '恒生指数', '日经225', '韩国KOSPI',
  '富时A50期货', '标普500期货', '纳斯达克期货', '道指期货'])
const signalRows = computed(() => {
  const list = (rule.value?.signals || []).slice()
  list.sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0)) // 权重高->低
  return list
})
function sigValueText(s: any): string {
  const v = s?.value
  if (typeof v === 'number' && PCT_SIGNAL_NAMES.has(s.name)) return fmtPct(v) // 涨跌幅类
  if (typeof v === 'number') return String(v) // VIX 点位
  if (typeof v === 'string' && /[/:]/.test(v) && v.length <= 14) return v // 涨跌家数比
  return '' // 事件类长文本不占行内值列
}
function sigValueClass(s: any): string {
  const v = s?.value
  if (typeof v === 'number' && PCT_SIGNAL_NAMES.has(s.name)) return clsByVal(v, '')
  return ''
}

// ---- 数据加载 ----
async function loadToday() {
  try {
    todayData.value = await warRoomApi.getToday()
  } catch (e) {
    console.warn('[WarRoom] loadToday', e)
  }
}

// 流程引导条角标实时刷新：每 60s 拉取一次 /today 聚合，保证盘前/盘中/盘后/周度
// 待办数字（以及当前时段 ● 标记）持续反映实际状态，而不只在挂载/切 Tab/操作后刷新。
let todayRefreshTimer: number | null = null
function startTodayRefresh() {
  stopTodayRefresh()
  todayRefreshTimer = window.setInterval(() => { loadToday() }, 60000)
}
function stopTodayRefresh() {
  if (todayRefreshTimer) { window.clearInterval(todayRefreshTimer); todayRefreshTimer = null }
}

// 宏观快照缺失且后端已在后台自动补生成时，轻轮询等待就绪（快照缺失当日仅自动生成一次）
let macroAutoTimer: number | null = null
function stopMacroAuto() {
  if (macroAutoTimer) { window.clearInterval(macroAutoTimer); macroAutoTimer = null }
}

async function loadMacro() {
  loading.value = true
  try {
    // 打开即读今日已生成快照。快照缺失时后端自动在后台补生成一次并携带
    // auto_generating=true → 展示"自动生成中…"并轻轮询取回，而非空态催促点击。
    const res: any = await warRoomApi.getMacroOverview()
    macro.value = res?.snapshot || null
    macroAutoGenerating.value = !!res?.auto_generating
    if (macroAutoGenerating.value) {
      stopMacroAuto()
      macroAutoTimer = window.setInterval(async () => {
        try {
          const r: any = await warRoomApi.getMacroOverview()
          if (r?.snapshot) {
            macro.value = r.snapshot
            macroAutoGenerating.value = false
            stopMacroAuto()
          }
        } catch (e) { /* 轮询失败忽略，下轮重试 */ }
      }, 15000)
    }
  } catch (e: any) {
    macro.value = null
    if (typeof document !== 'undefined') {
      document.body.setAttribute('data-macro-error', String(e?.message || e).slice(0, 200))
    }
  }
  loading.value = false
}

// 参考 Tab：独立实时数据（指数/日历/快讯）——轻量接口、短缓存、秒回，与宏观快照解耦。
// 请求 main 数据（refresh=false 时后端命中缓存），失败保持空态由模板提示「刷新」重试。
async function loadReference() {
  referenceLoading.value = true
  try {
    reference.value = await warRoomApi.getMacroReference()
  } catch (e) {
    console.warn('[WarRoom] loadReference', e)
    if (!reference.value) reference.value = null
  } finally {
    referenceLoading.value = false
  }
}

// 参考 Tab「刷新」：强制重建日历/快讯缓存（不动宏观快照、不跑 LLM）
async function refreshReference() {
  referenceRefreshing.value = true
  try {
    reference.value = await warRoomApi.getMacroReference(true)
    ElMessage.success('参考数据已刷新')
  } catch (e) {
    console.warn('[WarRoom] refreshReference', e)
    ElMessage.error('参考数据刷新失败，请稍后重试')
  } finally {
    referenceRefreshing.value = false
  }
}

async function loadPlans() {
  plansLoading.value = true
  try {
    const data = await warRoomApi.getPlans()
    plans.value = data?.items || []
  } catch (e) {
    console.warn('[WarRoom] loadPlans', e)
  } finally {
    plansLoading.value = false
  }
}

async function loadSignals() {
  signalsLoading.value = true
  try {
    const [list, stats] = await Promise.all([
      warRoomApi.getSignals(undefined, 50),
      warRoomApi.getSignalStats()
    ])
    signals.value = list?.items || []
    signalStats.value = stats || null
  } catch (e) {
    console.warn('[WarRoom] loadSignals', e)
  } finally {
    signalsLoading.value = false
  }
}

async function loadTodayTrades() {
  tradesLoading.value = true
  try {
    const res = await warRoomApi.getTodayTrades()
    todayTrades.value = res?.items || []
  } catch (e) {
    console.warn('[WarRoom] loadTodayTrades', e)
  } finally {
    tradesLoading.value = false
  }
}

async function loadTodayAlerts() {
  alertsLoading.value = true
  try {
    const res = await warRoomApi.getTodayAlerts()
    todayAlerts.value = res?.items || []
  } catch (e) {
    console.warn('[WarRoom] loadTodayAlerts', e)
  } finally {
    alertsLoading.value = false
  }
}

async function refreshMacro() {
  macroRefreshing.value = true
  try {
    macro.value = await warRoomApi.refreshMacro()
    macroAutoGenerating.value = false
    stopMacroAuto()
    ElMessage.success('宏观快照已刷新')
    await loadToday()
  } catch (e) {
    ElMessage.error('宏观快照刷新失败，请稍后重试')
  } finally {
    macroRefreshing.value = false
  }
}

async function loadRegime() {
  try {
    // 设计文档 A.3 Tab2①：大盘状态条复用市场看板 regime（趋势/波动/建议）
    const { vibeApi } = await import('@/api/vibe')
    const res: any = await vibeApi.getDashboard()
    regime.value = res?.data?.regime || null
  } catch (e) {
    console.warn('[WarRoom] loadRegime', e)
  }
}

async function loadPositions() {
  try {
    const res = await portfolioApi.getSummary()
    posSummary.value = res?.data || null
  } catch (e) {
    console.warn('[WarRoom] loadPositions', e)
  }
}

async function loadWeekly() {
  try {
    weekly.value = await warRoomApi.getWeeklyReview()
  } catch (e) {
    console.warn('[WarRoom] loadWeekly', e)
  }
}

// 周度是否为本期（week_start 与 /today 的 week_start 一致）；历史周数据需明示提醒
const isCurrentWeek = computed(() => {
  const wk = weekly.value?.week_start
  return !!wk && !!todayData.value?.week_start && wk === todayData.value.week_start
})

// ── 决策带数据（各时段顶部一行关键状态，替代散落各 block 的碎片数字）──
// 盘中：已触达触发价的待执行买入指令数（实时由 SSE 更新 triggered 标记）
const intradayExecutable = computed(() => (guide.value?.buys || []).filter((b: any) => b.triggered).length)
// 盘后：当日成交盈亏合计（p 字段缺失则不参与，null 表示无盈亏数据）
const todayTradesPnl = computed(() => {
  let sum = 0
  let has = false
  for (const t of todayTrades.value) {
    if (t.pnl != null) { sum += Number(t.pnl); has = true }
  }
  return has ? sum : null
})

async function loadFavorites() {
  try {
    const res: any = await favoritesApi.list()
    favorites.value = (res?.data || []) as any[]
  } catch (e) {
    console.warn('[WarRoom] loadFavorites', e)
  }
}

async function runScan() {
  // 重操作确认：全市场扫描约需数分钟，避免误触发起重复重型任务
  if (scanLoading.value) return
  try {
    await ElMessageBox.confirm(
      '全市场三买三卖扫描约需数分钟（扫描约 5000 只），完成后信号自动落库「信号跟踪」。',
      '运行盘后信号扫描', { type: 'warning', confirmButtonText: '开始扫描', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  scanLoading.value = true
  try {
    const res: any = await screeningApi.scanThreeBuysThreeSells({ top_n: 30, limit: 20 })
    scanResult.value = res?.data || null
    ElMessage.success(`扫描完成，命中 ${scanResult.value?.total ?? 0} 只，信号已自动落库`)
    await loadSignals()
    await loadToday()
  } catch (e) {
    ElMessage.error('三买三卖扫描失败（可能超时，可重试）')
  } finally {
    scanLoading.value = false
  }
}

// 个股外部链接：新标签页打开本应用股票详情页（相对路径，跟随当前部署域名）
function stockHref(code?: string): string {
  if (!code) return ''
  return `/stocks/${code}`
}

// 次日计划预填：取「信号跟踪」中待验证的买点信号（16:00 自动扫描 / 手动扫描均落库，
// 与本次会话是否手动扫描解耦，保证刷新/重进页面后预填仍可用）
const prefillItems = computed(() =>
  (signals.value || []).filter(s => s.status !== 'filled').slice(0, 6)
)
// 今日已自动落库的信号数（盘后 16:00 自动扫描 / 手动扫描），提示避免重复全市场扫描
const scanTodaysCount = computed(() => {
  const today = todayData.value?.today
  return today ? (signals.value || []).filter(s => (s.trigger_date || '').slice(0, 10) === today).length : 0
})

// ---- 重要快讯相关性过滤（参考 Tab）----
// 相关标的口径 = 自选 + 持仓 + 当日计划；无关个股（含 6 位代码或个股行为词且非市场级）不展示，
// 避免"山东矿机 涨停"这类与用户无关、却被误标"高"的个股快讯混入"重要快讯"。
const newsRelated = computed(() => {
  const codes = new Set<string>()
  const names = new Set<string>()
  for (const f of favorites.value || []) {
    const c = String(f.symbol || f.stock_code || '').trim()
    if (c) codes.add(c)
    if (f.stock_name) names.add(String(f.stock_name).trim())
  }
  for (const p of posSummary.value?.positions || []) {
    const c = String(p.symbol || p.code || '').trim()
    if (c) codes.add(c)
    if (p.stock_name) names.add(String(p.stock_name).trim())
  }
  for (const p of plans.value || []) {
    const c = String(p.code || '').trim()
    if (c) codes.add(c)
    if (p.name) names.add(String(p.name).trim())
  }
  return { codes, names }
})
const STOCK_ACTION_RE = /涨停|跌停|连板|\d+板|中签|减持|增持|回购|停牌|复牌|公告|中标|签约|签订|签署|解禁|重组|业绩预告|扭亏|预增|预减|获准|批复|定增|配股|可转债|大涨|大跌/
// 市场级语义词（用于豁免个股判定）：不含机构词（证监会/国务院/政策等常伴随个股公告）
const MARKET_WORD_RE = /指数|大盘|板块|央行|利率|LPR|MLF|CPI|PPI|PMI|社融|M2|关税|国常会|美联储|非农|失业|GDP|通胀|北向|流动性|降准|降息|A股|港股|美股|现货|期货|市场|资金|监管|税收|议案|法案/
function isRelevantNews(n: any, related: { codes: Set<string>; names: Set<string> }): boolean {
  const title = String(n.title || '')
  if (!title) return true
  const codeMatch = title.match(/\d{6}/)
  if (codeMatch) return related.codes.has(codeMatch[0])
  // 无代码但命中"个股行为词"且未命中"市场级词" → 判为个股新闻，仅当命中相关名称保留
  if (STOCK_ACTION_RE.test(title) && !MARKET_WORD_RE.test(title)) {
    for (const nm of related.names) if (nm && nm.length >= 2 && title.includes(nm)) return true
    return false
  }
  return true
}
const relevantNews = computed(() =>
  (reference.value?.news_top || []).filter(n => isRelevantNews(n, newsRelated.value))
)
const filteredNewsCount = computed(() =>
  (reference.value?.news_top || []).length - relevantNews.value.length
)
// 资讯源徽标：资讯雷达的 RSS 源名过长，统一裁短
function sourceShort(src?: string): string {
  if (!src) return ''
  const s = String(src)
  if (s.startsWith('资讯雷达')) return '资讯雷达'
  return s.length > 8 ? s.slice(0, 8) : s
}

function addScanToPlan(row: any) {
  // 兼容两种来源：三买三卖扫描结果（signals[0].trigger_price / stop_price / primary_signal_label）
  // 与 signal_tracking 记录（signal_price / snapshot.stop_price / signal_label）
  const trigger = row.signal_price ?? row.signals?.[0]?.trigger_price ?? row.close ?? row.snapshot?.close
  const stop = row.snapshot?.stop_price ?? row.stop_price
  const sigLabel = row.signal_label || row.primary_signal_label || '三买三卖'
  const ma60 = row.snapshot?.ma60_direction ?? row.ma60_direction ?? ''
  planForm.value = {
    code: row.code,
    name: row.name,
    direction: 'buy',
    trigger_price: trigger ?? undefined,
    stop_loss: stop ?? undefined,
    sell_condition: `${sigLabel} · MA60 ${ma60}`.trim()
  }
  planDialog.value = true
}

// ---- 盘中买卖实时指导（买入触达 + 持仓卖出建议）----
const guide = ref<any>(null)
const guideBuys = computed(() => guide.value?.buys || [])
const guideSells = computed(() => guide.value?.sells || [])
// 实时行情整体不可用：卖出建议回退为信号快照价（无止损/止盈实时触发），向用户明示
const quotesUnavailable = computed(() =>
  !!guide.value && guideSells.value.length > 0
  && guideSells.value.every((s: any) => s.last_price == null)
)

async function loadIntradayGuide() {
  guideLoading.value = true
  try {
    const d: any = await warRoomApi.getIntradayGuide()
    guide.value = d
  } catch (e) {
    console.warn('[WarRoom] loadIntradayGuide', e)
  } finally {
    guideLoading.value = false
  }
}

// 卖出建议标签配色：清仓/止损=danger，减仓/止盈=warning，持有=info
function sellAdviceType(row: any): 'danger' | 'warning' | 'info' {
  const a = (row.advice || row.advice_label || '').toString()
  if (/清仓|止损|S3|离场/.test(a)) return 'danger'
  if (/减仓|止盈|S1|S2|安全|预警/.test(a)) return 'warning'
  return 'info'
}
// 盘前卖出观测「建议」文本的强调色
function sellAdviceTagClass(row: any): string {
  const a = (row.signal_label || row.advice_label || '').toString()
  if (/清仓|止损|S3|离场/.test(a)) return 'down'
  if (/减仓|止盈|预警/.test(a)) return 'warn'
  return ''
}

// 盘中卖出建议 → 加入当日计划（direction=sell）
function addSellToPlan(row: any) {
  planForm.value = {
    code: row.code,
    name: row.name,
    direction: 'sell',
    trigger_price: row.trigger_price ?? undefined,
    stop_loss: undefined,
    sell_condition: (row.reason || row.advice_text || row.advice || '').slice(0, 120)
  }
  planDialog.value = true
}

// 盘前卖出观测确认写库（direction=sell）
const confirmingSellIdx = ref<number>(-1)
async function confirmSellCandidate(ci: number) {
  const c = planGen.value?.sell_candidates?.[ci]
  if (!c) return
  confirmingSellIdx.value = ci
  try {
    await warRoomApi.createPlan({
      code: c.code,
      name: c.name || undefined,
      direction: 'sell',
      trigger_price: c.trigger_price,
      stop_loss: undefined,
      sell_condition: c.reason || c.sell_condition || undefined,
      source: c.source || undefined,
      // 卖出观测写库为「待确认」：需在当日计划表格点击「确认」后进入盘中提醒
      confirmed: false
    })
    ElMessage.success(`${c.name || c.code} 已写入卖出计划（待确认），请在当日计划中点「确认」进入盘中提醒`)
    planGen.value.sell_candidates.splice(ci, 1)
    planGen.value.sell_count = planGen.value.sell_candidates.length
    await loadPlans()
    await loadToday()
  } catch (e) {
    ElMessage.error('确认写库失败')
  } finally {
    confirmingSellIdx.value = -1
  }
}
async function removeSellCandidate(ci: number) {
  const c = planGen.value?.sell_candidates?.[ci]
  if (!c) return
  const code = String(c.code || '').trim()
  planGen.value.sell_candidates.splice(ci, 1)
  planGen.value.sell_count = planGen.value.sell_candidates.length
  ElMessage.success(`已否决卖出观测 ${c.name || c.code}`)
  // 持久化否决：切页/重进不还原（与候选一致）
  if (code) {
    try {
      await _fetchJSON('/api/war-room/daily-plan/dismiss', {
        method: 'POST',
        body: JSON.stringify({ code, kind: 'sell', dismissed: true }),
      }, 10000)
    } catch (e) { /* 持久化失败不阻塞 UI */ }
  }
}

// ---- 盘中实时（SSE 订阅 + 30s 轮询兜底）----
// SSE 订阅买卖点标的实时价：买入候选按触发价高亮"可执行"，持仓实时判定止损/止盈触发
let stopQuotes: (() => void) | null = null
let intradayPoll: number | null = null
// 最近一次实时行情推送时间（持仓追踪 / 自选重点头部展示数据新鲜度）
const quoteTs = ref('')

function onQuotesUpdate(signal: QuotesUpdateSignal) {
  const qs = signal.quotes
  if (!qs) return
  if (Object.keys(qs).length) {
    quoteTs.value = new Date().toTimeString().slice(0, 8)
  }
  // 买入建议：更新现价 + 重新判定触达/偏离
  if (guide.value?.buys) {
    guide.value.buys = guide.value.buys.map((p: any) => {
      const q = qs[p.code]
      if (!q || q.close == null) return p
      const tp = p.trigger_price
      const price = q.close
      const dist = tp ? Math.round((price / tp - 1) * 10000) / 100 : null
      const triggered = tp != null && price <= tp
      return {
        ...p,
        last_price: price,
        distance_pct: dist,
        triggered: !!triggered,
        advice: triggered
          ? `已回落至 ${tp} 下方，时间点成立，可执行买入`
          : (dist != null && dist <= 2 ? `接近触发价（距触发价 ${dist}%），可提前挂单` : p.advice)
      }
    })
  }
  // 卖出建议：更新现价/盈亏率，并做止损/止盈的实时触发判定（信号级建议仍以评估结果为准）
  if (guide.value?.sells) {
    guide.value.sells = guide.value.sells.map((p: any) => {
      const q = qs[p.code]
      if (!q || q.close == null) return p
      const price = q.close
      const cost = p.avg_cost
      const stop = p.stop_loss_price
      const take = p.take_profit_price
      let advice = p.advice
      let adviceLabel = p.advice_label
      let reason = p.reason
      if (stop && price <= Number(stop)) {
        advice = '触发止损'
        adviceLabel = '无条件离场'
        reason = `现价 ${price} 已跌破止损位 ${stop}，无条件止损离场`
      } else if (take && price >= Number(take) && !/持有/.test(advice || '')) {
        advice = '触及止盈'
        adviceLabel = '分批止盈'
        reason = `现价 ${price} 已达止盈位 ${take}，分批止盈一半`
      }
      return {
        ...p,
        last_price: price,
        profit_loss_rate: cost ? Math.round((price / cost - 1) * 10000) / 100 : null,
        advice, advice_label: adviceLabel, reason
      }
    })
  }
  // 持仓追踪 / 自选重点：同步实时价/盈亏率，避免表格停留在进入 Tab 时的静态快照
  if (posSummary.value?.positions?.length) {
    posSummary.value.positions = posSummary.value.positions.map((pos: any) => {
      const code = String(pos.symbol || pos.code || '')
      const q = code ? qs[code] : null
      if (!q || q.close == null) return pos
      const cost = pos.avg_cost
      return {
        ...pos,
        current_price: q.close,
        profit_loss_rate: cost ? Math.round((q.close / Number(cost) - 1) * 10000) / 100 : pos.profit_loss_rate,
      }
    })
  }
  if (favorites.value.length) {
    favorites.value = favorites.value.map((f: any) => {
      const code = String(f.symbol || f.stock_code || '')
      const q = code ? qs[code] : null
      if (!q) return f
      return { ...f, current_price: q.close, change_percent: q.pct_chg ?? f.change_percent }
    })
  }
}

function startIntradayLive() {
  stopIntradayLive()
  stopQuotes = subscribeQuotesUpdate(onQuotesUpdate, (status) => {
    // connected / degraded：由轮询兜底，无需额外提示
  })
  // 30s 轮询：买卖指导 + 今日预警列表（角标只更新计数，列表需随行刷新，保证盘中新预警可见）
  intradayPoll = window.setInterval(() => {
    loadIntradayGuide()
    loadTodayAlerts()
  }, 30000)
}

function stopIntradayLive() {
  if (stopQuotes) { stopQuotes(); stopQuotes = null }
  if (intradayPoll) { window.clearInterval(intradayPoll); intradayPoll = null }
}

// ---- 操作 ----
async function triggerBackfill() {
  backfillLoading.value = true
  try {
    const res = await warRoomApi.triggerBackfill()
    ElMessage.success(`已回填 ${res?.filled ?? 0} 条到期信号`)
    await loadSignals()
    await loadWeekly()
  } catch (e) {
    ElMessage.error('回填失败')
  } finally {
    backfillLoading.value = false
  }
}

async function generateWeekly() {
  genWeeklyLoading.value = true
  try {
    await warRoomApi.generateWeeklyReview()
    ElMessage.success('周度复盘已生成')
    await loadWeekly()
  } catch (e) {
    ElMessage.error('周报生成失败')
  } finally {
    genWeeklyLoading.value = false
  }
}

const planDialog = ref(false)
const planForm = ref({ code: '', name: '', direction: 'buy', trigger_price: undefined as number | undefined, stop_loss: undefined as number | undefined, sell_condition: '' })

function openPlanDialog() {
  planForm.value = { code: '', name: '', direction: 'buy', trigger_price: undefined, stop_loss: undefined, sell_condition: '' }
  planDialog.value = true
}

async function submitPlan() {
  if (!planForm.value.code.trim()) {
    ElMessage.warning('请填写代码')
    return
  }
  creatingPlan.value = true
  try {
    await warRoomApi.createPlan({
      code: planForm.value.code.trim(),
      name: planForm.value.name || undefined,
      direction: planForm.value.direction,
      trigger_price: planForm.value.trigger_price,
      stop_loss: planForm.value.stop_loss,
      sell_condition: planForm.value.sell_condition || undefined,
      // 手动添加即用户拍板 → 直接已确认，进入盘中提醒
      confirmed: true
    })
    ElMessage.success('计划已保存')
    planDialog.value = false
    // 卖出计划已写入当日计划：立即从「卖出建议」移除该持仓（后端同步过滤，30s 刷新后也不会回来）
    if (planForm.value.direction === 'sell' && guide.value?.sells) {
      guide.value.sells = guide.value.sells.filter((s: any) => String(s.code) !== String(planForm.value.code).trim())
    }
    await loadPlans()
    await loadToday()
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    creatingPlan.value = false
  }
}

// ---- 盘中买入·快速交易（同页直接成交，不跳转模拟交易页）----
const buyTradeDialog = ref(false)
const buyTradeRow = ref<any>(null)
const buyTradeQty = ref(100)
const buyTradeLoading = ref(false)
const canQuickBuy = computed(() => !!buyTradeRow.value?.triggered && buyTradeQty.value > 0)

function goTrade(row: any) {
  // 同页快速交易：弹出买入确认，成交后自动关联当日计划，不再跳转 /paper
  buyTradeRow.value = row
  buyTradeQty.value = 100
  buyTradeDialog.value = true
}

async function submitQuickBuy() {
  const row = buyTradeRow.value
  if (!row || !canQuickBuy.value) return
  buyTradeLoading.value = true
  try {
    await paperApi.placeOrder({
      code: row.code,
      side: 'buy',
      quantity: buyTradeQty.value,
      stock_name: row.name,
      analysis_id: row.plan_id || undefined,
    })
    ElMessage.success(`${row.name || row.code} 买入成交，当日计划已标记已执行`)
    buyTradeDialog.value = false
    // 成交后：计划自动关联为已执行 → 刷新盘中指导 / 当日计划 / 角标 / 持仓
    await loadIntradayGuide()
    await loadPlans()
    await loadToday()
    loadPositions()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '买入失败，请检查模拟账户资金是否充足')
  } finally {
    buyTradeLoading.value = false
  }
}

// ---- 5.3 计划生成流水线（四段审计痕迹，异步 + SSE 实时进度）----
const planGen = ref<any>(null)
const genPlanLoading = ref(false)
const confirmingIdx = ref<number>(-1)
const genPlanJobId = ref<string>('')
const genPlanProgress = ref(0)
const genPlanStage = ref('')
let planCompletionTimer: ReturnType<typeof setInterval> | null = null

// 清理计划生成的后台看门狗轮询
function _clearPlanWatchdog() {
  if (planCompletionTimer) {
    clearInterval(planCompletionTimer)
    planCompletionTimer = null
  }
}

const STEP_MAP: Record<string, string> = { 环境: '环境', 行业: '行业', 个股: '个股', 计划: '计划', 卖出: '卖出' }
function stepLabel(k?: string) { return STEP_MAP[k || ''] || k || '—' }
// 段标识（class 用拼音/英文），与后端 step 名（中文）一一对应
function pipelineKey(k?: string) {
  return { 环境: 'env', 行业: 'ind', 个股: 'stock', 计划: 'plan', 卖出: 'sell' }[k || ''] || 'env'
}
function keptPct(st: any) {
  if (!st || !st.scanned) return 0
  return Math.round((st.kept / st.scanned) * 100)
}

async function generatePlan() {
  // 防抖：以 genPlanLoading 为权威防抖依据（而非 genPlanJobId）。
  // genPlanJobId 曾在旧版本/keep-alive 缓存中残留非空值，若以它防抖会导致按钮"点了没反应"。
  if (genPlanLoading.value) return
  _clearPlanWatchdog()
  genPlanLoading.value = true
  planGen.value = null
  genPlanJobId.value = ''
  genPlanProgress.value = 0
  genPlanStage.value = '环境'
  try {
    const job = await _planGenerate()
    if (!job?.job_id) {
      ElMessage.error('计划生成失败')
      genPlanLoading.value = false
      genPlanJobId.value = ''
      return
    }
    const jobId = job.job_id
    genPlanJobId.value = jobId
    genPlanProgress.value = 50
    genPlanStage.value = '计划'
    // 直接轮询：每 300ms 查 status，done 就拉 result。
    // 后端四段流水线冷算约 50-150s，轮询窗口至少 180s，避免任务尚未完成就被判"超时"，
    // 造成按钮复位但结果无声无息（用户误以为失败、再点会叠加重型任务）。
    const deadline = Date.now() + 180000
    let done = false
    let failCount = 0
    while (!done && Date.now() < deadline) {
      await new Promise(r => setTimeout(r, 300))
      try {
        const st = await _planStatus(jobId)
        if (!st) continue
        // 更新进度
        if (st.progress != null) genPlanProgress.value = st.progress
        if (st.stage) genPlanStage.value = st.stage
        if (st.status === 'done') {
          const result = await _planResult(jobId)
          if (result) {
            planGen.value = result
            genPlanProgress.value = 100
            genPlanStage.value = ''
            if (result.pending_reason) {
              ElMessage.warning(result.pending_reason)
            } else {
              ElMessage.success(`已生成 ${result.candidates_count ?? 0} 条计划候选`)
            }
          }
          genPlanJobId.value = ''
          done = true
        } else if (st.status === 'error') {
          ElMessage.error(st.error || '计划生成失败')
          done = true
        }
      } catch {
        // 不再静默吞错：连续 5 次获取失败即视为链路异常，报错退出（否则按钮可能长时间"生成中"）
        if (++failCount >= 5) { ElMessage.error('计划状态获取失败，请重试'); done = true }
      }
    }
    if (!done) {
      // 极慢速兜底（>180s 仍 running）：后端任务仍会在完成后自动落库为「今日计划快照」，
      // 告知而非让用户误以为失败；快照在刷新 / daily-plan/today 时自动呈现。
      try {
        const result = await _planResult(jobId)
        if (result) { planGen.value = result; genPlanProgress.value = 100; genPlanStage.value = '' }
      } catch {}
      ElMessage.warning('生成仍在后台进行（耗时较长），完成后会自动保存，可稍后刷新查看')
      genPlanLoading.value = false
      genPlanJobId.value = ''
    } else {
      genPlanLoading.value = false
    }
  } catch (e) {
    ElMessage.error('计划生成失败')
  } finally {
    // 无论成功 / 失败 / 异常，一律复位按钮与 job 状态，杜绝"生成中…"卡死
    genPlanLoading.value = false
    genPlanJobId.value = ''
    _clearPlanWatchdog()
  }
}

// 打开即读「今日计划快照」（盘前 8:15 预生成落库）：GET 纯读、秒回；
// 快照未生成（冷启动/未到盘前）时保持空态，用户可点「生成当日计划」触发 job。
async function loadTodayPlan() {
  try {
    const d = await _fetchJSON<any>('/api/war-room/daily-plan/today', {}, 15000)
    if (d?.generated && d.result) {
      // 快照已生成：即使候选被「已计划去重」全部过滤（filtered_count>0），也保留
      // 快照结果给 UI 展示五段审计痕迹（证明流水线已由盘前 8:15 自动执行），
      // 而不是退化成「点击生成当日计划」的空态让用户误以为没有自动执行。
      planGen.value = d.result
      genPlanProgress.value = 100
      genPlanStage.value = ''
      return true
    }
    planGen.value = null
    return false
  } catch { /* 快照读取失败保持空态 */ planGen.value = null; return false }
}

// ---- 5.4 候选 → 人工确认 / 改价 / 删除 ----
async function confirmCandidate(ci: number) {
  const c = planGen.value?.candidates?.[ci]
  if (!c) return
  confirmingIdx.value = ci
  try {
    await warRoomApi.createPlan({
      code: c.code,
      name: c.name || undefined,
      direction: c.direction || 'buy',
      trigger_price: c.trigger_price,
      stop_loss: c.stop_loss,
      sell_condition: c.sell_condition || undefined,
      source: c.source || undefined,
      // 信号链审计：把信号标签/类型与周度信号有效性（历史命中率）带入当日计划
      signal_label: c.signal_label || undefined,
      signal_type: c.signal_type || undefined,
      hit_rate: c.hit_rate ?? undefined,
      signal_count: c.signal_count ?? undefined,
      // 候选写库为「待确认」：需在当日计划表格点击「确认」后进入盘中执行提醒
      confirmed: false
    })
    ElMessage.success(`${c.name || c.code} 已写入当日计划（待确认），请在当日计划中点「确认」进入盘中提醒`)
    // 从候选移除 → 前端本地刷新（不重取，避免 pending 漂移）
    planGen.value.candidates.splice(ci, 1)
    planGen.value.candidates_count = planGen.value.candidates.length
    await loadPlans()
    await loadToday()
  } catch (e) {
    ElMessage.error('确认写库失败')
  } finally {
    confirmingIdx.value = -1
  }
}

function editCandidate(ci: number) {
  const c = planGen.value?.candidates?.[ci]
  if (!c) return
  editMode.value = 'candidate'
  editCandidateIdx.value = ci
  editTargetId.value = ''
  editTargetCode.value = c.code
  editTargetName.value = c.name || c.code
  editForm.value = {
    trigger_price: c.trigger_price ?? undefined,
    stop_loss: c.stop_loss ?? undefined,
    sell_condition: c.sell_condition || ''
  }
  editDialog.value = true
}

async function removeCandidate(ci: number) {
  const c = planGen.value?.candidates?.[ci]
  if (!c) return
  const code = String(c.code || '').trim()
  planGen.value.candidates.splice(ci, 1)
  planGen.value.candidates_count = planGen.value.candidates.length
  ElMessage.success(`已否决候选 ${c.name || c.code}`)
  // 持久化否决：切页/重进不还原（后端快照读取时按 plan_overrides 过滤）
  if (code) {
    try {
      await _fetchJSON('/api/war-room/daily-plan/dismiss', {
        method: 'POST',
        body: JSON.stringify({ code, kind: 'candidate', dismissed: true }),
      }, 10000)
    } catch (e) { /* 持久化失败不阻塞 UI */ }
  }
}

// ---- 5.4 已写计划的人工可改 ----
const editDialog = ref(false)
const editMode = ref<'candidate' | 'plan'>('plan')
const editTargetId = ref('')
const editTargetCode = ref('')
const editTargetName = ref('')
const editCandidateIdx = ref(-1)
const savingEdit = ref(false)
const editForm = ref({ trigger_price: undefined as number | undefined, stop_loss: undefined as number | undefined, sell_condition: '' })

function editPlan(row: any) {
  editMode.value = 'plan'
  editTargetId.value = row.id
  editTargetCode.value = row.code
  editTargetName.value = row.name || row.code
  editCandidateIdx.value = -1
  editForm.value = {
    trigger_price: row.trigger_price ?? undefined,
    stop_loss: row.stop_loss ?? undefined,
    sell_condition: row.sell_condition || ''
  }
  editDialog.value = true
}

async function saveEdit() {
  savingEdit.value = true
  try {
    if (editMode.value === 'candidate') {
      const c = planGen.value.candidates[editCandidateIdx.value]
      if (!c) return
      if (editForm.value.trigger_price != null) c.trigger_price = editForm.value.trigger_price
      if (editForm.value.stop_loss != null) c.stop_loss = editForm.value.stop_loss
      c.sell_condition = editForm.value.sell_condition || c.sell_condition
      // 持久化改价：确认写库 / 切页 / 重进均按已改价格为准
      if (c.code) {
        try {
          await _fetchJSON('/api/war-room/daily-plan/override', {
            method: 'POST',
            body: JSON.stringify({
              code: String(c.code).trim(),
              trigger_price: c.trigger_price ?? undefined,
              stop_loss: c.stop_loss ?? undefined,
              sell_condition: c.sell_condition || undefined,
            }),
          }, 10000)
        } catch (e) { /* 持久化失败不阻塞 UI */ }
      }
    } else {
      const payload: Record<string, any> = {}
      if (editForm.value.trigger_price != null) payload.trigger_price = editForm.value.trigger_price
      if (editForm.value.stop_loss != null) payload.stop_loss = editForm.value.stop_loss
      if (editForm.value.sell_condition) payload.sell_condition = editForm.value.sell_condition
      await warRoomApi.updatePlanDetail(editTargetId.value, payload)
      await loadPlans()
    }
    ElMessage.success('已更新')
    editDialog.value = false
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    savingEdit.value = false
  }
}

// 当日计划「确认」：把计划从「待确认」置为「已确认」，此后进入盘中执行提醒
const confirmingPlanId = ref<string>('')
async function confirmPlanWrite(row: any) {
  if (row.status !== 'pending' || row.confirmed) return
  confirmingPlanId.value = row.id
  try {
    await warRoomApi.updatePlanDetail(row.id, { confirmed: true })
    ElMessage.success(`${row.name || row.code} 已确认，盘中价格触达将提醒`)
    await loadPlans()
  } catch (e) {
    ElMessage.error('确认失败')
  } finally {
    confirmingPlanId.value = ''
  }
}

async function removePlan(row: any) {
  try {
    await ElMessageBox.confirm(`确认删除计划「${row.name || row.code}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await warRoomApi.deletePlan(row.id)
    ElMessage.success('计划已删除')
    await loadPlans()
    await loadToday()
  } catch (e) {
    ElMessage.error('删除失败')
  }
}

function shortSell(s?: string) {
  if (!s) return '—'
  return s.length > 18 ? s.slice(0, 18) + '…' : s
}

// 周度信号有效性徽标：命中率 ≥ 60% 高亮（历史样本越多越可信），低值弱化提示
function hitRateCls(hit: number | null | undefined): string {
  if (hit == null) return ''
  return hit >= 60 ? 'hit-good' : 'hit-low'
}

function goScheduled() {
  router.push('/tasks')
}

// 按时段加载其静态数据（SSE 启停统一由 syncIntradayLive 管理，不在此处理）
function loadPeriodData(name: string) {
  if (name === 'pre_market') { ensureMacroAuto(); loadPlans(); loadTodayPlan() }
  if (name === 'intraday') { loadTodayAlerts(); loadRegime(); loadPositions(); loadIntradayGuide(); loadFavorites() }
  if (name === 'post_market') { loadSignals(); loadTodayTrades() }
  if (name === 'weekly') { loadWeekly(); loadTodayPlan() }
}

// 统一刷新：并行刷新全部时段数据 + 参考，一次点按全页更新。
// 重操作（生成计划/宏观重算/信号扫描/周报）不在此触发，保留各自兜底按钮，避免误触重型任务。
async function refreshCurrent() {
  loading.value = true
  await Promise.allSettled([
    ensureMacroAuto(), loadPlans(), loadTodayPlan(),
    loadIntradayGuide(), loadRegime(), loadPositions(), loadFavorites(), loadTodayAlerts(),
    loadSignals(), loadTodayTrades(), loadWeekly(), loadReference(),
  ])
  syncIntradayLive()
  loading.value = false
}

// 盘前宏观：读取已生成的今日快照（后端在快照缺失时会自动生成一次），
// 统一刷新仅重新拉取快照，不触发重新生成（生成由 8:15 调度/缺失时自动补）。
function ensureMacroAuto() {
  loadMacro()
}

// 时间线节点 / 折叠摘要条点击：切换查看时段（不依赖 el-tabs 内部 v-model）
function goPeriod(key: string) {
  if (key === activeTab.value) { scrollToPeriod(key); return }
  periodPinned.value = true
  activeTab.value = key
  loadPeriodData(key)
  syncIntradayLive()
  scrollToPeriod(key)
}

function scrollToPeriod(key: string) {
  window.setTimeout(() => {
    const el = document.getElementById('period-' + key)
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, 60)
}

// SSE 实时订阅生命周期：仅外层在「今日作战」且查看时段为盘中时运行（不看盘中不空耗）
function syncIntradayLive() {
  if (outerTab.value === 'ops' && activeTab.value === 'intraday') startIntradayLive()
  else stopIntradayLive()
}

// 外层 Tab（今日作战 / 参考）切换
function onOuterTabChange(name: string | number) {
  outerTab.value = String(name)
  if (name === 'reference') {
    // 参考独立 Tab：自选/持仓/当日计划（供重要快讯相关性过滤）+ 独立实时数据
    loadFavorites(); loadPositions(); loadPlans(); loadReference()
  } else {
    refreshCurrent()
  }
  syncIntradayLive()
}

// 时段自动流转：后端 currentPeriod 变化（60s /today 轮询感知）时，
// 用户未手动锁定则自动展开新时段并平滑定位；● 标记始终指向真实当前时段。
watch(currentPeriod, (np) => {
  if (periodPinned.value) return
  if (activeTab.value !== np && np !== 'reference') {
    activeTab.value = np
    loadPeriodData(np)
    syncIntradayLive()
    scrollToPeriod(np)
  }
})

// ---- 格式化辅助 ----
function regionLabel(r?: string) {
  if (!r) return '—'
  if (r.toUpperCase().includes('CN')) return '中国'
  if (r.toUpperCase().includes('US')) return '美国'
  return r
}
function importanceLabel(v?: string) {
  if (v === 'high' || v === '高') return '高'
  if (v === 'medium' || v === '中') return '中'
  if (v === 'low' || v === '低') return '低'
  return v || '—'
}
type TagType = 'success' | 'warning' | 'info' | 'danger' | 'primary'
function importanceTag(v?: string): TagType {
  if (v === 'high' || v === '高') return 'danger'
  if (v === 'medium' || v === '中') return 'warning'
  return 'info'
}
function newsTime(t?: string) {
  if (!t) return '—'
  const d = new Date(t)
  if (Number.isNaN(d.getTime())) return t
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
function tradeTime(t?: string) {
  if (!t) return '—'
  const d = new Date(t)
  if (Number.isNaN(d.getTime())) return t
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
function severityLabel(s?: string) {
  return { critical: '严重', warn: '警告', info: '提示' }[s || ''] || s || '—'
}
function alertTime(ts?: number) {
  if (!ts) return '—'
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return '—'
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}`
}
// 三态计划：待确认(pending&!confirmed) / 已确认(pending&confirmed) / 已执行 / 已取消
function planStatusLabel(row: any) {
  const s = row.status
  if (s === 'pending') return row.confirmed ? '已确认' : '待确认'
  return { executed: '已执行', cancelled: '已取消' }[s] || s
}
function planStatusTag(row: any): TagType {
  const s = row.status
  if (s === 'pending') return row.confirmed ? 'success' : 'warning'
  return { executed: 'success', cancelled: 'info' }[s] as TagType || 'info'
}
function positionText(p: any) {
  if (!p) return '—'
  if (p.shares) return `${p.shares}股 (${fmtPct(p.ratio * 100, 0)})`
  if (p.ratio) return fmtPct(p.ratio * 100, 0)
  return JSON.stringify(p)
}
function outcomeLabel(o: string) {
  return { win: '胜', loss: '负', flat: '平' }[o] || o
}
function snapshotText(s: any) {
  if (!s) return '—'
  const parts = ['bias', 'ma60', 'quadrant', 'price'].filter(k => s[k] != null)
  return parts.map(k => `${k}: ${s[k]}`).join(' ')
}

onMounted(async () => {
  // ?tab= 直达兼容：reference → 外层参考 Tab；时段值 → 时间线内定位并锁定（不回自动流转）
  const q = route.query.tab
  if (typeof q === 'string' && q === 'reference') {
    outerTab.value = 'reference'
  } else if (typeof q === 'string' && tabIndexMap[q]) {
    activeTab.value = q
    periodPinned.value = true
  }
  // today 聚合：后续 currentPeriod watch 自动定位当前时段
  await loadToday()
  // 打开即全量呈现：并行拉取全部时段数据 + 参考（互不阻塞，单项失败不影响其他）。
  // 替代旧版"先选时段再逐块点按钮加载"的空态流程。
  await Promise.allSettled([
    ensureMacroAuto(), loadPlans(), loadTodayPlan(),
    loadIntradayGuide(), loadRegime(), loadPositions(), loadFavorites(), loadTodayAlerts(),
    loadSignals(), loadTodayTrades(), loadWeekly(), loadReference(),
  ])
  // 角标实时刷新定时器（每 60s 更新待办数字 + 支撑时段自动流转）
  startTodayRefresh()
  syncIntradayLive()
})

// keep-alive 激活钩子：每次组件被复用时强制清空全部计划生成相关状态。
// 残留状态危害：
//   1) genPlanJobId 残留在旧版本代码中非空 → generatePlan 防抖直接 return（按钮"点了没反应"）；
//   2) genPlanLoading 残留 true → 按钮永远显示"生成中…"卡死。
// 因此这里一次性复位 jobId/progress/stage/loading/结果，并停掉一切后台任务。
onActivated(() => {
  genPlanLoading.value = false
  genPlanJobId.value = ''
  genPlanProgress.value = 0
  genPlanStage.value = ''
  planGen.value = null
  _clearPlanWatchdog()
  // 每次从缓存返回都重新读今日快照（盘前预生成成品，秒回），保证最新
  loadTodayPlan()
  // 重新激活时立即刷新一次角标，并重启实时刷新定时器
  loadToday()
  startTodayRefresh()
  syncIntradayLive()
})

onUnmounted(() => {
  stopIntradayLive()
  stopTodayRefresh()
  stopMacroAuto()
})
</script>

<style lang="scss" scoped>
.war-room {
  // 日历已公布事件高亮与解读
  .cal-announced { font-weight: 600; color: var(--el-color-success); }
  .cal-analysis { color: var(--el-text-color-regular); }
  .cal-pending { color: var(--el-text-color-secondary); }

  // 外层 Tab（今日作战 / 参考）头部恢复展示，作为页面一级导航
  .war-tabs :deep(.el-tabs__header) { margin-bottom: 16px; }
  .war-tabs :deep(.el-tabs__item) { font-size: 15px; font-weight: 600; padding: 0 22px; }

  // ── 时间线 · 时段区块（单 Tab 内纵向主线：标题条 → 详情体 / 折叠摘要） ──
  .tl-period {
    margin-bottom: 16px;

    .tl-head {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 10px 14px;
      border: 1px solid var(--el-border-color-light);
      border-radius: 10px;
      cursor: pointer;
      transition: all .2s;
      background: var(--el-bg-color);

      &:hover { border-color: var(--el-color-primary-light-5); }
      &.on { border-color: var(--el-color-primary); }

      .tl-dot { font-size: 13px; color: var(--el-color-primary); }
      .tl-name { font-size: 15px; font-weight: 700; color: var(--el-text-color-primary); }
      .tl-badge {
        background: var(--el-color-danger); color: #fff; font-size: 11px; line-height: 1;
        padding: 2px 6px; border-radius: 10px;
      }
      .tl-sub { font-size: 12px; color: var(--el-text-color-placeholder); flex: 1; min-width: 0; }
      .tl-fold-tip { font-size: 12px; color: var(--el-color-primary-light-3); flex: none; }
    }

    .tl-body {
      border: 1px solid var(--el-border-color-lighter);
      border-top: none;
      border-radius: 0 0 10px 10px;
      padding: 14px;
      background: var(--el-bg-color-page);
    }

    // 折叠摘要条（非当前查看时段，点击回看）
    .tl-folder {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 14px;
      border: 1px dashed var(--el-border-color-light);
      border-top: none;
      border-radius: 0 0 10px 10px;
      cursor: pointer;
      transition: all .2s;

      &:hover { border-color: var(--el-color-primary-light-5); background: var(--el-color-primary-light-9); }
      .tf-main { font-size: 13px; color: var(--el-text-color-secondary); }
      .tf-tip { font-size: 12px; color: var(--el-color-primary); flex: none; }
    }
  }

  // ── 决策带（时段顶部一行关键状态，第一眼回答"现在什么最重要"） ──
  .decision-bar {
    display: flex;
    align-items: center;
    gap: 24px;
    flex-wrap: wrap;
    padding: 12px 16px;
    margin-bottom: 14px;
    border: 1px solid var(--el-color-primary-light-5);
    border-radius: 10px;
    background: var(--el-color-primary-light-9);

    .db-item {
      display: inline-flex;
      align-items: baseline;
      gap: 8px;

      .db-k { font-size: 12px; color: var(--el-text-color-secondary); }
      .db-v {
        font-size: 16px; font-weight: 700; color: var(--el-text-color-primary);
        font-variant-numeric: tabular-nums;
        &.hot { color: var(--el-color-danger); }
      }
    }
  }

  // ── 预警明细折叠（原生 details，无需额外状态） ──
  .quiet-details {
    summary {
      cursor: pointer;
      font-size: 13px;
      font-weight: 600;
      color: var(--el-color-primary);
      margin-bottom: 8px;
      outline: none;
      user-select: none;
    }
    summary:hover { color: var(--el-color-primary-dark-2); }
  }

  // 区块间距收紧：时间线内纵向噪音更小，分段感由 tl-period 容器承担
  .block { margin-bottom: 16px; }
  .block-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
    .block-title {
      font-size: 15px;
      font-weight: 600;
      color: var(--el-text-color-primary);
      display: inline-flex;
      align-items: center;
      gap: 6px;
      .el-icon { color: var(--el-color-primary); }
    }
    .block-hint { font-size: 12px; color: var(--el-text-color-secondary); &.llm-off { color: var(--el-color-warning); } }
    .block-actions { display: flex; gap: 8px; }
  }
  .block-tip { color: var(--el-text-color-secondary); font-size: 13px; margin: 0; }

  // 5.2 仪表盘式方向卡
  .direction-dash {
    .dash-top { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }
    .dash-left { display: flex; align-items: center; gap: 16px; }
    .dash-right { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; }
    .dir-badge {
      font-size: 20px; font-weight: 700; padding: 6px 18px; border-radius: 8px; letter-spacing: 1px;
      &.bull { background: var(--el-color-danger-light-9); color: var(--el-color-danger); }
      &.bear { background: var(--el-color-success-light-9); color: var(--el-color-success); }
      &.neutral { background: var(--el-bg-color-page); color: var(--el-text-color-secondary); }
      &.nodata { background: var(--el-fill-color); color: var(--el-text-color-secondary); }
    }
    .dash-conf {
      display: flex; align-items: baseline; gap: 8px; padding: 4px 14px; border-radius: 8px;
      background: var(--el-color-primary-light-9);
      &.low { background: var(--el-bg-color-page); }
      .conf-num { font-size: 26px; font-weight: 800; color: var(--el-color-primary); b { font-size: 15px; font-weight: 700; margin-left: 1px; } }
      &.low .conf-num { color: var(--el-text-color-secondary); }
      .conf-label { font-size: 12px; color: var(--el-text-color-secondary); white-space: nowrap; }
    }
    .dash-scale-hint { font-size: 12px; color: var(--el-text-color-placeholder); }
  }

  // 三段刻度条
  .gauge {
    position: relative; padding: 4px 0 0;
    .gauge-track {
      position: relative; display: flex; height: 34px; border-radius: 8px; overflow: visible;
      &.lock { box-shadow: 0 0 0 1px var(--el-border-color-lighter); }
      .gauge-seg {
        flex: 1; display: flex; align-items: center; justify-content: center;
        font-size: 13px; font-weight: 700; color: #fff;
        &:first-child { border-radius: 8px 0 0 8px; }
        &:last-child { border-radius: 0 8px 8px 0; }
      }
      .seg-bear { background: linear-gradient(90deg, var(--el-color-success-dark-2), var(--el-color-success)); }
      .seg-neutral { background: var(--el-fill-color-dark); color: var(--el-text-color-regular); }
      .seg-bull { background: linear-gradient(90deg, var(--el-color-danger), var(--el-color-danger-dark-2)); }
      .gauge-pointer {
        position: absolute; top: -6px; transform: translateX(-50%);
        transition: left .5s ease;
        .gauge-needle {
          width: 0; height: 0; margin: 0 auto;
          border-left: 7px solid transparent; border-right: 7px solid transparent;
          border-bottom: 12px solid var(--el-text-color-primary);
          filter: drop-shadow(0 1px 1px rgba(0,0,0,.35));
        }
      }
    }
    .gauge-scale {
      display: flex; align-items: center; margin-top: 8px; font-size: 12px;
      .g-scale { flex: 1; &:nth-child(2) { text-align: center; } &:nth-child(3) { text-align: right; } }
      .bear-zone { color: var(--el-color-success); }
      .neutral-zone { color: var(--el-text-color-secondary); }
      .bull-zone { color: var(--el-color-danger); }
    }
  }

  .dash-note {
    display: flex; align-items: flex-start; gap: 6px; margin-top: 12px;
    padding: 8px 12px; font-size: 13px; line-height: 1.6;
    background: var(--el-bg-color-page); color: var(--el-color-warning); border-radius: 6px;
    .el-icon { margin-top: 2px; }
  }

  // 5.1 方向拆解面板（信号溯源，折叠）
  .signal-collapse {
    margin-top: 12px;
    border: 1px solid var(--el-border-color-lighter); border-radius: 8px;
    :deep(.el-collapse-item__header) {
      height: auto; padding: 8px 14px; line-height: 1.6;
      border-bottom: none; background: var(--el-fill-color-light); border-radius: 8px 8px 0 0;
    }
    :deep(.el-collapse-item__wrap) { border-bottom: none; }
    .panel-collapse-title {
      display: flex; align-items: center; flex-wrap: wrap; gap: 6px;
      font-size: 13px; font-weight: 600; color: var(--el-text-color-primary);
      .el-icon { color: var(--el-color-primary); }
      .panel-hint { font-size: 12px; color: var(--el-text-color-secondary); font-weight: 400; }
      .panel-score {
        font-size: 12px; font-weight: 600; color: var(--el-text-color-regular); white-space: nowrap;
        b { color: var(--el-color-primary); }
      }
    }
  }
  .signal-panel {
    padding: 4px 2px;
    .signal-row {
      display: grid;
      grid-template-columns: minmax(140px, 190px) 72px 78px 72px 40px 1fr;
      column-gap: 10px; align-items: center;
      padding: 7px 12px;
      border-radius: 6px; font-size: 13px;
      &:nth-child(odd) { background: var(--el-bg-color-page); }
      .sig-name { font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .sig-value { font-variant-numeric: tabular-nums; font-weight: 500; color: var(--el-text-color-regular); white-space: nowrap; }
      .sig-weight { color: var(--el-text-color-placeholder); font-size: 12px; white-space: nowrap; }
      .sig-judge {
        justify-self: start; padding: 2px 8px; border-radius: 10px; font-size: 12px; font-weight: 600;
        &.bull { background: var(--el-color-danger-light-9); color: var(--el-color-danger); }
        &.bear { background: var(--el-color-success-light-9); color: var(--el-color-success); }
        &.neutral { background: var(--el-bg-color-page); color: var(--el-text-color-secondary); }
      }
      .sig-score { text-align: right; font-weight: 600; }
      .sig-explain { color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.5; }
    }
  }

  // 5.3 计划生成流水线
  .pipeline {
    display: flex; align-items: stretch; gap: 6px; flex-wrap: wrap;
    .pipeline-step {
      flex: 1 1 180px; min-width: 180px; padding: 12px 14px; border-radius: 10px;
      border: 1px solid var(--el-border-color-light); background: var(--el-bg-color);
      border-top: 3px solid var(--el-color-primary);
      &.p-step-env { border-top-color: var(--el-color-info); }
      &.p-step-ind { border-top-color: var(--el-color-warning); }
      &.p-step-stock { border-top-color: var(--el-color-danger); }
      &.p-step-plan { border-top-color: var(--el-color-success); }
      &.p-step-sell { border-top-color: #9261d6; }
      .p-step-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 6px; }
      .p-step-name { font-size: 15px; font-weight: 700; }
      .p-step-count { font-size: 12px; color: var(--el-text-color-secondary); b { color: var(--el-text-color-primary); font-size: 14px; } b.kept { color: var(--el-color-success); } }
      .p-step-rule { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.5; margin-bottom: 8px; min-height: 32px; }
      .p-step-bar { height: 6px; border-radius: 3px; background: var(--el-fill-color); overflow: hidden; }
      .fill { display: block; height: 100%; border-radius: 3px; background: var(--el-color-primary); transition: width .5s ease; }
      &.p-step-env .fill { background: var(--el-color-info); }
      &.p-step-ind .fill { background: var(--el-color-warning); }
      &.p-step-stock .fill { background: var(--el-color-danger); }
      &.p-step-plan .fill { background: var(--el-color-success); }
      .p-step-reasons { margin-top: 8px; display: flex; flex-direction: column; gap: 4px; }
      .p-reason { display: flex; align-items: flex-start; gap: 6px; font-size: 12px; color: var(--el-text-color-regular); line-height: 1.4; }
      .r-dot { flex: 0 0 auto; width: 6px; height: 6px; margin-top: 5px; border-radius: 50%; background: var(--el-color-primary); }
    }
    .pipeline-arrow { display: flex; align-items: center; color: var(--el-text-color-placeholder); font-size: 18px; align-self: center; }
  }
  // 计划审计漏斗（折叠，默认收起）
  .plan-audit-collapse {
    margin-top: 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px;
    :deep(.el-collapse-item__header) {
      height: auto; padding: 8px 14px; line-height: 1.6;
      background: var(--el-fill-color-light); border-radius: 8px 8px 0 0;
    }
    :deep(.el-collapse-item__wrap) { padding: 10px 14px; border-bottom: none; }
    .audit-collapse-title {
      display: flex; align-items: center; flex-wrap: wrap; gap: 8px;
      font-size: 13px; font-weight: 600; color: var(--el-text-color-primary);
      .audit-summary { font-size: 12px; font-weight: 400; color: var(--el-text-color-secondary); }
    }
  }
  .pipeline-tip { display: flex; align-items: center; gap: 6px; margin-top: 10px; font-size: 12px; color: var(--el-text-color-secondary); }
  // 预测行业池（Stage2 行业方向预测产物）
  .ind-strip { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-top: 10px;
    .ind-strip-label { flex: none; font-size: 12px; font-weight: 600; color: var(--el-text-color-regular); }
    .ind-tag { flex: none; }
  }

  // 5.4 计划候选 / 来源
  .cand-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }
  .cand-card {
    .cand-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 6px; }
    .cand-name { font-size: 15px; font-weight: 600; }
    .cand-meta { display: flex; align-items: center; gap: 6px; }
    .cand-sig { font-size: 11px; padding: 1px 6px; border-radius: 4px; background: var(--el-color-warning-light-9); color: var(--el-color-warning); white-space: nowrap; }
    .cand-source { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--el-color-primary); margin-bottom: 8px; }
    .cand-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 10px; font-size: 12px; margin-bottom: 10px; }
    .fld { display: flex; justify-content: space-between; gap: 6px; .k { color: var(--el-text-color-secondary); } .v { color: var(--el-text-color-primary); font-weight: 600; &.down { color: var(--el-color-success); } } }
    .cand-actions { display: flex; gap: 6px; }
  }
  // 信效徽标（候选卡片 + 当日计划表格共用）、待执行徽标、卖出操作比例 → 顶层，作用于表格/标题等非卡片场景
  .cand-hit { font-size: 11px; padding: 1px 6px; border-radius: 4px; white-space: nowrap; }
  .cand-hit.hit-good { background: var(--el-color-success-light-9); color: var(--el-color-success); font-weight: 600; }
  .cand-hit.hit-low { background: var(--el-color-danger-light-9); color: var(--el-color-danger); }
  .exec-badge { font-size: 11px; padding: 1px 8px; border-radius: 4px; background: var(--el-color-danger-light-9); color: var(--el-color-danger); margin-left: 8px; font-weight: 600; vertical-align: 1px; }
  .sell-act { font-size: 12px; color: var(--el-text-color-regular); margin-top: 3px; }
  .sell-act b { color: var(--el-color-danger); }
  .src-dot { flex: 0 0 auto; display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--el-color-primary); }
  .plan-source { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--el-color-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
  .plan-source.manual { color: var(--el-text-color-secondary); .src-dot { background: var(--el-fill-color-dark); } }
  .edit-target { color: var(--el-text-color-primary); font-weight: 600; }
  .no-op { color: var(--el-text-color-placeholder); }

  // 今日卖出观测 / 买卖点实时指导
  .sell-advice {
    display: inline-block; padding: 2px 8px; border-radius: 10px;
    font-size: 12px; font-weight: 600; white-space: nowrap;
    background: var(--el-fill-color); color: var(--el-text-color-regular);
    &.down { background: var(--el-color-danger-light-9); color: var(--el-color-danger); }
    &.warn { background: var(--el-color-warning-light-9); color: var(--el-color-warning); }
  }
  .guide-count {
    display: inline-block; margin-left: 4px; padding: 0 7px;
    font-size: 11px; line-height: 18px; border-radius: 10px;
    background: var(--el-color-primary-light-9); color: var(--el-color-primary); font-weight: 600;
  }
  // 快照已自动生成但候选被过滤时的说明条
  .plan-filtered-note {
    display: flex; align-items: flex-start; gap: 6px; margin-top: 10px;
    padding: 8px 12px; font-size: 13px; line-height: 1.6;
    background: var(--el-color-primary-light-9); color: var(--el-color-primary); border-radius: 6px;
    .el-icon { margin-top: 2px; }
  }

  // 盘中买入·快速交易弹窗
  .quick-trade {
    .qt-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px;
      .qt-name { font-size: 15px; font-weight: 700; } }
    .qt-advice { font-size: 13px; color: var(--el-text-color-regular); line-height: 1.6; margin-bottom: 10px; }
    .qt-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 14px;
      .fld { display: flex; flex-direction: column; gap: 2px; text-align: center; padding: 8px 6px;
        background: var(--el-fill-color-light); border-radius: 6px;
        .k { font-size: 11px; color: var(--el-text-color-secondary); }
        .v { font-size: 14px; font-weight: 700; color: var(--el-text-color-primary); } } }
    .qt-form { margin-bottom: 4px; }
    .qt-amount { font-size: 14px; font-weight: 700; color: var(--el-color-danger); }
    .qt-warn { margin-left: 10px; font-size: 12px; color: var(--el-color-warning); }
    .qt-tip { margin: 4px 0 0; font-size: 12px; color: var(--el-text-color-secondary); }
  }

  .llm-card {
    margin-top: 12px; padding: 14px 16px;
    border: 1px solid var(--el-border-color-lighter);
    border-left: 3px solid var(--el-color-primary);
    border-radius: 8px;
    background: var(--el-bg-color);
    display: flex; flex-direction: column; gap: 12px;
    .llm-sec { display: flex; gap: 12px; font-size: 13px; color: var(--el-text-color-primary); }
    .llm-tag { flex: 0 0 76px; color: var(--el-color-primary); font-weight: 600; padding-top: 2px; }
    .llm-body { flex: 1; line-height: 1.75; word-break: break-word; }
    .llm-line { padding: 2px 0; }
    .llm-kw {
      display: inline-block; padding: 2px 10px; margin: 0 6px 6px 0;
      background: var(--el-color-primary-light-9); color: var(--el-color-primary);
      border-radius: 12px; font-size: 12px;
    }
    .llm-body.risk { color: var(--el-color-danger); }
  }

  .grid-4 {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px;
    .idx-card { text-align: center; }
    .idx-name { font-size: 13px; color: var(--el-text-color-secondary); margin-bottom: 6px; }
    .idx-price { font-size: 20px; font-weight: 700; }
    .idx-pct { font-size: 14px; font-weight: 600; }
  }

  .region {
    display: inline-block; margin-left: 4px; padding: 0 6px;
    font-size: 11px; line-height: 16px; color: var(--el-text-color-secondary);
    background: var(--el-fill-color); border-radius: 4px; vertical-align: 1px;
  }

  .sub-block { margin-bottom: 18px; &:last-child { margin-bottom: 0; } }
  .sub-title {
    display: flex; align-items: center; gap: 6px;
    font-size: 13px; font-weight: 600; color: var(--el-text-color-primary);
    margin-bottom: 10px;
    .el-icon { color: var(--el-color-primary); }
  }

  .news-list { display: flex; flex-direction: column; gap: 6px; }
  .news-row {
    display: flex; align-items: center; gap: 10px; padding: 6px 8px;
    border-bottom: 1px dashed var(--el-border-color-lighter); font-size: 13px;
    .news-title { flex: 1; color: var(--el-text-color-primary); text-decoration: none; word-break: break-word; }
    a.news-title:hover { color: var(--el-color-primary); }
    .news-time { color: var(--el-text-color-secondary); font-size: 12px; flex: 0 0 auto; }
  }

  .kpi-row {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 12px;
    .kpi-cell {
      background: var(--el-bg-color); border: 1px solid var(--el-border-color-light);
      border-radius: 8px; padding: 12px 14px; text-align: center;
      .kpi-label { font-size: 12px; color: var(--el-text-color-secondary); }
      .kpi-value { font-size: 22px; font-weight: 700; margin: 4px 0; }
      .kpi-sub { font-size: 12px; color: var(--el-text-color-secondary); }
    }
  }

  .regime-bar {
    display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
    padding: 12px 16px; border-radius: 10px; margin-bottom: 8px;
    &.regime-bull { background: var(--el-color-danger-light-9); }
    &.regime-bear { background: var(--el-color-success-light-9); }
    &.regime-sideways { background: var(--el-bg-color-page); }
    .regime-chip { display: flex; align-items: center; gap: 8px; font-weight: 600; }
    .regime-advice { display: flex; align-items: center; gap: 6px; font-size: 13px; flex: 1; }
    .regime-asof { font-size: 12px; color: var(--el-text-color-secondary); }
  }

  .more-link { color: var(--el-color-primary); font-size: 13px; text-decoration: none; }
  .sep { margin: 0 4px; color: var(--el-text-color-secondary); }
  .hit-stop { margin-left: 6px; color: var(--el-color-danger); font-size: 12px; }
  .benchmark-warn {
    display: flex; align-items: center; gap: 6px; margin-top: 10px;
    font-size: 13px; color: var(--el-color-warning);
  }

  .fav-code { color: var(--el-text-color-secondary); font-size: 12px; font-weight: 400; }

  .stock-link {
    color: var(--el-color-primary); text-decoration: none;
    &:hover { text-decoration: underline; }
    &.stock-code { font-family: monospace; color: var(--el-text-color-secondary); }
  }

  .scan-summary {
    display: flex; gap: 16px; align-items: center; flex-wrap: wrap;
    margin-bottom: 12px; padding: 8px 12px; font-size: 13px;
    background: var(--el-bg-color-page); border-radius: 8px;
    b { color: var(--el-color-primary); }
  }

  .scan-prefill-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px;
    .prefill-card {
      padding: 12px 14px; border: 1px solid var(--el-border-color-light);
      border-radius: 8px; background: var(--el-bg-color); cursor: pointer;
      transition: all .2s;
      &:hover { border-color: var(--el-color-primary); box-shadow: var(--el-box-shadow-light); }
      .prefill-name { font-size: 15px; font-weight: 600; margin-bottom: 6px; }
      .prefill-line { font-size: 13px; color: var(--el-text-color-primary); b { color: var(--el-color-primary); } }
      .prefill-line.sub { color: var(--el-text-color-secondary); margin-top: 4px; }
    }
  }
}
</style>
